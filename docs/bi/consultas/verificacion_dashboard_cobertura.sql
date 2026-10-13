-- Verificacion del Panel 2 construido: es _SQL_COBERTURA de dashboard/queries.py (cobertura_por_tienda) con los
-- parametros por defecto sustituidos (tiendas = NULL; anomalias de inicio no confiable = ANOMALIAS_INICIO_NO_CONFIABLE),
-- envuelta en los mismos totales que calcula la funcion para los KPIs.
-- Esperado 12-oct-2026: 20 tiendas, 10 con vigente, 52 vigentes, 16 con fecha dudosa, 2 proximos, 532 paginas,
-- 1,858 precios vigentes, 694 folletos, 23 con fecha anomala, 28,634 precios, ultimo scrapeo 2026-10-05.
-- Si cambia _SQL_COBERTURA hay que actualizar este archivo.
SELECT count(*) tiendas, count(*) FILTER (WHERE folletos_vigentes > 0) tiendas_con_vigente,
       sum(folletos_vigentes) vigentes, sum(vigentes_fecha_dudosa) dudosos, sum(proximos) proximos,
       sum(paginas_vigentes) pags_vig, sum(precios_vigentes) precios_vig, sum(folletos_total) folletos,
       sum(folletos_fecha_anomala) anomalos, sum(precios_total) precios_total, max(ultimo_scrapeo) ult_scr,
       max(fecha_ultimo_folleto) max_ult
FROM (
WITH pag AS (
    SELECT folleto_id, COUNT(*) AS paginas, COUNT(*) FILTER (WHERE total_precios > 0) AS paginas_con_precio
    FROM paginas GROUP BY folleto_id
),
pre AS (
    SELECT folleto_id, COUNT(*) AS precios
    FROM extracciones
    WHERE tipo = 'PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL
    GROUP BY folleto_id
),
err AS (
    SELECT tienda_slug, COUNT(*) FILTER (WHERE NOT resuelto) AS abiertos, COUNT(*) AS total
    FROM errores_carga GROUP BY tienda_slug
),
x AS (
    SELECT v.tienda_id,
           COUNT(*)                                                     AS folletos_total,
           COUNT(*) FILTER (WHERE v.vigente)                            AS folletos_vigentes,
           COUNT(*) FILTER (WHERE v.vigente_dudoso)                     AS vigentes_fecha_dudosa,
           COUNT(*) FILTER (WHERE v.proximo)                            AS proximos,
           COUNT(*) FILTER (WHERE v.anomalia_fecha IS NOT NULL)         AS folletos_fecha_anomala,
           MAX(v.fecha_inicio) FILTER (WHERE v.fecha_inicio <= CURRENT_DATE
                 AND (v.anomalia_fecha IS NULL OR v.anomalia_fecha <> ALL(ARRAY['sin_fecha','fin_antes_inicio','inicio_antiguo','inicio_futuro_vs_scrapeo']::text[])))
                                                                        AS fecha_ultimo_folleto,
           MAX(v.scrapeado_at)                                          AS ultimo_scrapeo,
           SUM(COALESCE(p.paginas, 0))                                  AS paginas_total,
           SUM(COALESCE(p.paginas, 0)) FILTER (WHERE v.vigente)         AS paginas_vigentes,
           SUM(COALESCE(p.paginas_con_precio, 0)) FILTER (WHERE v.vigente) AS paginas_vig_con_precio,
           SUM(COALESCE(r.precios, 0)) FILTER (WHERE v.vigente)         AS precios_vigentes,
           SUM(COALESCE(r.precios, 0))                                  AS precios_total
    FROM v_folletos_vigencia v
    LEFT JOIN pag p ON p.folleto_id = v.id
    LEFT JOIN pre r ON r.folleto_id = v.id
    GROUP BY v.tienda_id
)
SELECT t.slug                                         AS tienda_slug,
       COALESCE(x.folletos_total, 0)                  AS folletos_total,
       COALESCE(x.folletos_vigentes, 0)               AS folletos_vigentes,
       COALESCE(x.vigentes_fecha_dudosa, 0)           AS vigentes_fecha_dudosa,
       COALESCE(x.proximos, 0)                        AS proximos,
       x.fecha_ultimo_folleto,
       x.ultimo_scrapeo::date                         AS ultimo_scrapeo,
       COALESCE(x.paginas_vigentes, 0)                AS paginas_vigentes,
       COALESCE(x.precios_vigentes, 0)                AS precios_vigentes,
       COALESCE(x.precios_total, 0)                   AS precios_total,
       COALESCE(x.folletos_fecha_anomala, 0)          AS folletos_fecha_anomala
FROM tiendas t
LEFT JOIN x   ON x.tienda_id = t.id
LEFT JOIN err e ON e.tienda_slug = t.slug
WHERE (NULL::text[] IS NULL OR t.nombre = ANY(NULL::text[]))
) q
