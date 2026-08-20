# Experimento de resolucion de OCR por tienda (ago 2026)

Continua la investigacion de la prioridad 6 del plan de mejora (ver hallazgo
de causa raiz: fuente nativa mas chica en alsuper/casa_ley vs el resto de
tiendas, medida el 09-ago-2026). Pregunta central: **subir la resolucion de
escalado de OCR (`ancho_objetivo`, hoy fijo a 1500px para todas las tiendas)
mejora el recall en las tiendas con OCR bajo, o depende de la tienda?**

## Parte 1 — Experimento en GPU: alsuper y casa_ley (09/11-ago-2026)

Se preparo un paquete via la skill de proyecto `preparar-traspaso-gpu`
(gitignoreada) para correr en la PC con GPU, comparando 1500px vs 2500px x
perfil `color_normal` vs `color_suave`, sobre las paginas del dataset manual
de alsuper y casa_ley (32 combinaciones).

Resultado crudo (`gpu_alsuper_casa_ley/resumen_resolucion.txt` /
`resultados_resolucion.csv`):

- **casa_ley mejora claramente**: PROD_OCR 50.4%→81.8%, PROD_NLP 44.3%→76.9%
  a 2500px. Su cuello de botella si es tamano de fuente pequeno.
- **alsuper empeora**: PRECIOS cae de 28.3%→18.2% (color_normal) y de
  28.9%→21.2% (color_suave) a 2500px. Su problema no es resolucion.

Datos completos (bloques OCR crudos de las 32 combinaciones):
`data/processed/_v8_experimento_resolucion_ocr/gpu_alsuper_casa_ley/resultados_detalle.json`.

## Parte 2 — Fix de factor_escala y su validacion (11 y 19-ago-2026)

Hipotesis original para explicar por que alsuper empeora: los umbrales de
distancia de `nlp/regex_extractor.py` (`DISTANCIA_MAX_CONTEXTO_PRECIO`, gaps
de precios fusionados) estaban calibrados fijos a 1500px — subir resolucion
alejaria en pixeles reales a bloques que en produccion estarian "cerca".

Se implemento un fix (11-ago-2026, sin commitear hasta esta sesion): agregar
`ANCHO_REFERENCIA_UMBRALES` y un `factor_escala = ancho_pagina_real /
ANCHO_REFERENCIA_UMBRALES` que escala esos umbrales dinamicamente
(`RegexExtractor.procesar_pagina`, `_hay_contexto_precio`,
`_hay_producto_cerca`, `_detectar_precios_fusionados`). `ancho_pagina` se
agrego a la salida de `probar_vision.py` para poder calcularlo.

**Validacion (19-ago-2026)**: se re-corrio `RegexExtractor` (ya con el fix)
sobre los bloques OCR crudos del experimento de GPU — sin volver a hacer
OCR — y se comparo contra el dataset manual
(`scripts/validar_fix.py` → `gpu_alsuper_casa_ley/resultado_validacion_factor_escala.txt`):

| tienda | perfil | ancho | PROD_NLP | PRECIOS |
|---|---|---:|---:|---:|
| alsuper | color_normal | 1500 | 54.5% | 25.3% |
| alsuper | color_normal | 2500 | 54.9% | **18.8%** |
| alsuper | color_suave | 1500 | 54.5% | 26.9% |
| alsuper | color_suave | 2500 | 57.3% | **21.6%** |
| casa_ley | color_normal | 1500 | 44.0% | 4.0% |
| casa_ley | color_normal | 2500 | 76.8% | 3.8% |

**Conclusion: el fix NO resuelve alsuper.** Con el umbral ya escalado
correctamente, PRECIOS sigue cayendo (~6.5pt color_normal, ~5.3pt
color_suave) al subir a 2500px — practicamente igual que sin el fix. La
hipotesis de "umbral de distancia fijo" queda **descartada** como causa
principal.

Causa real identificada: se comparo el set de bloques OCR nuevos que
aparecen a 2500px y no existian a 1500px (pagina alsuper/416306/pagina_002 y
otras). ~60-70% de esos bloques "nuevos" son lecturas de muy baja confianza
(0.10-0.20) que **fragmentan/corrompen texto que a 1500px se leia bien**
(ej. "Pechuga de Pollo sin hueso Premium" pasa a leerse como "Pechuga de" +
basura). No es ruido agregado sobre lecturas buenas preservadas — es la
misma region re-segmentada peor. Pasa igual con y sin sharpening
(`color_suave` tambien lo sufre), asi que tampoco es (solo) el sharpening
resaltando fondo de fotos, como se habia sospechado el 09-ago. La confianza
promedio de bloques en alsuper cae con resolucion (0.556→0.499
color_normal), mientras que en casa_ley sube (0.523→0.559) — la fuente
nativa de alsuper (~17px) ya esta cerca del limite de fragmentacion de
EasyOCR; estirarla mas no aporta nitidez real.

El fix de `factor_escala` sigue siendo correcto y sin regresion a 1500px
(`ancho_pagina == ANCHO_REFERENCIA_UMBRALES` → `factor_escala = 1.0`,
comportamiento identico al anterior) y ayuda a casa_ley, pero **no cierra
la prioridad 6 para alsuper**.

## Parte 3 — Extension a las 5 tiendas sin medir (19-ago-2026)

De las 16 tiendas de tiendeo, solo alsuper y casa_ley tenian medicion de
fuente nativa/resolucion (09-ago). El resto de tiendas con recall bajo en
`data/processed/_evaluacion_nlp/reporte.json` (walmart 75.6%, bodega_aurrera
81.2%, merco 81.6%, s-mart 58.9%, waldos 26.3%) nunca se habian probado.

Se corrio el mismo experimento (OCR real, CPU, `color_normal`, 1500px vs
2500px) sobre **todas** las paginas del dataset manual de esas 5 tiendas
(138 paginas x 2 resoluciones = 276 corridas), sin tocar
`data/processed/tiendeo/` de produccion.
Script: `scripts/experimento_5_tiendas.py` → datos crudos en
`cpu_5_tiendas/detalle_5_tiendas.jsonl`.
Analisis: `scripts/analizar_5_tiendas.py` →
`cpu_5_tiendas/resultado_prod_ocr_5_tiendas.txt`.

| tienda | PROD_OCR 1500px | PROD_OCR 2500px | cambio |
|---|---:|---:|---|
| walmart | 75.6% | 75.6% | sin cambio |
| bodega_aurrera | 81.2% | 81.2% | sin cambio |
| merco | 81.6% | 82.3% | +0.7pt (ruido) |
| s-mart | 58.4% | 58.0% | sin cambio |
| waldos | 26.3% | 31.6% | +5.3pt (muestra chica, no concluyente) |

**Ninguna mejora con resolucion.** Confirma la hipotesis sobre walmart
(fuente nativa ~19px, igual a chedraui que anda en 96% — su problema no es
tamano de fuente) y descarta que el patron de casa_ley sea generalizable.

## Clasificacion final — las 16 tiendas de tiendeo

| Categoria | Tiendas |
|---|---|
| Ya funcionan bien (90%+), no tocar | costco, oxxo, la_comer, chedraui, tiendas_3b, soriana_hiper, soriana_mercado, heb, sam's_club |
| Candidata confirmada a subir resolucion | **casa_ley** (unica) |
| Recall bajo, NO es problema de resolucion | alsuper (empeora, fragmentacion de texto), walmart, bodega_aurrera, merco, s-mart, waldos |

## Parte 4 — Aplicado a produccion y backfill de los 23 folletos existentes (19-ago-2026)

Se implemento `RESOLUCION_POR_TIENDA = {"casa_ley": 2500}` en
`catchup_tiendeo.py::catchup_vision()` (cachea un `Preprocessor` por
`ancho_objetivo` distinto en vez de uno solo para todo el batch; tiendas no
listadas siguen usando el default 1500px). Aplica hacia adelante a folletos
nuevos.

Los 23 folletos de casa_ley que ya estaban procesados a 1500px en
`data/processed/tiendeo/casa_ley/` se respaldaron completos en
`data/processed/_v8_experimento_resolucion_ocr/backup_casa_ley_1500px_pre_2500/`
(incluye `reporte_baseline_1500px_2026-08-19.json`, snapshot del reporte de
evaluacion ANTES del cambio) y se reprocesaron con el pipeline real de
produccion a 2500px (`scripts/reprocesar_casa_ley_2500.py`: mismo
`probar_vision.procesar_carpeta` + `probar_nlp.procesar_carpeta` que usa
`catchup_tiendeo.py`, con `forzar=True`).

**Resultado verificado con `evaluar_nlp.py` (dataset manual, pipeline real, no ad-hoc):**

| metrica | antes (1500px) | despues (2500px) | cambio |
|---|---:|---:|---|
| casa_ley PROD_OCR | 50.1% | **81.9%** | +31.8pt |
| casa_ley PROD_NLP | 43.6% | **75.8%** | +32.2pt |
| casa_ley PRECIOS | 3.5% | 3.5% | sin cambio (problema independiente, ya documentado) |
| GLOBAL PROD_NLP | 67.4% | **75.3%** | +7.9pt |
| GLOBAL PRECIOS | 27.9% | 27.9% | sin cambio |

**Decision: SE QUEDA.** Gran mejora en casa_ley, cero regresion en cualquier
otra metrica (no se toco ninguna otra tienda). El backup a 1500px se
conserva por si hiciera falta revertir.

Pendiente: los 23 folletos reprocesados pueden ya estar cargados en
PostgreSQL desde su version a 1500px (`load/load.py` usa `ON CONFLICT DO
NOTHING`, ver [[pricescraper-mx-fallback-de-fechas-de-vigencia]]) — el nuevo
`nlp_resultado.json` a 2500px NO se reflejaria automaticamente en la base
sin un reload explicito. No se automatizo ese reload en esta sesion.

## Decision final / pendientes

- Fix de `factor_escala` + `RESOLUCION_POR_TIENDA` en `catchup_tiendeo.py`:
  listos, verificados, pendientes de commitear.
- Evaluar si conviene un reload en PostgreSQL de los 23 folletos de casa_ley
  con los datos nuevos (mejor cobertura de producto).
- No gastar mas tiempo subiendo resolucion en alsuper/walmart/bodega_aurrera/
  merco/s-mart/waldos — su recall bajo tiene otra causa, pendiente de
  investigar tienda por tienda (no es prioridad 6, seria trabajo nuevo).
- alsuper en particular: la pista mas prometedora es la fragmentacion de
  texto de fuente muy chica por EasyOCR — explorar si un enfoque distinto al
  simple upscale (ej. super-resolucion dirigida, o deteccion de regiones de
  texto antes de escalar) ayuda, en vez de subir el ancho global de la
  pagina.

## Datos y scripts

- `data/processed/_v8_experimento_resolucion_ocr/gpu_alsuper_casa_ley/` —
  datos crudos y resultados del experimento en GPU (Parte 1) y de la
  validacion del fix (Parte 2).
- `data/processed/_v8_experimento_resolucion_ocr/cpu_5_tiendas/` — datos
  crudos y resultado del experimento de las 5 tiendas (Parte 3).
- `data/processed/_v8_experimento_resolucion_ocr/scripts/` — scripts usados
  (ad-hoc, no forman parte del pipeline de produccion).
