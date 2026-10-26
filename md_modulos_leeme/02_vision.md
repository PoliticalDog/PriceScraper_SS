# Módulo de visión

El módulo de visión es el segundo eslabón del pipeline. Recibe las páginas de folleto que descargó el scraper (`pagina_NNN.webp`), las prepara con OpenCV y extrae su texto con EasyOCR. Para cada bloque de texto guarda la confianza y la caja (`bbox`) en `ocr_resultado.json`, que después lee el módulo NLP. También incluye el detector de regiones (ROI) que usa el módulo de carga para asociar cada precio con el producto de su misma casilla.

## Propósito y alcance

Las páginas de los folletos son difíciles para un OCR: fondos de colores intensos, tipografías decorativas, precios con centavos en superíndice y texto sobre fotografías. Además, cada tienda publica sus imágenes a un tamaño distinto. El módulo normaliza el tamaño de la imagen, aplica el filtro que mejor le funciona a cada tienda y lee el texto sin interpretarlo.

| Hace | No hace |
|---|---|
| Escalar cada página a un ancho objetivo y aplicar el perfil de filtros de su tienda | Decidir qué es precio, producto o promoción (NLP) |
| Extraer bloques de texto con su confianza y su caja, ordenados de arriba abajo | Unir el producto con su precio (load; el ROI solo le da las casillas) |
| Guardar la página preprocesada y una imagen de comparación original/procesada | Guardar en la base de datos (load) |
| Detectar recuadros de producto (ROI) en las tiendas con diseño de retícula | Medir la calidad contra el ground truth (evaluador) |

Tabla: Alcance del módulo de visión

## Entradas y salidas

**Entrada:** `data/raw/<fuente>/<tienda>/<folleto>/pagina_NNN.webp`, producido por el scraper. Solo se procesan las carpetas con al menos un archivo `pagina_*.webp`.

**Salida:** en `data/processed/<fuente>/<tienda>/<folleto>/` quedan tres cosas:

- `ocr_resultado.json`, el contrato con el NLP;
- cada página preprocesada, con el mismo nombre (`pagina_NNN.webp`), que el visor de origen del dashboard usa para dibujar las cajas;
- `comparacion.jpg`, con la primera página original y la procesada lado a lado.

El JSON lo arma `procesar_carpeta` en `probar_vision.py`. Trae los metadatos del folleto y, por página, su ancho real después del preprocesamiento (`ancho_pagina`), la confianza promedio y los bloques:

```
{"fuente": "tiendeo", "tienda": "bodega_aurrera", "folleto_id": "413505",
 "motor_ocr": "easyocr", "perfil_imagen": "color_normal", "total_paginas": 6,
 "paginas": [ ...,
   {"pagina": "pagina_003.webp", "ancho_pagina": 1800, "confianza_prom": 0.642,
    "bloques": [
      {"texto": "Ahorra mucho más", "confianza": 0.909,
       "bbox": {"x": 209, "y": 32, "ancho": 706, "alto": 98}, "motor": "easyocr"},
      {"texto": "Antes: $3,990", "confianza": 0.834,
       "bbox": {"x": 279, "y": 456, "ancho": 251, "alto": 44}, "motor": "easyocr"},
      {"texto": "$429", "confianza": 0.675,
       "bbox": {"x": 1261, "y": 520, "ancho": 303, "alto": 129}, "motor": "easyocr"},
      {"texto": "Atvio R Licuadora", "confianza": 0.458,
       "bbox": {"x": 1274, "y": 651, "ancho": 229, "alto": 36}, "motor": "easyocr"},
      {"texto": "6 velocidades", "confianza": 0.992,
       "bbox": {"x": 1295, "y": 683, "ancho": 179, "alto": 31}, "motor": "easyocr"}, ...]}, ...],
 "confianza_global": 0.674, "total_bloques": 429}
```

Ejemplo real recortado: bodega_aurrera, folleto 413505, página 3 (tiendeo). La página tiene 95 bloques; aquí se muestran 5.

Las coordenadas de `bbox` están en píxeles de la imagen **preprocesada**, no de la original. Por eso existe `ancho_pagina`: el NLP escala sus umbrales con él (`factor_escala = ancho_pagina / 1500`, ver `03_nlp.md`), el evaluador lo usa para recortar la imagen original y el visor del dashboard convierte las cajas a porcentajes. `confianza_global` es el promedio de las confianzas de cada página, no de todos los bloques.

Al 26-oct-2026 hay 782 `ocr_resultado.json` de tiendeo y 39 de ofertomat (conteo de archivos en `data/processed/`).

Este JSON lo consumen `nlp/salida_json.py` (`clasificar_paginas_ocr`), `load/load.py` (`_leer_ocr`, que guarda en la BD `perfil_imagen`, el total de bloques y la confianza de cada página), el evaluador y `dashboard/origen.py`. Si cambian los nombres de las claves o la forma de `bbox`, se rompen todos esos módulos.

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `vision/preprocessor.py` | Filtros OpenCV, los seis perfiles y la configuración por tienda | `Preprocessor` (`procesar`, `procesar_y_guardar`, `guardar_comparacion`), `PERFILES`, `obtener_preprocesador`, `RESOLUCION_POR_TIENDA`, `PERFIL_POR_TIENDA`, `resolucion_para_tienda`, `perfil_para_tienda` |
| `vision/ocr_engine.py` | Envoltura de EasyOCR y Tesseract con salida común | `OCREngine.extraer_texto`, `ResultadoOCR` (`bbox_simple`), `MOTORES_DISPONIBLES`, `_ordenar_resultados` |
| `vision/region_detector.py` | Detección de recuadros de producto (ROI) y asociación precio-producto dentro de una casilla | `detectar_regiones`, `calificar_regiones`, `asociar_producto_por_region`, `dibujar_regiones` |
| `probar_vision.py` | Orquestador: menú, modo prueba y modo batch; escribe el JSON | `procesar_carpeta`, `modo_prueba`, `modo_batch` |
| `catchup_tiendeo.py` | OCR y NLP de lo pendiente en una pasada, con opción de GPU | `catchup_vision(fuente, usar_gpu)` |
| `evaluador/ocr_experimental.py` | OCR en CPU sobre las páginas de dev para medir un cambio sin tocar producción | `correr_ocr`, `version_ocr` |

Tabla: Archivos del módulo de visión

`vision/region_detector.py` no lo llama `probar_vision.py`. Lo usan `load/load.py` (`candidatas_roi_pagina`, `regiones_con_precio`, `construir_registros_pagina`) y el evaluador. En `borradores/` quedan los scripts con los que se midió el ROI (`probar_regiones.py`, `probar_hibrido_roi.py`, `revisar_desacuerdos.py`), que no forman parte del pipeline.

## Cómo funciona

### Flujo por folleto

```
data/raw/<fuente>/<tienda>/<folleto>/pagina_NNN.webp
   │
   ├─ ¿ya existe ocr_resultado.json?  sí y sin forzar → se salta el folleto
   ├─ perfil y ancho de la tienda     perfil_para_tienda / resolucion_para_tienda
   ├─ comparacion.jpg                 primera página, original | procesada
   │
   ├─ por cada página:
   │     Preprocessor.procesar_y_guardar → data/processed/.../pagina_NNN.webp
   │     cv2.imread de la página guardada (ndarray, 3 canales)
   │     OCREngine.extraer_texto(imagen, motor)
   │        ├─ EasyOCR readtext(detail=1, paragraph=False), confianza > 0.1
   │        └─ orden de lectura: fila de 20 px, luego x
   │     → {"pagina", "ancho_pagina", "confianza_prom", "bloques": [...]}
   │
   └─ ocr_resultado.json (+ confianza_global, total_bloques)
```

La imagen que entra al OCR se vuelve a leer del disco después de guardarse. En la primera versión, `procesar_y_guardar()` devolvía la ruta y esa ruta se pasaba al OCR, y EasyOCR fallaba con "Invalid input type"; se separó guardar de leer. `evaluador/ocr_experimental.py` hace lo mismo en memoria (`cv2.imencode` y `cv2.imdecode`), para incluir también la compresión del `.webp` y que sus mediciones sean comparables.

### Preprocesamiento

`Preprocessor.procesar` aplica los pasos activos de su perfil siempre en este orden:

```
1. escalar            cv2.resize INTER_CUBIC al ancho objetivo (alto proporcional)
2. CLAHE              en el canal L de LAB, clipLimit=2.0, cuadrícula 8x8
3. sharpening         filter2D con el kernel [[0,-1,0],[-1,5,-1],[0,-1,0]]
4. escala de grises   cvtColor BGR→GRAY
5. reducir ruido      GaussianBlur 3x3
6. corregir rotación  Canny + HoughLines; gira solo si la mediana pasa de 1°
7. binarizar          adaptiveThreshold GAUSSIAN_C, blockSize=11, C=2
```

El escalado es **adaptativo**. Con `escala_factor=None`, el factor es `ancho_objetivo / ancho_original`: una página de 900 px sube a 1800 y una de 2400 baja a 1800. Si la página ya mide el ancho objetivo, no se toca. Los seis perfiles usan escalado adaptativo.

| Perfil | Pasos activos | Uso actual |
|---|---|---|
| `color_suave` | Escalado | Ninguna tienda; perfil de respaldo de `obtener_preprocesador` |
| `color_normal` | Escalado + sharpening | **Default** (`PERFIL_DEFAULT`) y perfil del ROI |
| `color_fuerte` | Escalado + CLAHE + sharpening | Ninguna tienda |
| `bn_suave` | Escalado + grises | casa_ley y s-mart |
| `bn_normal` | Escalado + grises + gaussiano + rotación | Ninguna tienda |
| `bn_fuerte` | Escalado + grises + gaussiano + rotación + binarización | Ninguna tienda; el peor en todos los benchmarks |

Tabla: Perfiles de preprocesamiento (vision/preprocessor.py, PERFILES)

Los perfiles `color_*` se pensaron para EasyOCR y los `bn_*` para Tesseract. En la práctica, producción usa EasyOCR con los dos tipos. `obtener_preprocesador(nombre, ancho_objetivo)` devuelve el perfil del catálogo `PERFILES`. Si se pide otro ancho, devuelve una copia con ese ancho. Si el nombre no existe, avisa en el log y usa `color_suave`, no el default de producción.

### Perfil y resolución por tienda

Cada tienda usa el perfil y el ancho que mejor le funcionaron en los experimentos. Si una tienda no aparece en las tablas, usa `color_normal` a 1800 px (`ANCHO_OBJETIVO_DEFAULT`):

| Tienda | Perfil | Ancho (px) | F1 producto | F1 precio |
|---|---|---|---|---|
| chedraui | color_normal | 1200 | 0.641 | 0.578 |
| alsuper | color_normal | 1350 | 0.483 | 0.394 |
| costco | color_normal | 1350 | 0.736 | 0.342 |
| merco | color_normal | 1350 | 0.580 | 0.367 |
| walmart | color_normal | 1500 | 0.598 | 0.326 |
| casa_ley | **bn_suave** | 1800 | 0.592 | 0.296 |
| s-mart | **bn_suave** | 1800 | 0.434 | 0.727 |
| demás tiendas | color_normal | 1800 | — | — |

Tabla: Configuración OCR por tienda (RESOLUCION_POR_TIENDA y PERFIL_POR_TIENDA) | Fuente: experimento GPU perfil × resolución, 05-oct-2026 (sources/vision/configuracion_ocr_por_tienda.md)

Las cifras son F1 contra el ground truth de las 315 páginas etiquetadas, con el evaluador de entonces (`evaluador_calidad.comparar_pagina`, que medía producto y precio por separado). No se pueden comparar con el F1 de registros completos del evaluador actual (`03_nlp.md`). Se verificaron los perfiles y anchos que usan hoy los JSON de producción: chedraui tiene sus 591 páginas a 1200 px, walmart a 1500, alsuper a 1350, y casa_ley y s-mart están en `bn_suave` a 1800.

### Motores OCR

`OCREngine.extraer_texto(imagen, motor)` acepta `"easyocr"` (default) o `"tesseract"` (`MOTORES_DISPONIBLES`). Si recibe otro nombre, usa EasyOCR. Los dos motores son **opciones independientes que se eligen en cada corrida**: no hay respaldo automático de uno al otro.

| Motor | Configuración | Filtro | Uso |
|---|---|---|---|
| EasyOCR 1.7.2 | `idiomas=["es", "en"]`, `detail=1`, `paragraph=False`, `gpu=usar_gpu` | confianza > 0.1 | Producción |
| Tesseract (pytesseract 0.3.13) | `--oem 3 --psm 11 -l spa+eng` | confianza ≥ 10/100 | Solo pruebas; descartado (ver Reglas y decisiones) |

Tabla: Motores OCR (vision/ocr_engine.py)

- **Inicialización perezosa.** EasyOCR carga sus modelos de deep learning (tarda unos segundos) la primera vez que se llama `extraer_texto`, no al crear el `OCREngine`. En un batch el costo se paga una sola vez.
- **Caja común.** `ResultadoOCR.bbox` guarda los cuatro vértices; `bbox_simple` lo convierte en `{x, y, ancho, alto}`, que es lo que se escribe en el JSON.
- **Orden de lectura.** EasyOCR devuelve los bloques en orden de detección. `_ordenar_resultados` los ordena por `(y_min // 20, x_min)`: filas de 20 px de tolerancia y, dentro de cada fila, de izquierda a derecha.

### CPU y GPU

`probar_vision.py` siempre crea el motor en CPU (`OCREngine(..., usar_gpu=False)`). Para GPU está `catchup_tiendeo.py --gpu`, que primero comprueba `torch.cuda.is_available()` y se detiene si no hay CUDA. La laptop del proyecto no tiene GPU: los reprocesos masivos se corren en otra PC y se traen por USB (skill `preparar-traspaso-gpu`).

| Dato | Valor | Fuente |
|---|---|---|
| OCR en CPU | 35-45 s por página; dev completo, unas 2 h | Engram #135, 11-oct-2026 |
| OCR en GPU (RTX 5070) | 1.9-10.3 s por página según la tienda | `configuracion_ocr_por_tienda.md`, 05-oct-2026 |
| Catch-up en GPU | 103 folletos en ~42 min, 0 errores | Engram #63, 07-ago-2026 |
| CPU frente a GPU | En heb/416210 p1 coincidieron 74 de 81 textos únicos | Engram #135 |

Tabla: Tiempos de OCR en CPU y GPU

Como EasyOCR no da exactamente lo mismo en CPU que en GPU, un experimento de OCR compara su cambio contra una base corrida **también en CPU** (`python -m evaluador ocr`), nunca contra los JSON de producción, que salieron de la GPU.

### Detección de regiones (ROI)

Algunos folletos dibujan un recuadro alrededor de cada producto. Si el precio y un nombre están dentro del mismo recuadro, ese nombre es casi seguro el producto correcto, aunque el nombre de la casilla de arriba esté más cerca. `vision/region_detector.py` aprovecha eso en tres pasos:

```
imagen original → Preprocessor "color_normal" (1800 px)
   │
   ├─ detectar_regiones: solo geometría
   │     Canny(50,150) → dilate 3x3 → findContours
   │     filtros: área entre 0.1% y 50% de la página, rectangularidad ≥ 0.6,
   │              4 a 8 vértices (approxPolyDP), proporción lado largo/corto ≤ 3.0
   │     _quitar_anidadas: si dos cajas se solapan ≥ 85% de la menor, queda la mayor
   │
   ├─ calificar_regiones: ¿hay un precio adentro?
   │     un precio del NLP con ≥ 50% de su caja dentro de la región
   │     y cuyo texto coincide con un patrón de precio de RegexExtractor
   │
   └─ asociar_producto_por_region(precio, productos, regiones confiables)
         región que contiene el centro del precio → productos con su centro adentro
         1 candidato → ese; candidatos dispersos (> 50% del ancho) → None
         varios → el más cercano por arriba del precio
         None → load usa la asociación por cercanía
```

Solo se usa en las tiendas de `TIENDAS_ROI_HIBRIDO` en `load/load.py` (walmart, chedraui, soriana_hiper y soriana_mercado, con el slug de `data/raw`). En las demás tiendas, si falta la imagen o si algo falla, `_detectar_regiones_pagina` devuelve `None` y el precio se asocia por cercanía, igual que antes de que existiera el ROI. El evaluador guarda las candidatas en `data/processed/_eval/cache_regiones/<version_vision>/`. Esa versión es un hash de `preprocessor.py` y `region_detector.py`, así que el caché se invalida solo cuando cambia alguno de los dos.

`dibujar_regiones` pinta las regiones en verde (con precio) o rojo (sin precio) para revisarlas a mano.

## Cómo se corre

```
venv/Scripts/python.exe probar_vision.py
   1 → modo prueba: elige una carpeta, siempre reprocesa (forzar=True)
   2 → modo batch: todo data/raw/ que no tenga ocr_resultado.json; pide confirmación
   Motor:      Enter = EasyOCR
   Perfil:     Enter = el de cada tienda (o 1-6 para forzar uno a todo el batch)
   Resolución: Enter = la de cada tienda (o 1200/1350/1500/1800 para forzarla)

venv/Scripts/python.exe catchup_tiendeo.py [--gpu] [--fuente tiendeo|ofertomat|todas]
   OCR + NLP de los folletos pendientes, con perfil y resolución por tienda
```

Los dos modos de `probar_vision.py` generan `comparacion.jpg` y escriben su log en consola y en `logs/vision.log`, que rota a los 5 MB y guarda 5 archivos. En modo prueba, si la confianza global queda bajo 50%, sugiere otro perfil. Una opción fuera de rango en los menús de perfil o resolución vuelve a "por tienda", y en el de motor vuelve a EasyOCR (commit 05d4a96).

Para medir un cambio de `preprocessor.py` u `ocr_engine.py` sin tocar producción:

```
venv/Scripts/python.exe -m evaluador ocr --nombre base_heb --tienda heb      # base, código actual, CPU
   ... editar vision/preprocessor.py u ocr_engine.py ...
venv/Scripts/python.exe -m evaluador ocr --nombre cambio_heb --tienda heb
venv/Scripts/python.exe -m evaluador correr --ocr-exp base_heb --tienda heb
venv/Scripts/python.exe -m evaluador correr --ocr-exp cambio_heb --tienda heb
venv/Scripts/python.exe -m evaluador comparar <corrida_base> <corrida_cambio>
```

`evaluador ocr` acepta además `--max-paginas`, `--perfil`, `--resolucion` y `--forzar`. Escribe en `data/processed/_eval/ocr_exp/<nombre>/`, solo con las páginas de dev que tienen precio en el ground truth. Se puede reanudar si se interrumpe, y se niega a mezclar resultados de código distinto (compara `version_ocr`, un hash de los dos archivos). Al 26-oct-2026 esa carpeta está vacía: todavía no hay experimentos de OCR guardados con esta herramienta.

## Reglas y decisiones

- **EasyOCR solo, sin Tesseract de respaldo.** La propuesta original planteaba Tesseract como respaldo automático cuando la confianza de EasyOCR bajara de 40%. Ese respaldo nunca quedó en el código y se descartó con dos mediciones:
  - En el folleto de Bodega Aurrerá 412322, mezclar Tesseract hundía la tasa útil del NLP de 48% a 9-19%. Leía más bloques, pero eran ruido: nombres de estados, texto legal, tallas (bitácora de `sources/vision/01` a `04`, resumida en Engram #29).
  - De 150 precios que EasyOCR perdía por el superíndice de centavos, Tesseract recuperó 3 con `bn_suave`, 2 con `bn_normal` y 0 con `bn_fuerte` (07-ago-2026, Engram #62).

  El problema era la nitidez de la imagen, no el motor. Tesseract sigue disponible en el menú para pruebas.
- **`color_normal` como default.** En el benchmark de seis perfiles sobre Bodega Aurrerá 412322, `color_normal` ganó con 54% de tasa útil. El color solo ayudaba combinado con sharpening: `color_suave` y `bn_suave` daban lo mismo, y `color_fuerte` destruía el texto igual que la binarización (Engram #29, `sources/vision/03_C_*`). `bn_fuerte` fue el peor perfil en los tres análisis independientes (visual, Tesseract y EasyOCR; Engram #96).
- **Perfil por tienda solo con mejora robusta.** En septiembre de 2026, `bn_suave` le ganó a `color_normal` en 22 páginas nativas de ~900 px. En el experimento GPU de octubre (315 páginas, 3 perfiles × 5 resoluciones, 4,725 corridas de OCR) el global empató: configuración vigente con F1 producto 0.579 y F1 precio 0.381, `bn_suave` a 1800 px con Δ −0.002. La ventaja de septiembre era propia de imágenes chicas sin escalar. Por eso no se cambió el default, sino solo dos tiendas, que pasaron tres pruebas a la vez (IC 95% > 0 por página, IC 95% > 0 por folleto y mejora en todos sus folletos):
  - casa_ley, `bn_suave`@1800 frente a `color_normal`@2500: Δ +0.042, IC por folleto [+0.027, +0.058], 4 de 4 folletos;
  - s-mart, `bn_suave`@1800: Δ +0.060, IC [+0.049, +0.078], 4 de 4 folletos.

  Commit 7b012b6 (`sources/vision/10_experimento_perfil_resolucion_gpu.docx`, Engram #115).
- **1800 px de default y resolución por tienda.** El experimento de 4 resoluciones (26-sep-2026; 30 folletos, 114 páginas × 4) dio 1800 px como ganador global, con F1 producto 0.513 y F1 precio 0.422 y mejora en cada escalón. Pero el resultado no se repetía en todas las tiendas: alsuper empeoraba con más resolución y casa_ley mejoraba mucho (Engram #109, `sources/vision/09_*`). El experimento GPU de octubre confirmó la tabla por tienda: en chedraui, alsuper, costco, merco y walmart, la resolución vigente queda primera o empatada (commit 7e7e51b).
- **Más resolución no ayuda a todas las tiendas.** En alsuper, subir a 2500 px bajó los precios de 25.3% a 18.8%, incluso con los umbrales del NLP ya escalados. Entre 60% y 70% de los bloques nuevos eran lecturas de confianza 0.10-0.20 que partían texto que a 1500 px se leía bien: su fuente nativa (~17 px) ya está en el límite de EasyOCR. En walmart, bodega_aurrera, merco, s-mart y waldos, pasar de 1500 a 2500 px no cambió nada (`sources/vision/08_experimento_resolucion_ocr_por_tienda.md`, 19-ago-2026).
- **`ancho_pagina` en la salida.** Se agregó para que el NLP escale sus umbrales en píxeles cuando las tiendas se procesan a distintos anchos (commit 19aba03). Sin ese dato, un cambio de resolución alteraría la clasificación de precios.
- **ROI como señal adicional, no como reemplazo.**
  - En el corpus completo de julio de 2026 (2,104 páginas), solo 41.4% de las páginas tenía al menos una región con precio. La cobertura de área promedio era de 17%, y el ROI casi no encontraba nada en folletos sin retícula como s-mart, oxxo o costco (`sources/vision/05_benchmark_roi_deteccion_regiones.md`).
  - Por eso se integró como híbrido con respaldo por cercanía, solo en las cuatro tiendas con retícula. Sobre 2,880 precios no hubo ninguna regresión, por diseño del respaldo.
  - `PROPORCION_MAX = 3.0` y `DISPERSION_MAX_FRACCION = 0.5` bajaron los desacuerdos con la asociación por cercanía de 9.0% a 4.6%, a cambio de resolver menos precios por ROI (22.2% → 12.7%). Esos dos filtros evitan regiones que juntan dos casillas sin borde entre ellas (`sources/vision/06_hibrido_roi_asociacion_producto_precio.md`, commit 1c06941, Engram #37).
  - **No agregues una tienda a `TIENDAS_ROI_HIBRIDO` sin medirla con el evaluador.**

## Configuración

| Constante | Valor | Dónde | Para qué |
|---|---|---|---|
| `ANCHO_OBJETIVO_DEFAULT` | 1800 px | `Preprocessor` | Ancho de escalado si la tienda no está en `RESOLUCION_POR_TIENDA` (antes 1500) |
| `RESOLUCION_POR_TIENDA` | chedraui 1200; alsuper, costco y merco 1350; walmart 1500; casa_ley 1800 | `preprocessor.py` | Ancho por tienda |
| `PERFIL_DEFAULT` / `PERFIL_POR_TIENDA` | `color_normal` / casa_ley y s-mart → `bn_suave` | `preprocessor.py` | Perfil por tienda |
| `MOTORES_DISPONIBLES` | `["easyocr", "tesseract"]` | `ocr_engine.py` | Motores aceptados |
| Confianza mínima del OCR | > 0.1 (EasyOCR), ≥ 10 (Tesseract) | `_extraer_easyocr`, `_extraer_tesseract` | Quita ruido extremo antes de escribir el JSON |
| Tolerancia de fila | 20 px | `_ordenar_resultados` | Agrupa bloques en filas para el orden de lectura |
| `AREA_MIN_FRACCION` / `AREA_MAX_FRACCION` | 0.001 / 0.5 | `region_detector.py` | Tamaño admitido de una región |
| `RECTANGULARIDAD_MIN` | 0.6 | `region_detector.py` | Área del contorno / área de su caja |
| `PROPORCION_MAX` | 3.0 | `region_detector.py` | Descarta filas de casillas fusionadas |
| `SOLAPE_MIN_FRACCION` | 0.5 | `region_detector.py` | Parte de la caja del precio que debe caer en la región |
| `DISPERSION_MAX_FRACCION` | 0.5 | `region_detector.py` | Dispersión máxima de los productos candidatos en una región |
| `TIENDAS_ROI_HIBRIDO` | walmart, chedraui, soriana_hiper, soriana_mercado | `load/load.py` | Tiendas donde se usa el ROI |

Tabla: Constantes principales del módulo de visión

Los parámetros de los filtros (kernel de sharpening, CLAHE, `blockSize=11` y `C=2` de la binarización, Canny 50/150) están fijos dentro de los métodos de `Preprocessor` y de `detectar_regiones`; no son constantes con nombre.

Dependencias (`requirements.txt`): `easyocr==1.7.2`, `opencv-python==4.13.0.92`, `torch==2.10.0`, `pytesseract==0.3.13`, `numpy==2.4.3`. Tesseract necesita además el ejecutable instalado aparte. En Git Bash puede no estar en el PATH; en ese caso pytesseract solo deja en el log "Tesseract no disponible" (Engram #96).

## Pruebas

No hay pruebas unitarias directas de `vision/`: el OCR y los filtros se validan con el evaluador contra el ground truth. Las pruebas de `tests/` que tocan el módulo son:

- `test_load_legibilidad.py::test_roi_que_elige_un_ilegible_pasa_a_cercania`: si el ROI elige un bloque ilegible ("Sskrvih", confianza 0.21, Chedraui 428354), el precio pasa a la asociación por cercanía.
- `test_evaluador.py::test_ocr_experimental_nombre_seguro` y `test_ocr_exp_obliga_nlp_memoria`: el nombre de un experimento de OCR no puede salirse de su carpeta, y un OCR experimental obliga a regenerar el NLP en memoria.
- `test_guardia_agente.py::test_ocr_experimental_solo_vision_y_qa`: solo los agentes de visión y QA pueden correr `evaluador ocr`, y el agente de visión no puede correr `probar_vision.py` (que escribe en producción).

```
venv/Scripts/python.exe -m pytest tests/test_load_legibilidad.py tests/test_evaluador.py tests/test_guardia_agente.py -q
venv/Scripts/python.exe -m evaluador correr --split dev      # calidad de los JSON en disco (--nlp disco, default) contra el ground truth
```

Las cuatro pruebas de arriba pasan al 26-oct-2026. El ground truth tiene 77 folletos, 315 páginas y 2,413 productos de 16 tiendas, repartidos en dev (56 folletos) y holdout (21) (`sources/vision/ground_truth_resumen.md`, 21-oct-2026). Los cambios de visión los propone el agente `especialista-vision` y los verifica `qa-evaluador` (skill `ciclo-experimento`). El hook `.claude/hooks/guardia_agente.py` solo deja al agente de visión editar `vision/region_detector.py`, `vision/preprocessor.py`, `vision/ocr_engine.py`, `load/load.py` y `tests/`.

## Limitaciones conocidas y pendientes

- **Coordenadas del ROI en chedraui y walmart.** `candidatas_roi_pagina` preprocesa la imagen con `obtener_preprocesador("color_normal")`, que escala a 1800 px. Pero el OCR de chedraui está a 1200 px y el de walmart a 1500 (verificado en sus `ocr_resultado.json`). Las regiones y las cajas del NLP quedan entonces en escalas distintas (1.5× y 1.2×), y en esas dos tiendas el ROI compara posiciones que no corresponden. Ya estaba anotado como pendiente desde el 05-oct-2026 (Engram #115) y no se ha medido su efecto. soriana_hiper y soriana_mercado no se ven afectadas, porque procesan a 1800. La idea de solución es preprocesar el ROI con `resolucion_para_tienda` y medir con el evaluador antes y después.
- **Precios con superíndice.** Según el análisis de causa raíz de agosto de 2026, más del 70% de los precios no recuperados era pérdida real del OCR: el superíndice de centavos sale truncado o mal leído. Ni otro motor ni más resolución de toda la página lo resolvieron. Queda pendiente probar un recorte y reescalado de las zonas de precio (Engram #62 y #63).
- **alsuper y waldos.** En alsuper la fuente es tan chica que EasyOCR la fragmenta, y en waldos el F1 de producto ronda 0.17-0.19 a cualquier resolución. En los dos casos la causa no es la resolución y está sin investigar.
- **Muestras chicas.** casa_ley (12 páginas) y s-mart (8 páginas) cambiaron de perfil con pocos datos. Hay que revisarlo cuando crezca el ground truth. oxxo, sam's_club y waldos tienen menos de 20 productos etiquetados cada una.
- **Corrección de rotación.** Está activa en `bn_normal` y `bn_fuerte`, pero en los folletos digitales no sirve (las páginas no vienen giradas). Se dejó por compatibilidad.
- **Canales de color.** `procesar_carpeta` le pasa a EasyOCR la imagen en BGR, como la entrega `cv2.imread`, mientras que `extraer_texto_desde_archivo` la convierte a RGB. Con esa diferencia se midieron todos los benchmarks, así que el resultado sigue siendo comparable. No se ha medido si convertir a RGB cambia algo.

## Historial

| Fecha | Cambio | Referencia |
|---|---|---|
| jun-2026 | Primera versión: tres perfiles (suave, normal, fuerte) con factor fijo de ×1.5, `fastNlMeansDenoising` y Tesseract como respaldo previsto. Benchmark en Bodega Aurrerá 412322 (4 páginas): suave 252 bloques y 67% de confianza, normal 251 y 66%, fuerte 192 y 52% | Propuesta, capítulo de visión; `sources/vision/00_modulo_vision.docx` |
| jun-2026 | Escalado adaptativo a un ancho objetivo (default 1350 px, luego 1500) y seis perfiles (tres de color con sharpening/CLAHE y tres en B/N con gaussiano) | Commit 69b3586; `sources/vision/04_escalado_adaptativo.docx` |
| jul-2026 | Detector de regiones ROI e integración híbrida en load | Commits 888efde y 1c06941; `sources/vision/05_*` y `06_*` |
| ago-2026 | Se descarta Tesseract como respaldo; `ancho_pagina` en la salida; casa_ley a 2500 px | Engram #62; commit 19aba03; `sources/vision/08_*` |
| sep-oct 2026 | Default a 1800 px, `RESOLUCION_POR_TIENDA` y `PERFIL_POR_TIENDA` (casa_ley vuelve a 1800 con `bn_suave`); `catchup_tiendeo.py --gpu`; reproceso completo en GPU | Commits 7e7e51b y 7b012b6; `sources/vision/09_*` y `10_*` |
| oct-2026 | OCR experimental en CPU para medir cambios con el evaluador | `evaluador/ocr_experimental.py`; Engram #135 |

Tabla: Historial del módulo de visión

Respecto a la propuesta, cambió esto:

- ya no hay respaldo automático con Tesseract;
- hay seis perfiles y no tres, y el default es `color_normal`, no el suave;
- el escalado es a un ancho objetivo por tienda, no un factor fijo de ×1.5;
- el ruido se reduce con `GaussianBlur 3x3`, no con `fastNlMeansDenoising`;
- la rotación se corrige antes de binarizar;
- el modo batch también genera `comparacion.jpg`;
- la salida incluye `ancho_pagina`;
- el módulo suma el detector de regiones.

Siguen vigentes la inicialización perezosa de EasyOCR, el orden de lectura con filas de 20 px, el salto de folletos ya procesados y la separación entre guardar la imagen y leerla.
