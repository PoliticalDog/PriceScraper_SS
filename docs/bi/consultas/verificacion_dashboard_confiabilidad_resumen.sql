-- Verificacion del Panel 1 (parte BD), de la serie semanal del Panel 2 y de los KPIs corregidos del Resumen tal como
-- los calcula dashboard/queries.py con los parametros por defecto:
--   conf_*   = totales de _SQL_CONFIABILIDAD (confiabilidad_por_tienda: totales.registros / pct_catalogo / pct_sin_categoria)
--   semana_* = suma de _SQL_FOLLETOS_SEMANA (folletos_por_semana sin fechas: CURRENT_DATE-182 .. CURRENT_DATE+30)
--   resumen_* = resumen_kpis(): VPreciosActuales.count() y VFolletosVigencia vigente / vigente_dudoso
-- Esperado 12-oct-2026: 20 tiendas, 28,634 registros, 4,146 catalogo (14.5%), 18,601 sin categoria (65.0%);
-- resumen 28,634 / 52 vigentes / 16 dudosos.
WITH base AS (
    SELECT e.tienda_id, p.metodo_norm, e.categoria_nlp
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
conf AS (
    SELECT (SELECT COUNT(*) FROM tiendas)                                          AS tiendas,
           COUNT(*)                                                                AS registros,
           COUNT(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo')) AS catalogo,
           COUNT(*) FILTER (WHERE COALESCE(categoria_nlp, '') = '')                AS sin_categoria
    FROM base
),
semana AS (
    SELECT COUNT(*) AS folletos, COUNT(DISTINCT DATE_TRUNC('week', v.fecha_inicio)) AS semanas
    FROM v_folletos_vigencia v
    WHERE (v.anomalia_fecha IS NULL OR v.anomalia_fecha <> ALL(ARRAY['sin_fecha','fin_antes_inicio','inicio_antiguo','inicio_futuro_vs_scrapeo']::text[]))
      AND v.fecha_inicio >= CURRENT_DATE - 182
      AND v.fecha_inicio <= CURRENT_DATE + 30
)
SELECT conf.tiendas, conf.registros, conf.catalogo,
       ROUND(100.0 * conf.catalogo / conf.registros, 1)      AS pct_catalogo,
       conf.sin_categoria,
       ROUND(100.0 * conf.sin_categoria / conf.registros, 1) AS pct_sin_categoria,
       semana.folletos                                       AS semana_folletos,
       semana.semanas                                        AS semana_semanas,
       (SELECT COUNT(*) FROM v_precios_actuales)                          AS resumen_registros,
       (SELECT COUNT(*) FROM v_folletos_vigencia WHERE vigente)           AS resumen_vigentes,
       (SELECT COUNT(*) FROM v_folletos_vigencia WHERE vigente_dudoso)    AS resumen_dudosos
FROM conf, semana
