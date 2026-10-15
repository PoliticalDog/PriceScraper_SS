-- Validacion independiente del filtro "Folleto" (docs/bi/metricas.md seccion 6).
-- Otro camino: resuelve primero el folletos.id interno (subconsulta por (fuente, folleto_id_fuente) como llave
-- natural) y cuenta desde la tabla base extracciones por folleto_id (sin vistas ni join a folletos); la comparativa se
-- recalcula agregando extracciones completas con BOOL_OR; las paginas salen de paginas; los errores se cruzan con
-- folletos por (fuente, folleto_id_fuente). Debe cuadrar con filtro_folleto.sql.
WITH ids(folleto) AS (VALUES ('430658'), ('413647'), ('999999')),
fol AS (
    SELECT i.folleto, f.id AS folleto_pk, f.fuente
    FROM ids i LEFT JOIN folletos f ON f.folleto_id_fuente = i.folleto
),
reg AS (
    SELECT e.folleto_id, e.texto_norm, e.categoria_nlp, e.tienda_id
    FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
grupos AS (
    SELECT texto_norm, categoria_nlp, COUNT(DISTINCT tienda_id) AS tiendas, ARRAY_AGG(DISTINCT folleto_id) AS folletos
    FROM reg GROUP BY texto_norm, categoria_nlp
)
SELECT fol.folleto,
       fol.folleto_pk,
       (SELECT COUNT(*) FROM reg r WHERE r.folleto_id = fol.folleto_pk)                                  AS precios,
       (SELECT COUNT(*) FROM reg r WHERE r.folleto_id = fol.folleto_pk
          AND LENGTH(BTRIM(COALESCE(r.categoria_nlp, ''))) > 0)                                          AS con_categoria,
       (SELECT COUNT(*) FROM grupos g WHERE g.tiendas >= 2 AND fol.folleto_pk = ANY(g.folletos))        AS comparativa,
       (SELECT COUNT(*) FROM paginas pg WHERE pg.folleto_id = fol.folleto_pk) > 0                       AS tiene_paginas,
       (SELECT COUNT(*) FROM errores_carga ec
         WHERE ec.fuente = fol.fuente::text AND ec.folleto_id_fuente = fol.folleto)                           AS errores,
       (SELECT COUNT(*) FROM extracciones e WHERE e.folleto_id = fol.folleto_pk)                        AS extracciones_todas
FROM fol
ORDER BY fol.folleto
