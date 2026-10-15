-- Validacion independiente del filtro "Con / sin categoria" (docs/bi/metricas.md seccion 5).
-- Otro camino: parte de la tabla base extracciones (no de las vistas), clasifica con LENGTH(BTRIM(...)) en lugar de
-- TRIM/COALESCE, obtiene tienda/folleto con EXISTS (sin JOIN) y cuenta cada clase en una consulta separada.
-- Debe cuadrar con filtro_con_categoria.sql: precios del dashboard, historico, confiabilidad y cobertura vigentes.
WITH base AS (
    SELECT e.id, e.folleto_id,
           CASE WHEN e.categoria_nlp IS NOT NULL AND LENGTH(BTRIM(e.categoria_nlp)) > 0 THEN 'con' ELSE 'sin' END AS clase
    FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND EXISTS (SELECT 1 FROM tiendas t WHERE t.id = e.tienda_id)
      AND EXISTS (SELECT 1 FROM folletos f WHERE f.id = e.folleto_id)
)
SELECT 'registros_dashboard' AS medida,
       (SELECT COUNT(*) FROM base)                        AS todos,
       (SELECT COUNT(*) FROM base WHERE clase = 'con')    AS con_cat,
       (SELECT COUNT(*) FROM base WHERE clase = 'sin')    AS sin_cat
UNION ALL
SELECT 'registros_con_fecha_inicio (historico)',
       (SELECT COUNT(*) FROM base b WHERE EXISTS (SELECT 1 FROM folletos f WHERE f.id = b.folleto_id AND f.fecha_inicio IS NOT NULL)),
       (SELECT COUNT(*) FROM base b WHERE b.clase = 'con' AND EXISTS (SELECT 1 FROM folletos f WHERE f.id = b.folleto_id AND f.fecha_inicio IS NOT NULL)),
       (SELECT COUNT(*) FROM base b WHERE b.clase = 'sin' AND EXISTS (SELECT 1 FROM folletos f WHERE f.id = b.folleto_id AND f.fecha_inicio IS NOT NULL))
UNION ALL
SELECT 'registros_en_folleto_vigente (cobertura)',
       (SELECT COUNT(*) FROM base b WHERE b.folleto_id IN (SELECT id FROM v_folletos_vigencia WHERE vigente)),
       (SELECT COUNT(*) FROM base b WHERE b.clase = 'con' AND b.folleto_id IN (SELECT id FROM v_folletos_vigencia WHERE vigente)),
       (SELECT COUNT(*) FROM base b WHERE b.clase = 'sin' AND b.folleto_id IN (SELECT id FROM v_folletos_vigencia WHERE vigente))
UNION ALL
SELECT 'grupos_comparativa_min2 (texto+categoria en 2+ tiendas)',
       (SELECT COUNT(*) FROM (SELECT 1 FROM extracciones e WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
                              GROUP BY e.texto_norm, e.categoria_nlp HAVING COUNT(DISTINCT e.tienda_id) >= 2) g),
       (SELECT COUNT(*) FROM (SELECT 1 FROM extracciones e WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
                                AND LENGTH(BTRIM(COALESCE(e.categoria_nlp, ''))) > 0
                              GROUP BY e.texto_norm, e.categoria_nlp HAVING COUNT(DISTINCT e.tienda_id) >= 2) g),
       (SELECT COUNT(*) FROM (SELECT 1 FROM extracciones e WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
                                AND LENGTH(BTRIM(COALESCE(e.categoria_nlp, ''))) = 0
                              GROUP BY e.texto_norm, e.categoria_nlp HAVING COUNT(DISTINCT e.tienda_id) >= 2) g)
