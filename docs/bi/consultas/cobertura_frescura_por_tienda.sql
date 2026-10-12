-- Panel 2 (PROPUESTA) - Cobertura y frescura por tienda.
-- Pregunta: de que tiendas tenemos folletos vigentes hoy, que tan reciente es lo ultimo que capturamos y cuanto dato
--           de precio hay detras de lo vigente?
-- Grano: una fila por tienda (20). "Hoy" = CURRENT_DATE (parametrizable como :fecha_corte al construir).
--
-- Clasificacion de fechas por folleto (no se corrige nada, solo se etiqueta; orden de precedencia):
--   sin_fecha                fecha_inicio o fecha_fin NULL                          (hoy 0)
--   fin_antes_inicio         fecha_fin < fecha_inicio                               (hoy 0)
--   inicio_antiguo           fecha_inicio < scrapeado_at - 365 dias                 (hoy 1: soriana_hiper 430896, 2022-09-01)
--   inicio_futuro_vs_scrapeo fecha_inicio > scrapeado_at + 30 dias                  (hoy 6: alsuper 371335, waldos x4, s-mart 418009)
--   vigencia_larga           fecha_fin - fecha_inicio > 120 dias                    (hoy 16)
--   NULL                     fecha confiable
-- Vigente hoy (KPI principal) = fecha confiable AND fecha_inicio <= hoy <= fecha_fin.
-- Vigente con fecha dudosa  = cumple el rango de fechas pero tiene etiqueta (se muestra aparte, no se suma).
-- Ultimo folleto = MAX(fecha_inicio) con fecha_inicio <= hoy entre folletos sin inicio_antiguo / inicio_futuro_vs_scrapeo
--   (vigencia_larga si cuenta: su fecha de inicio es plausible, lo dudoso es el fin).
-- Joins: folletos -> paginas y folletos -> extracciones son 1:N; se agregan POR SEPARADO a grano folleto antes de unir
--   (unir ambos directo multiplicaria paginas x precios).
-- errores_carga no tiene FK: se une por tienda_slug (los 13 slugs actuales existen en tiendas).
WITH fol AS (
    SELECT f.*,
           CASE
               WHEN f.fecha_inicio IS NULL OR f.fecha_fin IS NULL               THEN 'sin_fecha'
               WHEN f.fecha_fin < f.fecha_inicio                                THEN 'fin_antes_inicio'
               WHEN f.fecha_inicio < f.scrapeado_at::date - 365                 THEN 'inicio_antiguo'
               WHEN f.fecha_inicio > f.scrapeado_at::date + 30                  THEN 'inicio_futuro_vs_scrapeo'
               WHEN f.fecha_fin - f.fecha_inicio > 120                          THEN 'vigencia_larga'
           END AS anomalia_fecha
    FROM folletos f
),
fol_clas AS (
    SELECT fol.*,
           (anomalia_fecha IS NULL
            AND fecha_inicio <= CURRENT_DATE AND fecha_fin >= CURRENT_DATE)       AS vigente,
           (anomalia_fecha IS NOT NULL
            AND fecha_inicio <= CURRENT_DATE AND fecha_fin >= CURRENT_DATE)       AS vigente_dudoso,
           (anomalia_fecha IS NULL AND fecha_inicio > CURRENT_DATE)               AS proximo
    FROM fol
),
pag AS (     -- grano folleto
    SELECT folleto_id, COUNT(*) AS paginas, COUNT(*) FILTER (WHERE total_precios > 0) AS paginas_con_precio
    FROM paginas GROUP BY folleto_id
),
pre AS (     -- grano folleto; registros del dashboard (= v_precios_actuales)
    SELECT folleto_id, COUNT(*) AS precios
    FROM extracciones
    WHERE tipo = 'PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL
    GROUP BY folleto_id
),
err AS (
    SELECT tienda_slug, COUNT(*) FILTER (WHERE NOT resuelto) AS abiertos, COUNT(*) AS total
    FROM errores_carga GROUP BY tienda_slug
),
por_tienda AS (
    SELECT c.tienda_id,
           COUNT(*)                                                            AS folletos_total,
           COUNT(*) FILTER (WHERE c.vigente)                                   AS folletos_vigentes,
           COUNT(*) FILTER (WHERE c.vigente_dudoso)                            AS folletos_vigentes_dudosos,
           COUNT(*) FILTER (WHERE c.proximo)                                   AS folletos_proximos,
           COUNT(*) FILTER (WHERE c.anomalia_fecha IS NOT NULL)                AS folletos_fecha_anomala,
           MAX(c.fecha_inicio) FILTER (WHERE c.fecha_inicio <= CURRENT_DATE
                 AND COALESCE(c.anomalia_fecha, '') NOT IN ('inicio_antiguo', 'inicio_futuro_vs_scrapeo'))
                                                                               AS fecha_ultimo_folleto,
           MAX(c.scrapeado_at)                                                 AS ultimo_scrapeo,
           SUM(COALESCE(p.paginas, 0))                                         AS paginas_total,
           SUM(COALESCE(p.paginas, 0)) FILTER (WHERE c.vigente)                AS paginas_vigentes,
           SUM(COALESCE(p.paginas_con_precio, 0)) FILTER (WHERE c.vigente)     AS paginas_vigentes_con_precio,
           SUM(COALESCE(r.precios, 0)) FILTER (WHERE c.vigente)                AS precios_vigentes,
           SUM(COALESCE(r.precios, 0))                                         AS precios_total
    FROM fol_clas c
    LEFT JOIN pag p ON p.folleto_id = c.id
    LEFT JOIN pre r ON r.folleto_id = c.id
    GROUP BY c.tienda_id
)
SELECT t.slug                                                   AS tienda_slug,
       t.nombre                                                 AS tienda,
       COALESCE(x.folletos_total, 0)                            AS folletos_total,
       COALESCE(x.folletos_vigentes, 0)                         AS folletos_vigentes,
       COALESCE(x.folletos_vigentes_dudosos, 0)                 AS vigentes_fecha_dudosa,
       COALESCE(x.folletos_proximos, 0)                         AS proximos,
       x.fecha_ultimo_folleto,
       CURRENT_DATE - x.fecha_ultimo_folleto                    AS dias_desde_ultimo,
       x.ultimo_scrapeo::date                                   AS ultimo_scrapeo,
       COALESCE(x.paginas_vigentes, 0)                          AS paginas_vigentes,
       COALESCE(x.paginas_vigentes_con_precio, 0)               AS paginas_vig_con_precio,
       COALESCE(x.precios_vigentes, 0)                          AS precios_vigentes,
       COALESCE(x.paginas_total, 0)                             AS paginas_total,
       COALESCE(x.precios_total, 0)                             AS precios_total,
       COALESCE(x.folletos_fecha_anomala, 0)                    AS folletos_fecha_anomala,
       COALESCE(e.abiertos, 0)                                  AS errores_abiertos,
       COALESCE(e.total, 0)                                     AS errores_total
FROM tiendas t
LEFT JOIN por_tienda x ON x.tienda_id = t.id
LEFT JOIN err e        ON e.tienda_slug = t.slug
ORDER BY folletos_vigentes DESC, dias_desde_ultimo
