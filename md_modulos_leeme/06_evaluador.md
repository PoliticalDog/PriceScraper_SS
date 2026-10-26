# Evaluador de calidad

El evaluador (`evaluador/`, se corre con `python -m evaluador`) mide la calidad del pipeline contra un conjunto de folletos etiquetados a mano (el ground truth, GT). No forma parte del flujo scraper → visión → NLP → load: corre al lado, regenera en memoria lo que el pipeline mostraría en el dashboard para las páginas etiquetadas y lo califica registro por registro. Es el juez que decide si un cambio en visión, NLP o load mejora o empeora los datos.

## Propósito y alcance

Antes de octubre de 2026 la calidad se medía por separado (¿se leyó el precio?, ¿se leyó el nombre?), y un precio correcto con el producto de la casilla vecina contaba como acierto. El evaluador actual mide lo que ve el usuario: el **registro** producto + precio + precio anterior. Es el juez compartido de los agentes especialistas y de QA (skill `ciclo-experimento`): todos miden con el mismo código, el mismo GT y las mismas reglas, y nadie lo modifica. Antes de usarlo como juez se validó contra la calificación a ciegas de la persona: coincidió en 39 de 39 casos (ver "Validación humana del juez").

| Hace | No hace |
|---|---|
| Regenerar los registros de cada página del GT con el código actual (`--nlp memoria`) o leerlos de los JSON cargados (`--nlp disco`) | Escribir en `data/processed/<fuente>/` ni en la BD |
| Emparejar uno a uno registros y artículos del GT y decidir cuáles son correctos | Corregir el pipeline (eso lo proponen los especialistas) |
| Dar un código de error por la primera etapa que falló | Medir folletos sin etiquetar (producción) |
| Calcular precisión, recall, F1, IC95 y exactitudes, global y por tienda | Decidir si un cambio entra (lo decide la persona con el veredicto de QA) |
| Comparar dos corridas: regresiones por tienda y caso por caso | Editar el GT, los splits o las reglas (decisión de la persona) |
| Proteger el GT, los splits y las reglas con un sello (`manifest.json`) | |

Tabla: Alcance del evaluador

## Entradas y salidas

### Entrada 1: el ground truth

Un archivo por folleto en `data/raw/_revision_manual/tiendeo/<tienda>/<folleto>_contenido.json` (`RAIZ_GT` en `evaluador/gt.py`). Todo el GT es de la fuente `tiendeo` (`FUENTE_GT`). Cada archivo trae hasta 5 páginas del folleto (`paginas_incluidas`) y, por página, sus artículos con nombre impreso, categoría, precio, precio anterior y promoción, más las promociones generales de la página.

Fragmento real (recortado) de `sam's_club/421762_contenido.json`, en solo lectura:

```
{"fuente": "tiendeo", "tienda": "sam's_club", "folleto_id": "421762", "total_paginas": 4,
 "paginas_incluidas": ["pagina_001.webp", "pagina_002.webp", "pagina_003.webp", "pagina_004.webp"],
 "etiquetado_por": "manual", "fecha_etiquetado": "2026-08-06", "notas_folleto": "...",
 "paginas": [
   {"pagina": "pagina_001.webp", "articulos": [], "promociones_pagina": [],
    "notas_pagina": "Portada publicitaria ... sin producto ni precio especifico."},
   {"pagina": "pagina_004.webp",
    "articulos": [{"id": 1, "producto": "Metco BC Edulcorante de Mesa Baja en Calorias (azucar y stevia) 4kg",
                   "categoria": "alimentos", "precio": 199, "precio_anterior": null,
                   "unidad_medida": "kg", "promocion": null, "notas": "..."}],
    "promociones_pagina": [], "notas_pagina": ""}]}
```

Y una página con precio anterior y promociones de página (`heb/426799_contenido.json`, página 5):

```
"articulos": [{"id": 1, "producto": "Queso manchego, gouda o chihuahua menonita rebanados 200 g HEB Sabor Tradicional",
               "categoria": "alimentos", "precio": 53.9, "precio_anterior": 59.9, ...}],
"promociones_pagina": [{"texto": "En string cheese, cheese sticks, quesos tipo snack, cubicados o botaneros y quesos mini",
                        "tipo": "categoria", "notas": "PROMO AHORRO: AHORRA $25 por cada $100 de compra ..."}, ...]
```

`cargar_gt` convierte cada archivo en objetos `PaginaGT` (tienda, folleto, página, artículos) y `ArticuloGT` (id, producto, categoría, precio, precio anterior, promoción). De `promociones_pagina` solo usa `texto` y `notas`, unidos, para reconocer un registro que es una promoción. `unidad_medida` y las notas de los artículos no se usan. La clave de una página es `tienda/folleto/pagina`.

**Cifras del GT** (verificadas con `cargar_gt` y `splits.json` el 26-oct-2026; coinciden con `sources/vision/ground_truth_resumen.md`, del 21-oct-2026):

| | Total | Dev | Holdout |
|---|---|---|---|
| Tiendas | 16 | 16 | 16 |
| Folletos | 77 | 56 | 21 |
| Páginas | 315 | 229 | 86 |
| Páginas con al menos un precio (evaluables) | 233 | 158 | 75 |
| Artículos etiquetados | 2,413 | 1,819 | 594 |
| Artículos con precio | 2,131 | 1,556 | 575 |
| Artículos con precio anterior | 276 | 200 | 76 |

Tabla: Tamaño del ground truth por split

Las 16 tiendas son alsuper, bodega_aurrera, casa_ley, chedraui, costco, heb, la_comer, merco, oxxo, s-mart, sam's_club, soriana_hiper, soriana_mercado, tiendas_3b, waldos y walmart. El reparto es desigual: casa_ley tiene 443 artículos en 12 páginas, y sam's_club, oxxo y waldos tienen 10, 13 y 19. En dev, costco y oxxo no tienen ningún artículo con precio (los de costco son casi todos promociones sin monto), así que no se pueden medir en dev.

### Entrada 2: lo que produce el pipeline

Para cada página del GT, `FuentePipeline` (`evaluador/pipeline.py`) lee de `data/processed/tiendeo/<tienda>/<folleto>/`:

- `ocr_resultado.json` (siempre), o el de un experimento de OCR en `data/processed/_eval/ocr_exp/<nombre>/` si se usa `--ocr-exp`;
- `nlp_resultado.json` con `--nlp disco`, o el NLP regenerado en memoria con `--nlp memoria`: `resultado_nlp(ocr, clasificar_paginas_ocr(ocr, RegexExtractor()))`, el mismo código de `nlp/salida_json.py` que usa `probar_nlp.py`, pero sin escribir;
- la imagen de `data/raw/tiendeo/...` solo para las tiendas con ROI (las regiones se guardan en caché, ver "Configuración").

Después llama a `construir_registros_pagina` de `load/load.py`, la misma función que usa la carga a PostgreSQL. Por eso el evaluador mide exactamente lo que llegaría al dashboard (`05_load.md`).

### Salida: una corrida

Cada `correr` imprime un resumen y guarda un JSON en `data/processed/_eval/runs/<AAAAMMDD_HHMMSS>_<commit>[-sucio]_<split>.json` (`reporte.guardar_corrida`). Fragmento real de la corrida limpia del 26-oct-2026 (`20261026_115424_398c4e4_dev.json`, 1.2 MB):

```
{"meta": {"fecha": "2026-10-26T11:54:24", "split": "dev", "nlp": "memoria", "ocr_exp": null, "tienda": null,
          "paginas": 229, "version_vision": "1cd11e621184",
          "codigo": {"commit": "398c4e4", "cambios_sin_commit": false}},
 "integridad": {"valida": true, "problemas": [], "sellado_at": "2026-10-11T16:17:23"},
 "metricas": {"global": {"precision": 0.3313, "precision_ic95": [0.3049, 0.3589], "recall": 0.2474, "f1": 0.2833,
                         "conteos": {"paginas": 158, "registros_dashboard": 1162, "articulos_con_precio": 1556,
                                     "completos_ok": 385, ...},
                         "errores_registro": {...}, "errores_articulo": {...}, ...},
              "tiendas": {"alsuper": {...}, ...}},
 "ejemplos_error": {"asociacion_producto": {"chedraui": [...], ...}, ...},
 "detalle": {"articulos": {"sam's_club/421762/pagina_004.webp#1": {"estado": "ok", "similitud": 0.77, ...}, ...},
             "registros": {"sam's_club/421762/pagina_004.webp|199.0|299,795": {"estado": "ok", ...}, ...}}}
```

- `meta`: con qué se corrió (split, modo NLP, OCR experimental, tienda, páginas, versión de visión y commit).
- `integridad`: el resultado de comparar contra el sello. Una corrida con `"valida": false` no sirve para decidir.
- `metricas`: global y por tienda (ver "Métricas").
- `ejemplos_error`: hasta 10 casos por código y tienda (`EJEMPLOS_POR_CODIGO`), con el registro, lo esperado y las cajas, para ir a ver la imagen.
- `detalle`: el estado de **cada** artículo y de cada registro; es lo que usa `comparar --casos`.

Las corridas de holdout guardan solo `meta`, `integridad` y `metricas`: nunca registros ni ejemplos.

Este JSON lo consume `dashboard/confiabilidad.py`. Si cambian `meta.split`, `meta.fecha`, `meta.codigo.cambios_sin_commit`, `integridad.valida` o la forma de `metricas.tiendas.<slug>`, la página de confiabilidad del dashboard deja de encontrar una corrida vigente.

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave | ¿Sellado? |
|---|---|---|---|
| `__main__.py` | CLI (`argparse`) y relanzamiento con `PYTHONHASHSEED=0` | `cmd_correr`, `cmd_comparar`, `cmd_catalogo`, `cmd_ocr`, `cmd_verificar`, `cmd_sellar`, `cmd_splits`, `cmd_validacion`, `_con_semilla_fija` | No |
| `gt.py` | Lectura del GT y huella sha256 de cada archivo | `RAIZ_GT`, `ArticuloGT`, `PaginaGT`, `cargar_gt`, `huella_gt` | Sí |
| `splits.py` | Regla de partición dev/holdout y filtro | `generar`, `cargar`, `filtrar`, `SEMILLA`, `VERSION` | Sí |
| `splits.json` | Partición congelada: 56 folletos dev y 21 holdout | `version`, `semilla`, `regla`, `dev`, `holdout` | Sí (su hash) |
| `pipeline.py` | Registros de una página con el código del pipeline, sin escribir | `Registro`, `PaginaPipeline`, `FuentePipeline`, `version_vision` | No |
| `comparar.py` | El juez: emparejamiento, reglas de "correcto" y códigos de error | `similitud_nombre`, `emparejar`, `comparar_pagina`, `Par`, `_diagnosticar_perdida`, `UMBRAL_PRODUCTO` | Sí |
| `metricas.py` | Agregados, IC de Wilson y regresiones entre corridas | `agregar`, `agregar_por_tienda`, `wilson`, `comparar_corridas`, `UMBRAL_REGRESION_PTS`, `MUESTRA_MINIMA` | Sí |
| `integridad.py` | Sello y verificación del juez | `ARCHIVOS_REGLAS`, `huellas_actuales`, `sellar`, `verificar` | Sí |
| `manifest.json` | El sello: hashes del GT, de `splits.json` y de las 5 reglas | `sellado_at`, `motivo`, `gt`, `splits`, `reglas` | Es el sello |
| `reporte.py` | Resumen en consola y JSON de la corrida | `guardar_corrida`, `imprimir_resumen`, `imprimir_comparacion`, `imprimir_casos`, `ejemplos_error`, `version_codigo` | No |
| `casos.py` | Estado de cada artículo y registro, y comparación caso por caso | `detalle`, `comparar_casos` | No |
| `catalogo.py` | Diseño por tienda: dónde queda el nombre respecto al precio (solo dev, descriptivo) | `posicion`, `alcanzable_cercania`, `medir_pagina`, `construir`, `resumen` | No |
| `ocr_experimental.py` | OCR en CPU de las páginas de dev, sin tocar producción | `correr_ocr`, `paginas_disponibles`, `version_ocr`, `carpeta_exp` | No |
| `huella_load.py` | Lo que `Loader._procesar_pagina` escribiría en la BD, con un cursor falso | `CursorFalso`, `guardar`, `comparar` | No |
| `validacion.py` | Muestra para calificar a mano y concordancia juez-persona | `generar_muestra`, `concordancia`, `CUOTAS` | No |

Tabla: Archivos de evaluador/

El evaluador reutiliza código de otros módulos a propósito, para no medir una copia: de `nlp/evaluador_calidad.py` (el comparador de agosto) toma `tokens_significativos`, `recall_texto`, `corpus_de_bloques` y `TOLERANCIA_PRECIO`; de `nlp/regex_extractor.py`, los detectores de promoción; de `load/load.py`, `construir_registros_pagina`, `candidatas_roi_pagina` y `regiones_con_precio`; y el `Normalizador` de `nlp/normalizador.py`.

## Cómo funciona

### Flujo de una corrida

```
python -m evaluador correr --split dev --nlp memoria
   │  _con_semilla_fija(): si PYTHONHASHSEED != 0, se relanza a sí mismo con PYTHONHASHSEED=0
   │
   ├─ cargar_gt()  →  splits.filtrar(split)  →  [--tienda]  →  [--ocr-exp: solo sus páginas]
   │
   ├─ por cada página del GT:
   │     FuentePipeline.pagina(pg)
   │        OCR (producción o experimento) → NLP (disco o memoria) → regiones ROI (caché)
   │        construir_registros_pagina()  → Registro(precio, producto, categoría, antes, cajas)
   │     comparar_pagina(pp)
   │        página sin ningún precio en el GT → no evaluable, no cuenta
   │        emparejar() uno a uno          → pares (Par) con su error o correctos
   │        registros sin pareja           → promo_como_producto | duplicado | precio_mal_leido | precio_huerfano
   │        artículos sin pareja           → _diagnosticar_perdida(): primera etapa que falló
   │
   ├─ agregar_por_tienda()   → global y por tienda
   ├─ integridad.verificar() → ¿GT, splits y reglas iguales al sello?
   ├─ imprimir_resumen()
   └─ guardar_corrida()      → data/processed/_eval/runs/... (salvo --sin-guardar)
        código de salida: 0 si la integridad es válida, 2 si no
```

La semilla fija existe porque `Normalizador._extraer_marca` desempata marcas del mismo largo según el orden de un `set`: sin `PYTHONHASHSEED=0`, dos corridas del mismo código podían dar resultados distintos (Engram #132). `huella_load.py` hace lo mismo.

### Qué es un registro

`Registro` es una fila PRECIO tal como load la insertaría: precio y su texto, caja del precio, nombre que mostraría el dashboard (`producto`, el `_nombre_norm` del normalizador), texto OCR del bloque elegido, categoría, caja del producto y precio anterior. `en_dashboard` reproduce el filtro de `v_precios_actuales` (`valor IS NOT NULL AND texto_norm IS NOT NULL`): un precio sin producto **no** se cuenta como registro del dashboard, solo en `registros_sin_producto` (4 en la corrida del 26-oct).

### Emparejamiento uno a uno

`emparejar` arma una matriz registros × artículos con precio de la página y resuelve la asignación óptima con `scipy.optimize.linear_sum_assignment` (método húngaro, maximizando). El puntaje de un par es:

```
puntaje = 0.6 × (precio igual) + 0.4 × similitud de nombre      (PESO_PRECIO, PESO_NOMBRE)
el par ni siquiera se considera si el precio es distinto y la similitud es < 0.3   (UMBRAL_CANDIDATO)
```

Dos ideas fijan el diseño (commit 059f59d y `tests/test_evaluador.py`):

1. **Uno a uno.** Un registro nunca cuenta como acierto de dos artículos, y un artículo no recibe dos registros. Si el dashboard repite "Leche Lala $25" dos veces, uno empareja y el otro sobra (`duplicado`). Si hay tres artículos a $19.90 y dos registros, el tercero queda perdido (`test_tres_articulos_mismo_precio_dos_registros`).
2. **Un monto igual no basta.** Dos productos pueden costar lo mismo. Por eso el nombre entra en el puntaje: con "Jugo Jumex" y "Leche Lala" a $25, cada registro queda con su artículo (`test_mismo_precio_se_empareja_por_nombre`), y si los nombres están cruzados ninguno es correcto (`test_productos_intercambiados_no_reciben_credito`).

### Qué cuenta como correcto

Cada par (`Par`) se califica en tres partes:

| Parte | Regla | Dónde |
|---|---|---|
| Precio | Igual al centavo: `abs(a - b) < TOLERANCIA_PRECIO` (0.01) | `precio_igual` |
| Producto | `similitud_nombre(nombre_gt, registro) >= UMBRAL_PRODUCTO` (0.5) | `Par.producto_ok` |
| Precio anterior | Los dos vacíos, o los dos iguales al centavo | `anterior_igual` |

Tabla: Criterio de corrección de un par (evaluador/comparar.py)

- **Básico correcto** (`basico_ok`) = precio y producto.
- **Completo correcto** (`completo_ok`) = básico y precio anterior. Es lo que cuenta en la métrica principal: un registro sin el "antes" que sí trae el folleto, o con un "antes" que no existe, no es correcto.

**Similitud de nombre.** Es un F1 de tokens significativos (`tokens_significativos`: minúsculas, sin acentos, solo alfanuméricos, tokens de 3 o más letras, sin palabras vacías como "de", "la", "con"). La precisión es cuánto del registro está en el nombre del GT; el recall, cuánto del nombre del GT dice el registro. Dos tokens de 4 o más letras coinciden si `rapidfuzz.fuzz.ratio >= 85` (`FUZZY_TOKEN`), para tolerar una letra mal leída ("Salchkchas" ~ "Salchichas"). Los tokens del nombre de la tienda no cuentan (`tokens_tienda`): "Alsuper Kg" no es "Queso poroso Alsuper".

Ejemplos reales (corrida `20261026_115424`, sam's_club 421762):

| Página | GT | Registro del dashboard | Similitud | Estado |
|---|---|---|---|---|
| p4 | "Metco BC Edulcorante de Mesa Baja en Calorias (azucar y stevia) 4kg" $199 | "Metco Bc Edulcorantede Mesa Baja en Calorías 4 Kg" $199 | 0.77 | ok |
| p3 | "Philadelphia Original Queso Crema 1.9kg" $326 | "Philadelphia Criginal Quese Crema 19 Kg" $83.26 | 0.67 | `precio_mal_leido` |
| p2 | "Gabi Orejitas Gabi 650g (...)" $109 | "Crejitas Gaei G5c 9" $109 | 0.18 | `asociacion_producto` |

Tabla: Tres páginas de sam's_club 421762 calificadas por el juez

En p4, antes de la pila de `load/load.py` (commit caed57a), el registro era "Baja en Calorías 4 kg": su similitud con el mismo nombre del GT es 0.40 y no habría contado.

### Códigos de error

Cada par equivocado, cada registro sobrante y cada artículo perdido recibe **un** código: el de la primera etapa donde falló. Hay dos familias, porque responden a preguntas distintas.

**Errores de registro** (`ERRORES_REGISTRO`): lo que el dashboard muestra mal. Se cuentan sobre los registros.

| Código | Cuándo |
|---|---|
| `precio_mal_leido` | Par con el precio distinto; o registro sin pareja cuyo texto de precio contiene una firma de 3+ dígitos de algún precio del GT ("5219" → $52.19 cuando el folleto dice $219) |
| `asociacion_producto` | Par con el precio bien y la similitud de nombre < 0.5 |
| `asociacion_antes` | Par con precio y producto bien, pero el precio anterior no coincide |
| `promo_como_producto` | Registro sin pareja cuyo nombre es una promoción: lo detectan `_es_promo_fuerte`/`_es_promo_debil` del NLP o se parece (≥ 0.5) a una promoción de la página en el GT |
| `duplicado` | Registro sin pareja con el mismo precio que un par ya correcto |
| `precio_huerfano` | Registro sin pareja que no es nada de lo anterior: un precio que no está en el GT con un nombre cualquiera |

Tabla: Códigos de error de registro (evaluador/comparar.py)

Para los registros sin pareja, el orden de la tabla es el orden en que se prueban: promoción, duplicado, firma de precio y, al final, huérfano. Ejemplo real de `promo_como_producto`: heb 426799 p5, el registro "En String Cheese, Cheese Sticks; Quesos Tipo Snack..." con $25, que es la promoción de la página del GT de arriba.

**Errores de artículo** (`ERRORES_ARTICULO`): lo que se pierde del folleto. Un artículo emparejado con error hereda el código del par (`precio_mal_leido`, `asociacion_producto` o `asociacion_antes`). Un artículo sin pareja pasa por `_diagnosticar_perdida`, que recorre el pipeline en orden:

```
¿algún bloque OCR contiene las firmas del monto? (29.90 → "2990" o "29")
   no → ocr_no_leido
¿algún PRECIO del NLP vale exactamente eso?
   no → ¿algún PRECIO salió de un bloque con esos dígitos?  sí → precio_mal_leido
                                                         no → clasificacion   (se leyó como antes, ahorro, producto o descarte)
el precio sí se extrajo:
   ¿hay un precio con ese valor sin producto, y el nombre estaba en los productos del NLP
    pero no entre los aceptados por load?                  sí → producto_descartado
   si no → asociacion_producto
```

**Páginas no evaluables.** Una página del GT sin ningún artículo con precio (portadas, páginas de costco con productos sin monto) no entra en las métricas: sus registros no se cuentan como huérfanos (`ResultadoPagina.evaluable`, `test_pagina_gt_sin_precios_no_cuenta`). En dev son 71 de 229 páginas.

### Métricas

`agregar` suma los conteos de las páginas evaluables y calcula:

| Métrica | Fórmula | Clave en el JSON |
|---|---|---|
| **Precisión de registros completos** (principal) | completos correctos / registros en el dashboard | `precision` |
| IC95 de la precisión | Intervalo de Wilson, estable con muestras chicas | `precision_ic95` |
| Recall | completos correctos / artículos del GT con precio | `recall` |
| F1 | 2·P·R / (P + R) | `f1` |
| Precisión y recall básicos | Igual, con `basico_ok` (sin el "antes") | `precision_basica`, `recall_basico` |
| Exactitud de precio en pares | pares con precio igual / pares | `exactitud_precio_en_pares` |
| Exactitud de producto en pares | pares con producto ≥ 0.5 / pares | `exactitud_producto_en_pares` |
| Precisión del precio anterior | registros con "antes" correcto (y básico correcto) / registros con "antes" | `precision_antes` |
| Recall del precio anterior | mismos aciertos / artículos con "antes" | `recall_antes` |
| Exactitud de categoría | pares con producto correcto y categoría igual / pares con producto correcto y categoría en el GT | `exactitud_categoria` |

Tabla: Métricas de una corrida (evaluador/metricas.py)

Además guarda los conteos de errores de registro y de artículo y un **embudo**: cuántos artículos sobreviven al OCR (`embudo_ocr`: todos menos `ocr_no_leido`) y cuántos llegan con el precio bien extraído (`embudo_precio_nlp`: además sin `clasificacion` ni `precio_mal_leido`). En la corrida del 26-oct: 1,556 artículos → 1,490 tras el OCR → 1,033 con precio del NLP → 385 completos correctos.

La categoría se compara con la clave del GT (`alimentos`, `electronica`...) contra la categoría del registro, que el normalizador ya convierte a clave (`03_nlp.md`).

### Comparar dos corridas y regresiones por tienda

`comparar` toma dos JSON de corrida y avisa si alguna no es válida, si los splits son distintos o si no cubren las mismas páginas (con OCR experimental, base y cambio deben ser sobre las mismas páginas). Después `comparar_corridas` calcula, para el global y cada tienda, el delta en puntos de precisión y de recall:

- Una caída es **regresión** si es mayor que `UMBRAL_REGRESION_PTS` = 2.0 puntos.
- Es **significativa** si además la tienda tiene `n >= MUESTRA_MINIMA` (20, el menor de los dos denominadores) y la prueba z de dos proporciones da `|z| >= 1.96` (`Z_95`).
- Las tiendas con menos de 20 casos se reportan con conteos y no bloquean.

Una precisión, por ejemplo, de 60/100 a 40/100 en heb es significativa y bloquea; de 6/10 a 4/10 se reporta pero no bloquea (`test_regresion_significativa_bloquea`, `test_muestra_chica_no_bloquea`).

Ojo con un detalle del código: en `comparar_corridas`, `bloquea` es `n >= MUESTRA_MINIMA`, sin exigir la significancia, y `comparar` termina con código 1 si alguna regresión bloquea. La skill `ciclo-experimento` dice que la regresión bloquea "si además es significativa". El código es más estricto que la skill: la etiqueta `SIGNIFICATIVA` sale en la salida, pero no cambia el código de salida. Esto no se ha cambiado porque `metricas.py` está sellado; si la persona quiere alinearlos, es una decisión suya.

### Detalle caso por caso

Los agregados dan netos: un cambio que gana 30 artículos y pierde 28 se ve como +2. `casos.py` guarda en cada corrida de dev el estado (`ok` o el código de error) de cada artículo, con clave `tienda/folleto/pagina#id` (el `id` del GT, estable entre corridas), y de cada registro, con clave `pagina|precio|x,y` (monto y esquina del bloque de precio; estable mientras no cambie el OCR). `comparar --casos` lista por tienda los artículos ganados (error → ok), los perdidos (ok → error), los que cambian de un error a otro, los registros que dejan de estar bien y los registros nuevos con error, más la matriz de transiciones. La skill pide reportar los dos números ("+35 / −6"), no solo el neto. Ese fue justamente el primer uso (commit cadb8b7): la asociación v1 (68f215d) dio +35 / −6.

Las transiciones de un error a otro (por ejemplo `clasificacion -> precio_mal_leido`) suelen ser reasignaciones del juez porque cambiaron los registros de la página, no cambios reales de OCR o NLP (Engram #141).

### Catálogo de diseños (`evaluador catalogo`)

Herramienta descriptiva, fuera de las métricas: para cada artículo de dev con precio busca su bloque de precio en el NLP (monto igual) y su bloque de nombre en el OCR (similitud ≥ 0.5 completo, ≥ 0.3 parcial) y clasifica la posición del nombre respecto al precio: `arriba`, `fila_izq`, `fila_der` o `debajo`. También dice si ese nombre entraría en los candidatos de `asociar_por_cercania` (`alcanzable_cercania`), el porcentaje de páginas con ROI y la posición dominante por folleto. Sirve para ver qué tiendas y folletos comparten diseño antes de proponer una regla; varias tiendas cambian de diseño entre folletos (alsuper, s-mart, heb), por eso los especialistas no proponen reglas por nombre de tienda. Se guarda en `data/processed/_eval/catalogo/` y **nunca** corre sobre holdout (vería su contenido).

### OCR experimental (`evaluador ocr` y `correr --ocr-exp`)

Un cambio de `vision/preprocessor.py` u `vision/ocr_engine.py` no se ve en el evaluador hasta reprocesar el OCR, que se hace en GPU. `correr_ocr` corre el preprocesador y EasyOCR **en CPU** sobre las páginas de dev con precio, con el perfil y la resolución de cada tienda (o los que se fuercen), y escribe `data/processed/_eval/ocr_exp/<nombre>/<tienda>/<folleto>/ocr_resultado.json` con el mismo formato que producción. Guarda página por página y se reanuda si se interrumpe; se niega a mezclar páginas de otro código (`version_ocr`, hash de los dos archivos) salvo con `--forzar`. `carpeta_exp` rechaza nombres con `/`, `\`, `.` o `:`.

`correr --ocr-exp <nombre>` evalúa solo las páginas de ese experimento, siempre con el NLP en memoria y solo en dev. La base también se corre en CPU con este comando, porque EasyOCR en CPU no da exactamente lo mismo que en GPU: comparar contra el OCR de producción mezclaría hardware con cambio (commit 68f3a12). Tarda unos 35 a 45 s por página (Engram #136). Al 26-oct-2026 la carpeta `ocr_exp/` existe pero está vacía. Detalles de visión en `02_vision.md`.

### Huella de load (`evaluador.huella_load`)

No mide calidad: comprueba que un refactor de `load/load.py` no cambia nada de lo que se escribe en la BD. Corre `Loader._procesar_pagina` sobre todos los folletos de producción con `CursorFalso`, un cursor que registra cada INSERT y UPDATE con sus parámetros (las fechas se reemplazan por `<fecha>`, lo único no determinista), y guarda una línea por página en un `.jsonl.gz`. `comparar` dice cuántas páginas difieren y muestra la primera escritura distinta.

```
python -m evaluador.huella_load guardar data/processed/_eval/huella_antes.jsonl.gz [--limite N]
python -m evaluador.huella_load comparar huella_antes.jsonl.gz huella_despues.jsonl.gz    # EQUIVALENTES o DIFERENTES
```

Con esta herramienta se demostró que el refactor de load a funciones puras (51100fb), que hizo posible el evaluador, dejaba idénticas las 432,047 escrituras (Engram #132).

### Validación humana del juez (`evaluador validacion`)

Un juez automático puede equivocarse. Antes de usarlo, el 11-oct-2026:

1. `validacion muestra` armó 40 casos de dev (`CUOTAS`: 14 que el juez da por correctos, 16 con precio bien y producto dudoso, 10 registros sin pareja), repartidos por tienda y en un orden que no delata el grupo. Cada caso lleva el recorte de la imagen con el precio en azul y el producto en naranja.
2. La persona calificó los 40 a ciegas, viendo solo la imagen y el registro.
3. `validacion concordancia --respuestas DIR` comparó su veredicto básico (precio + producto) con el del juez.

La primera concordancia fue 34/40 (85%, meta 90%). De los desacuerdos, tres eran errores de la persona (69.92 contra 69.90, un precio de otro artículo) y uno era una página de costco sin precios en el GT. De ahí salió la regla de las páginas no evaluables. Tras la revisión quedó en **39/39 (100%)**, con el caso de costco excluido (Engram #133 y #136; verificado en `data/processed/_eval/validacion/concordancia_v1.json`).

## Ground truth, splits e integridad

### De dónde sale el ground truth

- **64 folletos etiquetados a mano** por la persona en agosto de 2026 (`"etiquetado_por": "manual"`), y **13 folletos** de octubre etiquetados por Claude a partir de la imagen (no del OCR) y revisados por la persona (`"claude (borrador revisado por el usuario)"`), para llegar a unos 150 productos con precio por tienda (`data/raw/_revision_manual/candidatas_etiquetado.md`, 03-oct-2026).
- **Regla de etiquetado:** el nombre se escribe literal, tal como está impreso. No se completa con la categoría ni con el tema del folleto. Esa regla salió de corregir páginas de estilo "lifestyle" donde se había escrito la categoría en vez de un nombre que no existía en la imagen (Engram #50) y del caso de Waldo's.
- `data/` no está en git: el GT está protegido por su huella en `manifest.json`, no por el repositorio.

### Splits dev y holdout

El GT se parte **por folleto**, no por página: las páginas de un folleto comparten diseño y errores de OCR, y repartirlas entre dev y holdout filtraría el holdout. La regla (versión 1, `splits.py`):

1. Tiendas con 3 a 5 folletos → 1 a holdout; con 6 o más → 2 (bodega_aurrera, chedraui, heb, la_comer y tiendas_3b).
2. Se elige el folleto con el número de artículos más cercano a la mediana de su tienda.
3. Si la tienda tiene precios anteriores etiquetados, el de holdout debe tener al menos uno.
4. Desempate determinista con sha256 de `SEMILLA = "pricescraper-eval-v1"` + folleto.

El resultado está en `evaluador/splits.json` (versionado en git): 56 folletos en dev y 21 en holdout, con las 16 tiendas en los dos lados. **No se regenera**: `evaluador splits --generar` se niega si el archivo ya existe. Si se agregan folletos al GT, se reparten con la misma regla subiendo la versión, y eso lo decide la persona.

**Por qué el holdout solo lo corre QA.** Dev es donde los especialistas miran casos, ejemplos de error y catálogo para formular hipótesis. Si también miraran el holdout, las reglas se ajustarían a esos folletos y el holdout dejaría de medir cómo generaliza el cambio. Por eso:

- solo el agente `qa-evaluador` corre `--split holdout` (o `todo`), y solo cuando se le pide; el hook `.claude/hooks/guardia_agente.py` lo bloquea a los especialistas (`tests/test_guardia_agente.py`);
- una corrida de holdout guarda solo agregados, sin `detalle` ni `ejemplos_error`;
- `catalogo`, `ocr` y `validacion` trabajan solo con dev.

Según los archivos de `runs/`, hay 8 corridas de holdout y la última es del 12-oct-2026 (`20261012_135834_5823d76-sucio_holdout.json`, con la que se aprobó e4184da: holdout F1 7.3 → 8.4, según su mensaje de commit). Los cambios posteriores, incluida la pila de load que subió el F1 de dev de 16.7 a 26.5, no se han confirmado en holdout.

### Sellado e integridad

`manifest.json` guarda el sha256 de:

- cada archivo del GT (`gt`, 77 entradas);
- `splits.json` (`splits`);
- las reglas, `ARCHIVOS_REGLAS = ("gt.py", "comparar.py", "metricas.py", "splits.py", "integridad.py")`: los archivos que definen qué cuenta como correcto.

Cada `correr` recalcula esas huellas (`integridad.verificar`). Si algo cambió sin volver a sellar, la corrida se imprime como `CORRIDA NO VALIDA` con la lista de problemas ("GT modificado: ...", "splits.json modificado", "regla modificada: evaluador/comparar.py") y termina con código 2. Una corrida no válida no sirve para decidir, y el dashboard la ignora.

`pipeline.py`, `reporte.py`, `casos.py`, `catalogo.py` y los demás no están sellados a propósito: no deciden qué es correcto, solo llaman al código que se evalúa o presentan resultados. Aun así, el hook de la guardia impide a los agentes editar cualquier archivo de `evaluador/` y de `data/`.

**Sellar es una decisión de la persona.** `evaluador sellar --motivo "..."` reescribe `manifest.json` con las huellas actuales, la fecha y el motivo. Como `manifest.json` está en git, cualquier resellado aparece en el diff. El sello vigente es del 11-oct-2026 a las 16:17:23, con el motivo "Hash de reglas con saltos de línea normalizados (CRLF/LF); sin cambio de criterio" (commit afccff2): con `core.autocrlf` un checkout convertía los saltos de línea y el hash crudo cambiaba sin cambio real, así que `_sha` normaliza CRLF a LF. Desde entonces no se ha resellado: ni el GT, ni los splits, ni las reglas han cambiado. `evaluador verificar` da `Integridad OK (sellado 2026-10-11T16:17:23)` al 26-oct-2026.

Si alguien cree que el juez está equivocado en un caso, no lo "arregla": lo reporta con el ejemplo a la persona.

## Comandos

Siempre con el Python del proyecto (`venv/Scripts/python.exe`) y desde la raíz del repo, porque las rutas son relativas (`data/...`). Todos los subcomandos se verificaron con `--help` el 26-oct-2026.

| Comando | Qué hace | Quién lo usa |
|---|---|---|
| `correr [--split dev\|holdout\|todo] [--nlp disco\|memoria] [--tienda T] [--sin-guardar] [--ocr-exp N]` | Mide contra el GT. Por defecto `--split dev --nlp disco` | Todos; holdout y todo solo QA |
| `comparar BASE.json NUEVA.json [--casos] [--tienda T] [--max N]` | Deltas y regresiones por tienda; con `--casos`, la lista de casos (`--max` 40 por defecto) | Especialistas y QA |
| `catalogo [--tienda T] [--nlp memoria\|disco]` | Diseño por tienda en dev (por defecto `--nlp memoria`) | Especialistas |
| `ocr --nombre N [--tienda T] [--max-paginas K] [--perfil P] [--resolucion R] [--forzar]` | OCR experimental en CPU sobre dev | Solo visión y QA |
| `verificar` | GT, splits y reglas contra `manifest.json` | Todos |
| `sellar --motivo "..."` | Reescribe el sello | Solo la persona |
| `splits --generar` | Genera `splits.json` una sola vez | Nadie (ya existe) |
| `validacion muestra` / `validacion concordancia --respuestas DIR` | Validación del juez contra una persona | La persona |

Tabla: Subcomandos de python -m evaluador (evaluador/__main__.py)

Opciones de `correr`:

- `--nlp disco` lee los `nlp_resultado.json` cargados en la BD: mide **lo que hoy muestra** el dashboard. `--nlp memoria` regenera el NLP con el código actual sin escribir: mide **un cambio** antes de reprocesar. Un cambio de `nlp/` solo se ve con `memoria`; un cambio de `load/load.py`, con cualquiera de los dos.
- `--tienda T` filtra por slug (`heb`, `sam's_club`). Sirve para iterar rápido, pero la decisión se toma con dev completo.
- `--sin-guardar` no escribe el JSON. Para `comparar --casos` hacen falta dos corridas guardadas.
- `--ocr-exp N` obliga a `--nlp memoria` y solo funciona con `--split dev`.

El ciclo de un experimento (skill `ciclo-experimento`):

```
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria       # base, ANTES de editar
# ... cambio mínimo + pruebas en tests/ ...
venv/Scripts/python.exe -m pytest tests -q
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria       # nueva
venv/Scripts/python.exe -m evaluador comparar <base.json> <nueva.json> --casos
```

Se mantiene un cambio solo si la precisión sube, el recall no baja, el F1 sube y no hay regresiones que bloqueen. Subir la precisión descartando registros buenos no es mejora.

## Corridas guardadas

- **Nombre:** `<fecha>_<hora>_<commit>[-sucio]_<split>.json`. El commit es el `HEAD` al correr (`git rev-parse --short HEAD`) y `-sucio` se agrega si había cambios sin commit en archivos versionados (`git status --porcelain --untracked-files=no`). Por eso la medición de un cambio todavía sin commit queda con el hash del commit **anterior** y `-sucio`: `20261025_224754_798a35f-sucio_dev.json` es la medición de f1b0afe antes de su commit.
- **Volumen:** al 26-oct-2026 hay 171 corridas: 161 de dev con `--nlp memoria`, 2 de dev con `--nlp disco` (11-oct) y 8 de holdout. Ninguna con `--tienda` ni `--ocr-exp` quedó guardada. Las de dev pesan alrededor de 1.2 MB.
- **Otras carpetas de `data/processed/_eval/`:** `catalogo/` (9 catálogos), `cache_regiones/<version_vision>/` (regiones ROI de cada página; `version_vision` es un hash de `vision/preprocessor.py` y `vision/region_detector.py`, así que el caché se invalida solo cuando cambia alguno; hay dos versiones), `ocr_exp/` (vacía), `validacion/` (`muestra_v1.json`, `concordancia_v1.json`) y los logs de huella.
- `data/` está en `.gitignore`: las corridas no viajan con el repo. Quien clone el proyecto tiene que generar su propia corrida.

## Uso en el dashboard

La página Calidad del dashboard (oculta de la barra) muestra la confiabilidad por tienda. La parte del evaluador la lee `dashboard/confiabilidad.py`, un módulo puro, sin BD (`07_dashboard.md`):

- `corrida_vigente()` toma, de `data/processed/_eval/runs/*.json`, la más reciente por `meta.fecha` entre las válidas: split `dev`, `cambios_sin_commit` en `false`, integridad válida y con fecha (`es_corrida_valida`). Descarta por nombre las `-sucio` y las que no son `_dev` sin abrirlas, y guarda cada archivo en caché por `mtime` y tamaño.
- `metricas_tienda()` saca de `metricas.tiendas.<slug>` la precisión, su IC95, el recall, los registros evaluados, los artículos del GT y el error dominante (el mayor de `errores_registro`), y le pone una etiqueta con `etiqueta_confiabilidad`: Sin medir, Muestra insuficiente (menos de 30 registros), Baja (precisión < 0.10), Aceptable (precisión ≥ 0.25 y IC95 inferior ≥ 0.15) o Media.

Consecuencia práctica: las corridas `-sucio` nunca llegan al panel. Después de cada commit que cambia la calidad hay que repetir `correr --split dev --nlp memoria` con el árbol limpio, como se hizo el 26-oct-2026 (`20261026_115424_398c4e4_dev.json`, la vigente hoy).

## Cifras actuales

Corrida `20261026_115424_398c4e4_dev.json`: dev, `--nlp memoria`, árbol limpio (commit 398c4e4), integridad válida, 229 páginas (158 evaluables).

| Métrica | Valor |
|---|---|
| **Precisión de registros completos** | **33.1%** (IC95 30.5–35.9%): 385 de 1,162 registros |
| Recall | 24.7%: 385 de 1,556 artículos con precio |
| F1 | 28.3% |
| Precisión y recall básicos (sin "antes") | 35.6% y 26.6% |
| Exactitud de precio en pares | 72.7% (701 de 964 pares) |
| Exactitud de producto en pares | 64.5% (622 de 964) |
| Precio anterior | precisión 60.0% (66 de 110), recall 34.7% (66 de 190) |
| Categoría | 68.9% (428 de 621) |

Tabla: Métricas globales en dev, 26-oct-2026 | Fuente: data/processed/_eval/runs/20261026_115424_398c4e4_dev.json

| Errores de registro | | Errores de artículo | |
|---|---|---|---|
| `precio_mal_leido` | 321 | `ocr_no_leido` | 66 |
| `asociacion_producto` | 287 | `clasificacion` | 300 |
| `asociacion_antes` | 29 | `precio_mal_leido` | 420 |
| `promo_como_producto` | 4 | `producto_descartado` | 0 |
| `duplicado` | 3 | `asociacion_producto` | 356 |
| `precio_huerfano` | 133 | `asociacion_antes` | 29 |

Tabla: Errores por código en dev, 26-oct-2026 | Fuente: corrida 20261026_115424

Lectura: del lado del dashboard, los dos errores grandes son el precio mal leído (321) y el producto equivocado (287). Del lado del folleto, lo que más se pierde es el precio mal leído (420), el producto (356) y los precios que el NLP clasificó como otra cosa (300); el OCR casi siempre lee los dígitos (solo 66 artículos con `ocr_no_leido`).

| Tienda | Páginas | Registros | Artículos | Correctos | Precisión | IC95 | Recall | F1 | Error dominante (registro) | Etiqueta en el panel |
|---|---|---|---|---|---|---|---|---|---|---|
| alsuper | 15 | 119 | 188 | 29 | 24.4% | 17.5–32.8 | 15.4% | 18.9% | `precio_mal_leido` | Media |
| bodega_aurrera | 20 | 66 | 167 | 35 | 53.0% | 41.2–64.6 | 21.0% | 30.0% | `asociacion_producto` | Aceptable |
| casa_ley | 9 | 185 | 295 | 13 | 7.0% | 4.2–11.7 | 4.4% | 5.4% | `precio_mal_leido` | Baja |
| chedraui | 13 | 72 | 76 | 25 | 34.7% | 24.8–46.2 | 32.9% | 33.8% | `asociacion_producto` | Aceptable |
| costco | 0 | 0 | 0 | 0 | — | — | — | — | — | Sin medir |
| heb | 14 | 123 | 116 | 35 | 28.5% | 21.2–37.0 | 30.2% | 29.3% | `precio_mal_leido` | Aceptable |
| la_comer | 12 | 59 | 90 | 17 | 28.8% | 18.8–41.4 | 18.9% | 22.8% | `precio_mal_leido` | Aceptable |
| merco | 13 | 68 | 117 | 21 | 30.9% | 21.2–42.6 | 17.9% | 22.7% | `asociacion_producto` | Aceptable |
| oxxo | 0 | 0 | 0 | 0 | — | — | — | — | — | Sin medir |
| s-mart | 6 | 153 | 160 | 55 | 35.9% | 28.8–43.8 | 34.4% | 35.2% | `asociacion_producto` | Aceptable |
| sam's_club | 6 | 6 | 6 | 3 | 50.0% | 18.8–81.2 | 50.0% | 50.0% | `precio_mal_leido` | Muestra insuficiente |
| soriana_hiper | 9 | 55 | 67 | 19 | 34.5% | 23.4–47.8 | 28.4% | 31.2% | `precio_mal_leido` | Aceptable |
| soriana_mercado | 11 | 71 | 88 | 3 | 4.2% | 1.5–11.7 | 3.4% | 3.8% | `precio_mal_leido` | Baja |
| tiendas_3b | 12 | 81 | 84 | 65 | 80.2% | 70.3–87.5 | 77.4% | 78.8% | `asociacion_producto` | Aceptable |
| waldos | 8 | 12 | 13 | 4 | 33.3% | 13.8–60.9 | 30.8% | 32.0% | `asociacion_producto` | Muestra insuficiente |
| walmart | 10 | 92 | 89 | 61 | 66.3% | 56.2–75.1 | 68.5% | 67.4% | `precio_mal_leido` | Aceptable |

Tabla: Calidad por tienda en dev, 26-oct-2026 (la etiqueta se calculó con dashboard/confiabilidad.py) | Fuente: corrida 20261026_115424

El resumen que imprime `correr` en consola elige el "error principal" entre los dos tipos de error, así que puede no coincidir con la columna del panel, que usa solo errores de registro. tiendas_3b y walmart son las únicas tiendas que pasan de 60%; casa_ley y soriana_mercado no llegan a 10%, y en las dos domina el precio mal leído. Con menos de 20 artículos (sam's_club y waldos), una diferencia de un registro mueve decenas de puntos.

## Evolución del F1 en dev

Todas las cifras son de dev con `--nlp memoria`, medidas con el mismo juez (el sello no ha cambiado desde el 11-oct-2026), así que son comparables entre sí. Cada fila es un commit que cambió el pipeline. Los valores salen del mensaje del commit y se contrastaron con las corridas de `runs/`.

| Fecha | Commit | Cambio | Precisión | Recall | F1 |
|---|---|---|---|---|---|
| 11-oct | afccff2 | Línea base del evaluador (corrida `20261011_162211`) | 3.8 | 3.5 | 3.6 |
| 11-oct | 68f215d | Load: nombre a la misma altura o debajo del precio | 5.6 | 5.3 | 5.5 |
| 11-oct | 4aaa0cc | NLP: "$" leído como dígito, Antes − Ahorra | 6.0 | 5.7 | 5.9 |
| 11-oct | c468950 | NLP: rótulos de casilla aislados a descarte | 7.1 | 6.8 | 7.0 |
| 11-oct | ecbaa5d | Normalizador: fuzzy solo si el canónico cubre el texto | 10.6 | 10.2 | 10.4 |
| 11-oct | c1a84b2 | Load: filtro de nombres ilegibles | 10.8 | 10.3 | 10.6 |
| 12-oct | 1838425, 7fad080 | NLP: anticipos de apartado y mensualidades MSI no son precio | 11.5 | 10.3 | 10.9 |
| 12-oct | e4184da | Load: nombre alineado debajo, por diseño de página | 12.8 | 11.5 | 12.1 |
| 12-oct | 2f616c3, 6d0670b | NLP: rótulos de promoción y plazos no son producto ni precio | 12.9 | 11.6 | 12.2 |
| 13-oct | 993e065 | Load: unidad suelta unida a su descripción | 13.4 | 12.0 | 12.7 |
| 13-oct | ea975ff | Load: columna propia si el ganador queda en diagonal | 14.7 | 13.2 | 13.9 |
| 14-oct | b0ce8ae | Load: línea perdida en la pila de la unidad | 14.8 | 13.2 | 14.0 |
| 24-oct | aa7f88d | NLP: precio sin "$" se rechaza si tiene letra o continúa el nombre | 17.8 | 13.3 | 15.2 |
| 24-oct | 43e4040 | NLP: entero y centavos en superíndice alineados arriba | 18.6 | 14.1 | 16.0 |
| 25-oct | 94cc22a | NLP: dígito espurio + miles con coma + superíndice | 19.4 | 14.6 | 16.7 |
| 25-oct | caed57a | Load: nombre partido en varias líneas (pila) | 30.8 | 23.3 | 26.5 |
| 25-oct | ddb5bbb | NLP: "$" como bloque aparte junto al número | 30.8 | 23.3 | 26.6 |
| 25-oct | 6865f14 | NLP: "$" leído como 5/6/8/s con la escala de la página | 31.8 | 24.6 | 27.7 |
| 25-oct | f1b0afe | NLP: centavos pegados en el mismo bloque | 33.1 | 24.7 | 28.3 |
| 26-oct | 284caaf | NLP: marca con borde de palabra (corrida limpia `20261026_115424`) | 33.1 | 24.7 | 28.3 |

Tabla: Evolución de la calidad en dev, octubre de 2026 (porcentajes) | Fuente: mensajes de commit y data/processed/_eval/runs/

En dos semanas el F1 pasó de 3.6 a 28.3. Los saltos grandes fueron del normalizador (ecbaa5d, +3.4) y de la pila de load (caed57a, +9.8). Entre el 14 y el 24 de octubre hubo commits sin efecto en dev: dfa5d73 (canónico del nombre unido; el evaluador no lee el canónico), 85e9e95 (campañas) y 9a1a450 (catálogo con tipos y marcas, que subió la exactitud de categoría de 52.0 a 55.1 sin mover el F1). Los detalles de cada regla están en `03_nlp.md` y `05_load.md`.

## Reglas y decisiones

- **La precisión es la métrica principal, con recall y F1 obligatorios.** El dashboard lo usan personas para comparar precios: un registro equivocado hace más daño que uno que falta. Pero subir la precisión descartando registros buenos no es mejora: si el recall baja, el cambio se rechaza aunque la precisión suba. Esa elección quedó abierta en la propuesta del 11-oct (Engram #131) y se fijó así en la skill `ciclo-experimento`.
- **Registros completos, no campos sueltos.** El comparador de agosto (`nlp/evaluador_calidad.py`) contaba un precio bien leído como acierto aunque el nombre fuera de la casilla vecina. El caso que lo motivó está en la prueba `test_precio_correcto_producto_equivocado_no_cuenta`: unos audífonos de $320 que el dashboard mostraba como "Desodorante" (Engram #132).
- **Asignación óptima uno a uno con nombre en el puntaje.** Ver "Emparejamiento uno a uno". Un emparejamiento voraz por precio regalaría aciertos a los registros con el monto de otro producto.
- **Umbral de nombre 0.5.** Es el mismo `UMBRAL_RECALL_TEXTO` del comparador anterior, y con él se validó el juez (39/39). "Pan de caja" contra "Pan de caja Bimbo 680g" da 0.67 y cuenta; "Laptop" contra "Acer Laptop 15.6" Mod. NX.J53AL.001" da 0.33 y no.
- **Un código por la primera etapa que falló.** Así se sabe a quién le toca: `ocr_no_leido` es de visión; `clasificacion` y `precio_mal_leido`, del NLP; `asociacion_producto` y `asociacion_antes`, de load; `producto_descartado`, del normalizador o del filtro de ilegibles.
- **IC de Wilson y prueba z por tienda.** Las tiendas tienen de 6 a 295 artículos en dev; con muestras chicas, el intervalo normal da límites fuera de [0, 1] y diferencias que son ruido. El umbral de 2 puntos es provisional y lo acordó la persona (comentario de `UMBRAL_REGRESION_PTS`).
- **Páginas sin precio fuera de las métricas.** Salió de la validación humana (costco, Engram #133).
- **El nombre de la tienda no identifica un producto.** "Alsuper Kg" no debe emparejar con "Queso poroso Alsuper" (`test_nombre_de_tienda_no_identifica_producto`).
- **Holdout sin detalle.** Una corrida de holdout con ejemplos o casos sería una puerta para mirar sus folletos.
- **El evaluador no se modifica para que un cambio "pase".** GT, splits, reglas y `manifest.json` son decisión de la persona; los agentes tienen bloqueado editar `evaluador/`, `data/`, `tests/test_evaluador.py` y `tests/conftest.py`, y correr `sellar` y `splits` (`.claude/hooks/guardia_agente.py`).

## Configuración

| Constante | Valor | Archivo | Para qué |
|---|---|---|---|
| `UMBRAL_PRODUCTO` | 0.5 | `comparar.py` | Similitud mínima para que el producto corresponda |
| `UMBRAL_CANDIDATO` | 0.3 | `comparar.py` | Sin precio igual, similitud mínima para considerar el par |
| `PESO_PRECIO`, `PESO_NOMBRE` | 0.6, 0.4 | `comparar.py` | Pesos del puntaje del emparejamiento |
| `FUZZY_TOKEN` | 85 | `comparar.py` | `fuzz.ratio` mínimo entre tokens de 4+ letras |
| `TOLERANCIA_PRECIO` | 0.01 | `nlp/evaluador_calidad.py` | Precios iguales al centavo |
| `UMBRAL_REGRESION_PTS` | 2.0 | `metricas.py` | Caída en puntos que cuenta como regresión |
| `MUESTRA_MINIMA` | 20 | `metricas.py` | Por debajo, la tienda no bloquea |
| `Z_95` | 1.96 | `metricas.py` | IC de Wilson y significancia |
| `SEMILLA`, `VERSION` | `"pricescraper-eval-v1"`, 1 | `splits.py` | Desempate y versión de la partición |
| `ARCHIVOS_REGLAS` | gt, comparar, metricas, splits, integridad | `integridad.py` | Archivos sellados |
| `EJEMPLOS_POR_CODIGO` | 10 | `reporte.py` | Ejemplos por código y tienda en el JSON |
| `SIM_NOMBRE`, `SIM_PARCIAL` | 0.5, 0.3 | `catalogo.py` | Nombre completo o parcial en el catálogo de diseños |
| `CUOTAS` | 14 / 16 / 10 | `validacion.py` | Composición de la muestra de validación |
| `RAIZ_RUNS` | `data/processed/_eval/runs` | `reporte.py` | Dónde se guardan las corridas |
| `RAIZ_CACHE_REGIONES` | `data/processed/_eval/cache_regiones` | `pipeline.py` | Caché de regiones ROI por versión de visión |
| `RAIZ_OCR_EXP` | `data/processed/_eval/ocr_exp` | `ocr_experimental.py` | Experimentos de OCR en CPU |

Tabla: Constantes del evaluador

Las de `comparar.py`, `metricas.py` y `splits.py` están en archivos sellados: cambiarlas invalida las corridas hasta que la persona vuelva a sellar, y las cifras de antes y después ya no serían comparables. `TOLERANCIA_PRECIO` no lo está (ver "Limitaciones conocidas y pendientes").

## Pruebas

| Archivo | Casos | Qué fija |
|---|---|---|
| `tests/test_evaluador.py` | 28 | Similitud (acentos, palabras vacías, una letra), uno a uno, mismo precio con otro nombre, nombres cruzados, duplicado, promoción, precio mal leído, precio anterior, Wilson, regresiones, splits deterministas, congelados, estratificados y con "antes" en holdout, huella del GT, nombre de tienda, concordancia, páginas sin precio, nombre seguro del OCR experimental y `ocr_exp` con NLP en memoria |
| `tests/test_evaluador_casos.py` | 4 | Estado de cada artículo y registro, ganados contra perdidos, registros nuevos con error, corridas iguales sin cambios |
| `tests/test_evaluador_catalogo.py` | 3 | Posiciones del nombre, alcance de la cercanía, estados por artículo y par más cercano |
| `tests/test_dashboard_confiabilidad.py` | 35 | Elección de la corrida vigente, etiquetas y umbrales del panel |
| `tests/test_guardia_agente.py` | 53 | Entre otras cosas: los agentes no editan `evaluador/` ni `data/`, no corren `sellar` ni `splits`, el holdout es solo de QA y `evaluador ocr` es solo de visión y QA |

Tabla: Pruebas que cubren el evaluador (casos recogidos por pytest al 26-oct-2026)

```
venv/Scripts/python.exe -m pytest tests/test_evaluador.py tests/test_evaluador_casos.py tests/test_evaluador_catalogo.py tests/test_dashboard_confiabilidad.py -q
venv/Scripts/python.exe -m evaluador verificar
```

Las primeras cuatro pasan al 26-oct-2026 (70 casos). Las pruebas del evaluador usan registros y artículos sintéticos, salvo las de splits y la huella del GT, que leen el GT real (por eso necesitan `data/`). `tests/test_evaluador.py` y `tests/conftest.py` están protegidos: los especialistas agregan sus pruebas en otros archivos. Los scripts `tests/_herramienta_*.py` son herramientas de medición de los agentes que importan el evaluador; pytest no los recoge.

## Limitaciones conocidas y pendientes

- **El holdout no se corre desde el 12-oct-2026.** La mejora de dev desde entonces (F1 12.1 → 28.3) no está confirmada en folletos que nadie miró. Vale la pena que QA lo corra antes de citar el resultado final.
- **El GT es chico y desigual.** 1,556 artículos con precio en dev; costco y oxxo no se pueden medir en dev, y sam's_club y waldos tienen menos de 20 artículos. Solo hay folletos de tiendeo: ofertomat no tiene GT.
- **`asociacion_producto` mezcla dos causas.** Un nombre correcto pero mal leído por el OCR ("Crejitas Gaei G5c 9" por "Gabi Orejitas", similitud 0.18) cuenta igual que el nombre de otra casilla. Lo mismo un nombre genérico pero cierto ("Laptop" por "Acer Laptop 15.6" ..."). Para separarlos hay que mirar los casos (`tests/_herramienta_asoc_diag.py` lo hace por subtipo, `05_load.md`).
- **Un solo umbral de nombre para todo.** Nombres largos del GT con descripciones entre paréntesis ("(azúcar y stevia)") bajan la similitud de un registro correcto.
- **Parte del juez vive fuera del sello.** `similitud_nombre` usa `tokens_significativos` y `TOLERANCIA_PRECIO` de `nlp/evaluador_calidad.py`, y `promo_como_producto` usa `_es_promo_fuerte`/`_es_promo_debil` de `nlp/regex_extractor.py`. Ninguno de los dos archivos está en `ARCHIVOS_REGLAS`, y la guardia deja al agente de producto editar `nlp/`. Un cambio en las palabras vacías o en la normalización de `evaluador_calidad.py` cambiaría qué cuenta como correcto sin dejar la corrida NO VALIDA. Los detectores de promoción solo cambian el código de los registros sobrantes, no qué es correcto. Según git, `nlp/evaluador_calidad.py` no cambia desde el 03-oct-2026 (842ccf5), antes del sello, así que las corridas de octubre siguen siendo comparables. Desde el 26-oct-2026 la guardia de agentes protege `nlp/evaluador_calidad.py` (ningún agente lo edita); sellarlo o copiar esas funciones a `evaluador/` sigue siendo una opción más fuerte, que decide la persona.
- **`bloquea` no exige significancia** (ver "Comparar dos corridas"): el código y la skill dicen cosas distintas.
- **La propuesta pedía F1 ≥ 70%** (criterio que también usaba `probar_evaluar_nlp.py`). El F1 de registros completos está en 28.3% global; solo tiendas_3b (78.8%) lo supera. Las dos métricas no son la misma: la de la propuesta medía campos por separado.

## Historial

- **Agosto de 2026: comparador por campos.** `evaluar_nlp.py` y `nlp/evaluador_calidad.py` (commit 8175349, 07-ago) comparaban el pipeline contra el etiquetado manual de 65 folletos y separaban la causa de cada pérdida (OCR, clasificación o dígitos perdidos por los centavos en superíndice). Con él se subió el recall de precio de 16.3% a 26.7%, y el 24-ago se calculó por primera vez un F1 (Engram #56, #61 y #89). El 03-oct el script se renombró a `probar_evaluar_nlp.py` (842ccf5). Medía producto y precio por separado, así que sus cifras no se comparan con las de hoy.
- **03-oct-2026: ampliación del GT** a unos 150 productos con precio por tienda, con 13 folletos nuevos (`candidatas_etiquetado.md`).
- **11-oct-2026: evaluador de registros.** Propuesta técnica (Engram #131); refactor de load a funciones puras con equivalencia demostrada por la huella (51100fb); el evaluador con juez uno a uno, splits congelados, sello y validación humana 39/39 (059f59d); sello independiente de los saltos de línea (afccff2); OCR experimental en CPU (68f3a12); los agentes especialistas, QA y la guardia (13019d8); el detalle caso por caso (cadb8b7) y el catálogo de diseños (34ae39e).
- **12-oct-2026:** el dashboard empieza a leer la corrida vigente para la confiabilidad por tienda (128b7d9).
- Desde entonces el evaluador no ha cambiado: lo que cambió es el pipeline que mide (ver "Evolución del F1 en dev"). La historia está en `git log -- evaluador/` y en Engram (proyecto `pricescraper_ss`, temas `evaluador/*`, `experimentos/producto/*` y `experimentos/qa/*`).
