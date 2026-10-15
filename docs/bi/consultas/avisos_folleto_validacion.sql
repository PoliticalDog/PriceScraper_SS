-- Validacion independiente de los avisos (docs/bi/metricas.md seccion 6).
-- Otro camino: clasifica con LEFT JOIN + agregacion sobre la tabla base extracciones (no la vista), y cuenta los
-- errores con FILTER por estado en una sola agregacion. Ademas cuenta cuantos folletos caen en cada estado
-- (debe dar 76 sin precios de 694 al 14-oct-2026). Debe cuadrar con avisos_folleto.sql.
WITH ids(folleto) AS (VALUES ('999999'), ('413679'), ('430658'), ('413647')),
reg AS (
    SELECT f.folleto_id_fuente, f.id,
           COUNT(e.id) FILTER (WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL) AS registros
    FROM folletos f LEFT JOIN extracciones e ON e.folleto_id = f.id
    GROUP BY f.folleto_id_fuente, f.id
),
err AS (
    SELECT folleto_id_fuente, COUNT(*) FILTER (WHERE resuelto) AS resueltos, COUNT(*) FILTER (WHERE NOT resuelto) AS abiertos
    FROM errores_carga GROUP BY folleto_id_fuente
)
SELECT i.folleto,
       CASE WHEN r.id IS NULL THEN 'no_existe' WHEN r.registros = 0 THEN 'sin_precios' ELSE 'con_precios' END AS estado,
       r.registros,
       COALESCE(er.abiertos, 0) AS abiertos,
       COALESCE(er.resueltos, 0) AS resueltos
FROM ids i
LEFT JOIN reg r ON r.folleto_id_fuente = i.folleto
LEFT JOIN err er ON er.folleto_id_fuente = i.folleto
UNION ALL
SELECT 'folletos sin_precios / total', NULL,
       (SELECT COUNT(*) FROM reg WHERE registros = 0), (SELECT COUNT(*) FROM reg), NULL
