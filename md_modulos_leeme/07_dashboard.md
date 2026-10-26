# Módulo Dashboard y BI

El dashboard es el último eslabón del pipeline: una aplicación web interna en Django que lee lo que el módulo de carga dejó en PostgreSQL (tablas y vistas) y lo muestra como páginas con tablas, gráficas e indicadores. No escribe en la base de datos ni modifica el esquema; solo consulta.

Este documento explica cómo está hecho. El uso página por página, con capturas, está en el manual de usuario.

## Propósito y alcance

La propuesta del proyecto pide un "prototipo de interfaz web de consulta" con filtros por tienda, categoría, fecha y promociones. El dashboard cumple ese papel y además sirve para revisar la calidad del dato: de qué folleto y página viene cada precio, qué tan confiable es cada tienda y qué folletos están vigentes.

| Hace | No hace |
|---|---|
| Consultar precios, compararlos entre tiendas y ver su histórico | Escribir en la BD o crear tablas propias (todos los modelos son `managed=False`) |
| Calcular KPIs de BI con reglas documentadas en `docs/bi/metricas.md` | Definir el esquema ni las vistas (eso es `load/schema.sql` y `load/vistas.sql`) |
| Mostrar la procedencia de cada registro: imagen de la página, cajas y JSON de OCR/NLP | Corregir datos mal leídos (eso se arregla en NLP o load y se recarga) |
| Leer la corrida vigente del evaluador para la confiabilidad por tienda | Correr el evaluador (eso es `python -m evaluador`) |
| Uso interno, sin inicio de sesión | Publicarse en internet (`DEBUG = True`, solo `localhost`) |

Tabla: Alcance del módulo Dashboard

## Arquitectura

Una consulta recorre siempre el mismo camino. Las páginas HTML llegan casi vacías y el navegador pide los datos a las APIs JSON:

```
Navegador ──GET /precios──► views.pagina_precios ──► render(precios.html)   (solo la estructura)
    │
    └─ JS de la página: fetch("/api/precios?tienda=...&folleto=...")
           │
           ▼
      views.api_precios ──► queries.precios_actuales(...)
                                 │  QuerySet del ORM o SQL crudo (_filas_sql)
                                 ▼
                     PostgreSQL: v_precios_actuales, extracciones, folletos...
                                 │
      JsonResponse ◄─────────────┘
           │
           ▼
      dashboard.js: renderTabla (DataTables) / renderChart (Chart.js)
```

La excepción es el Explorador (`/datos`), que Django arma completo en el servidor con su plantilla.

### Proyecto Django `priceScraper_web/`

| Archivo | Qué contiene |
|---|---|
| `settings.py` | Configuración: lee `.env`, define la BD, las apps, `LANGUAGE_CODE = "es-mx"`, `TIME_ZONE = "America/Mazatlan"` y las carpetas del visor de origen |
| `urls.py` | Un solo `include("dashboard.urls")` en la raíz: todas las rutas son de la app |
| `wsgi.py`, `asgi.py` | Los que genera Django por defecto; no se usan fuera de `runserver` |

Tabla: Archivos del proyecto Django

`settings.py` carga `.env` con `python-dotenv` y arma `DATABASES` a partir de `DATABASE_URL`, el mismo archivo y la misma variable que usa `load/db_builder.py`. El URL se parsea con `urllib.parse` para no agregar `dj-database-url` como dependencia. El formato es:

```
DATABASE_URL=postgresql://usuario:clave@localhost:5432/pricescraper
DJANGO_SECRET_KEY=una_clave_larga   # opcional: si falta, settings.py usa una clave de desarrollo
```

Otros valores que conviene conocer:

- `DEBUG = True` y `ALLOWED_HOSTS = ["localhost", "127.0.0.1"]`: es una herramienta interna; no está preparada para desplegarse.
- `INSTALLED_APPS` incluye `django.contrib.postgres`, que hace falta porque `ProductoCanonico.aliases` es un `ArrayField`.
- `ORIGEN_RAW_DIR = data/raw` y `ORIGEN_PROCESSED_DIR = data/processed`: las carpetas desde las que el visor de origen sirve imágenes y JSON, en solo lectura.

### App `dashboard/`

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `models.py` | Modelos ORM sobre tablas y vistas que ya existen | 8 tablas y 6 vistas, todos `managed=False` |
| `urls.py` | Rutas de páginas, visor de origen y APIs | 9 páginas, 3 rutas del visor, 20 APIs |
| `views.py` | Lee los parámetros del request, llama a `queries` y responde HTML o JSON | `_con_categoria`, `_folleto`, `_promo_params`, `api_*`, `pagina_*`, `imagen_pagina` |
| `queries.py` | Todas las consultas (unas 1,200 líneas): ORM y SQL crudo | `precios_actuales`, `comparativa_precios`, `resumen_kpis`, `confiabilidad_por_tienda`, `cobertura_por_tienda`, `promociones_por_folleto`, `filtrar_*` |
| `confiabilidad.py` | Lector de corridas del evaluador y etiqueta por tienda. Sin BD | `corrida_vigente`, `etiqueta_confiabilidad`, `unir_confiabilidad`, umbrales `UMBRAL_*` |
| `origen.py` | Rutas seguras a imágenes y JSON, fragmento de página, cajas en %. Sin BD | `ruta_imagen`, `ruta_json`, `fragmento_pagina`, `caja_pct`, `marcar_bloques`, `url_origen_segura` |
| `promociones.py` | Clasificación de `eventos_promo` en campañas, lemas y textos legales. Sin BD | `CAMPANIAS`, `clasificar_evento`, `combinar_promos`, `NIVELES_CON_DATOS` |
| `templates/dashboard/` | `base.html` (barra y librerías), una plantilla por página y tres parciales de filtros | `_filtro_con_categoria.html`, `_filtro_folleto.html`, `_filtro_promocion.html` |
| `static/dashboard/` | `dashboard.css` (paleta) y `dashboard.js` (utilidades compartidas) | `qs`, `fetchJSON`, `renderTabla`, `renderChart`, `renderOrigen`, `paramsCategoria`, `valorFolleto`, `avisoFolleto`, `paramsPromocion` |

Tabla: Archivos de la app dashboard

`confiabilidad.py`, `origen.py` y `promociones.py` no importan Django ni tocan la BD a propósito: así se prueban sin base de datos y sin levantar el servidor.

### Modelos `managed=False`

Django describe las tablas para poder consultarlas con el ORM, pero no las crea ni las migra. El esquema lo siguen definiendo `load/schema.sql` y `load/vistas.sql`, que ejecuta `load/db_builder.py`. Si cambias una columna en el SQL, cambia también el modelo.

| Modelo | Tabla o vista | Lo usa |
|---|---|---|
| `Tienda`, `Folleto`, `Pagina`, `Extraccion` | `tiendas`, `folletos`, `paginas`, `extracciones` | Casi todas las consultas; `Extraccion` es la base de los registros |
| `EventoPromo` | `eventos_promo` | Promociones y etiquetas de campaña |
| `ErrorCarga` | `errores_carga` | Página Errores de carga (sin FK a propósito: un folleto que falló entero no tiene fila en `folletos`) |
| `ProductoCanonico` | `productos_canonicos` | Solo a través de la FK de `Extraccion` (nombre canónico) |
| `Alerta` | `alertas` | Nadie hoy (la tabla existe en el esquema) |
| `VPreciosActuales` | `v_precios_actuales` | Resumen, Precios, filtros, avisos de folleto |
| `VComparativaPrecios` | `v_comparativa_precios` | Comparativa |
| `VHistoricoPrecios` | `v_historico_precios` | Histórico y sugerencias de producto |
| `VCalidadPipeline` | `v_calidad_pipeline` | Tabla operativa de Calidad |
| `VFolletosVigencia` | `v_folletos_vigencia` | Resumen, Cobertura, Promociones (única definición de vigencia) |
| `VEventosActivos` | `v_eventos_activos` | Nadie desde el 15-oct-2026 (ver Promociones) |

Tabla: Modelos del dashboard y su tabla o vista (dashboard/models.py)

Las vistas necesitan una columna `id` porque el ORM exige llave primaria. En `v_precios_actuales` y `v_historico_precios` es `extracciones.id`. Eso permite unir cada fila con su procedencia por PK sin tocar la vista. `VComparativaPrecios` no tiene id natural y usa `producto` como PK solo para satisfacer al ORM. `v_comparativa_precios_v2` y la columna `tiendas.cadena` (26-oct-2026) todavía no tienen modelo.

## Mapa de páginas

Cada ruta de `dashboard/urls.py`, qué muestra y de dónde sale:

| Ruta | Vista | Qué muestra | API | Consulta (`queries.py`) | Fuente SQL |
|---|---|---|---|---|---|
| `/` | `pagina_resumen` | Resumen: 5 KPIs, Top 10 categorías y folletos por tienda | `/api/resumen` | `resumen_kpis`, `resumen_top_categorias`, `resumen_folletos_por_tienda` | `v_precios_actuales`, `v_folletos_vigencia`, `tiendas`, `folletos` |
| `/precios` | `pagina_precios` | Precios actuales con descuento, promociones y origen (hasta 500 filas) | `/api/precios` | `precios_actuales` | `v_precios_actuales` + procedencia por id + `eventos_promo` |
| `/comparativa` | `pagina_comparativa` | Mínimo, máximo y diferencia por producto entre tiendas (hasta 300 grupos); al hacer clic, gráfica y detalle por tienda | `/api/comparativa`, `/api/comparativa/<producto>/por-tienda` | `comparativa_precios`, `comparativa_por_tienda` | `v_comparativa_precios`; el detalle, `extracciones` |
| `/historico` | `pagina_historico` | Línea de precio por tienda en el tiempo y tabla | `/api/historico`, `/api/productos/sugerencias` | `historico_precios`, `sugerir_productos` | `v_historico_precios` |
| `/cobertura` | `pagina_cobertura` | Folletos vigentes por tienda, días desde el último folleto, fechas dudosas y folletos por semana | `/api/cobertura`, `/api/cobertura/semanal` | `cobertura_por_tienda`, `folletos_por_semana` | `_SQL_COBERTURA`, `_SQL_FOLLETOS_SEMANA`, `_SQL_FOLLETOS_DUDOSOS` sobre `v_folletos_vigencia` |
| `/promociones` | `pagina_promociones` | Filas (folleto, campaña) con vigencia y precios del folleto | `/api/promociones`, `/api/filtros/promociones` | `promociones_por_folleto` | `eventos_promo` + `v_folletos_vigencia` + `extracciones` |
| `/calidad` (oculta) | `pagina_calidad` | Confiabilidad del dato por tienda y tabla operativa por folleto | `/api/confiabilidad`, `/api/calidad` | `confiabilidad_por_tienda`, `calidad_pipeline` | `_SQL_CONFIABILIDAD` + JSON del evaluador; `v_calidad_pipeline` |
| `/errores` (oculta) | `pagina_errores` | KPIs, gráfica por categoría y tabla de errores de carga | `/api/errores`, `/api/filtros/errores` | `errores_carga`, `listar_tiendas_error` | `errores_carga` |
| `/datos` | `pagina_explorador` | Explorador crudo de tiendas, folletos y extracciones (HTML del servidor, 200 filas por tabla) | ninguna | `listar_tiendas_detalle`, `listar_folletos`, `listar_extracciones` | `tiendas`, `folletos`, `extracciones` |
| `/origen/extraccion/<id>` | `pagina_origen_extraccion` | Visor de origen con un registro seleccionado | `/api/origen/...` | `origen_extraccion`, `contexto_pagina` | `extracciones`, `paginas`, `folletos` + archivos |
| `/origen/pagina/<id>` | `pagina_origen_pagina` | Visor de origen de una página, sin selección | `/api/origen/...` | `contexto_pagina` | igual |
| `/origen/pagina/<id>.webp` | `imagen_pagina` | La imagen de la página (`?version=proc` o `raw`) | — | `pagina_origen` | `paginas` + `data/processed` o `data/raw` |

Tabla: Rutas del dashboard (dashboard/urls.py)

El Explorador se abre en otra pestaña desde la barra y no usa `base.html`: es HTML plano, pensado para inspeccionar la BD sin escribir SQL.

### APIs

Todas son GET y responden JSON. Los parámetros de lista se repiten (`?tienda=Walmart&tienda=Chedraui`).

| API | Parámetros | Devuelve |
|---|---|---|
| `/api/filtros/tiendas` | — | Tiendas activas (`id`, `nombre`, `slug`) |
| `/api/filtros/categorias` | — | Las categorías distintas de los registros, no vacías |
| `/api/filtros/folleto` | `folleto` | Estado del folleto para los avisos: `no_existe`, `sin_precios`, `con_precios` |
| `/api/filtros/promociones` | — | Campañas, niveles (con o sin datos), clases y vigencias |
| `/api/filtros/errores` | — | Categorías de error y tiendas con errores |
| `/api/resumen` | `con_categoria`, `folleto` | `kpis`, `top_categorias`, `folletos_por_tienda` |
| `/api/precios` | `tienda`, `categoria`, `desde`, `hasta`, `q`, `solo_descuento`, `con_categoria`, `folleto`, `promocion`, `nivel`, `campania` | Filas con `promos` y procedencia |
| `/api/comparativa` | `categoria`, `q`, `min_tiendas`, `con_categoria`, `folleto`, `promocion`, `nivel`, `campania` | Grupos de la comparativa |
| `/api/comparativa/<producto>/por-tienda` | `con_categoria` | Un registro por precio, con vigencia, origen y promos |
| `/api/historico` | `producto`, `tienda`, `desde`, `hasta`, `con_categoria`, `folleto`, `promocion`, `nivel`, `campania` | Serie por fecha con procedencia |
| `/api/productos/sugerencias` | `q` | Hasta 20 productos con histórico, los de más registros primero |
| `/api/calidad` | `tienda`, `fuente`, `estado`, `tasa_util_min`, `folleto` | Filas de `v_calidad_pipeline` |
| `/api/confiabilidad` | `tienda`, `desde`, `hasta`, `con_categoria`, `folleto` | `corrida`, `totales`, `umbrales`, `filas` |
| `/api/cobertura` | `tienda`, `con_categoria` | `kpis`, `umbrales`, `filas`, `dudosos` |
| `/api/cobertura/semanal` | `tienda`, `desde`, `hasta` | Folletos por semana de inicio y tienda |
| `/api/promociones` | `tienda`, `folleto`, `campania`, `vigencia`, `clase`, `categoria` | `kpis` y `filas` |
| `/api/errores` | `categoria`, `tienda`, `fuente`, `estado`, `folleto` | `kpis`, `por_categoria`, `filas`, `ocultos_por_estado` |
| `/api/origen/pagina/<id>` | — | Metadatos de la página, vecinas, imagen, bloques y pestaña Precios |
| `/api/origen/extraccion/<id>` | — | El registro y su fila PRODUCTO, con cajas en % |
| `/api/origen/pagina/<id>/<tipo>` | `tipo` = `ocr` o `nlp`; `e` opcional (id de extracción) | Fragmento de esa página del JSON, con marcas si se pasa `e` |

Tabla: APIs JSON del dashboard (dashboard/urls.py y dashboard/views.py)

## Cómo se agregan los números

La fuente principal de esta sección es `docs/bi/metricas.md`, el catálogo de métricas del especialista de BI. Es local: no está en git. Ahí está cada KPI con su fórmula, grano, consulta de verificación (`docs/bi/consultas/`) y fecha de aprobación. Las cifras de abajo salen de una consulta de solo lectura a la BD del 26-oct-2026 (`consulta.py` de la skill `consulta-analitica`), salvo donde se indica otra fecha.

### El registro del dashboard

Todo el dashboard cuenta la misma unidad: un **registro** es una fila de `extracciones` con `tipo = 'PRECIO'`, `valor IS NOT NULL` y `texto_norm IS NOT NULL`. Es exactamente el filtro de la vista `v_precios_actuales`, que además une la tienda y el folleto y calcula `descuento_pct`. Lo que no cumple ese filtro (un precio sin nombre de producto, por ejemplo) no aparece en ningún panel. Al 26-oct-2026 hay 28,172 registros.

Las consultas en SQL crudo repiten ese filtro (`e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL`) en vez de usar la vista, porque necesitan columnas que la vista no expone (`pagina_id`, `metodo_norm`, cajas).

### KPIs del Resumen

`queries.resumen_kpis` arma cinco tarjetas:

| KPI | Fórmula | 26-oct-2026 |
|---|---|---|
| Tiendas activas | `COUNT(*) FROM tiendas WHERE activa` | 20 |
| Folletos cargados | `COUNT(*) FROM folletos` | 821 |
| Precios detectados (`registros_dashboard`) | `COUNT(*) FROM v_precios_actuales`, con los filtros con/sin categoría y folleto | 28,172 |
| Folletos vigentes hoy | `COUNT(*) FROM v_folletos_vigencia WHERE vigente`; aparte, los `vigente_dudoso` | 71 (+18 con fecha dudosa) |
| Categorías | Categorías distintas (`TRIM`, sin vacías) de `v_precios_actuales.categoria`, y % de registros con categoría | 18 · 62.3% (17,551 de 28,172) |

Tabla: KPIs del Resumen (queries.resumen_kpis; docs/bi/metricas.md sección 3)

Los filtros solo afectan a los KPIs de registros ("Precios detectados" y "Categorías") y a la gráfica Top 10. Tiendas, folletos y vigencia no dependen de productos. Con el filtro "sin categoría", el KPI Categorías no aplica: muestra "—" y la gráfica Top 10 queda vacía. El denominador del % es el total de registros del folleto filtrado, sin aplicar el filtro con/sin categoría (`kpi_categorias`).

Antes de corregirse (12-oct-2026, commit 128b7d9), "Precios detectados" contaba también los precios sin nombre de producto y "Folleto más reciente" mostraba 2026-12-25 por fechas mal declaradas. Las 18 categorías salen de `categoria_nlp`, no de `productos_canonicos.categoria`, porque la primera es la que ve el usuario en las tablas. "Frutas y Verduras" no es una categoría propia: `nlp/normalizador.py` la funde en alimentos.

### Confiabilidad por tienda

Esta sección está en la página Calidad, que está oculta de la barra. Responde: "¿qué tan confiable es lo que el dashboard muestra como precio de un producto en esta tienda?". Combina dos fuentes:

1. **La BD** (`_SQL_CONFIABILIDAD` en `queries.py`): por tienda, registros, % catálogo, % sin categoría, confianza OCR (media y mediana), % de duplicados exactos y número de precios atípicos (menos de $1 o más de $100,000). Aparecen todas las tiendas, aunque no tengan registros.
2. **El evaluador** (`confiabilidad.py`): precisión con su IC95, recall y error dominante por tienda, leídos de la corrida vigente en `data/processed/_eval/runs/*.json`.

**"% catálogo" y la regla COALESCE.** Un registro es "de catálogo" si el nombre que muestra se normalizó con `exacto`, `fuzzy` o `fuzzy_bajo`, y es heurístico si es el texto del folleto tal cual. El método se toma con:

```
COALESCE(e.metodo_norm, p.metodo_norm)   -- e = fila PRECIO, p = su fila PRODUCTO (producto_extraccion_id)
```

Desde el 25-oct-2026 (commit dfe3d51), load guarda en la fila PRECIO el `metodo_norm` del nombre que usa. Hacía falta porque, cuando load une líneas o una unidad suelta, el nombre del PRECIO ya no es el de su fila PRODUCTO: "Pechuga de pollo" (exacto) unida queda "Filete de Pechuga de Pollo" (heurístico). En cargas anteriores la fila PRECIO tiene `metodo_norm` NULL y se usa el de la fila PRODUCTO, así que el KPI no cambia con datos viejos. La misma regla define la insignia catálogo/heurístico del visor de origen (`armar_precios_pagina`, commit ff7aaed). Al 26-oct-2026, 2,077 de 28,172 registros (7.4%) son de catálogo, y ninguna fila PRECIO tiene `metodo_norm` NULL.

**Etiqueta de confiabilidad** (`etiqueta_confiabilidad`). Se calcula solo con la precisión que midió el evaluador:

| Etiqueta | Regla |
|---|---|
| Sin medir | La tienda no tiene artículos con precio en el ground truth de la corrida |
| Muestra insuficiente | Menos de 30 registros evaluados (`UMBRAL_REGISTROS_MINIMOS`) |
| Baja | Precisión < 0.10 (`UMBRAL_PRECISION_MEDIA`) |
| Aceptable | Precisión ≥ 0.25 y límite inferior del IC95 ≥ 0.15 |
| Media | El resto, incluida la precisión ≥ 0.25 con IC95 inferior < 0.15 |

Tabla: Etiqueta de confiabilidad por tienda (dashboard/confiabilidad.py)

Además, una tienda con menos de 20% de registros de catálogo lleva el distintivo "Base heurística" (`UMBRAL_PCT_CATALOGO_BASE_HEURISTICA`): sus nombres no sirven para comparar contra otras tiendas.

**Corrida vigente.** `corrida_vigente` toma la más reciente por `meta.fecha` que cumpla tres condiciones: split `dev`, sin cambios sin commit e integridad válida. Descarta por nombre las `-sucio` y las que no son `_dev` sin abrirlas, y guarda cada archivo en caché por `mtime` y tamaño. Al 26-oct-2026 es `20261025_141934_ff7aaed_dev.json`: 158 páginas, 14 de 16 tiendas medidas, precisión global 30.8% y recall 23.3%. Las corridas `-sucio` posteriores, como la `20261025_224754` que cita el módulo NLP, no cuentan para el panel. Sin corrida válida, o sin la carpeta `data/` (que está en `.gitignore`), todas las tiendas salen "Sin medir" y la página sigue funcionando.

El evaluador mide una muestra de dev, no producción completa, y el panel lo dice en un aviso. Los umbrales se aprobaron el 12-oct-2026; si los cambias, actualiza `docs/bi/metricas.md`.

### Cobertura y vigencia

**Vigencia.** `v_folletos_vigencia` (`load/vistas.sql`) es la **única definición de "vigente"** del dashboard: la usan Resumen, Cobertura y Promociones. La vista no corrige fechas: solo pone una etiqueta, en este orden de precedencia:

| Etiqueta | Regla |
|---|---|
| `sin_fecha` | `fecha_inicio` o `fecha_fin` NULL |
| `fin_antes_inicio` | `fecha_fin < fecha_inicio` |
| `inicio_antiguo` | `fecha_inicio < scrapeado_at - 365 días` |
| `inicio_futuro_vs_scrapeo` | `fecha_inicio > scrapeado_at + 30 días` |
| `vigencia_larga` | `fecha_fin - fecha_inicio > 120 días` (por ejemplo, bodega_aurrera "todo el año") |

Tabla: Etiquetas de fecha dudosa (load/vistas.sql, v_folletos_vigencia)

Con esas etiquetas se definen tres estados:

- **vigente**: sin etiqueta y `fecha_inicio <= hoy <= fecha_fin`;
- **vigente_dudoso**: con etiqueta y dentro del rango; se muestra aparte y no se suma a vigente;
- **proximo**: sin etiqueta y `fecha_inicio > hoy`.

"Hoy" es el `CURRENT_DATE` del servidor de BD. Al 26-oct-2026 hay 71 vigentes, 18 dudosos y 3 próximos.

`queries.py` repite los umbrales (`DIAS_INICIO_ANTIGUO = 365`, `DIAS_INICIO_FUTURO = 30`, `DIAS_VIGENCIA_LARGA = 120`) solo para mostrarlos en el panel. La prueba `tests/test_umbrales_vigencia.py` verifica que coincidan con la vista: si cambias uno, cambia el otro.

**Panel de Cobertura** (`_SQL_COBERTURA`). Por tienda calcula:

- folletos vigentes, dudosos y próximos;
- fecha del último folleto: `MAX(fecha_inicio)` hasta hoy, sin las anomalías de `ANOMALIAS_INICIO_NO_CONFIABLE`, y días desde entonces;
- último scrapeo;
- páginas y precios de folletos vigentes;
- errores de carga abiertos.

Páginas y precios se agregan por folleto **por separado** antes de unirlos: unir `paginas` y `extracciones` directo multiplicaría páginas por precios. `errores_carga` se une por `tienda_slug` porque no tiene FK. La serie semanal agrupa por `DATE_TRUNC('week', fecha_inicio)` y va de 182 días atrás a 30 adelante (`DIAS_SERIE_ATRAS`, `DIAS_SERIE_ADELANTE`). La serie también refleja cuándo se scrapeó: una semana sin scrapeo se ve como caída.

### Procedencia y visor de origen

Cada fila de Precios, Histórico, el detalle de Comparativa, el Explorador y los folletos dudosos de Cobertura lleva una celda **Origen** con este formato:

```
folleto_id_fuente · vigencia · pág. N
```

Lleva dos enlaces: `[pag]` abre el visor y `[folleto]` abre `url_origen`, solo si es http o https. El identificador visible es el id de Tiendeo u Ofertomat (`folleto_id_fuente`) porque el título no distingue folletos: Ofertomat siempre dice "Vista previa...".

**Cómo se une sin duplicar** (opción A, aprobada el 13-oct-2026). Las vistas no se tocaron. Como sus filas traen `id = extracciones.id`, `procedencia_por_ids` hace una segunda consulta por PK (`id__in`) y `origen.combinar_procedencia` la pega en Python: misma cantidad de filas, mismo orden. La verificación de `docs/bi/metricas.md` dio 32,073 filas = 32,073 ids (17-oct-2026).

**El visor** (`origen.html` y `/api/origen/pagina/<id>`) muestra:

- la imagen procesada con todas las cajas de la página;
- la caja del precio en rojo y la de su producto en azul;
- enlaces a las páginas vecinas;
- tres pestañas: OCR, NLP y Precios. OCR y NLP muestran solo el fragmento de esa página de `ocr_resultado.json` o `nlp_resultado.json`. Precios lista los pares precio-producto y permite recorrerlos con clic o con las flechas ← y →.

Al pasar `?e=<id>`, `marcar_bloques` resalta los elementos del JSON cuya caja coincide con la del registro: igualdad exacta o una superposición de al menos 50% del área de la caja menor (`SUPERPOSICION_MINIMA`).

**Coordenadas.** `extracciones.bbox_*` está en el espacio de la imagen **procesada**, cuyo ancho varía por página (1800, 1500, 1350 o 1200 px). Por eso `caja_pct` envía la caja en porcentaje del tamaño real de esa imagen, leído de su cabecera con Pillow. Nunca supongas 1800.

**Seguridad.** Solo GET, y las URLs reciben solo ids enteros. La ruta al archivo se arma con datos de la BD y aun así se valida en `origen.py`:

- fuente en `{tiendeo, ofertomat}`;
- expresiones regulares para slug, folleto y archivo;
- nombres de JSON fijos;
- `resolve().is_relative_to(base)`;
- límite de 25 MB por JSON;
- caché de 16 archivos.

Cualquier fallo responde 404 sin detalle. La imagen se sirve con `X-Content-Type-Options: nosniff`.

### Promociones

Desde el 15-oct-2026 (fase 1), las promociones se leen directo de `eventos_promo` y se clasifican en Python (`promociones.py`). Ya no se usa `v_eventos_activos` por tres motivos:

- todas sus fechas son NULL, así que todos los eventos parecían vigentes;
- junta eventos de varios folletos;
- su `num_precios_asociados` cuenta cada precio una vez por evento.

`clasificar_evento` aplica reglas en orden: nombre de producto ("vela aromática navidad"), texto legal ("excepto", "participantes"), campaña y lema de la tienda ("precios bajos todos los días"). Las campañas se reducen a diez slugs canónicos (`CAMPANIAS`: julio_regalado, hot_sale, buen_fin, regreso_a_clases, navidad, halloween_dia_de_muertos, liquidacion, aniversario, ofertones, fiestas_patrias). El mapa acepta tanto las variantes que hay hoy en la BD como los slugs ya canónicos que escribe el NLP actual. Las mismas reglas están en SQL en `docs/bi/consultas/promociones_campanias.sql`, y una prueba vigila que coincidan.

Cada registro trae `promos = {campania: [...], producto: [], bancaria: []}`. Hoy solo el nivel campaña tiene datos (`NIVELES_CON_DATOS`). Producto (2x1, %) y bancaria (MSI) quedan "pendiente de carga" porque load todavía no liga esas promociones al producto. En la interfaz esas opciones aparecen desactivadas.

- **Etiquetas sin duplicar**: `agregar_promos` hace una consulta por `folleto_id__in` y agrupa en Python. Un JOIN directo registro-evento inflaba las filas 12.5%, porque hay folletos con varios eventos.
- **Filtros** (`filtrar_promocion`): `EXISTS` sobre `eventos_promo`. Un registro "tiene promoción" si su folleto tiene al menos un evento de clase campaña. En Comparativa, un grupo "tiene promoción" si alguno de sus registros la tiene (EXISTS anidado).
- **Página Promociones** (`promociones_por_folleto`): una fila por (folleto, campaña), con la vigencia de `v_folletos_vigencia`. "Precios en el folleto" son los registros del dashboard de ese folleto. Los KPIs suman cada folleto una sola vez, porque un folleto puede tener dos campañas. Hay un enlace a `/precios?folleto=<id>`.

### Filtros compartidos

Hay tres filtros que se repiten en varias páginas. Los tres se combinan en AND con el resto y **solo agregan condiciones WHERE o EXISTS**: nunca un JOIN que cambie el número de filas.

| Filtro | Parámetro | Regla | Código |
|---|---|---|---|
| Con / sin categoría | `?con_categoria=si\|no` (vacío = todos) | Sin categoría ⇔ `COALESCE(BTRIM(categoria_nlp), '') = ''` sobre la fila PRECIO | `normalizar_con_categoria`, `filtrar_con_categoria` (ORM), `_SQL_CON_CATEGORIA` (SQL crudo) |
| Folleto | `?folleto=<folleto_id_fuente>` (vacío = todos) | Igualdad exacta tras quitar espacios; un id inexistente da vacío, no se ignora | `normalizar_folleto`, `filtrar_folleto`, `_en_folleto`, `_SQL_FOLLETO`, `estado_folleto` |
| Promoción | `?promocion=con\|sin`, `?nivel=`, `?campania=` (repetible) | EXISTS sobre `eventos_promo`; elegir campaña sin "Promoción" equivale a "con" | `filtrar_promocion` |

Tabla: Filtros compartidos (dashboard/queries.py)

Detalles que no son obvios:

- **Con/sin categoría** usa la categoría del registro y no la del canónico (`productos_canonicos.categoria`), que difería en 392 registros al 14-oct-2026. En Comparativa no parte grupos, porque la vista agrupa por (texto, categoría) y cada fila tiene una sola categoría. En Cobertura solo afecta los conteos de precios.
- **Folleto** acepta el id de la fuente (el de la celda Origen y el de la carpeta `data/raw/<fuente>/<tienda>/<id>`), no el `folletos.id` interno. El esquema solo garantiza unicidad por `(fuente, folleto_id_fuente)`; si un id se repitiera entre fuentes, el filtro traería ambos folletos.
- **Folleto en Comparativa**: deja los grupos que tienen al menos un registro del folleto, con `EXISTS`, pero el mínimo, el máximo y la diferencia siguen siendo entre todas las tiendas. El detalle por tienda no se filtra por folleto: quedaría una sola tienda.
- **Folleto en Cobertura y Promociones**: Cobertura no lo aplica, porque es un panel por tienda. Promociones sí tiene campo Folleto, porque desde el 15-oct-2026 lee `eventos_promo`, que sí tiene folleto.
- **Avisos de folleto** (`/api/filtros/folleto`): "folleto no encontrado", "existe pero no tiene precios" y, en Errores, "hay N errores ocultos por el filtro de Estado". El navegador los arma con `textContent`, así que el id nunca se interpreta como HTML.

### Comparativa

**Hoy el panel usa `v_comparativa_precios`.** La vista agrupa los registros por `(texto_norm, categoria_nlp)` y deja los grupos con `COUNT(DISTINCT tienda_id) > 1`. Por grupo devuelve:

- `precio_min`, `precio_max` y `diferencia`;
- `precio_promedio`;
- `num_registros` y `num_tiendas`;
- `tiendas`, la lista de nombres.

`comparativa_precios` ordena por diferencia descendente y corta en 300 grupos. La página pide `min_tiendas = 2` por defecto (la API, si no se le pasa, usa 1). Al 26-oct-2026 la vista tiene 489 grupos y 4,808 registros.

Al hacer clic en un grupo, `comparativa_por_tienda` trae todos los registros con ese `texto_norm`, con su vigencia, origen y promociones, ordenados por precio.

**`v_comparativa_precios_v2` (fase 1, aplicada en la BD el 26-oct-2026, commit 3f6eb7b).** Ataca los dos problemas de la vista actual (ver Limitaciones):

- **Cadena comercial.** Columna nueva `tiendas.cadena` (`load/schema.sql`): soriana = soriana_hiper + soriana_mercado y walmart = walmart + walmart_express. Bodega Aurrera, Sam's Club y las demás tiendas quedan con NULL, que significa que son su propia cadena. La vista agrupa por `COALESCE(t.cadena, t.slug)` y exige registros en al menos 2 cadenas.
- **Clave flexible.** La función `clave_comparativa(texto)` (`load/vistas.sql`) pone el texto en minúsculas, quita acentos y puntuación, unifica unidades (1 Kg = 1kg = 1 kilo; medio kilo = 500 g), quita palabras de relleno y ordena las palabras. Devuelve NULL para los 84 genéricos del catálogo ("Refresco", "Galletas", "Smart TV") y para textos con menos de 2 palabras de contenido, salvo una fruta o verdura sola.
- **Precios atípicos.** La base excluye valores fuera de $1 a $100,000. Además, la vista calcula la mediana por cadena y `ratio_medianas_cadena`, y marca `precio_sospechoso` cuando la mediana más alta es más de 10 veces la más baja (casi siempre son centavos pegados).
- **Columnas nuevas.** `num_cadenas`, `num_textos` (cuántos textos distintos juntó la clave), `precio_mediana`, y `producto` y `categoria` como el valor más frecuente (`MODE()`).

Al 26-oct-2026: 131 grupos, 1,293 registros y 21 con precio sospechoso. En la muestra de BI, la validez estricta (que el grupo compare de verdad el mismo producto) sube de 27.5% en la vista actual a cerca de 53% con la clave flexible (`docs/bi/metricas.md` sección 8; Engram #268 y #277). La clave casi no recupera comparaciones nuevas: lo que hace es quitar cerca del 85% de las inválidas.

**Pendiente.** La fase 2 (calcular la clave en load con el catálogo de Python) y la fase 3 (conectar `/comparativa` a la v2, con filtro "Mín. cadenas", insignia de precio sospechoso y un modelo Django con el campo `cadena`) están por aprobar. Hasta entonces la v2 solo se consulta por SQL.

## Pestañas ocultas

A pedido de la persona dueña del proyecto, dos pestañas se quitaron de la barra. **Solo se ocultaron**: rutas, vistas, plantillas y APIs siguen intactas y se puede entrar escribiendo la URL.

| Pestaña | Oculta desde | Ruta | APIs que siguen activas |
|---|---|---|---|
| Calidad | 19-oct-2026 (Engram #236) | `/calidad` | `/api/calidad`, `/api/confiabilidad` |
| Errores de carga | 21-oct-2026 (Engram #237) | `/errores` | `/api/errores`, `/api/filtros/errores` |

Tabla: Pestañas ocultas de la barra (dashboard/templates/dashboard/base.html; commit 7c09564)

Cada `<li>` está envuelto en `{% comment %} ... {% endcomment %}` en `base.html`, con una nota. Para restaurar una pestaña, borra esas dos etiquetas y la nota.

## Tecnologías de front

No hay npm ni paso de compilación: todo se carga por CDN desde `base.html`, salvo el adaptador de fechas, que solo carga `historico.html`.

| Librería | Versión | Para qué |
|---|---|---|
| Bootstrap (CSS y `bootstrap.bundle`) | 5.3.3 | Maquetación, barra, formularios, pestañas y acordeones |
| jQuery | 3.7.1 | Requisito de DataTables |
| DataTables, con su integración Bootstrap 5 | 1.13.11 | Tablas con orden, búsqueda y paginación en el navegador (`renderTabla`, 25 filas por página, textos en español) |
| Chart.js | 4.4.4 | Barras (Resumen, Comparativa, Cobertura, Calidad, Errores) y línea (Histórico) |
| chartjs-adapter-date-fns | 3.0.0 | Eje de tiempo semanal del Histórico |
| Tabler Icons (webfont) | `@latest`, sin versión fija | Iconos de la barra y de las tarjetas KPI (`ti ti-...`) |

Tabla: Librerías de front (dashboard/templates/dashboard/base.html e historico.html)

`dashboard.css` define la paleta de marca (morado `#786aca`) y, por separado, la paleta categórica de las gráficas. Esta se validó con la skill `dataviz` el 24-ago-2026 y tiene orden fijo. `dashboard.js` concentra las utilidades compartidas:

- `qs` arma el query string y repite los parámetros de lista;
- `fetchJSON` hace la petición;
- `renderTabla` y `renderChart` destruyen la instancia anterior antes de redibujar;
- `escaparHtml` escapa el texto del OCR antes de insertarlo en las tablas;
- `renderOrigen` arma la celda Origen;
- también están las utilidades de los filtros compartidos.

## Cómo correrlo

Requisitos: PostgreSQL arriba con la BD cargada (módulo load), `.env` con `DATABASE_URL` y el entorno virtual del proyecto.

```
venv/Scripts/python.exe probar_dashboard.py          # verifica la conexión y levanta http://localhost:8000
venv/Scripts/python.exe manage.py runserver          # lo mismo, sin la verificación previa
venv/Scripts/python.exe manage.py check              # revisa la configuración sin levantar nada
```

`probar_dashboard.py` llama a `verificar_conexion()` de `load/db_builder.py` y, si la conexión falla, termina con un mensaje en vez de levantar un servidor que daría error en cada página. Si la conexión responde, ejecuta `runserver 127.0.0.1:8000`.

El visor de origen necesita además las carpetas `data/raw` y `data/processed` con las imágenes y los JSON. Sin ellas, la página abre pero sin imagen ni fragmentos (404 o estado `ausente`). La confiabilidad por tienda necesita `data/processed/_eval/runs/`; sin esa carpeta, todo sale "Sin medir".

Al crear el proyecto (23-ago-2026) se corrió `manage.py migrate` para las apps internas de Django (`auth`, `sessions`...), según Engram #80. Esas tablas conviven con las del proyecto y el dashboard no las usa. En una BD nueva, `runserver` avisará de migraciones pendientes; el dashboard funciona igual porque no usa inicio de sesión. Esto no se probó en una BD nueva.

Para verificar una cifra contra la BD sin riesgo de escribir, usa la skill `consulta-analitica`: su `consulta.py` se conecta con un rol de solo lectura (`DATABASE_URL_RO`) y solo acepta SELECT. Las consultas de verificación de cada KPI están en `docs/bi/consultas/` (local).

## Pruebas

Las pruebas del dashboard **no tocan la BD**. Siete archivos tienen un fixture `_sin_bd` que hace fallar la prueba si algo intenta abrir una conexión. Esas pruebas revisan:

- el SQL que genera el ORM (a partir de `qs.query`);
- el SQL crudo;
- que las vistas pasen los parámetros;
- que las plantillas pinten los campos.

`test_dashboard_confiabilidad.py` prueba el módulo puro con corridas falsas en `tmp_path`. Los conteos reales se validan aparte con las consultas de `docs/bi/consultas/`.

| Archivo | Pruebas | Qué fija |
|---|---|---|
| `test_dashboard_promociones.py` | 108 | Clasificación de eventos, slugs, filtros de promoción, KPIs de la página y espejo SQL |
| `test_dashboard_origen.py` | 74 | Rutas seguras, fragmentos JSON, cajas en %, `url_origen_segura`, combinación por id |
| `test_dashboard_filtro_folleto.py` | 56 | Normalización del id, SQL del ORM y crudo, paso del parámetro en cada vista |
| `test_dashboard_filtro_categoria.py` | 46 | Regla de categoría vacía en ORM y SQL crudo, en cada panel |
| `test_dashboard_confiabilidad.py` | 35 | Elección de la corrida vigente, etiquetas y umbrales |
| `test_dashboard_avisos_folleto.py` | 32 | Estados del folleto y errores ocultos por Estado |
| `test_dashboard_origen_precios.py` | 13 | Pestaña Precios del visor y regla COALESCE de la insignia |
| `test_dashboard_kpi_categorias.py` | 11 | KPI Categorías y su denominador |
| `test_umbrales_vigencia.py` | 1 | Umbrales de `queries.py` = los de `v_folletos_vigencia` |

Tabla: Pruebas del dashboard (tests/; 376 pasan al 26-oct-2026)

```
venv/Scripts/python.exe -m pytest tests/test_dashboard_*.py tests/test_umbrales_vigencia.py -q   # 376 passed, ~2 s
```

Las pruebas hacen `django.setup()` con `priceScraper_web.settings`, que lee `.env`, pero no se conectan. No hay pruebas de navegador en el repo: las revisiones visuales se hicieron con Playwright durante el desarrollo.

## Reglas y decisiones

- **Django y ORM en vez de FastAPI.** La primera versión se hizo en FastAPI. Se migró a Django y luego al ORM porque la propuesta del proyecto comprometía "Django + Bootstrap" y "Django ORM para la capa de acceso". Solo se migró la lectura: `load/load.py` sigue en SQL crudo porque sus upserts condicionales no se traducen bien al ORM (commit c045f80; `sources/dashboard/02_migracion_django_orm.docx`).
- **ORM donde se puede, SQL crudo donde conviene.** Confiabilidad y Cobertura usan SQL crudo (`_filas_sql`) porque necesitan CTE, `PERCENTILE_CONT` y agregar por separado antes de unir; el ORM las haría ilegibles. El resto usa QuerySets.
- **Sin joins que dupliquen.** Cada métrica se verificó contando filas antes y después de cada unión. La procedencia y las promociones se resuelven con una segunda consulta por PK y se combinan en Python; los filtros usan `EXISTS`. Es la regla de la skill `consulta-analitica`.
- **Una sola definición de cada cosa.** Vigencia = `v_folletos_vigencia`. Registro = filtro de `v_precios_actuales`. Categoría = `categoria_nlp` de la fila PRECIO. Si algún día cambian, se cambian en un solo lugar.
- **Las vistas no se tocan sin aprobación.** Procedencia, folleto y promociones se resolvieron sin modificar vistas (opción A). La Comparativa v2 se creó como vista nueva en lugar de cambiar la actual, para que el panel siga funcionando mientras se decide la fase 3.
- **Decimal a float.** Las columnas `ROUND(...::NUMERIC)` llegan como `Decimal` y Django las serializaría como texto en el JSON. `_num()` las convierte a `float` para que la API devuelva números. En SQL crudo se usa `::float8` o `::bigint`.
- **Plotly y PySpark descartados.** Chart.js cubre las gráficas de negocio y es más ligero. Para PySpark, el volumen (cientos de miles de filas) es trivial para PostgreSQL (`sources/dashboard/02_migracion_django_orm.docx`).
- **Cada métrica pasa por BI y por la persona.** El especialista de BI propone la métrica, la valida con dos caminos SQL independientes y la documenta en `docs/bi/metricas.md`. Se construye solo después de que la persona la aprueba (skill `consulta-analitica`).

## Configuración

| Constante | Valor | Dónde | Para qué |
|---|---|---|---|
| `UMBRAL_REGISTROS_MINIMOS` | 30 | `confiabilidad.py` | Mínimo para etiquetar una tienda |
| `UMBRAL_PRECISION_MEDIA` / `UMBRAL_PRECISION_ACEPTABLE` | 0.10 / 0.25 | `confiabilidad.py` | Cortes de Baja, Media y Aceptable |
| `UMBRAL_IC95_INFERIOR_ACEPTABLE` | 0.15 | `confiabilidad.py` | IC95 mínimo para Aceptable |
| `UMBRAL_PCT_CATALOGO_BASE_HEURISTICA` | 20.0 | `confiabilidad.py` | Distintivo "Base heurística" |
| `DIAS_INICIO_ANTIGUO` / `DIAS_INICIO_FUTURO` / `DIAS_VIGENCIA_LARGA` | 365 / 30 / 120 | `queries.py` (espejo de la vista) | Etiquetas de fecha dudosa |
| `DIAS_SERIE_ATRAS` / `DIAS_SERIE_ADELANTE` | 182 / 30 | `queries.py` | Rango por defecto de la serie semanal |
| `MAX_BYTES_JSON` / `MAX_ARCHIVOS_CACHE` | 25 MB / 16 | `origen.py` | Límite y caché de los JSON del visor |
| `SUPERPOSICION_MINIMA` | 0.5 | `origen.py` | Coincidencia de cajas para las marcas OCR/NLP |
| `limite` de cada consulta | 500 Precios, 300 Comparativa, 200 Explorador, 1,000 Errores | `queries.py` | Filas máximas por respuesta |

Tabla: Constantes del dashboard

## Limitaciones conocidas y pendientes

- **La Comparativa actual mezcla cosas que no se comparan.** Con la BD del 26-oct-2026:
  - 197 de los 489 grupos de `v_comparativa_precios` son solo Soriana Hiper contra Soriana Mercado, que son la misma cadena y comparten precio idéntico en cerca de la mitad de sus grupos (Engram #271).
  - Los genéricos juntan productos distintos: "Galletas" reúne 91 registros de $2.23 a $657.50, y "Ariel", de $0.61 a $648.74.
  - Aparecen unidades como nombre de producto: "Pieza", sin categoría, tiene 72 registros.
  - 199 grupos tienen un precio máximo más de 10 veces el mínimo, casi siempre por precios mal leídos (centavos pegados, "$2189" = $21.89).
  - La vista no excluye atípicos.
  - BI estimó que solo 27.5% de los grupos de 2 o más cadenas comparan de verdad lo mismo (IC95 16-43%).

  La v2 corrige la cadena, los genéricos y los atípicos, pero falta conectarla al panel (fase 3).
- **El detalle por tienda de Comparativa** busca por `texto_norm` sin la categoría, así que, si un texto tiene dos categorías, mezcla los registros de ambos grupos. Además, `<str:producto>` de Django no acepta "/": los 4 grupos actuales con "/" en el nombre probablemente dan 404 en el detalle. Se dedujo del código y no se probó en el navegador.
- **Base heurística.** Solo 7.4% de los registros tiene nombre de catálogo, así que casi todo el dashboard muestra el texto del folleto tal cual. La confiabilidad medida por el evaluador es baja (precisión global 30.8% en dev): el visor de origen existe justamente para revisar cada precio.
- **Promociones de producto y bancarias**: pendientes de carga en load. Hoy solo hay campañas del folleto.
- **Tabler Icons sin versión fija** (`@latest`): un cambio del CDN podría romper iconos. Conviene fijar la versión.
- **`djangorestframework` está en `requirements.txt` pero no se usa**: las APIs son `JsonResponse` simples. Tampoco se usan los modelos `Alerta` ni `VEventosActivos`.
- **Sin exportación a CSV**: la propuesta la mencionaba (cronograma, mes 5) y no se implementó (`sources/dashboard/01_modulo_dashboard.docx`).
- **Si load agrega una tienda nueva de una cadena existente**, hay que asignarle `tiendas.cadena` a mano: el `UPDATE` de `schema.sql` solo corre al crear la BD (Engram #277).

## Historial

| Fecha | Commit | Cambio |
|---|---|---|
| 23-ago-2026 | c045f80 | Primer dashboard: FastAPI → Django → Django ORM en la misma sesión; 6 páginas y 9 APIs; se agregó `id` a tres vistas para el ORM |
| 23-ago-2026 | 4c6feaf | Paleta de marca e iconos Tabler |
| 3-oct-2026 | 842ccf5 | Explorador de datos (`/datos`) |
| 10-oct-2026 | b81056b | Pestaña Errores de carga y filtros de lista con casillas |
| 12-oct-2026 | 128b7d9 | Confiabilidad por tienda, Cobertura, vista `v_folletos_vigencia` y KPIs del Resumen corregidos |
| 13-oct-2026 | 276f6a7 | Procedencia por registro y visor de origen |
| 14-oct-2026 | 2c05700 | Filtro con/sin categoría; Top categorías por la categoría del registro |
| 15-oct-2026 | 88bc7e3 | Filtro por ID de folleto y avisos |
| 16-oct-2026 | 85caee1 | Campaña del folleto por registro, filtros de promoción y página Promociones sobre tablas |
| 25-oct-2026 | 7c09564 | Pestaña Precios del visor, KPI Categorías, arreglos del Histórico (búsqueda sin distinguir mayúsculas, sugerencias con histórico) y pestañas ocultas |
| 25-oct-2026 | dfe3d51, ff7aaed | `metodo_norm` del PRECIO para "% catálogo" y la insignia del visor |
| 26-oct-2026 | 3f6eb7b | `tiendas.cadena`, `clave_comparativa()` y `v_comparativa_precios_v2` (cambio en `load/`, el panel no cambia) |

Tabla: Historia del dashboard (git log -- dashboard/ load/vistas.sql)

La primera versión está descrita en `sources/dashboard/01_modulo_dashboard.docx` y la migración a Django y al ORM en `02_migracion_django_orm.docx`. Esos documentos describen 6 páginas y 12 modelos, y Promociones sobre `v_eventos_activos`: es historia, no el estado actual. El detalle de cada métrica, con su verificación, está en `docs/bi/metricas.md` y en Engram (proyecto `pricescraper_ss`, temas `bi/*`).
