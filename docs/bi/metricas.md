# Catalogo de metricas BI - PriceScraper MX

Autor: agente BI. Ultima actualizacion: 14-oct-2026.

Estado de cada metrica: **propuesta** (definida y validada contra la BD, no construida en el dashboard),
**aprobada** (la persona la acepto) o **publicada** (visible en el dashboard).

Convenciones comunes:

- **Registro del dashboard**: fila de `extracciones` con `tipo='PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL`
  (= `v_precios_actuales`). 28,634 al 12-oct-2026.
- **Producto de catalogo**: `metodo_norm IN ('exacto','fuzzy','fuzzy_bajo')` en la fila PRODUCTO a la que apunta el
  PRECIO (`producto_extraccion_id`). `heuristico` = texto del folleto tal cual. En la fila PRECIO `metodo_norm` siempre
  es NULL.
- **Categoria vacia** (= "sin categoria"): `COALESCE(BTRIM(categoria_nlp), '') = ''` sobre la fila PRECIO, es decir
  `''`, NULL o solo espacios (hoy todas las vacias son `''`: 17,102 de 27,760 al 14-oct-2026). Ver seccion 5.
- **Corrida del evaluador vigente**: el JSON mas reciente de `data/processed/_eval/runs/*_dev.json` con
  `meta.split='dev'`, `meta.codigo.cambios_sin_commit=false` e `integridad.valida=true`. Mide solo los folletos de dev
  con ground truth (56 folletos en el split, 16 tiendas; 158 paginas y 14 tiendas con articulos con precio en la corrida
  20261012_141917_e4184da). **No mide produccion completa**: es una muestra por tienda.

---

## 1. Confiabilidad del dato por tienda

| Campo | Valor |
|---|---|
| Estado | **aprobada** (propuesta y aprobada 12-oct-2026; construida, pendiente de que la persona la vea para "publicada") |
| Pregunta | Para cada tienda, que tan confiable es lo que el dashboard muestra como "precio de un producto"? |
| Donde | Pagina Calidad (`/calidad`), seccion superior; API `/api/confiabilidad` |
| Implementacion | `dashboard/confiabilidad.py` (lector del JSON, umbrales como constantes, etiqueta), `dashboard/queries.py` (`confiabilidad_por_tienda`, `_SQL_CONFIABILIDAD`), `dashboard/templates/dashboard/calidad.html` |
| Verificacion del construido | `docs/bi/consultas/verificacion_dashboard_confiabilidad.sql` (SQL exacta de queries.py con parametros por defecto): 20 filas identicas a la consulta de la metrica |
| Grano | Tienda (20 filas; las tiendas sin medicion aparecen como "Sin medir") |
| Fuente BD | `extracciones` (PRECIO y su fila PRODUCTO), `folletos` (filtro de fecha), `tiendas` |
| Fuente archivo | Corrida vigente del evaluador (JSON), `metricas.tiendas.<slug>` |
| Consulta | `docs/bi/consultas/confiabilidad_por_tienda.sql` |
| Validacion | `docs/bi/consultas/confiabilidad_por_tienda_validacion.sql` (desde la vista, EXISTS en vez de JOIN): cuadra fila por fila; totales 28,634 registros, 4,146 de catalogo, 18,601 sin categoria |
| Conciliacion evaluador-BD | `docs/bi/consultas/conciliacion_evaluador_bd.sql`: registros de la BD en las 158 paginas evaluadas = `registros_dashboard` del JSON en las 14 tiendas (1,401 = 1,401) |

KPIs (por tienda):

| KPI | Formula | Fuente |
|---|---|---|
| Registros | `COUNT(*)` registros del dashboard | BD |
| % catalogo | registros con PRODUCTO `metodo_norm IN (exacto,fuzzy,fuzzy_bajo)` / registros | BD |
| % heuristico | registros con PRODUCTO `metodo_norm='heuristico'` / registros (= 100 - % catalogo; hoy no hay otro valor) | BD |
| % sin categoria | registros con `COALESCE(categoria_nlp,'')=''` / registros | BD |
| Confianza OCR | media y mediana de `extracciones.confianza_ocr` de los registros (se muestra la mediana; la media en tooltip) | BD |
| Precision (evaluador) | `metricas.tiendas.<slug>.precision` = completos_ok / registros_dashboard (precio y producto correctos), con `precision_ic95` | JSON |
| Recall (evaluador) | `metricas.tiendas.<slug>.recall` = completos_ok / articulos_con_precio | JSON |
| Error dominante | categoria con mas casos en `errores_registro` (precio_mal_leido, asociacion_producto, precio_huerfano...) | JSON |
| Auxiliares | % duplicados exactos (filas sobrantes mismo folleto+pagina+texto+valor), # atipicos (< $1 o > $100,000) | BD |

Etiqueta de confiabilidad (se calcula solo con la precision medida; es **relativa**, ninguna tienda supera 40%):

| Etiqueta | Regla | Justificacion |
|---|---|---|
| Sin medir | la tienda no tiene articulos con precio en el GT de la corrida (no esta en el split o `paginas=0`) | No hay medicion; no se infiere |
| Muestra insuficiente | `registros_dashboard < 30` en la corrida | Con < 30 registros el IC95 abarca > 40 puntos (waldos 12 reg: 9%-53%) |
| Baja | precision < 0.10 | Menos de 1 de cada 10 registros es correcto; por debajo del global (12.8%) |
| Media | 0.10 <= precision < 0.25 | Alrededor del global; 1 de cada 4-10 registros correcto |
| Aceptable | precision >= 0.25 **y** limite inferior del IC95 >= 0.15 | Al menos 1 de cada 4 correcto con evidencia estadistica; hoy solo walmart y tiendas_3b |

Distintivo adicional "Base heuristica" cuando % catalogo < 20% (17 de 20 tiendas): los nombres de producto de esa tienda
no sirven para comparar contra otras tiendas.

Umbrales (constantes en `dashboard/confiabilidad.py`, cubiertas por `tests/test_dashboard_confiabilidad.py`):
`UMBRAL_REGISTROS_MINIMOS=30`, `UMBRAL_PRECISION_MEDIA=0.10`, `UMBRAL_PRECISION_ACEPTABLE=0.25`,
`UMBRAL_IC95_INFERIOR_ACEPTABLE=0.15`, `UMBRAL_PCT_CATALOGO_BASE_HEURISTICA=20.0`. Una tienda con precision >= 0.25
pero IC95 inferior < 0.15 queda en Media. Una tienda medida es la que tiene `conteos.paginas > 0` y
`conteos.articulos_con_precio > 0` en la corrida; si no, Sin medir.

Mecanismo evaluador -> dashboard (opcion A aprobada): Django lee `data/processed/_eval/runs/*.json`, descarta por nombre
los `-sucio` y los que no son `_dev` (atajo; nombres fuera de convencion se parsean), valida en el contenido
`meta.split='dev'`, `meta.codigo.cambios_sin_commit=false`, `integridad.valida=true` y toma la de `meta.fecha` mas
reciente. Cada archivo se parsea una vez por proceso mientras no cambie (cache por mtime+tamano; ~0.2 s la primera vez
con 73 corridas, ~0 despues). Sin corrida valida, o sin la carpeta (p. ej. en un servidor: `data/` esta en .gitignore),
las columnas del evaluador muestran "Sin medir" y la pagina funciona. El panel muestra commit, fecha, split, paginas y
tiendas medidas de la corrida, y el aviso de que es una muestra de dev.

Filtros: tienda; rango de fechas del folleto (`folletos.fecha_inicio`) para la parte BD. La parte del evaluador no se
filtra por fecha (es la medicion de la corrida) y el panel muestra commit y fecha de la corrida.
Exclusiones: ninguna en los KPIs principales (describen el dato tal como lo ve el dashboard); duplicados y atipicos se
muestran como auxiliares.
Confiabilidad del propio KPI: % catalogo y % sin categoria son conteos exactos de la BD. Precision/recall son muestras
(IC95 visible); se aplican a la tienda solo si el codigo cargado en la BD es el de la corrida (comprobar con la
conciliacion).

---

## 2. Cobertura y frescura por tienda

| Campo | Valor |
|---|---|
| Estado | **aprobada** (propuesta y aprobada 12-oct-2026; construida, pendiente de que la persona la vea para "publicada") |
| Pregunta | De que tiendas tenemos folletos vigentes hoy, que tan reciente es lo ultimo capturado y cuanto dato de precio hay detras? |
| Grano | Tienda (tabla) y semana ISO x tienda (serie temporal) |
| Donde | Pagina nueva Cobertura (`/cobertura`, entrada "Cobertura" en el menu); API `/api/cobertura` y `/api/cobertura/semanal` |
| Fuente | `v_folletos_vigencia` (**unica definicion de vigencia**, load/vistas.sql), `paginas`, `extracciones`, `tiendas`, `errores_carga` (por `tienda_slug`, sin FK) |
| Implementacion | `dashboard/queries.py` (`cobertura_por_tienda`, `folletos_por_semana`, `_SQL_COBERTURA`, `_SQL_FOLLETOS_SEMANA`, `_SQL_FOLLETOS_DUDOSOS`, constantes `DIAS_*`), modelo `VFolletosVigencia` en `dashboard/models.py`, `dashboard/templates/dashboard/cobertura.html` |
| Verificacion del construido | `docs/bi/consultas/verificacion_dashboard_cobertura.sql` (SQL exacta de queries.py): 20 tiendas, 10 con vigente, 52 vigentes, 16 dudosos, 2 proximos, 532 paginas, 1,858 precios vigentes, 694 folletos, 23 anomalos |
| Consulta | `docs/bi/consultas/cobertura_frescura_por_tienda.sql`, `docs/bi/consultas/folletos_por_semana_tienda.sql` |
| Validacion | `docs/bi/consultas/cobertura_frescura_por_tienda_validacion.sql` (desde `v_calidad_pipeline` y `v_precios_actuales`): cuadra por tienda; totales 52 folletos vigentes, 532 paginas, 1,858 precios. Serie semanal: suma 686 = `COUNT(*)` de folletos con el mismo filtro |

Clasificacion de fechas por folleto (solo etiqueta; no se corrige el dato):

| Etiqueta | Regla | Hoy |
|---|---|---|
| sin_fecha | `fecha_inicio` o `fecha_fin` NULL | 0 |
| fin_antes_inicio | `fecha_fin < fecha_inicio` | 0 |
| inicio_antiguo | `fecha_inicio < scrapeado_at - 365 dias` | 1 (soriana_hiper 430896, 2022-09-01 a 2027-02-28) |
| inicio_futuro_vs_scrapeo | `fecha_inicio > scrapeado_at + 30 dias` | 6 (alsuper 371335, waldos 426551/430141/430685/430802, s-mart 418009) |
| vigencia_larga | `fecha_fin - fecha_inicio > 120 dias` | 16 (sobre todo bodega_aurrera "todo el anio") |

KPIs (por tienda):

| KPI | Formula |
|---|---|
| Folletos vigentes hoy | folletos sin etiqueta con `fecha_inicio <= hoy <= fecha_fin` |
| Vigentes con fecha dudosa | folletos con etiqueta que cumplen el rango (se muestran aparte, no se suman) |
| Proximos | folletos sin etiqueta con `fecha_inicio > hoy` |
| Fecha del ultimo folleto | `MAX(fecha_inicio)` con `fecha_inicio <= hoy`, excluyendo inicio_antiguo e inicio_futuro_vs_scrapeo |
| Dias desde el ultimo folleto | `hoy - fecha del ultimo folleto` |
| Ultimo scrapeo | `MAX(scrapeado_at)` (frescura de captura, distinta de la de publicacion) |
| Paginas procesadas (vigentes) | `COUNT(paginas)` de folletos vigentes (hoy paginas = `total_paginas` en los 694 folletos) y cuantas tienen `total_precios > 0` |
| Precios en folletos vigentes | registros del dashboard de folletos vigentes |
| Errores de carga abiertos | `COUNT(*) FROM errores_carga WHERE NOT resuelto` por `tienda_slug` |
| Serie temporal | folletos por `DATE_TRUNC('week', fecha_inicio)` y tienda, sin inicio_antiguo/inicio_futuro_vs_scrapeo |

Joins: paginas y extracciones se agregan por folleto por separado antes de unir a folletos (694 filas antes y despues).
Umbrales de fecha: viven en la vista (365 / 30 / 120 dias); `dashboard/queries.py` los replica como constantes
`DIAS_INICIO_ANTIGUO`, `DIAS_INICIO_FUTURO`, `DIAS_VIGENCIA_LARGA` solo para mostrarlos en el panel (si cambia la vista,
cambiarlas). `ANOMALIAS_INICIO_NO_CONFIABLE` = sin_fecha, fin_antes_inicio, inicio_antiguo, inicio_futuro_vs_scrapeo
(se excluyen de "ultimo folleto" y de la serie). Serie por defecto: `CURRENT_DATE - 182` a `CURRENT_DATE + 30`
(`DIAS_SERIE_ATRAS`, `DIAS_SERIE_ADELANTE`): 674 folletos en 27 semanas al 12-oct-2026.
Filtros: tienda; rango de semanas en la serie. "Hoy" = `CURRENT_DATE` del servidor de BD (la vista no admite otra
fecha de corte; la fecha de corte parametrizable de la propuesta queda fuera). Categoria no aplica.
Panel: 4 KPIs (tiendas con vigente, folletos vigentes + dudosos + proximos, precios en vigentes + paginas, ultimo
scrapeo), tabla por tienda (dias > 14 en ambar y > 30 en rojo, siempre con icono), acordeon con los folletos de fecha
dudosa y sus reglas, y barras apiladas por semana (7 tiendas con mas folletos con color propio, resto en "Otras").
Confiabilidad: conteos exactos sobre fechas declaradas por la fuente (Tiendeo/Ofertomat); la serie semanal refleja
tambien la cadencia de scrapeo (semanas sin scrapeo se ven como caidas, p. ej. semana del 7-sep: 10 folletos de 1 tienda).

---

## 3. KPIs del Resumen (corregidos)

| Campo | Valor |
|---|---|
| Estado | **aprobada** (correccion de panel existente aprobada 12-oct-2026; pendiente de que la persona la vea) |
| Donde | Pagina Resumen (`/`), tarjetas KPI; API `/api/resumen` (`queries.resumen_kpis`) |
| Verificacion | `docs/bi/consultas/verificacion_dashboard_confiabilidad_resumen.sql` -> 28,634 / 52 / 16 |

| KPI | Antes | Ahora | Formula y fuente |
|---|---|---|---|
| Precios detectados (`registros_dashboard`) | `productos_con_precio` = PRECIO con valor (28,867; incluia 233 sin `texto_norm` que ningun panel muestra) | 28,634 | `COUNT(*) FROM v_precios_actuales` (registros del dashboard, todas las fechas) |
| Folletos vigentes hoy (`folletos_vigentes`) | `folleto_mas_reciente` = `MAX(folletos.fecha_inicio)` (mostraba 2026-12-25 por fechas anomalas de Waldos) | 52 (+16 con fecha dudosa, enlace a /cobertura) | `COUNT(*) FROM v_folletos_vigencia WHERE vigente`; nota `WHERE vigente_dudoso` |

Sin cambios: "Tiendas activas" (`tiendas.activa`) y "Folletos cargados" (`COUNT(*) FROM folletos`).
Grano: total. Filtros: ninguno. Confiabilidad: conteos exactos; la vigencia depende de las fechas declaradas por la
fuente (ver seccion 2).

---

## 4. Procedencia por registro

| Campo | Valor |
|---|---|
| Estado | **aprobada** (propuesta aprobada por la persona 13-oct-2026, opcion A: sin tocar vistas de la BD) |
| Pregunta | Al explorar un producto o precio, de que folleto y pagina viene, y como ir al origen |
| Grano | registro (`extracciones.id`); en el visor, pagina (`paginas.id`) |
| Donde | Columna "Origen" en Precios, Historico (tabla + tooltip/clic de la grafica), detalle por tienda de Comparativa, Explorador (`/datos`) y folletos con fecha dudosa de Cobertura. Visor `/origen/extraccion/<id>` y `/origen/pagina/<id>`; imagen `/origen/pagina/<id>.webp?version=proc\|raw`; API `/api/origen/pagina/<id>`, `/api/origen/extraccion/<id>`, `/api/origen/pagina/<id>/ocr\|nlp[?e=<extraccion_id>]` |
| Fuente | `extracciones` (pagina_id, folleto_id, bbox_*, producto_extraccion_id) -> `paginas` (numero_pagina, archivo_imagen) -> `folletos` (folleto_id_fuente, titulo, url_origen, fecha_inicio/fin) -> `tiendas` (slug). Archivos: `data/processed/<fuente>/<tienda.slug>/<folleto_id_fuente>/{pagina_NNN.webp, ocr_resultado.json, nlp_resultado.json}` y `data/raw/...` |
| Codigo | `dashboard/origen.py` (rutas seguras, fragmento JSON, cajas), `dashboard/queries.py` (`procedencia_por_ids`, `agregar_procedencia`, `contexto_pagina`, `origen_extraccion`), `dashboard/views.py`, `dashboard/templates/dashboard/origen.html`, `renderOrigen()` en `dashboard.js` |
| Consulta | `docs/bi/consultas/procedencia_cobertura.sql` |
| Validacion | `docs/bi/consultas/procedencia_cobertura_validacion.sql` (parte de la vista, folleto por clave natural, pagina con EXISTS) -> cuadra |
| Pruebas | `tests/test_dashboard_origen.py` (67, sin BD) |
| Fecha / autor | 13-oct-2026, especialista BI |

**Celda "Origen":** `folleto_id_fuente · vigencia · pag. N` (en Precios, Historico y Comparativa sin vigencia, que ya
tiene columna), titulo del folleto en tooltip, `[pag]` abre el visor y `[folleto]` abre `url_origen` (solo si existe
y es http/https). El titulo no identifica el folleto (172 distintos en 694; Ofertomat siempre "Vista previa..."):
por eso el identificador visible es `folleto_id_fuente`.

**Cobertura sobre los registros del dashboard** (BD recargada, codigo 01c2420, 13-oct-2026):

| Dato | Registros | % |
|---|---|---|
| Registros (= `v_precios_actuales`) | 27,760 | 100 |
| Con pagina (existe y es del mismo folleto) | 27,760 | 100 |
| Con `archivo_imagen` (archivo en disco, raw y processed: 4,783/4,783 paginas de la BD) | 27,760 | 100 |
| Con bbox de precio / de producto asociado en la misma pagina | 27,760 / 27,760 | 100 |
| Con vigencia | 27,760 | 100 |
| Con `titulo` | 27,748 | 99.96 |
| Con `url_origen` | 16,343 | 58.9 |

618 folletos y 3,885 paginas con registros. `url_origen` falta en los folletos scrapeados antes del 4-ago-2026.

**Joins sin duplicar:** las filas de las vistas traen `id = extracciones.id`; la procedencia se resuelve con una
segunda consulta por PK (`id__in`) y se combina en Python. `--contar`: `v_precios_actuales` 27,760 -> con
extracciones+paginas+folletos 27,760; `v_historico_precios` 27,760 -> 27,760. Folletos con fecha dudosa: 23 -> 23 al
unir `folletos` por PK; la primera pagina es subconsulta escalar.

**Cajas:** `extracciones.bbox_*` esta en el espacio de la imagen PROCESADA (ancho 1800, 1500, 1350 o 1200 segun
pagina; `ancho_pagina` en `ocr_resultado.json`). La caja se envia en % del ancho/alto real de la imagen procesada
(leido de su cabecera); como la procesada conserva la proporcion de la cruda (400/400 en muestra), el % vale tambien
sobre la original. Muestra de 400 paginas: 400/400 cajas dentro de la procesada, 375/400 se salen de la cruda.
Si falta la imagen procesada, el visor muestra la original y avisa "caja no disponible".

**Fragmentos OCR/NLP:** solo el elemento de `paginas` cuyo `pagina == archivo_imagen` (no el archivo completo).
Estados: `ok | ausente | corrupto | muy_grande | sin_pagina`. Cache en memoria por (mtime, tamano), maximo 16
archivos; limite 25 MB por archivo (el mayor hoy pesa ~1 MB). Con `?e=<extraccion_id>` se marcan los elementos cuya
caja coincide con la del precio (rojo) o del producto asociado (azul): igualdad exacta o superposicion >= 50% del area
del menor.

**Seguridad:** solo GET; las URLs reciben solo ids enteros; la ruta se arma con datos de la BD y se valida (fuente en
{tiendeo, ofertomat}; `archivo_imagen` ~ `^pagina_\d{3}\.(webp|jpg|jpeg|png)$`; `folleto_id_fuente` ~
`^[A-Za-z0-9_-]+$`; slug ~ `^[A-Za-z0-9_'-]+$`; nombres de JSON fijos; `resolve().is_relative_to(base)`).
Imagen con `FileResponse`, `inline`, `X-Content-Type-Options: nosniff`, `Cache-Control: private, max-age=3600`.
Cualquier fallo -> 404. Bases: `settings.ORIGEN_RAW_DIR` y `settings.ORIGEN_PROCESSED_DIR`.

**Confiabilidad:** la procedencia es exacta (llaves de la BD). Ver el origen no valida el registro: el visor sirve
justamente para comprobar si el precio y el producto asociado son correctos (precision medida baja, ver seccion 1).

---

## 5. Filtro "Con / sin categoria"

| Campo | Valor |
|---|---|
| Estado | **aprobada** (pedido y aprobado explicitamente por la persona 14-oct-2026; construido, pendiente de que la persona lo vea) |
| Pregunta | Ver por separado los registros que si tienen categoria y los que no (~62% de los registros no tiene) |
| Parametro | `?con_categoria=si\|no` en las APIs; vacio, ausente o invalido = todos (default: lo que se veia antes no cambia) |
| Definicion | **Sin categoria** <=> la categoria del registro (`extracciones.categoria_nlp` de la fila PRECIO; es la columna `categoria` de `v_precios_actuales`, `v_comparativa_precios` y `v_historico_precios`) es NULL, `''` o solo espacios: `COALESCE(BTRIM(categoria_nlp), '') = ''`. **Con categoria** = el complemento exacto. ORM: `Trim(campo)` IS NULL OR = `''` (con = NOT de eso; NULL nunca se cuela). SQL crudo: `_SQL_CON_CATEGORIA` |
| Casos ambiguos | `''` vs NULL vs espacios: los tres = sin categoria. Categorias genericas tipo "otros"/"sin categoria": no existen (18 categorias, todas especificas; verificado 14-oct-2026). Categoria del canonico (`productos_canonicos.categoria`): **no se usa** para el filtro porque no es la que ve el usuario; difiere de `categoria_nlp` en 392 registros (hallazgo `bi/hallazgos/categoria-nlp-vs-canonico`) |
| Combinacion | AND con los demas filtros. Con "Sin categoria" la lista de categorias se desactiva en la UI y no se envia (AND daria vacio) |
| Grano | el de cada panel; el filtro es solo un WHERE sobre filas (no agrega joins). En Comparativa la vista agrupa por (texto, categoria): cada fila tiene una sola categoria y se clasifica entera |
| Codigo | `dashboard/queries.py` (`normalizar_con_categoria`, `filtrar_con_categoria`, `_SQL_CON_CATEGORIA`), `dashboard/views.py` (`_con_categoria`), `dashboard/templates/dashboard/_filtro_con_categoria.html`, `paramsCategoria`/`enlazarConCategoria`/`textoConCategoria` en `dashboard.js` |
| Consulta | `docs/bi/consultas/filtro_con_categoria.sql` (mismos predicados que el dashboard, por panel; columna `cuadra`) |
| Validacion | `docs/bi/consultas/filtro_con_categoria_validacion.sql` (tabla base, `LENGTH(BTRIM())`, EXISTS en vez de JOIN) -> cuadra |
| Pruebas | `tests/test_dashboard_filtro_categoria.py` (46, sin BD) |
| Fecha / autor | 14-oct-2026, especialista BI |

**Donde aplica**

| Pagina | Que filtra | Que no filtra (no depende de productos) |
|---|---|---|
| Resumen | KPI "Precios detectados" (nota "de N en total") y grafica Top categorias (con "Sin categoria" queda vacia, con aviso) | Tiendas activas, folletos cargados, folletos vigentes, folletos por tienda |
| Precios | Tabla | - |
| Comparativa | Tabla y detalle por tienda (usa el filtro con el que se cargo la tabla) | - |
| Historico | Tabla y grafica | Sugerencias de producto (catalogo) |
| Calidad | Seccion Confiabilidad: registros, % catalogo, % sin categoria, OCR, duplicados, atipicos | Metricas del evaluador (precision, IC95, recall, error dominante: son de la corrida) y la tabla operativa por folleto (`v_calidad_pipeline`, conteos de `paginas`) |
| Cobertura | KPI y columna "Precios vigentes" (CTE `pre`) | Folletos, paginas, "Pags. con precio" (`paginas.total_precios`, sin categoria), fechas, errores, serie semanal |
| Explorador (`/datos`) | Tabla de extracciones (sobre `categoria_nlp`, todos los tipos) | Tiendas y folletos |
| Promociones | - | `v_eventos_activos.num_precios_asociados` (la vista no expone categoria; cambiarla requiere aprobacion) |

**Verificacion 14-oct-2026** (BD vigente ese dia, rol de solo lectura; con + sin = todos en todos los casos):

| Panel | Todos | Con categoria | Sin categoria |
|---|---|---|---|
| Resumen "Precios detectados" / Precios / Historico / Confiabilidad (registros) | 27,760 | 10,658 | 17,102 |
| Comparativa (filas, min. 2 tiendas) | 771 | 319 | 452 |
| Cobertura "Precios en folletos vigentes" | 1,741 | 507 | 1,234 |
| Resumen Top categorias (suma de barras, top 10, categoria del registro) | 10,230 | 10,230 | 0 |

Top categorias se alineo el 14-oct-2026 (aprobado por la persona): cuenta por la categoria del registro sobre
`v_precios_actuales` (antes, categoria del canonico sobre todas las filas PRECIO: 10,266, que no cuadraba). Sumando
las 18 categorias da 10,658 = registros con categoria; el top 10 suma 10,230. La lista del filtro de categorias
(`listar_categorias`) tambien sale ya de la categoria del registro (mismas 18 que antes).

La validacion independiente reproduce 27,760 / 10,658 / 17,102, 1,741 / 507 / 1,234 y 771 / 319 / 452.
Joins: la base de Confiabilidad (PRECIO -> PRODUCTO -> folletos, N:1) da 27,760 = `v_precios_actuales`.

**Confiabilidad:** "con categoria" no significa "producto de catalogo": de los 10,658 con categoria, 6,505 son
heuristicos (6,113 + 392). La categoria la asigna el NLP; no esta medida por el evaluador.
