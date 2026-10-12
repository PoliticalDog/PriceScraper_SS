# Catalogo de metricas BI - PriceScraper MX

Estado de cada metrica: **propuesta** (definida y validada contra la BD, no construida en el dashboard),
**aprobada** (la persona la acepto) o **publicada** (visible en el dashboard).

Convenciones comunes:

- **Registro del dashboard**: fila de `extracciones` con `tipo='PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL`
  (= `v_precios_actuales`). 28,634 al 12-oct-2026.
- **Producto de catalogo**: `metodo_norm IN ('exacto','fuzzy','fuzzy_bajo')` en la fila PRODUCTO a la que apunta el
  PRECIO (`producto_extraccion_id`). `heuristico` = texto del folleto tal cual. En la fila PRECIO `metodo_norm` siempre
  es NULL.
- **Categoria vacia**: `categoria_nlp = ''` o NULL (hoy todas las vacias son `''`).
- **Corrida del evaluador vigente**: el JSON mas reciente de `data/processed/_eval/runs/*_dev.json` con
  `meta.split='dev'`, `meta.codigo.cambios_sin_commit=false` e `integridad.valida=true`. Mide solo los folletos de dev
  con ground truth (56 folletos en el split, 16 tiendas; 158 paginas y 14 tiendas con articulos con precio en la corrida
  20261012_141917_e4184da). **No mide produccion completa**: es una muestra por tienda.

---

## 1. Confiabilidad del dato por tienda

| Campo | Valor |
|---|---|
| Estado | **propuesta** (12-oct-2026, agente BI) |
| Pregunta | Para cada tienda, que tan confiable es lo que el dashboard muestra como "precio de un producto"? |
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
| Estado | **propuesta** (12-oct-2026, agente BI) |
| Pregunta | De que tiendas tenemos folletos vigentes hoy, que tan reciente es lo ultimo capturado y cuanto dato de precio hay detras? |
| Grano | Tienda (tabla) y semana ISO x tienda (serie temporal) |
| Fuente | `folletos`, `paginas`, `extracciones`, `tiendas`, `errores_carga` (por `tienda_slug`, sin FK) |
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
Filtros: tienda; fecha de corte ("hoy", por defecto `CURRENT_DATE`); rango de semanas en la serie. Categoria no aplica.
Confiabilidad: conteos exactos sobre fechas declaradas por la fuente (Tiendeo/Ofertomat); la serie semanal refleja
tambien la cadencia de scrapeo (semanas sin scrapeo se ven como caidas, p. ej. semana del 7-sep: 10 folletos de 1 tienda).
