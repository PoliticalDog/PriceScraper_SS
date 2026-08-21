# Cobertura de precios "bare digits" de 2 y 5 dígitos + fix de ambigüedad 4 dígitos (ago 2026)

Continúa la prioridad 4 del plan de mejora (`sources/nlp/03_promo_requiere_precio_en_pagina.md`
es el doc anterior de la serie). La prioridad 4 original suponía que el 70%
de los precios no detectados era "pérdida real de OCR" y necesitaba trabajo
de imagen/GPU. Antes de invertir ahí, se re-auditaron los 1209 fallos de
precio actuales (`data/processed/_evaluacion_nlp/reporte.json`) cruzando cada
caso con los bloques OCR crudos de su página.

## Hallazgo: no era (solo) pérdida de OCR

| categoría | casos | % |
|---|---:|---:|
| `sin_evidencia_en_ningun_bloque` (pérdida real) | 444 | 36.7% |
| `exacto_no_extraido` (el bloque OCR tiene el número completo, NLP no lo saca) | 293 | 24.2% |
| `perdida_1_digito` (falta 1 dígito, superíndice de centavos) | 268 | 22.2% |
| `simbolo_extra_1_digito` | 198 | 16.4% |

Una muestra de 127 casos de `exacto_no_extraido` (bloque = precio esperado
exacto) se auditó corriendo `RegexExtractor` en vivo: el 65% no tenía NINGÚN
patrón de regex para esa longitud de número (2 o 5 dígitos), y el 20% era
una ambigüedad de precedencia entre dos reglas ya existentes.

## Cambios en `nlp/regex_extractor.py`

**Regla B-2** (`PATRON_BARE_DIGITOS_2`): precio entero <$100 sin centavos
(ej. "15"→$15). Gate: contexto fuerte O producto cerca (igual que B-4).
Excluye explícitamente "00" (ver bug abajo).

**Regla B-5** (`PATRON_BARE_DIGITOS_5`): precio ≥$100 con centavos (ej.
"15490"→$154.90). El plan original proponía un gate AND (contexto fuerte Y
producto cerca) por el riesgo de SKU ya documentado para 5-6 dígitos
(`541583`/`559944`, jul-2026). Medido: el AND dejaba pasar 0/62 casos reales
del dataset manual (ninguno tenía contexto fuerte). Se relajó a OR, igual que
B-2/B-4, y se validó que no subieran `precios_mal_clasificados`.

**Fix de ambigüedad B-4 vs Regla A** (`PATRON_DIGITO_ESPURIO`): un string de
4 dígitos puros puede ser un precio real con centavos (B-4, "6990"→$69.90,
92/93 casos validados) o un "$" mal leído + precio entero (Regla A, "8249"
→$249, 6 casos confirmados jul-2026, ninguno termina en "0"). Regla A se
evaluaba primero con gate más débil y, si fallaba, mataba la función sin
darle oportunidad a B-4 -- precios reales terminados en ".90" (69.90, 59.90,
64.90, 89.90...) se estaban descartando. Fix: para texto sin sufijo, se
intenta primero B-4; solo si su gate falla se intenta Regla A. Con sufijo
(letras/c-u pegado) el comportamiento no cambia (B-4 nunca los matchea).

## Bug encontrado y corregido antes de terminar: precios de $0.00

Al revisar los valores extremos extraídos tras el cambio, aparecieron 173
precios de **$0.00** en todo el corpus -- el bloque de texto "00" (remanente
de centavos de un precio ya fusionado en 2 bloques, ej. "199"+"00") estaba
matcheando la nueva Regla B-2 como si fuera un precio propio. Se agregó una
exclusión explícita (`m.group(1) != "00"`). Verificado: bajó de 173 a 3
precios en $0.00 (los 3 restantes son de un patrón distinto, preexistente,
fuera de este cambio).

## Metodología de validación

Cada paso (B-2, B-5, fix de ambigüedad, fix de "00") se validó por separado:
reprocesar NLP de los 431 folletos de `data/processed/tiendeo/` (rápido, es
regex puro, no toca OCR) y correr `evaluar_nlp.py` contra el dataset manual,
comparando recall Y `precios_mal_clasificados` (no solo ganancia, también
que no aparecieran regresiones). Snapshot del baseline antes de empezar:
`data/processed/_evaluacion_nlp/reporte_baseline_prioridad4_2026-08-19.json`.

## Resultado final

| métrica | antes | después | cambio |
|---|---:|---:|---|
| PRECIOS global | 27.9% (471/1688) | **33.4% (564/1688)** | +5.5pt |
| PROD_NLP global | 75.3% (1369/1818) | 75.2% (1368/1818) | -1 caso, ruido |
| precios_mal_clasificados | 8 | 8 | sin cambio |
| precios en $0.00 (falso positivo) | 0 (no existía la regla) | 3 (preexistentes, no de este cambio) | -- |

Sin tocar OCR/GPU/resolución -- puramente regex. Deja pendiente, fuera de
alcance de este cambio: `perdida_1_digito` (22.2%) y buena parte de
`sin_evidencia_en_ningun_bloque` (36.7%) sí son trabajo de imagen real
(recorte + reescalado dirigido del bbox del precio) -- la prioridad 4
original tal como se concibió, para una fase futura.
