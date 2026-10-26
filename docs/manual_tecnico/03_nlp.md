# Módulo NLP

El módulo NLP es el tercer eslabón del pipeline. Recibe el texto que el OCR leyó en cada página de folleto (`ocr_resultado.json`) y clasifica cada bloque en una de ocho categorías: precio, precio anterior, ahorro, promoción, campaña, producto, atributo o descarte. No asocia el producto con su precio; eso lo hace el módulo de carga (`load/load.py`).

## Propósito y alcance

Un folleto no trae datos estructurados: trae cientos de bloques de texto sueltos, muchos mal leídos por el OCR ("$429" puede llegar como "8429", "s429" o "$" y "429" en bloques distintos). El NLP decide qué es cada bloque usando expresiones regulares, la geometría de la página (tamaño y posición de los bloques) y un catálogo de productos.

| Hace | No hace |
|---|---|
| Clasificar cada bloque OCR y extraer el valor numérico de precios, precios anteriores y ahorros | Unir el producto con su precio (load) |
| Reconstruir precios partidos en varios bloques (entero + centavos en superíndice) | Leer la imagen (vision) |
| Asignar categoría a productos y atributos con el catálogo | Guardar en la base de datos (load) |
| Detectar la campaña del folleto (Julio Regalado, Hot Sale...) | Calcular métricas de calidad (evaluador) |

Tabla: Alcance del módulo NLP

## Entradas y salidas

**Entrada:** `data/processed/<fuente>/<tienda>/<folleto>/ocr_resultado.json`, producido por el módulo de visión. Cada página trae su ancho (`ancho_pagina`) y sus bloques con texto, confianza del OCR y caja (`bbox`):

```
{"pagina": "pagina_003.webp", "ancho_pagina": 1800, "confianza_prom": 0.642,
 "bloques": [{"texto": "$429", "confianza": 0.675,
              "bbox": {"x": 1261, "y": 520, "ancho": 303, "alto": 129}, "motor": "easyocr"}, ...]}
```

**Salida:** `nlp_resultado.json` en la misma carpeta. El contrato lo arma `nlp/salida_json.py` (`resultado_nlp`) y lo consumen `load/load.py` y el evaluador. Trae un resumen con totales por categoría y la tasa útil (bloques que no son descarte / total), y por página una lista por categoría:

```
"resumen": {"total_productos": 231, "total_precios": 52, "total_precios_anterior": 7,
            "total_promos": 4, "total_atributos": 1, "total_descartes": 110, "tasa_util": 0.728, ...}
"paginas": [{"pagina": "pagina_003.webp",
             "precios":   [{"texto": "$429", "valor": 429.0, "confianza": 0.675, "bbox": {...}}],
             "productos": [{"texto": "...", "confianza": 0.44, "bbox": {...}, "categoria": ""}],
             "precios_anteriores": [{"texto": "...", "valor": ..., "candidatos": [...], ...}], ...}]
```

Ejemplo real: bodega_aurrera, folleto 413505, página 3 (tiendeo).

Si cambia este contrato (nombres de claves, estructura de `bbox`), se rompen `load/load.py`, el evaluador y la base de datos. Por eso los agentes del proyecto tienen prohibido cambiarlo sin aprobación.

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `nlp/regex_extractor.py` | Clasificador de bloques y reglas de precio (unas 2,400 líneas) | `RegexExtractor.procesar_pagina`, `_clasificar`, `_extraer_precio`, `_extraer_precio_sin_simbolo`, `_detectar_precios_fusionados`, `slug_evento` |
| `nlp/normalizador.py` | Convierte el texto de un producto en un nombre canónico comparable | `Normalizador.normalizar` → `ResultadoNorm` (`nombre_canonico`, `confianza_norm`, `metodo`) |
| `nlp/catalogo_productos.py` | Catálogo de categorías con palabras clave, tipos de producto y marcas | `CATALOGO`, `buscar_categoria(texto)` → `(encontrado, categoria, es_atributo)` |
| `nlp/salida_json.py` | Arma el contenido de `nlp_resultado.json` sin escribir en disco | `clasificar_paginas_ocr`, `resultado_nlp` |
| `probar_nlp.py` | Orquestador: menú, modo prueba y modo batch; escribe los JSON | `procesar_carpeta(carpeta, extractor, forzar)` |

Tabla: Archivos del módulo NLP

## Cómo funciona

### Flujo por página

`RegexExtractor.procesar_pagina` recorre la página en este orden:

```
bloques OCR de la página
   │
   ├─ pasada previa: ¿la página tiene algún precio real?  (_pagina_tiene_precio)
   ├─ pre-paso: anticipos de apartado, mensualidades MSI, puntos y plazos junto a su rótulo → DESCARTE
   ├─ pre-paso: precios partidos entero + centavos en superíndice → PRECIO  (_detectar_precios_fusionados)
   │
   ├─ por cada bloque restante (confianza ≥ 0.15):  _clasificar
   │     0. ¿es la campaña del folleto?                → EVENTO_PROMO
   │     1. ¿es ruido, letra chica, banco, tienda...?  → DESCARTE
   │     2. ¿"Antes: $X" o "DE $X A"?                  → PRECIO_ANTERIOR
   │     3. ¿mecánica de promoción (3x2, %, regalo)?   → PROMO
   │     4. ¿"Ahorra $X"?                              → AHORRO
   │     5. ¿precio con "$" (o confirmado por cuota)?  → PRECIO
   │     6. ¿precio sin "$" con contexto suficiente?   → PRECIO
   │     7. ¿está en el catálogo?                      → PRODUCTO o ATRIBUTO
   │     8. ¿parece nombre de producto?                → PRODUCTO
   │     9. nada de lo anterior                        → DESCARTE
   │
   └─ al final: los centavos ya sumados a otro precio dejan de ser precio propio
```

El orden importa: cada paso solo ve lo que no atraparon los anteriores. Por ejemplo, la campaña se evalúa antes del descarte porque "72ANIVERSARIO]" de casa_ley caía en el descarte de símbolos raros.

### Escala de la página

Los umbrales en píxeles (distancias de contexto, tamaño de los superíndices) se calibraron con páginas de 1500 px de ancho (`ANCHO_REFERENCIA_UMBRALES`). Cada página multiplica esos umbrales por `factor_escala = ancho_pagina / 1500`, para que una página procesada a 1800 px se comporte igual.

### Precios con "$"

`_extraer_precio` reconoce "$" + número con miles y decimales, prefijos ("desde", "a sólo") y sufijos ("c/u", "MXN"). También tolera el "$" leído como "s", "S" u "8" pegado a los dígitos (`PATRON_PRECIO_OCR_CORRUPTO`).

Un caso especial son los **centavos pegados**: en el diseño de soriana el OCR junta entero y centavos en un solo bloque ("$1989" es $19.80). Un "$" literal seguido de 4 o 5 dígitos sin separador se lee como entero + centavos (`PATRON_CENTAVOS_PEGADOS`), salvo que la casilla confirme el entero (`_entero_confirmado`): una mensualidad cuyo total da el entero (9 MSI de $288.33 = $2,595), un "DE $X A" que solo es creíble con el entero, u otro monto con coma de miles en el mismo bloque.

### Precios sin "$"

Es la parte más delicada. El OCR pierde o confunde el "$" con frecuencia, pero un número suelto también puede ser un gramaje, un modelo o un porcentaje. `_extraer_precio_sin_simbolo` aplica reglas con distinta exigencia de contexto:

| Regla | Forma | Ejemplo | Condición |
|---|---|---|---|
| A-miles / A2-miles | dígito espurio + miles con coma | "52,49000" → $2,490 | El superíndice se ignora: tres dígitos tras la coma siempre son miles |
| A2 | dígito espurio + número con decimal | "824.95" → $24.95 | — |
| A-escala | 5/6/8/s + entero de 2 dígitos | "835" → $35 | Todos los números de 3 caracteres del mismo tamaño en la página empiezan con 5/6/8/s (al menos 2) |
| A | dígito espurio + entero | "8249" → $249 | Se intenta después de B-4 |
| B-5 | 5 dígitos | "15490" → $154.90 | Contexto de precio |
| B-4 | 4 dígitos | "6990" → $69.90 | Contexto de precio |
| B-3 | 3 dígitos | "999" → $9.99 | Contexto fuerte |
| B-2 | 2 dígitos | "15" → $15 | Contexto fuerte; no continúa un nombre |
| C | miles con coma | "12,499" → $12,499 | No ambiguo |

Tabla: Reglas de precio sin "$" (nlp/regex_extractor.py)

El **contexto fuerte** son palabras como "a sólo", "de oferta", "antes", "ahorra", "c/u" o "paquete" cerca del número (`PATRON_CONTEXTO_PRECIO_FUERTE`). La palabra "puntos" cerca anula el contexto, y un año (2020-2029) nunca se lee como precio.

Desde el 24-oct-2026, un número de dígitos puros sin "$" se rechaza si mide menos de 1.3 veces la mediana del texto de la página (`ALTO_MIN_PRECIO_SIN_SIMBOLO`; un precio siempre es más grande que el texto) o si continúa un nombre (el "14" de "iPhone 14"). Hay dos excepciones: un rótulo de precio de la casilla encima ("PRECIAZO", "PRECIO BODEGA") o un "$" que el OCR leyó como bloque aparte, pegado a la izquierda.

### Precios partidos en dos bloques

Muchos folletos imprimen el precio con los centavos en superíndice ("$39⁹⁹"), y el OCR los lee como dos bloques. `_detectar_precios_fusionados` une un entero corto con un bloque de 2 dígitos más chico, a su derecha y alineado arriba (`_es_superindice_de`). Los centavos usados ya no cuentan como precio propio (antes salían "$90" y "$99" sueltos).

### Normalización del nombre

`Normalizador.normalizar` busca el nombre canónico del producto en tres pasos y deja constancia del método:

| Método | Cuándo | Umbral |
|---|---|---|
| `exacto` | El texto (o un alias) está en `CATALOGO_CANONICO` | — |
| `fuzzy` | Coincidencia aproximada (rapidfuzz) alta | ≥ 0.80 (`UMBRAL_ALTO`) |
| `fuzzy_bajo` | Coincidencia aproximada aceptable | ≥ 0.60 (`UMBRAL_BAJO`) |
| `heuristico` | Sin coincidencia: se usa el texto del folleto | hasta 150 caracteres |
| `sin_match` | Basura o vacío: se descarta | — |

Tabla: Métodos del normalizador (nlp/normalizador.py)

El catálogo de `nlp/catalogo_productos.py` asigna la categoría por palabras clave (línea blanca, electrónica, alimentos...). Desde el commit 9a1a450, `buscar_categoria` busca primero el tipo de producto y solo después la marca, y una marca nunca es atributo. Con ese cambio, los precios sin categoría en producción bajaron de 61.4% a 56.3%.

## Reglas y decisiones

Las decisiones importantes y por qué se tomaron:

- **El "$" leído como dígito necesita la escala de la página.** "879"+"99" es $79.99 en merco, pero "544"+"90" es $544.90 en casa_ley. Ni el ancho ni la confianza separan los dos casos; lo que sí los separa es el primer dígito de los demás números del mismo tamaño en la página. Por eso `PATRON_ENTERO_FUSION` no acepta "$" + 3 dígitos y la regla A-escala exige que toda la página use esa forma (commits 43e4040 y 6865f14; Engram #253, #265 y #266).
- **El filtro por altura se calibró sin perder precios reales.** El diagnóstico de las 360 páginas que el filtro deja sin precio (25-oct-2026) dio 42 de 50 sin precios reales y ninguna con precios sin "$" quitados por el filtro (Engram #263).
- **Los centavos pegados se protegen con la casilla.** La primera versión dividía entre 100 nueve precios reales (moto $65,999 → $659.99). La guarda `_entero_confirmado` los protege a los nueve sin tocar los demás (Engram #275).
- **Campañas con slug canónico.** Antes el texto completo se guardaba como campaña (45 variantes de "julio regalado"); ahora `slug_evento` devuelve uno de los slugs de `CAMPANAS_EVENTO` y excluye lemas y letra chica (commit 85e9e95).
- **Se descartó spaCy como extractor principal.** El experimento NER quedó documentado en `sources/nlp/05_experimento_spacy_ner.md` y `06_viabilidad_ner_custom.docx`; las reglas con geometría resultaron más controlables y medibles con el evaluador.

Cada regla nueva se mide con el evaluador (dev completo) y la revisa el agente de QA antes del commit (skill `ciclo-experimento`; las reglas de precio siguen además la skill `regex-precio-checklist`).

## Configuración

| Constante | Valor | Para qué |
|---|---|---|
| `CONFIANZA_MINIMA` | 0.15 | Bloques con menos confianza OCR se ignoran |
| `ANCHO_REFERENCIA_UMBRALES` | 1500 px | Ancho con el que se calibraron las distancias |
| `DISTANCIA_MAX_CONTEXTO_PRECIO` | 220 px | Radio para buscar contexto de precio |
| `ALTO_MIN_PRECIO_SIN_SIMBOLO` | 1.3 | Un precio sin "$" mide al menos 1.3× la mediana del texto |
| `ALTO_MAX_CENTAVOS_VS_ENTERO` | 0.75 | Tamaño máximo del superíndice respecto al entero |
| `MESES_MSI` | 3, 6, 9, 12, 15, 18, 24 | Plazos válidos para confirmar un precio por su mensualidad |
| `UMBRAL_ALTO` / `UMBRAL_BAJO` | 0.80 / 0.60 | Similitud mínima del normalizador |

Tabla: Constantes principales del módulo NLP

## Pruebas

Las reglas tienen pruebas unitarias con cajas reales de folletos en `tests/`:

- Reglas de precio: `test_regex_precio_espurio.py`, `test_regex_precio_espurio_miles.py`, `test_regex_precio_fusionado.py`, `test_regex_precio_bare_alto.py`, `test_regex_precio_signo_suelto.py`, `test_regex_precio_digito_signo_escala.py`, `test_regex_precio_centavos_pegados.py`, `test_regex_precio_centavos_pegados_guarda.py`, `test_regex_centavos_consumidos.py`, `test_regex_precio_cuotas.py`.
- Rótulos y promociones: `test_regex_rotulos_casilla.py`, `test_regex_rotulos_promo.py`, `test_regex_mensualidad_msi.py`, `test_regex_anticipo_apartado.py`, `test_regex_cantidades_rotulo.py`, `test_eventos_campania.py`.
- Catálogo y normalizador: `test_catalogo_productos.py`, `test_normalizador_cobertura.py`.

```
venv/Scripts/python.exe -m pytest tests -q                      # suite completa (1,324 pruebas al 26-oct-2026)
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria   # calidad del pipeline contra el ground truth
```

Los archivos `tests/_herramienta_*.py` no son pruebas: son scripts de medición de los agentes y pytest no los recoge.

Calidad en dev al 25-oct-2026 (corrida `20261025_224754`): precisión 33.1%, recall 24.7%, F1 28.3%, medida sobre registros completos producto + precio. El cuello de botella ya no es la lectura del precio sino la asociación con el producto (módulo load).

## Limitaciones conocidas y pendientes

- **alsuper sin "$"**: el primer dígito de los centavos se pega al precio ("699" es $69.90 y sale $99); en la muestra de QA solo 1 de 6 salió bien.
- **"550 mg"** de cajas de analgésicos se lee como $50.
- **"$ddd" de soriana** ("$780" = $7.80) sigue sin dividirse, porque "$379" también puede ser un precio real.
- **Centavos sueltos restantes** (~390) junto a enteros de 3 dígitos o enteros que el OCR deformó.
- **"AHORRA $25 por cada $100"** de heb se lee como un precio de $25.

## Historial

La primera versión (julio de 2026) clasificaba con regex simples y un catálogo de palabras clave (`sources/nlp/01_modulo_nlp.docx`); la v3 agregó el catálogo canónico (`02_modulo_nlp_v3_catalogo.docx`). Desde octubre de 2026 las reglas usan la geometría de la página y se validan con el evaluador; su historia detallada está en los mensajes de commit (`git log -- nlp/`) y en Engram (proyecto `pricescraper_ss`, temas `experimentos/producto/*` y `experimentos/qa/*`).
