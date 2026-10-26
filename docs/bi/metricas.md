# Catalogo de metricas BI - PriceScraper MX

Autor: agente BI. Ultima actualizacion: 25-oct-2026 (seccion 8).

Estado de cada metrica: **propuesta** (definida y validada contra la BD, no construida en el dashboard),
**aprobada** (la persona la acepto) o **publicada** (visible en el dashboard).

Convenciones comunes:

- **Registro del dashboard**: fila de `extracciones` con `tipo='PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL`
  (= `v_precios_actuales`). 28,634 al 12-oct-2026.
- **Producto de catalogo**: `metodo_norm IN ('exacto','fuzzy','fuzzy_bajo')` del nombre que muestra el PRECIO:
  `COALESCE(e.metodo_norm, p.metodo_norm)`. Desde el 25-oct-2026 load guarda `metodo_norm` en la fila PRECIO, porque con
  nombre unido (unidad suelta o lineas contiguas) el nombre del PRECIO ya no es el de su fila PRODUCTO
  (`producto_extraccion_id`): "Pechuga de pollo" (exacto) unida queda "Filete de Pechuga de Pollo" (heuristico). En
  cargas anteriores la fila PRECIO lo tiene NULL y se usa el de la fila PRODUCTO. `heuristico` = texto del folleto tal cual.
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
| Donde | Pagina Calidad (`/calidad`), seccion superior; API `/api/confiabilidad`. **Nota 19-oct-2026:** la pestana Calidad esta oculta de la barra de navegacion a pedido de la persona (comentario de plantilla en `dashboard/templates/dashboard/base.html`); la pagina `/calidad` y sus APIs siguen funcionando por URL directa |
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
| % catalogo | registros con `COALESCE(PRECIO, PRODUCTO).metodo_norm IN (exacto,fuzzy,fuzzy_bajo)` / registros | BD |
| % heuristico | registros con `COALESCE(PRECIO, PRODUCTO).metodo_norm='heuristico'` / registros (= 100 - % catalogo; hoy no hay otro valor) | BD |
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
| Categorias (`categorias`, `pct_con_categoria`) — nuevo 17-oct-2026 | (no existia) | 18 · 39.0% de los precios con categoria (12,495 / 32,073) | `COUNT(DISTINCT TRIM(categoria)) FROM v_precios_actuales WHERE COALESCE(TRIM(categoria),'') <> ''`; subtitulo = registros con categoria / registros base x 100 |

**KPI "Categorias"** (aprobado por la persona 17-oct-2026; autor: especialista BI):

- Pregunta: cuantas categorias distintas tienen los precios que muestra el dashboard. Grano: total (o folleto filtrado).
- Fuente: `v_precios_actuales.categoria` (= `extracciones.categoria_nlp` de la fila PRECIO), la misma que la grafica
  "Top 10 categorias" y el filtro con/sin categoria. No se usa `productos_canonicos.categoria`.
- Limpieza: TRIM; vacia (`''`) y NULL no cuentan como categoria (misma regla que `filtrar_con_categoria`). No hay variantes
  de escritura: 18 crudas = 18 con `lower(btrim())`.
- Filtros: respeta "Folleto". Con "Con categoria" la cifra es la misma; con "Sin categoria" no aplica (valor "—", nota
  `no aplica con filtro "sin categoría"`). Denominador del % = registros del folleto/filtro **sin** el filtro con/sin
  categoria.
- Confiabilidad: solo el 39.0% de los precios tiene categoria (19,578 vacias); el subtitulo lo muestra siempre.
  "Frutas y Verduras" no es categoria propia: `nlp/normalizador.py:28` la funde en `alimentos` (de las 4 categorias foco
  solo existen 3 en la BD).
- Codigo: `queries.resumen_kpis`, `queries.qs_categorias_distintas`, `queries.kpi_categorias`; tarjeta en
  `templates/dashboard/resumen.html`. Pruebas: `tests/test_dashboard_kpi_categorias.py` (sin BD).
- Validacion (17-oct-2026, consulta.py): el SQL que genera el ORM da 18; desde la tabla base
  (`extracciones` PRECIO con `valor` y `texto_norm`, `COUNT(DISTINCT BTRIM(categoria_nlp))`) da 18 / 12,495 / 32,073 ->
  cuadra. Folleto `416117`: vista 12 / 104 / 409 (25.4%) = base `extracciones` + `folletos` 12 / 104 / 409 -> cuadra.

Sin cambios: "Tiendas activas" (`tiendas.activa`) y "Folletos cargados" (`COUNT(*) FROM folletos`).
Grano: total. Filtros (desde 14-oct-2026; corregido aqui 17-oct-2026): "Con / sin categoria" (seccion 5) y "Folleto"
(seccion 6). Aplican solo a los KPIs de registros: "Precios detectados" (nota "de N en total") y "Categorias" (con
"sin categoria" no aplica), y a la grafica "Top 10 categorias". "Tiendas activas", "Folletos cargados", "Folletos
vigentes hoy" y la grafica "Folletos cargados por tienda" no dependen de los filtros. Confiabilidad: conteos exactos;
la vigencia depende de las fechas declaradas por la fuente (ver seccion 2).

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

**Cobertura sobre los registros del dashboard** (actualizada 17-oct-2026 con la BD recargada el 17-oct; consulta
`procedencia_cobertura.sql` y su validacion -> cuadran. Cifras del 13-oct entre parentesis):

| Dato | Registros | % |
|---|---|---|
| Registros (= `v_precios_actuales`) | 32,073 (27,760) | 100 |
| Con pagina (existe y es del mismo folleto) | 32,073 | 100 |
| Con `archivo_imagen` (en la BD; el archivo en disco se verifico el 13-oct en 4,783/4,783 paginas y no se reverifico) | 32,073 | 100 |
| Con bbox de precio / de producto asociado en la misma pagina | 32,073 / 32,073 | 100 |
| Con vigencia | 32,073 | 100 |
| Con `titulo` | 32,061 (27,748) | 99.96 |
| Con `url_origen` | 20,656 (16,343) | 64.4 |

706 folletos y 4,394 paginas con registros (618 y 3,885 el 13-oct); 5,357 paginas en la BD. `url_origen` falta en los
folletos scrapeados antes del 4-ago-2026.

**Pestana "Precios" del visor** (aprobada por la persona 17-oct-2026; autor: especialista BI). Junto a OCR/NLP, lista
los pares precio-producto de la pagina y permite recorrerlos uno a uno (clic en el renglon, anterior/siguiente con
"N / total", flechas ← / →). Al seleccionar (`seleccionar(id)` en `origen.html`): caja roja del precio y azul de su
producto, tarjeta "Registro seleccionado", marcas OCR/NLP con `?e=<id>` (AbortController: una respuesta vieja no pisa
la seleccion nueva) y `history.replaceState('/origen/extraccion/<id>')`. Entrando por `/origen/extraccion/<id>` abre
con ese renglon activo; por `/origen/pagina/<id>`, sin seleccion.

- Fuente y filtro: `extracciones` con `tipo='PRECIO'`, `valor`, `texto_norm` y `producto_extraccion_id` no nulos (= los
  registros de `v_precios_actuales` de la pagina: la vista no trae `pagina_id` ni cajas). Hoy los 300 PRECIO sin
  producto son los mismos 300 sin `texto_norm`, asi que la lista = los registros del dashboard de la pagina.
- Grano: una fila por PRECIO; joins N:1 por PK a la fila PRODUCTO (INNER) y a `productos_canonicos` (LEFT): 32,073
  filas = 32,073 ids. Orden `bbox_y, bbox_x, id`. API: claves `precios` y `precios_sin_producto` en
  `/api/origen/pagina/<id>` (sin ruta nueva). Peso: maximo 82 precios por pagina.
- Renglon: precio, precio anterior y % de descuento (mismo calculo que la vista), producto (`texto_norm` del PRECIO;
  si difiere, tambien el de la fila PRODUCTO: 722 pares), catalogo (solo si `metodo_norm` es exacto/fuzzy/fuzzy_bajo;
  desde 25-oct-2026 el del PRECIO, con la misma regla COALESCE que "% catalogo"),
  categoria o "sin categoria", insignia catalogo/heuristico (84.6% heuristico) y "(repetido)" si otro precio de la
  pagina tiene el mismo texto y valor (son cajas distintas, no filas duplicadas: 477 grupos).
- Pagina sin pares: la pestana se ve con el aviso "N precios de esta pagina no tienen producto asociado y no se
  listan" (ej. pagina 69371: 0 renglones, 6 sin producto).
- Codigo: `queries.qs_precios_de_pagina`, `armar_precios_pagina`, `precios_de_pagina` (desde `contexto_pagina`),
  `views._precio_con_cajas`; pruebas `tests/test_dashboard_origen_precios.py` (sin BD).
- Validacion (17-oct-2026): el SQL que genera el ORM, corrido con consulta.py, da 64943 -> 17, 64928 -> 17,
  66216 -> 7, 69371 -> 0 (6 PRECIO en la pagina); cuadra con `v_precios_actuales` unida por `id` (17 / 17 / 7 / 0).
- No incluye (sin aprobar): cajas clicables sobre la imagen ni el color por tipo para registros que no son PRECIO
  abiertos desde el Explorador (hoy se pintan en rojo como "precio").

**Joins sin duplicar:** las filas de las vistas traen `id = extracciones.id`; la procedencia se resuelve con una
segunda consulta por PK (`id__in`) y se combina en Python. `--contar` (13-oct): `v_precios_actuales` 27,760 -> con
extracciones+paginas+folletos 27,760; `v_historico_precios` 27,760 -> 27,760 (17-oct: 32,073 = 32,073). Folletos con fecha dudosa: 23 -> 23 al
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

---

## 6. Filtro "Folleto"

| Campo | Valor |
|---|---|
| Estado | **aprobada** (pedido y aprobado explicitamente por la persona 14-oct-2026; construido, pendiente de que la persona lo vea) |
| Pregunta | Ver solo los registros, errores o metricas de un folleto concreto |
| Parametro | `?folleto=<id de la fuente>` en las APIs y en `/datos`; vacio o ausente = todos (default sin cambios) |
| Id aceptado | **Solo `folletos.folleto_id_fuente`**: el id de Tiendeo/Ofertomat que muestra la celda "Origen" y el nombre de la carpeta `data/raw/<fuente>/<tienda>/<id>`. Coincidencia **exacta** tras quitar espacios de los extremos (sin LIKE). Un id inexistente o mal escrito da vacio sin error (no se ignora). El `folletos.id` interno no se acepta en este campo (el usuario no lo ve; `/datos` ya filtra por el con `folleto_id`, y ambos van en AND) |
| Unicidad | El esquema solo garantiza `UNIQUE (fuente, folleto_id_fuente)`. Hoy el id es unico en toda la tabla: 694/694, todos de 6 digitos, ninguno repetido entre Tiendeo y Ofertomat y ninguno igual a un `folletos.id` (verificado 14-oct-2026). Si un dia se repite entre fuentes, el filtro traeria ambos folletos (sin duplicar filas) |
| Combinacion | AND con los demas filtros (tienda, categoria, con/sin categoria, fechas, producto...) |
| Codigo | `dashboard/queries.py` (`normalizar_folleto`, `filtrar_folleto`, `_en_folleto`, `_SQL_FOLLETO`), `dashboard/views.py` (`_folleto`), `dashboard/templates/dashboard/_filtro_folleto.html`, `valorFolleto` en `dashboard.js` |
| Consulta | `docs/bi/consultas/filtro_folleto.sql` (mismo predicado que el dashboard, por panel, 2 folletos reales + 1 inexistente) |
| Validacion | `docs/bi/consultas/filtro_folleto_validacion.sql` (resuelve `folletos.id` por llave natural y cuenta desde `extracciones` por `folleto_id`; comparativa recalculada con agregacion propia) -> cuadra |
| Pruebas | `tests/test_dashboard_filtro_folleto.py` (56, sin BD) |
| Fecha / autor | 14-oct-2026, especialista BI |

**Donde aplica y como (sin joins que dupliquen)**

| Pagina | Que filtra | Como |
|---|---|---|
| Resumen | KPI "Precios detectados" (nota "folleto X · de N en total") y grafica Top categorias | `v_precios_actuales.folleto_id_fuente =` |
| Precios | Tabla (ningun folleto pasa de 409 registros: el limite de 500 filas no corta) | igual |
| Comparativa | Tabla: grupos (texto, categoria) con al menos un registro del folleto; min/max/diferencia siguen siendo entre todas las tiendas | `EXISTS` sobre `extracciones` (la vista no tiene folleto; no se toca) |
| Comparativa, detalle por tienda | **No se filtra** (quedaria una sola tienda y no habria que comparar); resalta las filas del folleto | - |
| Historico | Tabla y grafica del producto | `v_historico_precios.folleto_id_fuente =` |
| Calidad, Confiabilidad | Solo la tienda del folleto, con los datos de ese folleto; las metricas del evaluador son de la tienda (no se filtran) | `f.folleto_id_fuente =` en la base + `EXISTS` para la fila de tienda |
| Calidad, tabla operativa | La fila del folleto | `v_calidad_pipeline.folleto_id_fuente =` |
| Errores de carga | Grafica y tabla (los KPIs son globales por diseno) | `errores_carga.folleto_id_fuente =` (sin FK) |
| Explorador (`/datos`) | Tabla de folletos y de extracciones (todos los tipos; muestra hasta 200, 275 folletos tienen mas) | `folletos.folleto_id_fuente =`; extracciones via FK N:1 a folletos |

**Donde no aplica:** Cobertura (es por tienda: con un solo folleto, "ultimo folleto", "dias desde el ultimo" y la
serie semanal pierden sentido) y Promociones (`v_eventos_activos` agrupa eventos de varios folletos y no tiene
columna de folleto; filtrar requiere cambiar la vista, con aprobacion).

**Verificacion 14-oct-2026** (BD vigente ese dia, rol de solo lectura):

| Folleto | Precios / Resumen / Historico / Confiabilidad | Con categoria (Top categorias) | Comparativa | Calidad | Errores | Extracciones (/datos) |
|---|---|---|---|---|---|---|
| 430658 (la_comer, id 311) | 213 | 113 | 14 | 1 fila | 0 | 1,408 |
| 413647 (walmart, id 707) | 173 | 112 | 12 | 1 fila | 1 | 899 |
| 999999 (no existe) | 0 | 0 | 0 | 0 | 0 | 0 |

La validacion independiente reproduce todas las cifras. Un folleto que existe pero sin registros (76 de 694) tambien
da vacio en los paneles de registros.

### 6.1 Avisos del filtro "Folleto" y de Errores de carga

Aprobados por la persona 14-oct-2026. Con el filtro de folleto vacio no se consulta nada y no se pinta ningun aviso.

| Aviso | Cuando | Texto (resumen) | Donde |
|---|---|---|---|
| Folleto no encontrado (amarillo) | ningun `folletos.folleto_id_fuente` igual al id | `Folleto no encontrado: no existe ningun folleto con ID "X"...` (explica que es el ID de la fuente, exacto) | Resumen, Precios, Comparativa, Historico, Calidad (ambas secciones), Errores, Explorador |
| No esta cargado pero tiene errores (amarillo) | no existe en `folletos` y si hay filas en `errores_carga` (folleto que fallo entero; hoy 0 casos) | `El folleto "X" no esta cargado en la BD ... tiene N error(es) de carga` | Errores, Explorador |
| Existe sin precios (azul) | existe y 0 registros en `v_precios_actuales` (76 de 694) | `El folleto "X" existe (tienda · fuente) pero no tiene precios registrados` | Paginas de registros: Resumen, Precios, Comparativa, Historico, Calidad-Confiabilidad, Explorador. No en Calidad-tabla operativa ni Errores (no dependen de precios) |
| Errores ocultos por Estado (azul, boton `Ver "Todos"`) | Estado = Abiertos (o Resueltos) y hay errores del estado contrario que cumplen los demas filtros, incluido el folleto | `Hay N error(es) resuelto(s) que cumplen los demas filtros y no se muestran porque Estado = "Abiertos". Para verlos, elige Estado "Todos".` | Errores de carga. Solo con un folleto escrito (decision de la persona 15-oct-2026): con el folleto vacio no hay aviso ni consulta |

Fuente: `queries.estado_folleto` (endpoint `/api/filtros/folleto?folleto=`; tres COUNT sobre `folletos`,
`v_precios_actuales` y `errores_carga`, cada uno sin joins) y `queries.errores_ocultos_por_estado` (mismo filtro de
Errores con el estado contrario, COUNT sobre `errores_carga`). En el navegador el aviso se arma con `createElement` y
`textContent` (el id nunca se interpreta como HTML); en el Explorador lo escapa Django.
Consulta: `docs/bi/consultas/avisos_folleto.sql`. Validacion: `docs/bi/consultas/avisos_folleto_validacion.sql`
(clasifica desde `extracciones` con LEFT JOIN y agrega errores con FILTER) -> cuadra. Pruebas:
`tests/test_dashboard_avisos_folleto.py` (29, sin BD).

**Verificacion 14-oct-2026:**

| Folleto | Estado | Registros | Errores de carga | Errores ocultos con Estado = Abiertos |
|---|---|---|---|---|
| 999999 | no_existe -> "Folleto no encontrado" | 0 | 0 | 0 (sin aviso de estado) |
| 413679 | sin_precios -> "existe pero no tiene precios" | 0 | 0 | 0 |
| 430658 | con_precios -> sin aviso | 213 | 0 | 0 |
| 413647 | con_precios -> sin aviso | 173 | 1 (resuelto) | 1 -> aviso "Hay 1 error(es) resuelto(s)..." |
| (vacio) | sin aviso de folleto | - | 13 | sin aviso (desde 15-oct-2026 solo se avisa con folleto escrito) |

Folletos sin precios: 76 de 694 (ambos caminos).

---

## 7. Promociones por niveles (Fase 1: campaña del folleto)

| Campo | Valor |
|---|---|
| Estado | **aprobada** (Fase 1 aprobada por la persona 15-oct-2026; construida sin commit, pendiente de revision en el navegador) |
| Pregunta | Que promociones tiene cada precio: (A) campaña del folleto, (B) promocion del producto, (C) bancaria. Conviven |
| Estructura | Cada registro trae `promos = {campania: [{slug, nombre}], producto: [], bancaria: []}`. Hoy solo A tiene datos; B y C "pendiente de carga" (load debe ligar las PROMO al producto) |
| Fuente | `eventos_promo` (ligada solo a folleto) leida directo desde `queries.py`, sin vistas (patron de Procedencia, opcion A). **Ya no se usa `v_eventos_activos`**: fechas NULL en todos los eventos (todos "vigentes"), mezcla folletos y su `num_precios_asociados` cuenta cada precio una vez por evento del folleto |
| Mapa de campañas | `dashboard/promociones.py` (provisional): convierte las variantes actuales de `nombre_evento` a los slugs acordados con el pipeline (`julio_regalado, hot_sale, buen_fin, regreso_a_clases, navidad, halloween_dia_de_muertos, liquidacion, aniversario, ofertones, fiestas_patrias`; fiestas_patrias agregada 16-oct-2026) y acepta los slugs ya canonicos (cuando se recargue con el pipeline nuevo sigue igual). Clases: campaña / lema / texto legal / nombre de producto / otro; solo "campaña" se muestra como etiqueta. Espejo SQL: `docs/bi/consultas/promociones_campanias.sql` (una prueba vigila que las reglas coincidan) |
| Sin duplicados | Etiquetas: segunda consulta por `folleto_id__in` agrupada en Python (`agregar_promos`), mismas filas y orden. Filtros: `EXISTS` (vistas por llave natural `(fuente, folleto_id_fuente)`; extracciones por `folleto_id`; Comparativa con EXISTS anidado sobre los registros del grupo). Un join directo registro-evento inflaria 12.5% (15 folletos tienen varios eventos) |
| Donde | Columna "Promociones" en Precios, detalle por tienda de Comparativa, Historico (tabla + tooltip); columna "Campania" en el Explorador (folletos y extracciones); cabecera del visor de origen. Filtros "Promocion" (Todos/Con alguna/Sin promocion), "Nivel" (Producto y Bancaria desactivados: pendiente de carga) y "Campaña" en Precios, Comparativa e Historico |
| Semantica de filtros | Registro con promocion = su folleto tiene al menos un evento de clase campaña (del nivel/campañas elegidas). Campaña sin "Promocion" = "con" esas campañas. Nivel solo no filtra. Comparativa: grupo con al menos un registro en un folleto con promocion. AND con los demas filtros |
| Pagina Promociones | Grano (folleto, campaña); vigencia desde `v_folletos_vigencia` (vigente / vigente con fecha dudosa / proximo / fuera); "Precios en el folleto" = registros del dashboard del folleto (nivel folleto, no producto; con Categoria solo esas y se ocultan los ceros), enlace a `/precios?folleto=<id>` (Precios lee `?folleto=` de la URL). KPIs suman cada folleto una vez. Filtros: tienda, folleto, campaña, vigencia, categoria, tipo de texto (por defecto solo campañas; lemas/legal/producto para revisar) |
| Consulta / validacion | `docs/bi/consultas/promociones_validacion.sql` (camino A = predicado del ORM; camino B = tabla base con IN/NOT IN y BOOL_OR) -> cuadra |
| Pruebas | `tests/test_dashboard_promociones.py` (sin BD) |
| Fecha / autor | 15-oct-2026, especialista BI |

**Verificacion 15-oct-2026** (BD recargada con el scrapeo del 14/15-oct: 32,074 registros, 786 folletos, 92 eventos en
70 folletos, 13 de 20 tiendas con algun evento):

| Medida | Todos | Con promocion | Sin promocion |
|---|---|---|---|
| Registros (vista, EXISTS del ORM) | 32,074 | 1,731 (5.4%) | 30,343 |
| Registros (tabla base, IN / NOT IN) | 32,074 | 1,731 | 30,343 |
| Registros con etiqueta (agregado por folleto antes de unir) | 32,074 | - | - |
| Comparativa, grupos en 2+ tiendas (EXISTS anidado / BOOL_OR) | 901 | 206 | 695 |

Pagina Promociones (clase campaña): 36 filas (folleto, campaña), 35 folletos, 5 campañas, 7 tiendas, 1,731 precios en
esos folletos, 3 folletos vigentes hoy. Eventos por clase (92): campaña 37, lema 38, texto legal 11, nombre de producto 6, otro 0.

| Campaña | Folletos | Registros en esos folletos | Tiendas | Vigentes hoy |
|---|---|---|---|---|
| Julio Regalado | 13 | 925 | soriana_hiper, soriana_mercado | 0 |
| Regreso a clases | 13 | 656 | bodega_aurrera, chedraui, soriana_mercado, walmart, waldos | 0 |
| Hot Sale | 1 | 409 | soriana_hiper (mismo folleto que un Julio Regalado) | 0 |
| Liquidacion | 1 | 140 | casa_ley | 0 |
| Navidad | 8 | 10 | waldos | 3 |

Por campaña suman 2,140 > 1,731 porque un folleto lleva dos campañas: por eso los KPIs cuentan cada folleto una vez.
Sin datos todavia: Buen Fin, Halloween/Dia de Muertos, Aniversario, Ofertones (los detectara el pipeline nuevo).

---

## 8. Comparativa: clave de agrupacion flexible (propuesta)

| Campo | Valor |
|---|---|
| Estado | **fase 1 aplicada** 26-oct-2026, aprobada por la persona: `tiendas.cadena` (soriana = hiper + mercado; walmart = walmart + express; Bodega Aurrera y Sam's propias), `clave_comparativa()` y `v_comparativa_precios_v2` en `load/schema.sql` y `load/vistas.sql`. Tras la recarga del 25-oct con los centavos corregidos: **131 grupos, 1,293 registros, 21 con precio sospechoso, 43 con 3+ cadenas**. El panel `/comparativa` sigue sobre `v_comparativa_precios` (fase 3, cambiar el panel, por aprobar). |
| Pregunta | Que productos se pueden comparar de verdad entre cadenas distintas, y a que precio esta cada uno en cada cadena? |
| Comparacion valida | Mismo producto (tipo + variedad/corte), misma presentacion cuando aplica (cantidad y unidad; en granel, precio por kg o por pieza) y misma marca si el producto es de marca, en **>= 2 cadenas distintas**. Juicio por grupo: **V** = cumple; **D** = mismo tipo pero marca, tamano o variedad no verificables o distintos; **I** = genericos que juntan productos distintos ("Refresco", "Galletas", "Smart TV"), marcas o rotulos sueltos ("Great Value", "Colores Disponibles", "Variedad de Quesos"), fragmentos ("A Elegir", "Para Asar") o presentaciones distintas (docepack contra lata). Validez **estricta** = V; **laxa** = V + D. La identidad se juzga aparte del precio: un precio mal leido no invalida el grupo, se marca con la dispersion |
| Cadena | `tiendas` no tiene cadena. Propuesta: Soriana Hiper + Soriana Mercado = `soriana` (comparten precio identico en 49.6% de sus 230 grupos; los demas pares, 0-9%: `comparativa_pares_tiendas.sql`); Walmart + Walmart Express = `walmart`; el resto, su propia cadena. Bodega Aurrera y Sam's Club quedan aparte (otro formato y precio); juntarlas a Walmart solo quita 4 grupos de 140 (`comparativa_claves/walmex.sql`). **Decide la persona** |
| Grano | Grupo = valor de la clave con registros en >= 2 cadenas. Registros = filas del dashboard (incluye duplicados exactos) |
| Base y exclusiones | Registros del dashboard (PRECIO, `valor` y `texto_norm` no nulos): 28,735. Se excluyen 43 atipicos (9 < $1, 34 > $100,000) -> 28,692. La vista actual no excluye nada |
| Dispersion (alerta) | `ratio_medianas` = mediana mas alta entre cadenas / mas baja. > 10 = precio sospechoso (casi siempre centavos pegados: "$2189" = $21.89) |
| Muestra de validez | 40 grupos por clave, orden `md5(clave_nombre \|\| '\|' \|\| clave \|\| '\|bi-comparativa-20261025')` (reproducible); censo cuando la clave tiene menos de 40 grupos. IC95 de Wilson |
| Consultas | `docs/bi/consultas/comparativa_linea_base.sql`, `comparativa_pares_tiendas.sql`, `comparativa_clave_a_ejemplos.sql`; `docs/bi/consultas/comparativa_claves/` (`candidatas.sql`, `muestra_<clave>.sql`, `diferencias_ka_khr.sql`, `dispersion_khr.sql`, `similares_resumen.sql`, `similares_muestra.sql`, `walmex.sql`, `validacion.sql`, `propuesta_inline.sql`), generadas por `tests/_herramienta_bi_claves_comparativa.py` desde el catalogo (no editar a mano) |
| Validacion | (1) Linea base desde la vista: grupos cuyo `tiendas` no es solo Soriana Hiper + Soriana Mercado ni solo Walmart + Walmart Express = 293 grupos / 3,955 registros = `comparativa_linea_base.sql` desde la tabla base. (2) `validacion.sql` (EXISTS de otro registro de otra cadena, en lugar de GROUP BY/HAVING) = `candidatas.sql` en k0, ka, kar, kbr y khr. (3) `propuesta_inline.sql` (funcion por fila, otro camino) = kar de `candidatas.sql`: 132 grupos / 1,343 registros |
| Fecha / autor | 25-oct-2026, especialista BI |

Claves medidas (grupos y registros con >= 2 cadenas, base de 28,692):

| Clave | Definicion | Grupos | Registros | Nuevos vs k0 | Pares de cadenas | Ratio > 2 | Validez estricta (IC95) | Validez laxa (IC95) | Costo |
|---|---|---|---|---|---|---|---|---|---|
| k0 (actual) | `texto_norm` + `categoria_nlp` | 292 | 3,947 | - | 84 | 77.7% | 27.5% (16.1-42.8), n=40 | 52.5% (37.5-67.1) | - |
| (a) ka | texto normalizado: minusculas, sin acentos ni puntuacion, unidades unificadas, sin relleno, palabras ordenadas; >= 2 palabras de contenido o una fruta/verdura | 156 | 2,075 | 188 | 66 | 76.9% | 57.5% (42.2-71.5), n=40 | 82.5% (68.1-91.3) | SQL puro |
| (a') kar | ka + "medio kilo" = 500 g, sin "cada uno/ejemplo/precio/oferta", sin los 84 genericos de catalogo no granel | 132 | 1,343 | 194 | 63 | 73.5% | ~53% (parte A de la muestra khr: 19/36) | ~86% (31/36) | SQL puro (funcion + vista) |
| (b) kb / kbr | tipo de catalogo + marca + presentacion (las tres) | 10 / 11 | 46 / 49 | 38 / 41 | 10 | 50% | 5/10 (censo) | 8/10 | listas del catalogo: columna en load o tabla de equivalencias |
| (b sin marca) kb2 | tipo + presentacion | 123 | 999 | 991 | 46 | 68.3% | 20.0% (10.5-34.8), n=40 | 47.5% (32.9-62.5) | igual que (b) |
| (c) kc | canonico de catalogo (PRECIO o su PRODUCTO) + presentacion | 17 | 127 | 127 | 9 | 47.1% | 2/17 (censo) | 10/17 | SQL puro (join a la fila PRODUCTO) |
| (c sin presentacion) kc0 | canonico de catalogo solo (como antes de la union de lineas) | 91 | 4,336 | 2,227 | 113 | 97.8% | no muestreada: genericos, ya juzgados invalidos (#261) | - | - |
| **khr (recomendada)** | kbr si existe; si no, kar | **140** | **1,378** | 229 | 63 | 71.4% | **52.5% (37.5-67.1)**, n=40 | **85.0% (70.9-92.9)** | fase 1 SQL (kar); fase 2 columna en load |
| (d) equivalencias | pares de claves kar de cadenas distintas, mismo tipo y presentacion, similitud de trigramas >= 0.6 | 809 pares (460 nuevos) | - | - | - | - | 40.0% (26.3-55.4) de pares, n=40 | 77.5% (62.5-87.7) | tabla curada a mano |

Lectura: (c) "re-normalizar con el normalizador" es la clave actual, porque `texto_norm` del PRECIO ya es la salida
del normalizador sobre el nombre unido (`texto_norm = productos_canonicos.nombre_canonico` en 28,735 de 28,735); por eso
se midio como canonico del catalogo + presentacion. Los grupos validos esperados (estricta) son ~80 con k0
(292 x 27.5%; IC 47-125) y ~74-93 con khr (140 x 52.5% directo; ~93 si se parte de la muestra de ka y se descuentan,
por censo, los 25 genericos que khr quita y los 3 validos que agrega). **La clave flexible casi no recupera
comparaciones validas: quita ~85% de las invalidas** (de ~410 grupos invalidos en la vista, contando los 197
solo-Soriana, a ~66). La recuperacion real requiere (d) una tabla de equivalencias revisada y arreglar la lectura de
precios (dispersion: en khr, 48 grupos con ratio > 10; Soriana pone la mediana alta en 33).

Propuesta (opcion 1, sin recarga): `docs/bi/consultas/comparativa_clave_flexible_propuesta.sql` (columna
`tiendas.cadena`, funcion `clave_comparativa(texto)` IMMUTABLE y vista nueva `v_comparativa_precios_v2` con
`num_cadenas`, `num_textos`, mediana, `ratio_medianas_cadena` y `precio_sospechoso`). Validacion tras crearla:
`SELECT COUNT(*), SUM(num_registros) FROM v_comparativa_precios_v2` = 132 | 1,343 (datos del 25-oct-2026).
Confiabilidad del panel: base 92.4% heuristica (2,173 de 28,735 registros con nombre de catalogo); validez estricta
~50% de los grupos; 34% de los grupos (45 de 132) con precio sospechoso. Debe decirse en el panel.
