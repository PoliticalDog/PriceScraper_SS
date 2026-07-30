# Benchmark hibrido ROI vs distancia para asociacion producto-precio (jul 2026)

Continua `05_benchmark_roi_deteccion_regiones.md`. Responde la pregunta que
quedo abierta ahi: dado que ROI detecta regiones confiables sobre todo en
tiendas con layout de grid, ¿usarlo como señal *adicional* (con fallback al
metodo actual de distancia bbox) mejora la asociacion producto-precio real en
esas tiendas?

## Metodologia

`probar_hibrido_roi.py`: para cada precio de un folleto ya procesado, compara
dos metodos --
- **Distancia** (actual, `load/load.py::_asociar_producto`, replicado exacto): producto mas cercano arriba del precio, dentro de una banda de 400px en x.
- **Hibrido**: si el precio cae dentro de una region ROI confiable que tambien contiene un producto, se usa ese producto (misma "caja visual" que el precio). Si no, fallback identico al metodo de distancia.

No vuelve a correr OCR: reutiliza `nlp_resultado.json` ya generado por el
pipeline de produccion (productos/precios con bbox) y solo corre deteccion de
regiones (OpenCV, sin GPU) sobre la imagen original.

Alcance: las 4 tiendas grid-friendly con carpeta procesada disponible --
walmart, chedraui, soriana_hiper, soriana_mercado (2880 precios, ver
`05_benchmark_roi_deteccion_regiones.md` para por que se excluyen merco y
soriana_híper).

## Primera corrida: 22.2% via ROI, pero con un modo de falla nuevo

| Metrica | Valor |
|---|---|
| Precios evaluados | 2880 |
| Resueltos via ROI directo | 640 (22.2%) |
| Sin producto -- distancia | 120 (4.2%) |
| Sin producto -- hibrido | 95 (3.3%) |
| Desacuerdos (producto distinto) | 260 (9.0%) |
| Mejora (hibrido encontro, distancia no) | 25 (0.9%) |
| Regresion (distancia encontro, hibrido no) | 0 (0.0%, garantizado por diseño del fallback) |

Revision manual de 16 desacuerdos (imagenes con recuadros de comparacion,
`data/processed/_v7_hibrido_roi_asociacion/muestra_desacuerdos/`):

- **ROI gana claramente** cuando el precio y su producto estan en la misma
  caja visual pero el producto mas cercano por distancia esta en una caja
  vecina de arriba (ej. Soriana Hiper: precio de "Costilla de res" -- distancia
  agarraba "Melón chino" de la caja de arriba; Chedraui: precio de un
  refrigerador LG -- distancia agarraba "GARANTIA" de un refrigerador
  distinto listado arriba).
- **ROI tambien fallaba** cuando `detectar_regiones()` fusionaba 2+ cajas
  vecinas en una sola region (fondo continuo entre ellas, ej. banners de
  precio repetidos en Walmart, columnas de producto muy pegadas en Soriana
  Mercado) -- en esos casos, ROI a veces elegia el producto de la caja
  vecina equivocada dentro de la region fusionada.
- Un tercer patron, no atribuible a ninguno de los dos metodos: el producto
  real nunca fue clasificado como "PRODUCTO" por el NLP (ambos metodos
  agarran texto de badges MSI o specs tecnicas en su lugar) -- limite de la
  etapa de clasificacion, no de la asociacion.

## Ajuste a region_detector.py

Dos filtros nuevos, aditivos (no se toco el heuristico de calidad por region
ya validado):

1. **`PROPORCION_MAX = 3.0`** en `detectar_regiones()`: descarta candidatas
   cuya proporcion (lado largo/lado corto) exceda el umbral -- una fila de 2+
   celdas fusionadas por falta de borde entre ellas es notablemente mas
   ancha/alta que una celda real.
2. **`DISPERSION_MAX_FRACCION = 0.5`** en `asociar_producto_por_region()`: si
   los productos candidatos dentro de una region confiable estan dispersos
   horizontalmente mas de esta fraccion del ancho de la region (señal de que
   la region agrupa mas de una celda aunque haya pasado el filtro de
   proporcion), no se asocia por ROI -- fallback a distancia en vez de
   arriesgar el vecino equivocado.

## Segunda corrida (post-ajuste): mas conservador, menos desacuerdos

| Metrica | Antes | Despues |
|---|---:|---:|
| Resueltos via ROI directo | 640 (22.2%) | 365 (12.7%) |
| Sin producto -- hibrido | 95 (3.3%) | 110 (3.8%) |
| Desacuerdos | 260 (9.0%) | 132 (4.6%) |
| Mejora | 25 (0.9%) | 10 (0.3%) |
| Regresion | 0 | 0 |

Revision manual de la nueva muestra de 14 desacuerdos: **el patron de
"banner/caja fusionada" ya no aparece** (los 4 casos de Walmart en la muestra
anterior, todos del mismo error, desaparecieron). Los desacuerdos restantes
son mayormente el tercer patron (producto real no clasificado como PRODUCTO
por el NLP) -- limite de otra etapa del pipeline, no corregible desde
`region_detector.py`.

Trade-off esperado y aceptado: ser mas conservador reduce tanto los aciertos
como los errores de ROI -- baja la cobertura (menos precios resueltos via ROI,
22.2% -> 12.7%) a cambio de mas confiabilidad cuando si se usa.

## Decision

El hibrido (ROI con fallback a distancia) es seguro de integrar para las 4
tiendas grid-friendly evaluadas: **0% regresion siempre** (por diseño del
fallback) y, tras el ajuste, la mayoria de los desacuerdos restantes ya no
son errores de asociacion sino casos donde ninguno de los dos metodos tiene
buena informacion (limite de clasificacion NLP). Pendiente: decidir si se
integra a `load/load.py` (reemplazando `_asociar_producto` con la version
hibrida para las tiendas grid-friendly) o se deja documentado sin integrar
hasta priorizarlo.

## Archivos

- `vision/region_detector.py`: `asociar_producto_por_region()` (nuevo),
  filtros `PROPORCION_MAX` y `DISPERSION_MAX_FRACCION`.
- `probar_hibrido_roi.py`: benchmark hibrido, `data/processed/_v7_hibrido_roi_asociacion/resumen.csv`.
- `revisar_desacuerdos.py`: genera muestra visual de desacuerdos para revision manual, `data/processed/_v7_hibrido_roi_asociacion/muestra_desacuerdos/`.
- Todo en la branch `feature/roi-integration` (no mergeada a `main`).

## Integracion a load/load.py (jul 2026)

Con el resultado de arriba (0% regresion garantizada, mejora confirmada
manualmente) se integro el hibrido a produccion:

- `TIENDAS_ROI_HIBRIDO = {"walmart", "chedraui", "soriana_hiper", "soriana_mercado"}`
  (slug CRUDO de `data/raw/<fuente>/<slug>/`, no el slug corregido de
  `CORRECCION_TIENDAS`) -- unica lista de control, NO agregar tiendas sin
  antes correr `probar_hibrido_roi.py` para esa tienda.
- `Loader._detectar_regiones_pagina()`: si la tienda no esta en la lista, o
  no existe la imagen original, o algo falla (try/except), devuelve `None` --
  fallback identico al comportamiento previo a esta integracion.
- `Loader._procesar_pagina()`: por cada precio, intenta `asociar_producto_por_region()`
  primero; si devuelve `None`, cae a `_asociar_producto()` (distancia, sin cambios).
- Validado sin tocar la base de datos: `Loader._detectar_regiones_pagina()`
  corrido sobre 209 paginas reales de las 4 tiendas (5 folletos c/u) + costco
  (tienda no incluida) via `Loader.__new__(Loader)` -- 0 errores, comportamiento
  correcto (`None` para tiendas fuera de la lista, lista de regiones para las
  incluidas).

**Pendiente operativo, no resuelto por este cambio:** los folletos de estas 4
tiendas que ya estaban cargados en PostgreSQL fueron insertados con el metodo
de distancia puro (antes de esta integracion). `extracciones` no tiene
deduplicacion -- volver a correr `cargar_folleto()` sobre un folleto ya
cargado insertaria filas duplicadas, no las reemplaza. Para que la mejora
aplique a datos historicos hace falta un refresh controlado (borrar
extracciones de esos folletos antes de recargar, o una migracion explicita),
que no se hizo en esta sesion. Sin ese refresh, el hibrido solo aplica a
folletos nuevos que se carguen de aqui en adelante.
