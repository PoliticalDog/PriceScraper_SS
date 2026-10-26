# Módulo de carga (load)

El módulo de carga es el cuarto eslabón del pipeline. Lee lo que el NLP clasificó en cada página (`nlp_resultado.json`), decide qué producto y qué precio anterior le tocan a cada precio y escribe el resultado en PostgreSQL. Es la etapa que convierte bloques de texto sueltos en registros "producto + precio" que muestra el dashboard.

## Propósito y alcance

El NLP entrega, por página, listas separadas de precios, productos, atributos y promociones, cada uno con su caja (`bbox`), pero no sabe qué nombre va con qué precio. Load hace esa unión con la geometría de la página y, solo para cuatro tiendas, con las regiones (casillas) que detecta el módulo de visión.

| Hace | No hace |
|---|---|
| Asociar cada precio con su producto y su precio anterior | Leer la imagen ni hacer OCR (vision) |
| Unir el nombre partido en varias líneas | Clasificar bloques ni extraer valores (nlp) |
| Normalizar el nombre y registrar su identidad canónica | Definir el esquema de la BD (`04_base_de_datos.md`) |
| Insertar tiendas, folletos, páginas, extracciones y eventos de campaña | Calcular métricas de calidad (evaluador) |
| Registrar los errores de carga por categoría | Mostrar los datos (dashboard) |

Tabla: Alcance del módulo de carga

Este documento explica qué filas escribe load y con qué lógica. Las tablas, columnas y vistas están en `04_base_de_datos.md`.

## Entradas y salidas

**Entradas.** Por cada folleto, dos archivos en `data/processed/<fuente>/<tienda>/<folleto>/`:

- `nlp_resultado.json`, producido por el NLP (contrato en `nlp/salida_json.py`, descrito en `03_nlp.md`). Load usa de cada página las listas `productos`, `precios`, `precios_anteriores`, `atributos`, `promos` y `eventos_promo`. Las listas `ahorros` y `financiero` no se guardan como filas; solo cuentan para la tasa útil de la página.
- `ocr_resultado.json`, producido por visión. De él salen `perfil_imagen`, `motor_ocr` y, por página, el número de bloques y la confianza promedio. Si falta o está roto, el folleto se carga igual y esas métricas quedan en NULL (`_leer_ocr`).

Fragmento real (recortado) de `tiendeo/sam's_club/421762/nlp_resultado.json`, página 4:

```
{"fuente": "tiendeo", "tienda": "sam's_club", "folleto_id": "421762", "total_paginas": 4,
 "paginas": [{"pagina": "pagina_004.webp",
   "precios":   [{"texto": "$199", "valor": 199.0, "confianza": 0.879,
                  "bbox": {"x": 299, "y": 795, "ancho": 293, "alto": 132}}],
   "productos": [{"texto": "Metco BC",              "bbox": {"x": 289, "y": 606, "ancho": 319, "alto": 78}, ...},
                 {"texto": "Edulcorantede Mesa",    "bbox": {"x": 218, "y": 686, "ancho": 462, "alto": 56}, ...},
                 {"texto": "Baja en Calorías 4 kg", "bbox": {"x": 219, "y": 747, "ancho": 456, "alto": 68}, ...}],
   ...}]}
```

El nombre del producto viene partido en tres bloques. Load los une y el registro queda como "Metco BC Edulcorantede Mesa Baja en Calorías 4 kg" con precio $199 (caso fijado en `tests/test_load_nombre_partido.py`).

Además, load lee la metadata del folleto (título, vigencia, URL, fecha de scraping) de `data/registro_folletos_scrapeados.json`, con la llave `"<fuente>:<folleto_id>"` (`_leer_metadata`). Para las tiendas con ROI también abre la imagen de la página en `data/raw/<fuente>/<tienda>/<folleto>/<pagina>`.

**Salidas.** Filas en PostgreSQL:

| Tabla | Qué escribe load |
|---|---|
| `tiendas` | Una fila por slug de tienda (`_upsert_tienda`, no la duplica) |
| `folletos` | Una fila por `(fuente, folleto_id_fuente)` con la metadata y `estado = 'done'` (`_upsert_folleto`) |
| `paginas` | Una fila por página y, al final de la página, sus totales y métricas OCR (`total_bloques_ocr`, `confianza_ocr_prom`, `tasa_util`) |
| `extracciones` | Una fila por producto aceptado (`PRODUCTO`), precio (`PRECIO`), atributo (`ATRIBUTO`), promoción (`PROMO`) y campaña (`EVENTO_PROMO`) |
| `productos_canonicos` | Upsert de la identidad canónica de cada nombre (ver Normalización) |
| `eventos_promo` | Una fila por campaña y folleto, con la vigencia del folleto |
| `errores_carga` | Un renglón por página o folleto que falló, con su categoría |

Tabla: Tablas que escribe load/load.py

La tabla `alertas` existe en el esquema, pero load no la escribe.

La fila `PRECIO` es la que importa para el dashboard: `valor`, `valor_anterior`, `texto_norm` (el nombre que se muestra), `categoria_nlp`, `producto_extraccion_id` (la fila `PRODUCTO` de la que salió el nombre), `producto_canonico_id` y `metodo_norm`. Un precio sin producto se inserta igual, con esos campos en NULL, y cuenta en `precios_sin_producto`.

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `load/load.py` | Asociación producto-precio (funciones puras, sin BD) y carga a PostgreSQL (clase `Loader`), unas 1,400 líneas | `rutas_nlp`, `construir_registros_pagina`, `asociar_por_cercania`, `nombre_con_unidad`, `nombre_en_pila`, `metodo_nombre`, `emparejar_precios_anteriores`, `categorizar_error`, `Loader` |
| `load/db_builder.py` | Conexión con psycopg 3; si faltan tablas, ejecuta `load/schema.sql` | `get_connection`, `get_cursor` (commit al salir, rollback si hay excepción), `verificar_conexion`, `resumen_bd` |
| `probar_load.py` | Orquestador con menú: cargar un folleto (siempre con `reemplazar=True`), batch, batch forzado y conteo de tablas. Escribe el log en `logs/load.log` | `modo_prueba`, `modo_batch(loader, forzar)`, `modo_ver_bd` |
| `vision/region_detector.py` | Detección de casillas con OpenCV y elección del producto dentro de la casilla del precio | `detectar_regiones`, `calificar_regiones`, `asociar_producto_por_region` |

Tabla: Archivos del módulo de carga

La conexión sale de `DATABASE_URL` en el archivo `.env` de la raíz, con el formato `postgresql://usuario:clave@localhost:5432/pricescraper`. El `.env` no va al repositorio.

La parte de asociación de `load/load.py` no toca la BD a propósito (commit 51100fb): el evaluador (`evaluador/pipeline.py`) llama a `construir_registros_pagina` para medir exactamente lo que llegaría al dashboard, y `evaluador/huella_load.py` corre `Loader._procesar_pagina` con un cursor falso para comparar las escrituras antes y después de un cambio.

## Cómo funciona

### Flujo de un folleto

```
cargar_batch(forzar)
   │  rutas_nlp(): data/processed/{tiendeo,ofertomat}/*/*/nlp_resultado.json
   │  sin forzar: salta los folletos que ya están en la tabla folletos (_ya_cargado)
   │
   └─ cargar_folleto(ruta, reemplazar=forzar)          ── una transacción por folleto
        ├─ lee nlp_resultado.json, ocr_resultado.json y la metadata del scraper
        ├─ _upsert_tienda, _upsert_folleto
        ├─ si reemplazar: DELETE eventos_promo y paginas del folleto (cascada a extracciones)
        ├─ por cada página:
        │     _detectar_regiones_pagina      (solo tiendas ROI; si falla, None)
        │     SAVEPOINT (conn.transaction())
        │        _procesar_pagina
        │           construir_registros_pagina  → productos, precios, atributos
        │           INSERT PRODUCTO (+ upsert productos_canonicos)
        │           INSERT PRECIO, ATRIBUTO, PROMO, EVENTO_PROMO (+ eventos_promo)
        │           UPDATE paginas con totales y métricas OCR
        │     si la página falla: se descarta solo esa página y se anota el error
        └─ _guardar_errores (después del commit o del rollback del folleto)
```

`FUENTES = ("tiendeo", "ofertomat")` es igual al `fuente_enum` del esquema. Solo esas dos carpetas son producción. Antes del commit 9010a75 la búsqueda era recursiva y tomaba también las carpetas de experimentos y respaldos (`_v*`, `*_anterior_*`, con los mismos `folleto_id`): encontraba 1,336 folletos en vez de 694.

### `cargar_batch` y `cargar_folleto`

- `cargar_batch(data_processed, forzar=False)` recorre `rutas_nlp()`. Sin `forzar`, un folleto que ya existe en `folletos` se omite: los cambios de código no llegan a los folletos ya cargados. Con `forzar=True` llama a `cargar_folleto(..., reemplazar=True)` para todos. Devuelve totales: procesados, omitidos, errores, páginas con error, extracciones, eventos y errores por categoría.
- `cargar_folleto(ruta_nlp, metadata=None, reemplazar=False)` toma la identidad del folleto de la ruta (`processed/<fuente>/<tienda>/<folleto>/`) por si el JSON no se puede leer, y después la del JSON. Con `reemplazar=True`, `_upsert_folleto` actualiza la metadata (si un campo viene vacío conserva el anterior) y se borran las páginas y eventos del folleto **dentro de la misma transacción**: si la carga falla, el rollback deshace también el borrado. Sin ese borrado, recargar duplicaba las extracciones, porque `extracciones` no tiene llave natural.
- `_procesar_pagina` va dentro de un SAVEPOINT por página. Antes de 9010a75, un error SQL dejaba la transacción abortada y el commit final revertía el folleto entero sin avisar.

### Registro de errores: `errores_carga` y `categorizar_error`

`categorizar_error` clasifica la excepción por su código SQLSTATE, no por el texto del mensaje, porque el mensaje depende del idioma del servidor:

| Categoría | Origen |
|---|---|
| `tamano_excesivo` | SQLSTATE 22001 (texto más largo que su columna) |
| `valor_fuera_de_rango` | 22003 |
| `formato_invalido` | 22P02, 22007, 22008 |
| `violacion_integridad` | cualquier 23xxx (llave duplicada, FK, NOT NULL) |
| `json_corrupto` | `json.JSONDecodeError` |
| `archivo_faltante` | `FileNotFoundError` |
| `otro` | lo demás |

Tabla: Categorías de error de carga (load/load.py, _CATEGORIA_POR_SQLSTATE)

`_guardar_errores` corre después de que termina la transacción del folleto, para que el rollback de un folleto fallido no se lleve también su registro de error. Cada renglón guarda la corrida (`corrida_at`), fuente, tienda, folleto, página (NULL si falló el folleto completo), categoría, SQLSTATE, mensaje, detalle y ruta. Cuando un folleto vuelve a cargar sin fallar, sus errores abiertos se marcan `resuelto = TRUE`. Si no se puede escribir en `errores_carga`, solo se anota en el log: registrar el error nunca tumba la carga.

En las recargas del 25-oct-2026 los 821 folletos cargaron con 0 errores (Engram #262, #267 y #276).

### `construir_registros_pagina`: qué decide load en una página

Es una función pura (`pag_data`, `regiones_confiables`, `normalizador`) que devuelve `{"productos", "precios", "atributos"}`:

```
productos del NLP ──► productos_aceptados(incluir_ilegibles=True)
                         ├─ candidatos  (legibles + ilegibles: los ve ROI)
                         └─ productos   (solo legibles: cercanía, pila, inserción)
precios_anteriores ─► emparejar_precios_anteriores  (uno a uno)
conteo_vecinos_alineados ─► ¿página "nombre debajo"?  ¿retícula?

1) por cada precio elige un bloque:
      ROI (si hay regiones)  ──► si no elige, o elige un ilegible ──► asociar_por_cercania
2) por cada precio arma el nombre:
      bloque elegido es unidad suelta y está en la columna del precio ──► nombre_con_unidad
      cualquier otro bloque ──► nombre_en_pila (cortando en los bloques elegidos por otros precios)
3) atributos: asociar_por_cercania simple (sin ROI ni pila)
```

Los dos pasos van separados a propósito: primero se eligen los bloques de **todos** los precios y después se arman las pilas, para que una pila no se robe la línea que eligió otro precio.

### `productos_aceptados` y los ilegibles

Cada bloque `PRODUCTO` pasa por `Normalizador.normalizar`. Los que el normalizador descarta (basura, vacíos o más de 150 caracteres) no existen para load. De los que quedan, un bloque es **ilegible** (`_ilegible`) si su nombre sería texto crudo del folleto (método `heuristico`), no tiene categoría del catálogo y su confianza OCR es menor que `CONFIANZA_MINIMA_HEURISTICO = 0.30`.

Los ilegibles no se insertan ni dan nombre a un precio, pero ROI sí los ve: el texto está físicamente en la casilla y cuenta para la dispersión de candidatos. Si ROI elige uno, el precio pasa a cercanía entre los legibles. Cada aceptado legible recibe un `_idx` (su posición entre los legibles) que liga el precio con el id de la fila `PRODUCTO` insertada, más `_resultado`, `_nombre_norm` y la categoría del normalizador.

Por qué 0.30 (commit c1a84b2, dev 11-oct-2026): con ese umbral caían 142 bloques de nombre sucio ("Sskrvih", "Flldi", "Esfecus"), 19 limpios que ya daban un registro erróneo y 2 que daban un registro correcto ("fACAPUNTAS", con confianza 0.20, se pierde). Las señales de texto (consonantes seguidas, palabras sin vocales) se descartaron porque atrapaban casi tantos nombres legítimos como basura ("Hass", "Kit"). Antes del commit 685d16b cualquier bloque `PRODUCTO`, incluidos ruido y nombres de tienda, competía por el precio.

### Elección por regiones ROI

Solo para `TIENDAS_ROI_HIBRIDO = {"walmart", "chedraui", "soriana_hiper", "soriana_mercado"}` (se compara con el slug de la carpeta). `candidatas_roi_pagina` preprocesa la imagen con el perfil `color_normal` y llama a `detectar_regiones`. `regiones_con_precio` se queda con las regiones que contienen algún precio del NLP. Después, `asociar_producto_por_region`:

1. busca la región que contiene el centro del precio;
2. toma los productos cuyo centro cae en esa región;
3. si los candidatos están dispersos en más de la mitad del ancho de la región (`DISPERSION_MAX_FRACCION = 0.5`, señal de dos casillas fusionadas), no decide;
4. si no, elige el más cercano por arriba del precio, o el primero si ninguno está arriba.

Si no hay imagen, la tienda no aplica o el detector falla, la página sigue con cercanía (`_detectar_regiones_pagina` devuelve `None` y deja una advertencia en el log). Esas cuatro tiendas son las únicas donde el benchmark de julio de 2026 confirmó una mejora: sobre 2,880 precios, ROI decidió el 12.7% y discrepó de la cercanía en 4.6% (commit 1c06941; `sources/vision/06_hibrido_roi_asociacion_producto_precio.md`). La parte de visión está en `02_vision.md`.

### Elección por cercanía: `asociar_por_cercania`

Para precios se llama con `admitir_debajo=True`. Compiten los productos legibles a menos de 400 px en horizontal (valor fijo en el código) que estén arriba del precio o, como mucho, `alto_precio + MARGEN_DEBAJO_PRECIO` (100 px) por debajo de su borde superior. Gana la menor distancia vertical entre bordes superiores; en empate, el de arriba. Encima de esa regla general hay tres ajustes por diseño de página:

| Ajuste | Qué hace | Por qué (commit, dev) |
|---|---|---|
| Admitir debajo | El nombre puede estar a la misma altura o debajo del precio | En 153 de 266 precios bien leídos con el producto equivocado, el nombre correcto estaba al lado o debajo (68f215d; F1 3.6 → 5.5) |
| Nombre alineado debajo | En páginas "nombre debajo", gana el producto alineado a la izquierda con el precio (\|dx\| ≤ `ALINEACION_DEBAJO_PX` = 20 px) que empieza bajo su centro, salvo que sea la 2.ª línea de otro nombre (`_continua_otro_bloque`) o tenga su propio precio debajo (`_tiene_precio_propio`) | Chedraui y Walmart: en 32 de 51 precios mal asociados ganaba la columna vecina ("Lavadora" contra "Lavasecadora") o basura OCR ("Veloc") (e4184da; F1 10.9 → 12.1, +19/−1) |
| Columna propia | Si el ganador queda en diagonal (no se traslapa con el precio ni en x ni en y) y hay un candidato que sí se traslapa en x, gana ese | Retículas de Casa Ley, Alsuper y 3B tomaban el nombre de la casilla vecina (ea975ff; F1 12.7 → 13.9, +19/−1) |
| Retícula | En páginas de retícula, entre los candidatos de la columna gana primero el de arriba | En Casa Ley el más cercano de la columna era el encabezado de la casilla de abajo cuando su precio no se leyó (01c2420; dev +0/−0, ~824 registros de casa_ley cambian en producción) |

Tabla: Ajustes de la asociación por cercanía (load/load.py)

El diseño de la página se decide sin ground truth ni nombre de tienda, con `conteo_vecinos_alineados`: para cada precio se mira si tiene un producto alineado solo arriba, solo debajo o en ambos lados.

- **Nombre debajo** (`_es_nombre_debajo`): `solo_debajo > solo_arriba + ambos`. Domina en Walmart 413251/413647 y en Chedraui.
- **Retícula** (`_es_reticula`): `ambos >= MIN_AMBOS_RETICULA` (3) y `ambos > solo_arriba + solo_debajo`. Sin el mínimo de 3 entraban páginas de 1 o 2 precios de Costco, HEB, La Comer y Merco. En producción (13-oct-2026) eran 158 de 185 páginas de Casa Ley, 24 de Soriana Hiper y 4 de Chedraui.

Lo que se probó y se descartó está en los docstrings: aplicar "arriba primero" en todas las páginas que no son "nombre debajo" perdía 2 en dev (10 si se aplicaba en todas); cambiar el ganador de la misma fila por el de la columna daba +16/−23 (es el nombre a la izquierda de Merco, Alsuper y S-Mart); y aplicar la guarda de 2.ª línea al bloque pegado encima del precio bajaba chedraui de 21.0% a 16.1% de precisión.

### Unidad suelta: `nombre_con_unidad`

El OCR parte la descripción de la casilla en un bloque por línea y la última suele ser la presentación ("Elote" / "Dorado" / "Del Monte" / "Carton"). Por cercanía gana esa última línea y el dashboard mostraba "Carton" como nombre: en dev 12-oct-2026 había 1,267 registros así (826 de casa_ley). Quitar la unidad no servía, porque el precio pasaba a otro fragmento.

Si el bloque elegido es **solo** una unidad (`PATRON_UNIDAD_SUELTA`: cartón y sus variantes de OCR, pieza, paquete, gramos, producto, rollo, variedad, con una cantidad opcional como "25 Piezas") y está en la columna del precio (`unidad_en_columna_del_precio`, con margen `MARGEN_COLUMNA_UNIDAD_PX` = 50 px), el nombre es la pila de líneas producto contiguas **encima** de la unidad, más la unidad, hasta `MAX_LINEAS_DESCRIPCION` = 6 líneas. La pila se corta en una banda de sección que cubre dos casillas (`_es_banda`).

- **Guarda de columna** (QA 13-oct-2026): sin ella, en 4 páginas revisadas solo 9 de 36 uniones eran de su propia casilla, y Huggies salía como "Suavelastic Paquete", un error creíble peor que "Paquete". Con 50 px se aplica a 313 de 729 uniones en producción y ~9 de cada 10 son de su casilla (commit 993e065).
- **Línea perdida** (b0ce8ae): una vez por pila se acepta un hueco de hasta `HUECO_LINEA_PERDIDA_ALTURAS` = 2 altos, para la línea que el OCR leyó con confianza tan baja que no llegó al NLP (casa_ley 424405 p3: "Soluble" / "Dolca" / [línea perdida] / "Carton"). La contigüidad se mide con el alto menor de las dos últimas líneas (`_alto_tope`), para que un encabezado alto no salte a la casilla de arriba.

El nombre unido se normaliza otra vez y queda en `_resultado_unido`, para que el precio se ligue al canónico del nombre unido y no al de "Carton" (dfa5d73: 687 filas PRECIO cambiaron de canónico). La fila `PRODUCTO` enlazada sigue siendo la de la unidad.

### Nombre partido en varias líneas: `nombre_en_pila`

Es el cambio que más subió la calidad (commit caed57a, 25-oct-2026). En el diagnóstico de dev del 24-oct, 153 de los 418 registros con el precio bien leído y el producto equivocado tenían el nombre partido: el bloque elegido era **una** línea y el resto estaba en las líneas contiguas de la misma columna. Ejemplos de las pruebas, con cajas reales:

- sam's_club 421762 p4: se mostraba "Baja en Calorías 4 kg"; ahora "Metco BC Edulcorantede Mesa Baja en Calorías 4 kg".
- chedraui 416057 p7 (nombre debajo del precio): "Bocina" / "Mod. Charge Essential 2" queda "Bocina Mod. Charge Essential 2".

Para cualquier bloque elegido que no sea unidad suelta, `_pila_lineas` sube y baja por las líneas producto contiguas (misma regla `_linea_encima` y `_alto_tope` de la unidad, **sin** hueco), hasta 6 líneas en total. La pila se corta:

1. en una línea que eligió **otro** precio de la página (`ajenos`): no se roba el nombre de otra casilla;
2. hacia arriba, en una banda de sección (`_es_banda`);
3. en un inicio de renglón de lista (`PATRON_INICIO_RENGLON_LISTA`): las viñetas de características de chedraui (el OCR lee "•" como `'` o `~`) y la lista numerada de bodega ("2- Limpiador multiusos Fabuloso");
4. en una línea de promoción, vigencia u oferta (`PATRONES_CORTE_PILA`, `_tipo_corte_pila`);
5. si el texto unido lo descarta el normalizador (más de 150 caracteres): entonces no se une nada (`_unir_pila`). Además, `extracciones.texto_norm` es VARCHAR(300) y un texto más largo tumbaría la página.

La línea elegida por el precio **nunca** se corta, aunque sea de promoción.

**Corte por promoción, vigencia u oferta** (iteración 2, QA 25-oct-2026, Engram #259 y #260). La primera versión unía letra chica pegada al nombre: merco "Todos los Helados Mi marca y Yummy 3.9 L" + "Yoghurt", s-mart "De oferta" (34 registros), calimax "Salchichas de Pavo Fud" + "del Viernes 24 al Jueves 30 de Julio de 2026".

| Tipo | Corta | No corta (a propósito) |
|---|---|---|
| `promocion` | "todos los X", "en toda la", porcentajes de 2 dígitos, MSI, "meses sin", "precio especial", "llévate", NxM con N > M de un dígito (2x1, 3x2) | "Todas las variedades/sabores/presentaciones/colores/tallas/modelos", "70% cacao", "0% grasa", "2x75ml", "4x4" |
| `vigencia` | "del/al/hasta el" + día de la semana, "13 de Octubre", "03 al 16 de Agosto", "vigencia", "válido", "hasta agotar", "solo hoy" | "Tallas del 2 al 8" (rango sin mes ni día) |
| `oferta` | "de oferta", "en oferta" | "Ejemplo:" (ese renglón de s-mart y soriana lleva el nombre) |

Tabla: PATRONES_CORTE_PILA (load/load.py)

En producción (821 folletos) el corte cambió 127 nombres respecto a la primera versión: 72 por promoción, 41 por oferta y 14 por vigencia. La contaminación nueva por promoción frente a la versión sin pila bajó de 97 a 22 registros. En la muestra de 30 de QA, 11 mejoraron, 11 quedaron igual y 8 empeoraron; ninguno quedó peor que antes de la pila (Engram #260).

**Protección de pila: probada y descartada** (25-oct-2026, Engram #259 y #261). La idea era que una línea compartida por las pilas de dos precios fuera solo de la pila cuyo precio estuviera claramente más cerca. Corregía chedraui 424417 p12 ($39 "Sandwichera" se llevaba "PAW PATROL / 3 recipientes" de $134) y en dev daba 0/0, pero en producción, de 138 nombres que cambiaba, ~55 empeoraban y ~12 mejoraban. Es común que **varios precios sean del mismo producto** (casa_ley pieza y cartón, precio y "antes" mal leído, dos precios de un electrodoméstico), y repartir el nombre lo parte: "Suavizante Ensueño Color Primaveral" quedaba "Color Primaveral" y heb "Pollo entero con Vísceras" quedaba "Vísceras". Se revirtió; queda el comentario en `load.py` y la prueba `test_linea_compartida_por_dos_pilas_sigue_en_ambas`.

Cifras de caed57a. En dev, la precisión pasó de 19.4% a 30.8%, el recall de 14.6% a 23.3% y el F1 de 16.7% a 26.5%, con +139/−5 artículos y sin regresiones. En producción cambió el nombre de ~58% de los registros (en la muestra de QA, 75% mejora y 1.8% empeora) y 4,813 registros ganaron categoría. La Comparativa del dashboard bajó de 9,383 a ~4,840 registros, porque los nombres genéricos de catálogo pasan a texto del folleto; la persona lo aceptó porque muchos grupos que desaparecen eran fragmentos de nombre ("Para Asar", "De Cerdo") (Engram #261).

### `metodo_nombre`: por qué la fila PRECIO guarda `metodo_norm`

Con nombre unido, el nombre que muestra el precio ya no es el de su fila `PRODUCTO`: "Pechuga de pollo" (método `exacto`) unida a su pila queda "Filete de Pechuga de Pollo" (`heuristico`). El KPI "% catálogo" del dashboard leía el método de la fila `PRODUCTO` y, tras la recarga, habría marcado ~15% cuando lo que se muestra con nombre de catálogo es ~7.5%.

`metodo_nombre(producto)` devuelve el método del nombre que usa el precio:

- sin unión, el de `_resultado`;
- con unión, el de `_resultado_unido`;
- si el normalizador descartó la unión, `heuristico` (se muestra el texto tal cual);
- sin producto, `None`.

Load lo guarda en `extracciones.metodo_norm` de la fila `PRECIO`, una columna que existía pero siempre quedaba en NULL (commit dfe3d51). Las consultas del KPI usan `COALESCE(e.metodo_norm, p.metodo_norm)`, así que con cargas anteriores no cambian. En la recarga del 25-oct, las filas PRECIO con `metodo_norm` pasaron de 0 a 28,209 y el "% catálogo" de 15.1% a 7.5% (Engram #262).

### Precio anterior: `emparejar_precios_anteriores`

Hasta oct-2026, cada precio tomaba el "antes" con la esquina más cercana (≤ 300 px) sin validar nada: un mismo "antes" acababa en varios precios, incluidas mensualidades MSI, y el 47% de los descuentos salía de más de 70% (commit 7819d24). Ahora:

1. `_costo_par` solo acepta pares en la misma columna (traslape en x de al menos 30% del más angosto), pegados arriba o abajo (Walmart y Bodega lo ponen abajo). Penaliza el desfase horizontal y que el "antes" sea más grande que el precio.
2. Los precios de financiamiento ("msi", "meses", "quincena", "semana") no reciben "antes".
3. Los pares se asignan de menor a mayor costo, **uno a uno**.
4. **Elección entre los candidatos**: el NLP guarda en `candidatos` las lecturas posibles del "antes" ("81090" → 10.90; el tachado de Chedraui con 1 inicial "19,995" → 10,995). `_lectura_coherente` toma el primer candidato que da un descuento creíble, entre `DESCUENTO_MIN` = 3% y `DESCUENTO_MAX` = 50% (en el ground truth el mínimo real es 7% y el p95 es 47%).
5. Si el precio actual es "5XXX" u "8XXX" (Walmart, "$" leído como 5) y su otra lectura (sin el primer dígito) también da un descuento creíble, no se empareja: no se sabe cuál es el precio real.

Con el ground truth (276 pares), la precisión del "antes" pasó de 26% a 84% y el recall de 22% a 28% (7819d24). En dev al 25-oct-2026 (corrida `20261025_224754`), la precisión del precio anterior es 60.0% y el recall 34.7%.

### Normalización y `productos_canonicos`

`_insertar_productos` inserta cada producto legible como fila `PRODUCTO` con su `texto_norm` (nombre canónico), categoría, `confianza_norm` y `metodo_norm`. Si el normalizador dio nombre canónico, antes hace `_upsert_producto_canonico`:

- `INSERT ... ON CONFLICT (nombre_canonico) DO UPDATE`: la categoría y la marca solo se llenan si estaban vacías (`COALESCE`).
- **Alias nuevo** solo si el método fue `fuzzy` o `fuzzy_bajo`: se guarda la forma normalizada del texto OCR (`texto_norm_base`), para que la próxima vez ese texto coincida como `exacto`. Con `exacto` o `heuristico` no hace falta, porque el texto ya es el nombre canónico. No se repite un alias que ya está.

La fila `PRECIO` toma el canónico de su producto. Si el nombre es unido (unidad suelta o pila) y tiene canónico, se hace el upsert del nombre unido y el precio se liga a ese (dfa5d73). Los métodos y umbrales del normalizador están en `03_nlp.md`.

Una recarga forzada borra páginas y extracciones, pero **no** `productos_canonicos`: el catálogo se acumula entre cargas.

### Eventos de campaña

Por cada bloque `eventos_promo` del NLP, `_normalizar_nombre_evento` llama a `slug_evento` (de `nlp/regex_extractor.py`) y obtiene uno de los slugs acordados (`julio_regalado`, `hot_sale`, `buen_fin`, `regreso_a_clases`, `navidad`, `halloween_dia_de_muertos`, `liquidacion`, `aniversario`, `ofertones`, `fiestas_patrias`). Si devuelve `None`, el bloque no se inserta. Así se filtran los lemas y la letra chica que traen los `nlp_resultado.json` generados antes del 15-oct-2026.

Si hay slug, se inserta una fila `EVENTO_PROMO` en `extracciones` y un renglón en `eventos_promo` (`ON CONFLICT (folleto_id, nombre_evento) DO NOTHING`: uno por campaña y folleto) con la vigencia del folleto como fechas. Antes del commit 85e9e95 las fechas quedaban en NULL en los 88 eventos y `v_eventos_activos` los daba todos por vigentes; y el nombre era el texto completo en minúsculas: 45 slugs para 77 eventos. Hoy, con la recarga del 25-oct, hay 132 eventos (Engram #276).

## Recargas forzadas

### Cuándo hacen falta

La BD solo refleja un cambio de código cuando los folletos se vuelven a cargar, y `cargar_batch` sin `forzar` omite los que ya están. Por eso:

| Qué cambió | Qué hay que hacer |
|---|---|
| `load/load.py` (asociación, pila, inserciones) | Recarga forzada |
| `nlp/` (reglas de precio, clasificación, catálogo, normalizador, campañas) | Reproceso del NLP **y** recarga forzada |
| `vision/region_detector.py` | Recarga forzada (ROI corre dentro de load) |
| OCR o preprocesamiento | Reproceso OCR (GPU), NLP y recarga |

Tabla: Qué requiere cada tipo de cambio

**Por qué el reproceso NLP es necesario cuando cambia `nlp/`.** Load no clasifica nada: lee `nlp_resultado.json` del disco. Si cambia una regla de precio y solo se recarga, load vuelve a insertar las clasificaciones viejas. Esto confunde porque el evaluador sí ve el cambio sin reprocesar: con `--nlp memoria` regenera el NLP en memoria con el código actual y no escribe nada. Por eso las cifras de dev pueden mejorar mientras el dashboard sigue igual.

### Procedimiento

Es el que se siguió en las recargas del 24 y 25-oct-2026 (Engram #255, #262, #267, #276). Lo hace la persona, no los agentes: el hook `.claude/hooks/guardia_agente.py` bloquea a los agentes cualquier comando sobre `load.py`, `probar_load`, `db_builder`, `psql`, `pg_dump` o `pg_restore`, y en la recarga del 25-oct el clasificador de permisos pidió confirmación explícita de la persona (Engram #276).

1. **Foto del antes.** Guardar los conteos que se van a comparar: filas PRECIO, `v_precios_actuales`, "% catálogo", grupos y registros de la Comparativa, registros sin categoría y precios de $1,000 o más. Antes de recargar conviene tener la cifra esperada: la simulación del especialista o de QA, o `python -m evaluador.huella_load` sobre producción.
2. **Respaldo** fuera del repo, en la carpeta `PRICE_SCRAPER_SS/`:
   - la BD con `pg_dump` en formato custom (`respaldo_antes_reproceso_nlp_<fecha>.dump`, se restaura con `pg_restore`);
   - los JSON del NLP (`respaldo_nlp_resultado_<fecha>.tar.gz`, los 821 `nlp_resultado.json`).
3. **Reproceso NLP** de todas las carpetas de `data/processed/tiendeo/*/*` y `data/processed/ofertomat/*/*` con `probar_nlp.procesar_carpeta(carpeta, extractor, forzar=True)`. El modo batch del menú de `probar_nlp.py` usa `forzar=False` y no reescribe nada. Hay que pasar rutas **relativas** desde la raíz del repo: `procesar_carpeta` hace `relative_to(Path("data/processed"))` y con rutas absolutas falla en todos los folletos sin escribir nada (Engram #227).
4. **Recarga**: `Loader().cargar_batch(forzar=True)`, o la opción 3 de `probar_load.py`. Revisar en el resumen que no haya folletos ni páginas con error.
5. **Verificación**: repetir la foto y comparar contra lo esperado. Si no cuadra, investigar antes de seguir; el respaldo permite volver atrás.

Estos pasos están en `recargar_bd.py` (raíz del repo, desde el 26-oct-2026): `python recargar_bd.py todo` hace verificar antes → respaldo → nlp → load → verificar después, y cada paso se puede correr por separado. El paso `nlp` usa `probar_nlp.carpetas_con_ocr()`, que solo toma las carpetas de producción (`tiendeo/` y `ofertomat/`). Si el NLP termina con errores, se detiene antes de tocar la BD.

Una advertencia que se deduce del código: si una recarga forzada se interrumpe a la mitad, **no** se puede reanudar con `cargar_batch()` sin `forzar`, porque los folletos que faltaban ya existen en `folletos` (con los datos viejos) y se omitirían. Hay que recargar los que faltan con `cargar_folleto(ruta, reemplazar=True)` o repetir la recarga forzada completa. (El 11-oct-2026 una recarga murió por falta de memoria tras 508 folletos y se reanudó con los 186 restantes, Engram #129; la observación no dice con qué método.)

### Cifras de las recargas del 25-oct-2026

| Recarga | Commits | Folletos | Extracciones | PRECIO | v_precios_actuales | % catálogo | Fuente |
|---|---|---|---|---|---|---|---|
| 1.ª | caed57a, dfe3d51 (pila y `metodo_norm`) | 821, 0 errores | 223,207 | 28,441 → 28,441 | 28,209 | 15.1 → 7.5 | Engram #262 |
| 2.ª | ddb5bbb, 6865f14 ("$" suelto, A-escala) | 821, 0 errores | 223,752 | 28,441 → 28,984 | 28,735 | 7.5 → 7.6 | Engram #267 |
| 3.ª | 32001ee (centavos pegados) | 821, 0 errores | 223,188 | 28,984 → 28,420 | 28,172 | 7.6 → 7.4 | Engram #276 |

Tabla: Recargas forzadas del 25-oct-2026 | Fuente: Engram #262, #267 y #276

En las tres, el cambio en la BD cuadró con lo que habían medido el especialista y QA. Ejemplos: la 2.ª recarga sumó +543 PRECIO, exacto lo esperado (504 de A-escala + 39 del "$" suelto). En la 3.ª, los precios de $1,000 o más bajaron de 5,179 a 2,503, que son los 2,676 divididos entre 100. La 1.ª recarga no cambió el número de precios, solo sus nombres: la Comparativa pasó de 9,383 a 4,849 registros y los registros sin categoría de 15,493 a 10,694.

## Calidad: el error de asociación

El evaluador compara los registros que arma `construir_registros_pagina` contra el ground truth. Un error `asociacion_producto` es un registro con el precio bien leído y el producto equivocado.

| Corrida dev | Precisión | Recall | F1 | `asociacion_producto` | `precio_mal_leido` | `precio_huerfano` |
|---|---|---|---|---|---|---|
| `20261024_161858` (antes de la pila) | 19.4% | 14.6% | 16.7% | 418 | 328 | 182 |
| `20261025_121803` (con pila, caed57a) | 30.8% | 23.3% | 26.5% | 271 | 344 | 162 |
| `20261025_224754` (25-oct-2026) | 33.1% | 24.7% | 28.3% | 287 | 321 | 133 |
| `20261026_115424` (limpia, 26-oct-2026; la que usa el panel) | 33.1% | 24.7% | 28.3% | 287 | 321 | 133 |

Tabla: Errores por registro en dev (data/processed/_eval/runs/)

Hasta el 24-oct, `asociacion_producto` era el error dominante. Desde la pila quedó como el **segundo**, muy cerca de `precio_mal_leido`. En la última corrida, el producto es correcto en 64.5% de los pares con precio y el precio en 72.7%: la asociación sigue siendo el cuello de botella del lado del producto.

**Subtipos.** Diagnóstico de los 418 registros de `asociacion_producto` de la corrida `20261024_161858`, hecho con `tests/_herramienta_asoc_diag.py` (Engram #259):

| Subtipo | Registros | Qué significa |
|---|---|---|
| S | 153 | Ningún bloque solo tiene el nombre, pero la unión de 2-4 bloques cercanos sí (nombre partido) |
| A-otro | 125 | Había un bloque con el nombre correcto y se eligió ruido, un encabezado o un fragmento |
| O | 77 | El nombre no se encuentra (OCR ilegible, nombre del ground truth no impreso) |
| A-vecino | 35 | El bloque elegido está más cerca de otro precio (es de la casilla vecina) |
| A-attr | 8 | Se eligió un atributo o presentación (unidad, medida, talla) |
| C | 7 | El nombre está en el OCR, pero el NLP lo clasificó como otra cosa |
| N | 7 | Se eligió el bloque correcto y el normalizador cambió el nombre |
| D | 4 | El nombre está en un bloque que el normalizador descarta o es ilegible |
| A-marca | 2 | Se eligió solo la marca |

Tabla: Subtipos del error asociacion_producto, dev 24-oct-2026 | Fuente: Engram #259

La pila atacó el subtipo S y bajó el error de 418 a 271. El diagnóstico no se ha repetido sobre la corrida más reciente, así que no hay un desglose por subtipo de los 287 actuales.

## Configuración

| Constante | Valor | Para qué |
|---|---|---|
| `FUENTES` | `("tiendeo", "ofertomat")` | Carpetas de producción que se cargan |
| `TIENDAS_ROI_HIBRIDO` | walmart, chedraui, soriana_hiper, soriana_mercado | Tiendas que usan regiones de visión |
| (literal en `asociar_por_cercania`) | 400 px | Tolerancia horizontal de la cercanía |
| `MARGEN_DEBAJO_PRECIO` | 100 px | Cuánto por debajo del precio puede empezar el nombre |
| `ALINEACION_DEBAJO_PX` | 20 px | Alineación izquierda de "nombre debajo" y de los vecinos alineados |
| `MIN_AMBOS_RETICULA` | 3 | Mínimo de precios con vecino arriba y abajo para llamar retícula a la página |
| `CONFIANZA_MINIMA_HEURISTICO` | 0.30 | Debajo de esto, un nombre heurístico sin categoría es ilegible |
| `MAX_LINEAS_DESCRIPCION` | 6 | Tope de líneas de una pila |
| `MARGEN_COLUMNA_UNIDAD_PX` | 50 px | Guarda de columna de la unidad suelta |
| `HUECO_LINEA_PERDIDA_ALTURAS` | 2 | Hueco máximo (en altos de línea) de la línea perdida, solo en la unidad suelta |
| `DESCUENTO_MIN` / `DESCUENTO_MAX` | 0.03 / 0.50 | Descuento creíble para emparejar un precio anterior |
| `DISPERSION_MAX_FRACCION` (`vision/region_detector.py`) | 0.5 | Dispersión máxima de candidatos dentro de una región ROI |

Tabla: Constantes principales del módulo de carga

`PATRON_UNIDAD_SUELTA`, `PATRON_INICIO_RENGLON_LISTA` y `PATRONES_CORTE_PILA` son expresiones regulares; cada una lleva junto, en `load/load.py`, el comentario con los casos que la motivaron.

## Pruebas

Las pruebas de load usan cajas reales de folletos y no necesitan la BD, porque prueban las funciones puras:

| Archivo | Funciones de prueba | Qué fija |
|---|---|---|
| `tests/test_load_asociacion.py` | 34 | Cercanía (arriba, debajo, empates), "nombre debajo", 2.ª línea, precio propio, columna propia, retícula y emparejamiento del precio anterior |
| `tests/test_load_unidad_presentacion.py` | 27 | `PATRON_UNIDAD_SUELTA` y sus variantes de OCR, pila de la unidad, guarda de columna, bandas, línea perdida y `_resultado_unido` |
| `tests/test_load_nombre_partido.py` | 19 | Pila arriba y abajo, viñetas y listas, línea de otro precio, línea compartida (protección descartada), `PATRONES_CORTE_PILA` positivos y negativos y `metodo_nombre` |
| `tests/test_load_legibilidad.py` | 12 | Filtro de ilegibles, `_idx` solo de legibles, ROI que elige un ilegible y recorte de puntuación del nombre heurístico |

Tabla: Pruebas del módulo de carga (algunas funciones son parametrizadas y corren varios casos)

```
venv/Scripts/python.exe -m pytest tests/test_load_asociacion.py tests/test_load_unidad_presentacion.py tests/test_load_nombre_partido.py tests/test_load_legibilidad.py -q
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria     # calidad de la asociación contra el ground truth
python -m evaluador.huella_load guardar <archivo.jsonl.gz>               # huella de escrituras, para comparar antes y después
```

Los scripts `tests/_herramienta_asoc_*.py` (diagnóstico por subtipo, simulación en producción, visor de cajas) son herramientas de medición de los agentes, no pruebas: pytest no los recoge.

## Limitaciones conocidas y pendientes

- **Casilla vecina.** Un precio puede tomar el nombre de la casilla de al lado (subtipo A-vecino, 35 en el diagnóstico del 24-oct). El 13-oct-2026, el 29.4% de los nombres heurísticos se repetía en dos o más precios de valor distinto en la misma página (alsuper 45%, casa_ley 42%), una señal de nombre vecino. El peor caso era el logo "Bodegaaurrera" en 44 registros (Engram #200). De las unidades sueltas que no se unen, 426 de 694 están en la misma fila del precio y no en su columna, así que la guarda de columna no las toca.
- **Varios precios del mismo producto.** Pieza y cartón, precio y "antes" mal leído, contado y otro precio. Por eso falló la protección de pila. Para retomarla primero hay que saber agrupar los precios que son del mismo producto, y solo repartir el nombre entre precios de productos distintos (Engram #259 y #261).
- **Nombres partidos con hueco.** `nombre_en_pila` no tolera la línea perdida por el OCR; solo `nombre_con_unidad` la tolera. Una línea intermedia que no llega a `productos` (confianza OCR menor a 0.15, que el NLP ignora, o un bloque ilegible) corta la pila de cualquier nombre que no termine en unidad.
- **Sobrecorte de "todos los X".** Cuando esa línea es el nombre ("Todas las Albercas E Inflables Acuáticos Bestway" → "Acuáticos Bestway") o en "Compatible con todos los volantes y Pedales" → "Y Pedales". La idea de QA es quitar solo el prefijo en vez de cortar la línea (Engram #260).
- **Línea elegida de promoción.** Si el bloque elegido es la vigencia, no se corta: soriana_hiper 432749 y 432835 p1 siguen con "Jitomate" + "Solo Hoy 13 de Octubre" (2 registros). Además, `nombre_con_unidad` todavía no aplica el corte por promoción y vigencia, y el rótulo "Ofertas semanales" de calimax no está cubierto.
- **Rótulos como nombre** en páginas "nombre debajo" ("Antcs: 532.95", "en dinero electrónico", "ETAPA 4"), deuda anotada en el commit e4184da.
- **Atributos** se asocian solo por cercanía simple, sin ROI, pila ni diseño de página.

## Historial

La primera versión (julio de 2026) asociaba cada precio con el producto más cercano arriba de él, sin filtrar ruido y sin guardar los productos como filas propias. El 29-jul se integró el híbrido ROI + distancia para cuatro tiendas (1c06941). El 23-ago, el modelo v3 agregó `productos_canonicos` y las filas `PRODUCTO` y `ATRIBUTO`; solo los productos aceptados por el normalizador compiten por el precio (685d16b). El 10-oct llegaron `errores_carga`, el SAVEPOINT por página y el modo reemplazar (9010a75). Desde el 11-oct cada cambio de la asociación se mide con el evaluador en dev y lo revisa QA antes del commit:

| Commit | Fecha | Cambio | F1 dev |
|---|---|---|---|
| 68f215d | 11-oct-2026 | Admitir el nombre al lado o debajo del precio | 3.6 → 5.5 |
| c1a84b2 | 11-oct-2026 | Filtro de ilegibles | 10.4 → 10.6 |
| e4184da | 12-oct-2026 | Nombre alineado debajo, por diseño de página | 10.9 → 12.1 |
| 993e065 | 13-oct-2026 | Unidad suelta unida a su descripción | 12.2 → 12.7 |
| ea975ff | 13-oct-2026 | Columna propia si el ganador queda en diagonal | 12.7 → 13.9 |
| 01c2420 | 13-oct-2026 | Retícula: arriba primero en la columna | 13.9 → 13.9 |
| b0ce8ae | 14-oct-2026 | Línea perdida en la pila de la unidad | 13.9 → 14.0 |
| caed57a | 25-oct-2026 | Nombre partido en varias líneas (pila) | 16.7 → 26.5 |
| dfe3d51 | 25-oct-2026 | `metodo_norm` en la fila PRECIO | sin cambio (KPI) |

Tabla: Historia de la asociación producto-precio | Fuente: mensajes de commit de load/load.py

Entre un commit de load y el siguiente también hubo cambios del NLP y del evaluador, por eso el F1 "antes" de un renglón no siempre es el "después" del anterior. La historia completa está en `git log -- load/load.py` y en Engram (proyecto `pricescraper_ss`, temas `experimentos/producto/*`, `experimentos/qa/*` y `proyecto/reproceso-nlp-recarga-*`).
