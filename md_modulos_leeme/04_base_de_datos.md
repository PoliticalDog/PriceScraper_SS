# Base de datos

PriceScraper guarda en PostgreSQL todo lo que el pipeline extrae de los folletos: las tiendas, los folletos con su vigencia, cada página con sus métricas de OCR y cada bloque de texto ya clasificado por el NLP. El esquema está en `load/schema.sql` y las vistas que consume el dashboard están en `load/vistas.sql`. Quien escribe en la base es el módulo de carga (`load/load.py`, ver `05_load.md`); el dashboard solo lee (ver `07_dashboard.md`).

## Propósito y alcance

La base de datos tiene dos trabajos: conservar la procedencia de cada dato (de qué tienda, folleto, página y caja de la imagen salió un precio) y dar al dashboard consultas listas para leer. Por eso guarda los bloques del NLP casi tal cual, en lugar de un registro "limpio" por producto, y deja la agregación a las vistas.

| Hace | No hace |
|---|---|
| Guardar tiendas, folletos, páginas y cada bloque útil del NLP con su caja (`bbox`) | Leer los JSON del datalake (eso es `load/load.py`) |
| Relacionar cada PRECIO con la fila PRODUCTO que lo nombra | Decidir qué producto va con qué precio (load) |
| Deduplicar nombres de producto en un catálogo canónico | Corregir fechas de vigencia dudosas (solo las etiqueta) |
| Registrar los errores de carga por folleto y página | Guardar las imágenes (quedan en `data/`) |
| Ofrecer vistas de precios, comparativa, histórico, calidad y vigencia | Calcular la calidad contra el ground truth (evaluador) |

Tabla: Alcance de la base de datos

## Panorama del esquema

Motor: PostgreSQL 18.4, base `pricescraper`, 175 MB (consulta de solo lectura, 26-oct-2026). Conexión desde Python con psycopg 3 (`load/db_builder.py`) y desde Django con su backend de PostgreSQL.

| Objeto | Cantidad | Nombres | Definido en |
|---|---|---|---|
| Extensión | 1 | `pg_trgm` (búsqueda por similitud de texto) | `load/schema.sql` |
| Tipos ENUM | 4 | `fuente_enum`, `estado_folleto_enum`, `tipo_extraccion_enum`, `categoria_error_enum` | `load/schema.sql` |
| Tablas del pipeline | 8 | `tiendas`, `folletos`, `paginas`, `extracciones`, `productos_canonicos`, `eventos_promo`, `errores_carga`, `alertas` | `load/schema.sql` |
| Vistas | 7 | `v_precios_actuales`, `v_comparativa_precios`, `v_comparativa_precios_v2`, `v_historico_precios`, `v_calidad_pipeline`, `v_folletos_vigencia`, `v_eventos_activos` | `load/vistas.sql` |
| Funciones propias | 1 | `clave_comparativa(text)` | `load/vistas.sql` |
| Tablas de Django | 10 | `auth_*` (6), `django_admin_log`, `django_content_type`, `django_migrations`, `django_session` | `manage.py migrate` |

Tabla: Objetos de la base de datos pricescraper (verificado en information_schema el 26-oct-2026)

Las tablas de Django no tienen relación con el pipeline: las crea `manage.py migrate` para las apps `django.contrib.*` de `priceScraper_web/settings.py`. Los modelos del dashboard (`dashboard/models.py`) declaran las tablas y vistas del pipeline con `managed = False`, así que Django nunca las crea, altera ni escribe.

## Diagrama entidad-relación

El diagrama más reciente es `load/diagrama_ER_V3.svg` (septiembre de 2026; último commit que lo tocó: 842ccf5, 3-oct-2026). Se comparó contra la base actual el 26-oct-2026:

- **Sigue vigente** para las siete tablas que dibuja (`tiendas`, `folletos`, `paginas`, `productos_canonicos`, `extracciones`, `eventos_promo`, `alertas`): sus columnas y tipos coinciden con `schema.sql`, y sus diez relaciones son las diez llaves foráneas que existen hoy.
- **Le falta** la tabla `errores_carga` (agregada el 8-oct-2026, commit 9010a75; no tiene llaves foráneas, así que no cambia ninguna relación) y la columna `tiendas.cadena` (26-oct-2026, commit 3f6eb7b).
- `load/diagrama_ER_V1.svg` es el modelo anterior y queda solo como historia.

El SVG no se puede insertar tal cual en el borrador de Word (el convertidor solo acepta imágenes rasterizadas); para el documento hay que exportarlo a PNG después de agregarle lo que falta. Mientras tanto, este es el diagrama actual en texto:

```
tiendas 1 ──< folletos 1 ──< paginas 1 ──< extracciones >── 1 productos_canonicos
   │  1          │ 1                         │  ▲
   │             │                           │  └─ producto_extraccion_id (PRECIO/ATRIBUTO → PRODUCTO, misma tabla)
   │             └──< eventos_promo          │
   ├────────────────< eventos_promo          │
   ├────────────────< extracciones ──────────┘  (tienda_id y folleto_id desnormalizados)
   └────────────────< alertas  (tienda_id opcional)

errores_carga   (sin llaves foráneas: se une por fuente + folleto_id_fuente o por tienda_slug)
```

## Tipos enumerados

| Tipo | Valores | Uso |
|---|---|---|
| `fuente_enum` | `tiendeo`, `ofertomat` | `folletos.fuente` |
| `estado_folleto_enum` | `pending`, `processing`, `done`, `error` | `folletos.estado` |
| `tipo_extraccion_enum` | `PRODUCTO`, `PRECIO`, `PRECIO_ANTERIOR`, `AHORRO`, `PROMO`, `EVENTO_PROMO`, `ATRIBUTO`, `DESCARTE` | `extracciones.tipo` (las mismas categorías del NLP) |
| `categoria_error_enum` | `tamano_excesivo` (SQLSTATE 22001), `valor_fuera_de_rango` (22003), `formato_invalido` (22P02, 22007, 22008), `violacion_integridad` (23xxx), `json_corrupto`, `archivo_faltante`, `otro` | `errores_carga.categoria` |

Tabla: Tipos ENUM de load/schema.sql

Cada `CREATE TYPE` va dentro de un bloque `DO ... EXCEPTION WHEN duplicate_object` para que `schema.sql` se pueda ejecutar más de una vez sin fallar.

## Tablas

### tiendas

Una fila por tienda o formato comercial. La crea `load.py` la primera vez que carga un folleto de esa tienda (`ON CONFLICT (slug) DO NOTHING`).

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | SERIAL PK | |
| `nombre` | VARCHAR(100) | Nombre para mostrar ("Soriana Hiper") |
| `slug` | VARCHAR(60) UNIQUE | Identificador canónico normalizado (post-corrección ETL) |
| `fuente_slug` | VARCHAR(60) | Slug original del scraper (antes de `CORRECCION_TIENDAS` en load.py) |
| `activa` | BOOLEAN | Por defecto TRUE |
| `cadena` | VARCHAR(50) | Cadena comercial para la Comparativa (NULL = la tienda es su propia cadena) |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de tiendas

**`cadena`** se agregó el 26-oct-2026 (commit 3f6eb7b, fase 1 de la Comparativa v2, aprobada por la persona; `docs/bi/metricas.md` sección 8). Agrupa formatos de una misma empresa para que la Comparativa no cuente dos veces a la misma cadena: `soriana` = `soriana_hiper` + `soriana_mercado`, y `walmart` = `walmart` + `walmart_express`. Las otras 16 tiendas tienen `cadena` NULL; Bodega Aurrera y Sam's Club quedan como cadena propia por decisión de la persona. En `schema.sql` la columna se crea con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` y se llena con dos `UPDATE ... WHERE cadena IS NULL`, así que repetir el script no pisa un valor puesto a mano.

### folletos

Un folleto digital descargado de una fuente. La llave natural es `(fuente, folleto_id_fuente)`.

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | SERIAL PK | |
| `tienda_id` | FK → `tiendas` | |
| `folleto_id_fuente` | VARCHAR(30) | ID asignado por la fuente (Tiendeo/Ofertomat) |
| `fuente` | `fuente_enum` | |
| `titulo`, `url_origen` | VARCHAR(200), TEXT | Metadatos del scraper |
| `fecha_inicio`, `fecha_fin` | DATE | Vigencia. El COMMENT dice "NULL para Ofertomat, que no expone fecha de fin", pero hoy los 39 folletos de Ofertomat tienen `fecha_fin` |
| `total_paginas` | INTEGER | Páginas del folleto |
| `perfil_ocr` | VARCHAR(40) | Perfil de preprocesamiento: color_normal, color_suave, etc. |
| `motor_ocr` | VARCHAR(20) | Motor OCR usado: easyocr |
| `scrapeado_at` | TIMESTAMP | Momento de la descarga; `v_folletos_vigencia` lo usa para detectar fechas dudosas |
| `estado` | `estado_folleto_enum` | Por defecto `pending`; hoy los 821 están en `done` |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de folletos

Llaves: `uq_folleto_fuente_id UNIQUE (fuente, folleto_id_fuente)`. Índices: `ix_folleto_tienda_fecha (tienda_id, fecha_inicio)`, `ix_folleto_fuente`, `ix_folleto_estado`.

Las métricas de OCR del folleto (`total_paginas`, `perfil_ocr`, `motor_ocr`) se llenan desde el 9-oct-2026, cuando `load.py` empezó a leer `ocr_resultado.json`; antes quedaban vacías y `v_calidad_pipeline` no mostraba nada (Engram #124). Una recarga forzada conserva el `id` del folleto (hace `ON CONFLICT ... DO UPDATE`).

### paginas

Una fila por página de folleto, con las métricas de calidad de OCR y NLP de esa página.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | SERIAL PK | Cambia en cada recarga forzada (la página se borra y se vuelve a insertar) |
| `folleto_id` | FK → `folletos` ON DELETE CASCADE | |
| `numero_pagina` | INTEGER | |
| `archivo_imagen` | VARCHAR(100) | Nombre del archivo, por ejemplo `pagina_003.webp` |
| `total_bloques_ocr` | INTEGER | Bloques que leyó el OCR |
| `confianza_ocr_prom` | FLOAT | Confianza promedio del OCR en la página |
| `total_productos`, `total_precios`, `total_promos`, `total_atributos` | INTEGER | Conteos del NLP por categoría |
| `tasa_util` | FLOAT | Ratio entidades útiles / total bloques OCR (benchmark de calidad) |
| `procesado_at` | TIMESTAMP | |

Tabla: Columnas de paginas

Llave: `uq_pagina_folleto_num UNIQUE (folleto_id, numero_pagina)`. Al 26-oct-2026 hay 5,688 páginas, todas con confianza OCR; la confianza promedio es 0.674, la tasa útil promedio 0.626, y 4,366 páginas tienen al menos un precio.

### extracciones

Es la tabla principal: **un evento por bloque OCR clasificado** por el NLP. Cada fila guarda el texto original, su tipo, el valor numérico si lo tiene y la caja en la imagen, para que el dashboard pueda mostrar de dónde salió cada dato (visor de origen).

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | BIGSERIAL PK | Cambia en cada recarga forzada |
| `pagina_id` | FK → `paginas` ON DELETE CASCADE | |
| `folleto_id`, `tienda_id` | FK → `folletos`, `tiendas` | Desnormalizados para filtrar sin unir con `paginas` |
| `tipo` | `tipo_extraccion_enum` | Categoría del NLP |
| `texto_raw` | TEXT | Texto OCR original sin modificar |
| `texto_norm` | VARCHAR(300) | Nombre canónico (filas PRODUCTO/PRECIO) o texto limpio |
| `categoria_nlp` | VARCHAR(60) | Departamento del catálogo (alimentos, linea_blanca...) |
| `valor` | FLOAT | Precio actual en MXN o monto de ahorro |
| `valor_anterior` | FLOAT | Precio anterior ("Antes $X" / "DE $X A") de la misma columna, pegado arriba o abajo del precio, con descuento creíble (`load.emparejar_precios_anteriores`) |
| `texto_promo` | VARCHAR(300) | Existe en el esquema, pero hoy ninguna fila lo usa (0 filas con valor) |
| `confianza_ocr` | FLOAT | Score de confianza EasyOCR: 0.0 – 1.0 |
| `bbox_x`, `bbox_y`, `bbox_ancho`, `bbox_alto` | INTEGER | Caja del bloque en la imagen procesada |
| `producto_extraccion_id` | BIGINT, FK → `extracciones` | Fila PRODUCTO asociada por cercanía/ROI (self-FK). Solo aplica a PRECIO/ATRIBUTO |
| `producto_canonico_id` | FK → `productos_canonicos` | Identidad canónica deduplicada. NULL si se descartó por ruido |
| `confianza_norm` | FLOAT | Score 0.0–1.0 del match contra `productos_canonicos` (solo filas PRODUCTO) |
| `metodo_norm` | VARCHAR(20) | `exacto`, `fuzzy`, `fuzzy_bajo`, `heuristico` o `sin_match` (`nlp/normalizador.py`) |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de extracciones

Índices: `ix_ext_tipo`, `ix_ext_tienda_tipo (tienda_id, tipo)`, `ix_ext_folleto_pagina (folleto_id, pagina_id)`, `ix_ext_valor`, `ix_ext_confianza`, `ix_ext_producto_extraccion`, `ix_ext_producto_canonico` y `ix_ext_texto_norm_trgm` (GIN con `gin_trgm_ops`, para buscar nombres parecidos con errores de OCR).

**Qué tipos se guardan.** El enum tiene ocho valores, pero `load.py` solo inserta cinco. El precio anterior no se guarda como fila propia: se empareja con su PRECIO y queda en `valor_anterior`. Los ahorros y los descartes no se guardan.

| tipo | Filas | Con `producto_extraccion_id` | Con `metodo_norm` | Con `producto_canonico_id` |
|---|---|---|---|---|
| PRODUCTO | 188,471 | — | 188,471 | 188,471 |
| PRECIO | 28,420 | 28,172 | 28,172 | 28,172 |
| PROMO | 5,284 | 0 | 0 | 0 |
| ATRIBUTO | 720 | 681 | 0 | 0 |
| EVENTO_PROMO | 293 | 0 | 0 | 0 |
| **Total** | **223,188** | | | |

Tabla: Filas de extracciones por tipo | Fuente: consulta de solo lectura, 26-oct-2026

**PRECIO → PRODUCTO.** Desde la v3 del esquema (22-ago-2026, commit 685d16b), `load.py` inserta primero las filas PRODUCTO de la página y, al insertar cada PRECIO, guarda en `producto_extraccion_id` el `id` de la fila PRODUCTO que la asociación eligió (por cercanía o por región de la casilla). Antes solo se copiaba el texto del producto en el PRECIO y la fila del producto se perdía. El PRECIO conserva además una copia del nombre (`texto_norm`), su categoría (`categoria_nlp`) y su identidad canónica (`producto_canonico_id`), que es lo que leen las vistas sin tener que unir la tabla consigo misma. Los 248 PRECIO sin producto asociado tienen `texto_norm` NULL y quedan fuera de todas las vistas de precios.

Un ejemplo real (soriana_hiper, folleto 414181, página 2): el bloque "$2489" se guardó como PRECIO con `valor` 24.89, `texto_norm` "Naranja" y `metodo_norm` `exacto`, y su `producto_extraccion_id` apunta a la fila PRODUCTO cuyo `texto_raw` es "NARANJA". Para recorrer la relación:

```sql
SELECT pr.id, pr.texto_raw AS precio_ocr, pr.valor, pr.texto_norm, pr.metodo_norm,
       pd.texto_raw AS producto_ocr, pd.metodo_norm AS metodo_producto
FROM extracciones pr
JOIN extracciones pd ON pd.id = pr.producto_extraccion_id
WHERE pr.tipo = 'PRECIO'
LIMIT 20;
```

**`metodo_norm` en la fila PRECIO.** Desde el 25-oct-2026 (commit dfe3d51) la fila PRECIO también guarda el método con que se normalizó el nombre que muestra (`metodo_nombre()` en `load/load.py`). Antes la columna existía pero en PRECIO siempre quedaba NULL, y el KPI "% catálogo" leía el método de la fila PRODUCTO. Eso dejó de servir cuando load empezó a unir nombres: si une el nombre con una unidad suelta o con otra línea de la pila, el nombre que muestra el PRECIO ya no es el de su fila PRODUCTO ("Pechuga de pollo", `exacto`, queda "Filete de Pechuga de Pollo", `heuristico`). Las consultas del KPI usan `COALESCE(e.metodo_norm, p.metodo_norm)` para seguir funcionando con cargas anteriores. Con la recarga de ese día las filas PRECIO con `metodo_norm` pasaron de 0 a 28,209 y el "% catálogo" de 15.1% a 7.5% (Engram #262). Distribución al 26-oct-2026:

| metodo_norm | PRODUCTO | PRECIO |
|---|---|---|
| `heuristico` | 168,115 | 26,095 |
| `fuzzy` | 10,370 | 896 |
| `exacto` | 8,062 | 1,096 |
| `fuzzy_bajo` | 1,924 | 85 |

Tabla: Método de normalización por tipo de fila | Fuente: consulta de solo lectura, 26-oct-2026

`sin_match` no aparece porque el normalizador descarta esos textos antes de insertarlos.

### productos_canonicos

Catálogo deduplicado de identidades de producto, creado en la v3 (22-ago-2026). La semilla es `CATALOGO_CANONICO` de `nlp/normalizador.py`, pero también entran los nombres sin coincidencia con `metodo_norm = 'heuristico'`: así el catálogo crece con el uso y esas filas se pueden filtrar y auditar, en vez de perderse como texto suelto.

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | SERIAL PK | |
| `nombre_canonico` | VARCHAR(150) UNIQUE | Nombre normalizado; es la llave del upsert |
| `categoria` | VARCHAR(60) | Departamento amplio (`catalogo_productos.py`): alimentos, linea_blanca, etc. |
| `marca` | VARCHAR(80) | |
| `aliases` | TEXT[] | Variantes de texto OCR ya vistas para este producto (crece con el tiempo) |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de productos_canonicos

Índices: `ix_prodcanon_categoria` e `ix_prodcanon_nombre_trgm` (GIN trigramas). `load.py` hace `INSERT ... ON CONFLICT (nombre_canonico) DO UPDATE`: llena `categoria` y `marca` solo si estaban vacías y agrega el alias si es nuevo.

Al 26-oct-2026 hay 91,224 filas: 21,355 con categoría, 5,898 con marca y 104 con algún alias. **16,973 no las usa ninguna extracción**: la recarga forzada borra páginas y extracciones, pero nunca esta tabla, así que conserva los nombres de cargas anteriores (ver Limitaciones).

### eventos_promo

Campañas comerciales detectadas en un folleto (Julio Regalado, Hot Sale, Buen Fin...). Una fila por par (folleto, campaña).

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | SERIAL PK | |
| `folleto_id`, `tienda_id` | FK → `folletos`, `tiendas` | |
| `nombre_evento` | VARCHAR(100) | Slug normalizado: julio_regalado, hot_sale, buen_fin, etc. (`slug_evento` del NLP) |
| `texto_raw` | VARCHAR(200) | Texto del folleto que lo detectó |
| `fecha_inicio`, `fecha_fin` | DATE | Copiadas de la vigencia del folleto al insertar |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de eventos_promo

Llave: `uq_evento_folleto UNIQUE (folleto_id, nombre_evento)`. Índices: `ix_evento_nombre`, `ix_evento_tienda`, `ix_evento_fechas`.

Las fechas se copian del folleto desde el 16-oct-2026 (commit 85e9e95, `_upsert_evento_promo` en `load/load.py`); antes quedaban NULL y `v_eventos_activos` daba todas las campañas por vigentes. Al 26-oct-2026 hay 132 eventos en 121 folletos, todos con fechas, repartidos en 9 slugs: `halloween_dia_de_muertos` 35, `aniversario` 24, `ofertones` 22, `regreso_a_clases` 14, `julio_regalado` 13, `navidad` 9, `fiestas_patrias` 8, `hot_sale` 4 y `liquidacion` 3. Las 293 filas EVENTO_PROMO de `extracciones` son los bloques individuales; `eventos_promo` es el resumen por folleto.

### errores_carga

Registro de fallas al cargar un folleto o una página desde `nlp_resultado.json`. Se creó el 8-oct-2026 (commit 9010a75): antes los errores solo quedaban en `logs/load.log`, y un error SQL en una página revertía el folleto completo sin marcarlo como fallido. Hoy cada página va en su propio SAVEPOINT y, si falla, se registra aquí sin perder las demás.

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | BIGSERIAL PK | |
| `corrida_at` | TIMESTAMP | Inicio de la corrida (batch o carga individual) que produjo el error |
| `fuente` | VARCHAR(20) | VARCHAR y no `fuente_enum`: registrar el error nunca debe fallar por el valor de la fuente |
| `tienda_slug`, `folleto_id_fuente` | VARCHAR | Identifican el folleto sin llave foránea |
| `pagina` | VARCHAR(100) | Archivo de la página; NULL = el error afectó al folleto completo |
| `categoria` | `categoria_error_enum` | Se clasifica por el SQLSTATE, no por el texto del mensaje |
| `sqlstate` | CHAR(5) | Código de error PostgreSQL; NULL si el error no vino de la BD |
| `mensaje`, `detalle` | TEXT | Mensaje y diagnóstico extra (detail/context) o tipo de excepción Python |
| `ruta_archivo` | TEXT | JSON que se estaba cargando |
| `resuelto`, `resuelto_at` | BOOLEAN, TIMESTAMP | TRUE cuando una carga posterior del mismo folleto terminó sin error a nivel folleto |
| `created_at` | TIMESTAMP | |

Tabla: Columnas de errores_carga

**No tiene llave foránea a `folletos` a propósito**: si falla el folleto completo, no existe su fila en `folletos`. El dashboard la une por `tienda_slug` o por `(fuente, folleto_id_fuente)`. Índices: `ix_error_folleto (fuente, folleto_id_fuente)` e `ix_error_abiertos (categoria) WHERE NOT resuelto`. Al 26-oct-2026 tiene 13 filas, todas `tamano_excesivo` del 8-oct-2026 y todas resueltas; ninguna recarga posterior ha registrado errores. La consulta la página Errores de carga del dashboard (`/errores`).

### alertas

Tabla pensada para una capa futura de monitoreo de precios por producto y tienda.

| Columna | Tipo | Descripción (COMMENT) |
|---|---|---|
| `id` | SERIAL PK | |
| `tienda_id` | FK → `tiendas`, opcional | NULL = aplica a todas las tiendas |
| `slug_producto` | VARCHAR(200) | Slug del nombre canónico del producto a monitorear |
| `umbral_precio` | FLOAT | |
| `activa` | BOOLEAN | |
| `disparada_at`, `created_at` | TIMESTAMP | |

Tabla: Columnas de alertas

Índices: `ix_alerta_tienda_prod (tienda_id, slug_producto)` e `ix_alerta_activa`. **Hoy no se usa**: tiene 0 filas y ningún código la llena ni la lee (solo existe su modelo en `dashboard/models.py`). Se conserva porque viene de la propuesta original.

## Vistas y función

Las vistas resumen `extracciones` para el dashboard. Todas son `CREATE OR REPLACE VIEW` y los modelos de Django las leen con `managed = False`. Las que el ORM usa como modelo traen una columna `id` (agregada el 23-ago-2026) porque Django exige una llave primaria.

| Vista | Qué devuelve | Filtro base | Quién la usa en el dashboard |
|---|---|---|---|
| `v_precios_actuales` | Una fila por PRECIO con tienda, producto, categoría, precio, precio anterior, `descuento_pct` y vigencia del folleto | `tipo='PRECIO'`, `valor` y `texto_norm` no nulos | Resumen (KPIs y top de categorías), Precios (`/precios`), filtros de categoría y folleto |
| `v_comparativa_precios` | Rango de precios (mín., máx., promedio, diferencia) por `(texto_norm, categoria_nlp)` en 2 o más tiendas | Igual que la anterior, agrupada | Comparativa (`/comparativa`) |
| `v_comparativa_precios_v2` | Comparativa por clave flexible en 2 o más cadenas, con mediana y bandera de precio sospechoso | Además `valor` entre 1 y 100,000 | Ninguna página todavía (fase 3 por aprobar) |
| `v_historico_precios` | Precio por producto, tienda y fecha de inicio del folleto | Además `fecha_inicio` no nula | Histórico (`/historico`) y sugerencias de producto |
| `v_calidad_pipeline` | Métricas de OCR/NLP por folleto (páginas, productos, precios, confianza, tasa útil, perfil y motor OCR) | Todos los folletos | Calidad (`/calidad`) |
| `v_folletos_vigencia` | Una fila por folleto con `anomalia_fecha`, `vigente`, `vigente_dudoso` y `proximo` | Todos los folletos | Resumen (folletos vigentes), Cobertura (`/cobertura`), Promociones (`/promociones`) |
| `v_eventos_activos` | Campañas con `fecha_fin` vacía o futura y su número de precios | — | Ninguna desde el 15-oct-2026 (existe su modelo `VEventosActivos`) |

Tabla: Vistas de load/vistas.sql y su uso (dashboard/queries.py y dashboard/views.py)

### v_precios_actuales

A pesar del nombre, **no filtra por vigencia**: devuelve todos los precios cargados. El COMMENT de la vista indica filtrar con `WHERE vigencia_hasta >= CURRENT_DATE` para obtener solo los activos. `descuento_pct` solo se calcula si el precio anterior es mayor que el actual:

```sql
ROUND(((valor_anterior - valor) / valor_anterior * 100)::NUMERIC, 1)
```

Su conteo es la cifra "registros del dashboard": 28,172 al 26-oct-2026 (los 28,420 PRECIO menos los 248 sin producto).

### v_comparativa_precios y v_comparativa_precios_v2

La v1 agrupa por el texto exacto del producto, así que "Cebolla Blanca 1 Kg" y "Cebolla blanca 1kg" quedan en grupos distintos y una misma cadena con dos formatos (Soriana Hiper y Soriana Mercado) cuenta como dos tiendas. La v2 (26-oct-2026, commit 3f6eb7b, fase 1 aprobada por la persona) corrige las dos cosas:

- **Agrupa por `clave_comparativa(texto_norm)`**, una función SQL `IMMUTABLE` que pasa el texto a minúsculas, quita acentos y puntuación, unifica unidades (1 Kg = 1kg = 1 kilo; medio kilo = 500 g; piezas = pza), quita palabras de relleno ("de", "con", "precio", "oferta"...) y ordena las palabras únicas. Devuelve NULL si el texto es un genérico del catálogo ("Refresco", "Galletas", "Smart TV"...) o si tiene menos de dos palabras de contenido, salvo una fruta o verdura sola.
- **Cuenta cadenas**, no tiendas: `COALESCE(t.cadena, t.slug)`, y exige al menos dos.
- Usa la **mediana** por cadena y marca `precio_sospechoso` cuando la mediana más alta es más de 10 veces la más baja (`ratio_medianas_cadena > 10`), señal de un precio mal leído.

| Texto | `clave_comparativa` |
|---|---|
| Cebolla Blanca 1 Kg | `1kg blanca cebolla` |
| Medio kilo de Jamón de Pavo | `500g jamon pavo` |
| Pepino | `pepino` |
| Refresco | NULL (genérico) |

Tabla: Ejemplos de clave_comparativa (consulta de solo lectura, 26-oct-2026)

| Vista | Grupos | Registros | Otros |
|---|---|---|---|
| `v_comparativa_precios` | 489 | 4,808 | — |
| `v_comparativa_precios_v2` | 131 | 1,293 | 21 con precio sospechoso |

Tabla: Tamaño de las dos comparativas al 26-oct-2026 | Fuente: consulta de solo lectura; coincide con Engram #276 y #277

El panel `/comparativa` sigue sobre la v1. Cambiarlo a la v2 es la fase 3 y está pendiente de aprobación. La función y la vista salen de `docs/bi/consultas/comparativa_clave_flexible_propuesta.sql`, que genera `tests/_herramienta_bi_claves_comparativa.py`; si cambia el catálogo de genéricos, hay que regenerarla ahí y copiarla a `vistas.sql`.

### v_folletos_vigencia

Es la **única definición de "vigente"** del dashboard. No corrige fechas, solo las etiqueta en `anomalia_fecha`, en este orden de precedencia:

| Etiqueta | Condición | Ejemplo citado en vistas.sql |
|---|---|---|
| `sin_fecha` | `fecha_inicio` o `fecha_fin` NULL | |
| `fin_antes_inicio` | `fecha_fin < fecha_inicio` | |
| `inicio_antiguo` | `fecha_inicio < scrapeado_at - 365 días` | soriana_hiper 430896, 2022-09-01 |
| `inicio_futuro_vs_scrapeo` | `fecha_inicio > scrapeado_at + 30 días` | waldos con inicio 25-dic scrapeado en octubre |
| `vigencia_larga` | `fecha_fin - fecha_inicio > 120 días` | bodega_aurrera "todo el año" |

Tabla: Etiquetas de fecha dudosa de v_folletos_vigencia

Con eso: `vigente` = sin etiqueta y hoy dentro del rango; `vigente_dudoso` = con etiqueta y dentro del rango (se muestra aparte); `proximo` = sin etiqueta e inicio futuro. Al 26-oct-2026 hay 821 folletos: 71 vigentes, 18 vigentes dudosos, 3 próximos y 25 con alguna etiqueta. Como depende de `CURRENT_DATE`, estas cifras cambian cada día. `dashboard/queries.py` replica los umbrales (`DIAS_INICIO_ANTIGUO = 365`, `DIAS_INICIO_FUTURO = 30`, `DIAS_VIGENCIA_LARGA = 120`) solo para mostrarlos, y `tests/test_umbrales_vigencia.py` verifica que coincidan con la vista.

### v_historico_precios, v_calidad_pipeline y v_eventos_activos

- `v_historico_precios` usa la `fecha_inicio` del folleto como fecha del precio y está ordenada por producto, tienda y fecha. Al 26-oct-2026 tiene 28,172 filas.
- `v_calidad_pipeline` une `folletos` con `paginas` (LEFT JOIN) y promedia confianza y tasa útil por folleto: 821 filas, una por folleto.
- `v_eventos_activos` agrupa `eventos_promo` por campaña y tienda; su `id` es `MIN(ep.id)` porque meter `ep.id` en el GROUP BY rompía la agregación (de unas 44 filas pasó a 131). La página Promociones dejó de usarla el 15-oct-2026 porque juntaba folletos y contaba cada precio una vez por evento; ahora lee `eventos_promo` directo (`dashboard/promociones.py`). Hoy devuelve 17 filas.

## Cómo crear la base de datos

1. **Instalar PostgreSQL** (la base actual corre en la versión 18.4) y crear el usuario y la base. Por ejemplo, desde pgAdmin o como superusuario:

```sql
CREATE USER pricescraper_user WITH PASSWORD '<clave>';
CREATE DATABASE pricescraper OWNER pricescraper_user;
-- PostgreSQL 15+: el esquema public ya no da permisos por defecto (README del repo)
GRANT ALL ON SCHEMA public TO pricescraper_user;
```

2. **Crear `.env` en la raíz del repo** (está en `.gitignore`; nunca se sube):

```
DATABASE_URL=postgresql://usuario:clave@localhost:5432/pricescraper
DATABASE_URL_RO=postgresql://usuario_ro:clave@localhost:5432/pricescraper   # opcional, rol de solo lectura
```

`DATABASE_URL` la leen `load/db_builder.py` (con `python-dotenv`) y `priceScraper_web/settings.py`. `DATABASE_URL_RO` solo la usa `.claude/skills/consulta-analitica/consulta.py`, la herramienta de consultas de solo lectura de los agentes (rol `pricescraper_ro`, solo SELECT). Este documento no verificó los permisos del rol de solo lectura, solo que funciona para consultar.

3. **Crear las tablas.** No hace falta correr `schema.sql` a mano: `load.db_builder.get_connection()` revisa si existen las 8 tablas de `_TABLAS_REQUERIDAS` y, si falta alguna, ejecuta `load/schema.sql` completo. Pasa la primera vez que se corre `probar_load.py`, que además hace un chequeo de conexión (`verificar_conexion`) antes de abrir el menú. El script es idempotente (`IF NOT EXISTS` y bloques `DO ... EXCEPTION`).

4. **Crear las vistas.** `db_builder.py` **no** aplica `vistas.sql`. Hay que ejecutarlo aparte, después de `schema.sql` (la v2 de la Comparativa necesita `tiendas.cadena`): en el Query Tool de pgAdmin, que es como lo indica el README, o con `psql -U <usuario> -d pricescraper -f load/vistas.sql`.

5. **Crear las tablas de Django** con `venv/Scripts/python.exe manage.py migrate` (auth, sesiones, admin). No toca las tablas del pipeline.

Para ver cuántas filas tiene cada tabla del pipeline, `probar_load.py` opción 4 ("Ver estado de la BD") usa `resumen_bd()`.

### Cambios al esquema en una base existente

`get_connection()` solo ejecuta `schema.sql` cuando falta una tabla completa. **Una columna nueva no se aplica sola**: por eso `schema.sql` agrega las columnas posteriores con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (las de la v3 de `extracciones` y `tiendas.cadena`), y en una base que ya existe hay que ejecutar ese fragmento a mano. La fase 1 de la Comparativa, por ejemplo, se aplicó con un script de psycopg aparte (Engram #277). En el proyecto, `schema.sql` y `vistas.sql` están protegidos para los agentes de Claude (`.claude/hooks/guardia_agente.py`): solo pueden proponer cambios, y los aplica la persona.

## Recargas y respaldos

Cada vez que cambia una regla del NLP o de la asociación en load, se reprocesa el NLP de todos los folletos y se recarga la base. Una **recarga forzada** es `probar_load.py` opción 3, o `Loader.cargar_batch(forzar=True)`. Por cada folleto, en una sola transacción:

1. hace upsert del folleto (conserva su `id` y actualiza sus metadatos);
2. borra sus `eventos_promo` y sus `paginas`, y el `ON DELETE CASCADE` borra sus `extracciones`;
3. vuelve a insertar páginas, extracciones y eventos, con un SAVEPOINT por página.

Si la carga del folleto falla, el rollback deshace también el borrado. Los `id` de `paginas` y `extracciones` cambian en cada recarga (los enlaces del visor de origen del dashboard dejan de servir); `tiendas`, `folletos` y `productos_canonicos` conservan los suyos.

### Procedimiento

El procedimiento que se siguió en las recargas del 23 al 25-oct-2026 (Engram #243, #255, #262, #267 y #276) tiene cuatro pasos:

1. **Verificar el antes.** Guardar en un JSON una foto de los conteos clave.
2. **Respaldar.** `pg_dump` en formato personalizado de la base completa, y un `.tar.gz` de los `nlp_resultado.json` que se van a reemplazar. Hay que confirmar que el `.dump` se puede leer con `pg_restore --list`.
3. **Reprocesar y recargar.** NLP de los 821 folletos y luego la carga forzada, revisando que ambos terminen con 0 errores.
4. **Verificar el después** con los mismos conteos y comparar contra lo que el especialista y QA predijeron. Si algo no cuadra, se restaura el respaldo.

```bash
# Respaldo (la URL sale de .env; no la escribas en la terminal ni en un script versionado)
pg_dump --format=custom --file=../respaldo_antes_reproceso_nlp_AAAAMMDD_HHMM.dump "<DATABASE_URL>"
pg_restore --list ../respaldo_antes_reproceso_nlp_AAAAMMDD_HHMM.dump > /dev/null   # ¿se puede leer?

# Restaurar, solo si la recarga salió mal (borra y recrea los objetos del respaldo)
pg_restore --clean --if-exists --dbname="<DATABASE_URL>" ../respaldo_antes_reproceso_nlp_AAAAMMDD_HHMM.dump
```

El script que automatizó esos pasos (`recarga_20261025.py`, Engram #262) quedó en un directorio temporal de esa sesión y **no está en el repo**; los comandos de arriba son el formato general, no una copia de ese script. La restauración no se ha documentado como probada.

Conteos que se comparan antes y después (todos de solo lectura):

```sql
SELECT
  (SELECT COUNT(*) FROM extracciones)                                      AS extracciones,
  (SELECT COUNT(*) FROM extracciones WHERE tipo = 'PRECIO')                AS precios,
  (SELECT COUNT(*) FROM v_precios_actuales)                                AS registros_dashboard,
  (SELECT COUNT(*) FROM extracciones WHERE tipo = 'PRECIO' AND metodo_norm IS NOT NULL) AS precio_con_metodo,
  (SELECT COUNT(*) FROM extracciones WHERE tipo = 'PRECIO' AND valor >= 1000)           AS precios_mil_o_mas,
  (SELECT COUNT(*) FROM v_comparativa_precios)                             AS grupos_comparativa,
  (SELECT COUNT(*) FROM eventos_promo)                                     AS eventos,
  (SELECT COUNT(*) FROM errores_carga WHERE NOT resuelto)                  AS errores_abiertos;
```

### Dónde quedan los respaldos

Los respaldos son **solo locales** y no van a git:

- Desde el 16-oct-2026, en la carpeta padre del repo (`PRICE_SCRAPER_SS/`): `respaldo_antes_reproceso_nlp_AAAAMMDD_HHMM.dump` y `respaldo_nlp_resultado_AAAAMMDD_HHMM.tar.gz`. Hay 6 pares, del 16 al 25-oct-2026; el más reciente es `..._20261025_2258`.
- Antes, en `data/backups_bd/` (`data/` está en `.gitignore`): `pricescraper_pre_recarga_<commit>_<fecha>.dump`, `pricescraper_pre_v3_20260822_150301.dump` y los zip del NLP.

No hay copia fuera de esta computadora; si se pierde el disco, se pierden los respaldos.

### Recargas recientes

| Fecha | Commit | Extracciones | PRECIO | v_precios_actuales | Observación |
|---|---|---|---|---|---|
| 24-oct-2026 | 43e4040 | 223,207 | 28,441 | — | Filtro de precios sin "$" y fusión de centavos (#255) |
| 25-oct-2026 (1a) | ff7aaed | 223,207 | 28,441 | 28,209 | `metodo_norm` en PRECIO: 0 → 28,209 (#262) |
| 25-oct-2026 (2a) | 798a35f | 223,752 | 28,984 | 28,735 | "$" suelto y regla A-escala (#267) |
| 25-oct-2026 (3a) | 32001ee | 223,188 | 28,420 | 28,172 | Centavos pegados y consumidos (#276) |

Tabla: Recargas forzadas del 24 y 25-oct-2026 | Fuente: Engram #255, #262, #267 y #276

Todas terminaron con 821 folletos, 0 errores y 132 eventos. El 26-oct-2026 no hubo recarga: solo se aplicó la fase 1 de la Comparativa (columna `cadena`, función y vista v2), que no toca `extracciones`.

## Conteos actuales

| Tabla o vista | Filas |
|---|---|
| `tiendas` | 20 (4 con `cadena`) |
| `folletos` | 821 (782 tiendeo, 39 ofertomat) |
| `paginas` | 5,688 |
| `extracciones` | 223,188 |
| `productos_canonicos` | 91,224 |
| `eventos_promo` | 132 |
| `errores_carga` | 13 (0 abiertos) |
| `alertas` | 0 |
| `v_precios_actuales` / `v_historico_precios` | 28,172 |
| `v_comparativa_precios` | 489 grupos, 4,808 registros |
| `v_comparativa_precios_v2` | 131 grupos, 1,293 registros |
| `v_calidad_pipeline` | 821 |
| `v_folletos_vigencia` | 821 (71 vigentes, 18 dudosos, 3 próximos) |
| `v_eventos_activos` | 17 |

Tabla: Conteos de la base al 26-oct-2026, 10:47 | Fuente: consulta de solo lectura con consulta.py; extracciones y comparativas coinciden con Engram #276 y #277

## Limitaciones conocidas y pendientes

- **Diagrama desactualizado.** A `load/diagrama_ER_V3.svg` le faltan `errores_carga` y `tiendas.cadena`, y hay que exportarlo a PNG para el borrador de Word.
- **`productos_canonicos` acumula filas.** La recarga no la limpia: 16,973 de las 91,224 filas no las usa ninguna extracción. No afecta a las vistas, pero infla el catálogo. La limpieza no se ha decidido.
- **Tiendas nuevas sin cadena.** El `UPDATE` de `cadena` solo corre con `schema.sql`; si load crea una tienda nueva de una cadena existente, hay que asignarle `cadena` a mano (Engram #277).
- **`db_builder.py` no aplica columnas nuevas ni vistas** en una base existente; hay que hacerlo a mano (sección "Cambios al esquema").
- **`v_precios_actuales` no filtra vigencia** aunque su nombre lo sugiera.
- **Comparativa v2 fuera del panel.** Faltan la fase 2 (calcular la clave en load con el catálogo de Python) y la fase 3 (panel `/comparativa` sobre la v2); ambas por aprobar. Dentro de los grupos aún hay máximos atípicos (Chile serrano $12,495, Lechuga $990), probablemente precios "$ddd" mal leídos (Engram #277).
- **Columnas y objetos sin uso:** `alertas` (0 filas), `extracciones.texto_promo` (siempre NULL), los valores `PRECIO_ANTERIOR`, `AHORRO` y `DESCARTE` del enum (no se guardan como filas) y `v_eventos_activos` (ningún panel la lee). El comentario de `dashboard/queries.py` que dice que esta vista "no tiene fechas (todas NULL)" ya no es cierto: desde el 16-oct los eventos tienen fechas.
- **COMMENT desactualizado:** `folletos.fecha_fin` dice "NULL para Ofertomat", pero hoy todos los folletos de Ofertomat tienen fecha de fin.
- **Respaldos solo locales**, sin copia externa.

## Cambios respecto a la propuesta original

La propuesta (`Propuesta_PriceScraper_SS.docx`, Capítulo 3, "Modelo de Base de Datos") describía cinco tablas: `tiendas`, `folletos`, `productos`, `precios` (tabla principal, un registro inmutable por precio) y `alertas`. El esquema real conserva la idea de un histórico que solo crece con cada carga, pero cambió su estructura:

| Propuesta | Esquema actual | Por qué cambió |
|---|---|---|
| `precios`: un registro por precio con `producto_id`, `precio`, `precio_promo`, `texto_promo`, `pagina` y `bbox` JSON | `extracciones`: un evento por bloque OCR clasificado (PRODUCTO, PRECIO, PROMO, ATRIBUTO, EVENTO_PROMO), con la caja en cuatro columnas enteras | El NLP clasifica bloques sueltos y la asociación producto-precio se sigue corrigiendo. Guardar cada bloque permite auditar de dónde salió cada dato (visor de origen) y recalcular sin volver a leer las imágenes |
| `productos` con `nombre_raw`, `nombre_limpio` y `hash_nombre` MD5 | Filas PRODUCTO en `extracciones` + `productos_canonicos` (nombre único, categoría, marca, aliases) + `metodo_norm` | Un hash del nombre no une variantes del OCR ("Cebolla Blanca" / "CEBOLLA BLANCA 1KG"); el normalizador con coincidencia exacta o aproximada sí, y deja constancia de cómo se decidió (v3, 22-ago-2026) |
| Página como número dentro de `precios` | Tabla `paginas` con métricas de OCR y NLP | Para medir la calidad del pipeline por página y por folleto (`v_calidad_pipeline`) |
| `precio_promo` | `valor_anterior` emparejado geométricamente; promociones como filas PROMO | El folleto imprime "Antes $X / Ahora $Y"; lo que el OCR encuentra es el precio anterior, no un precio con promoción aplicada |
| — | `eventos_promo` | Las campañas (Julio Regalado, Buen Fin) resultaron útiles para el BI |
| — | `errores_carga` (8-oct-2026) | Un error en una página revertía el folleto completo sin dejar rastro |
| `tiendas` (id, nombre, slug, activa) | Además `fuente_slug` y `cadena` | Los slugs del scraper se corrigen en load; la Comparativa necesita agrupar formatos de la misma cadena |
| `folletos.paginas` | `total_paginas`, `perfil_ocr`, `motor_ocr` y `folleto_id_fuente` con llave única por fuente | Reproducibilidad del OCR y evitar duplicados al recargar |
| `alertas` por `producto_id` | `alertas` por `slug_producto` y `tienda_id` opcional; sin uso | Se conserva para una capa futura |
| Tipos DECIMAL(10,2) y DATETIME | FLOAT y TIMESTAMP de PostgreSQL | El proyecto pasó de SQLite a PostgreSQL el 27-jun-2026 (commit 7515099) |
| Consultas directas sobre las tablas | 7 vistas y la función `clave_comparativa` | El dashboard lee vistas con una sola definición de cada métrica (por ejemplo, la vigencia) |

Tabla: Modelo de la propuesta contra el esquema actual

## Historial

- **Jun-2026:** primer esquema en SQLite; se cambió a PostgreSQL con psycopg 3 (commit 7515099, 27-jun-2026). El modelo de esa época está en `sources/modelado_bd/modelado_bd_v1.docx` y `load/diagrama_ER_V1.svg` (histórico).
- **22/23-ago-2026, v3** (commit 685d16b): `extracciones` guarda también PRODUCTO y ATRIBUTO, con `producto_extraccion_id`, `producto_canonico_id`, `confianza_norm` y `metodo_norm`; nace `productos_canonicos`; las vistas reciben `id` para Django. Respaldo previo: `data/backups_bd/pricescraper_pre_v3_20260822_150301.dump`. Documentado en `sources/modelado_bd/modelado_bd_v3.docx` y `schema_v3.dbml`.
- **8/9-oct-2026:** `errores_carga`, SAVEPOINT por página y modo reemplazar (commit 9010a75); se llenan las métricas de OCR de `folletos` y `paginas` (Engram #124).
- **11-oct-2026:** `valor_anterior` emparejado geométricamente (commit 7819d24).
- **12-oct-2026:** `v_folletos_vigencia` como definición única de vigencia (commit 128b7d9).
- **16-oct-2026:** los eventos usan slug canónico y copian la vigencia del folleto (commit 85e9e95).
- **25-oct-2026:** `metodo_norm` en la fila PRECIO (commit dfe3d51).
- **26-oct-2026:** `tiendas.cadena`, `clave_comparativa()` y `v_comparativa_precios_v2` (commit 3f6eb7b).

La historia completa está en `git log -- load/schema.sql load/vistas.sql` y en Engram (proyecto `pricescraper_ss`, temas `proyecto/reproceso-nlp-recarga-*` y `bi/comparativa-fase1-aplicada`).
