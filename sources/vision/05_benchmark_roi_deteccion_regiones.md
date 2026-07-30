# Benchmark de deteccion de regiones ROI (jul 2026)

Continua la cronologia de `sources/vision/01` a `04`. Evalua si vale la pena
integrar deteccion de regiones (ROI) al pipeline de OCR/NLP: usar
`cv2.findContours`/`HoughLinesP` para detectar los recuadros que delimitan
cada producto en el folleto, correr OCR por region en vez de por pagina
completa, y asociar producto-precio por contenedor visual en vez de por
distancia de bounding boxes. Idea propuesta originalmente en
`sources/nlp/02_modulo_nlp_v3_catalogo.docx` (mejora futura de mayor impacto,
estimada en subir la tasa util de NLP de 42-49% a 65-75%).

## Implementacion

- `vision/region_detector.py`: `detectar_regiones()` (candidatas via OpenCV),
  `calificar_regiones()` (marca una region como "confiable" si algun bloque
  OCR con patron de precio cae dentro de ella), `dibujar_regiones()`
  (visualizacion verde/rojo para revision manual).
- `probar_regiones.py`: harness de benchmark. Preprocesa con el perfil de
  produccion (`color_normal`, ancho 1500px), corre EasyOCR de pagina completa
  (mismo OCR que ya corre en produccion, sin costo extra), detecta y califica
  regiones, y guarda un CSV de resumen. Flags `--full` (corpus completo en vez
  de muestra curada), `--gpu`, `--sin-imagenes`.

## Metodologia

Primero se corrio sobre una muestra curada de 29 paginas / 17 tiendas (CPU,
maquina principal) para iterar el detector. Luego, para tener una lectura
representativa, se corrio sobre el **corpus completo: 250 folletos, 2104
paginas, 17 tiendas**, en una segunda maquina con GPU (RTX 5070, PyTorch
2.10.0+cu130, sm_120) via Cursor, siguiendo instrucciones en un prompt
dedicado. Corrida limpia: 2104/2104 paginas procesadas, 0 errores, 0
paginas omitidas.

Metrica principal: `% de paginas con al menos 1 region "confiable"` (region
candidata que contiene un bloque OCR con patron de precio). Metrica
secundaria: `cobertura de area confiable` (que fraccion de la pagina cubren
las regiones confiables, cuando hay al menos una).

## Resultados

### Global

- 26,039 regiones candidatas detectadas en total.
- 2,054 regiones calificadas como confiables (tienen un precio OCR adentro).
- **41.4% de las paginas (872/2104) tienen al menos 1 region confiable.**
- 58.6% de las paginas (1232/2104) no tienen ninguna.
- Cobertura de area promedio, en paginas con >=1 region confiable: solo 17%
  -- incluso cuando el detector "acierta", no cubre la mayoria de productos
  de la pagina.

### Por tienda (ordenado por % de paginas confiables)

| Tienda           | Folletos | Paginas | % paginas confiables | Cobertura prom. (paginas confiables) |
|-------------------|---------:|--------:|----------------------:|---------------------------------------:|
| desconocidos      |        3 |      36 |                 77.8% |                                  42.8% |
| walmart           |        5 |      61 |                 77.1% |                                  34.6% |
| merco             |       10 |     114 |                 64.9% |                                  17.7% |
| soriana_hiper     |       55 |     572 |                 64.2% |                                  12.9% |
| chedraui          |       16 |     192 |                 63.0% |                                  25.4% |
| soriana_mercado   |       34 |     184 |                 57.1% |                                  11.7% |
| casa_ley          |        7 |      21 |                 47.6% |                                   2.2% |
| bodega_aurrera    |       45 |     175 |                 22.9% |                                   9.2% |
| alsuper           |        5 |      35 |                 20.0% |                                   6.7% |
| tiendas_3b        |        7 |      45 |                 15.6% |                                  11.1% |
| heb               |       14 |      88 |                 13.6% |                                  26.7% |
| la_comer          |       14 |     369 |                 11.4% |                                  16.1% |
| waldos            |       16 |      55 |                 10.9% |                                  12.1% |
| sam's_club        |        3 |      12 |                  8.3% |                                  68.4% |
| costco            |        2 |      81 |                  4.9% |                                  11.6% |
| oxxo              |        4 |      40 |                  2.5% |                                  49.4% |
| s-mart            |       10 |      24 |                  0.0% |                                     -- |

Datos completos (pagina por pagina): `data/processed/_v6_regiones_datacompleta/resumen.csv`.
Log completo de la corrida: `data/processed/_v6_regiones_datacompleta/benchmark_completo.log`.
(Copia de datos de prueba, no forma parte del datalake principal de produccion.
`_v5_regiones_dataparcial/` guarda la corrida previa sobre la muestra curada
de 29 casos, con las imagenes de comparacion verde/rojo. Numeracion de
version dentro de la linea completa de benchmarks en `data/processed/`: v1
color vs bn, v2/v3 reservados para Tesseract vs EasyOCR -- aun no corridos
a esta escala --, v4 crops_candidatos, v5-v6 este benchmark de regiones.)

## Interpretacion

Confirma con datos a escala completa la hipotesis que ya se habia visto en la
muestra curada de 29 casos: **lo que predice si ROI funciona no es la tienda
en si, sino si el diseño del folleto dibuja un recuadro real alrededor del
precio (layout tipo grid)**.

- Tiendas con layout de grid consistente (walmart, merco, soriana_hiper,
  chedraui, soriana_mercado, casa_ley) concentran la mayoria del corpus por
  volumen de paginas (~1180/2104, ~56%) y tienen 47-78% de paginas
  confiables.
- Tiendas sin grid o con el precio flotando fuera del recuadro del producto
  (s-mart, oxxo, costco, sam's_club, waldos, la_comer, heb, tiendas_3b,
  alsuper, bodega_aurrera) caen a 0-23% -- el detector casi no encuentra
  nada util ahi. Esto es consistente con observaciones previas puntuales:
  "costco: producto aislado a pagina completa (sin grid)" y "la_comer: precio
  flota AFUERA del recuadro de producto" (bitacora historica, jul 2026).

## Decision

**No se integra ROI como reemplazo general en `load/load.py`.** Casi la
mitad del corpus (44%, 924/2104 paginas) casi no se beneficia, y reemplazar
el metodo actual (asociacion por distancia de bounding boxes) por ROI de
forma universal arriesgaria perder senal en esas tiendas sin ganar nada a
cambio. La cobertura de area baja (17% promedio) tambien indica que, aun en
paginas "confiables", ROI no reemplaza la cobertura de productos que da el
metodo actual.

Camino alternativo, no implementado: usar ROI como señal *adicional*,
limitada a un subconjunto de tiendas con layout grid confirmado (walmart,
merco, soriana_hiper, soriana_mercado, chedraui), no como pipeline universal.
Queda como pendiente futuro si se retoma este trabajo.

## Estado del codigo

`vision/region_detector.py` y `probar_regiones.py` quedan en la branch
`feature/roi-integration` (no mergeada a `main`). El punto de partida antes
de esta investigacion esta marcado con el tag git `pre-roi-integration` sobre
`main`.
