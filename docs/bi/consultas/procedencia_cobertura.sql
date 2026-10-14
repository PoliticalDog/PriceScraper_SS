-- Procedencia (folleto + pagina) de los registros del dashboard: cobertura de cada dato de origen.
-- Base: registros del dashboard = v_precios_actuales (PRECIO con valor y texto_norm), desde la tabla base.
-- Joins: extracciones -> paginas (pagina_id, N:1) y -> folletos (folleto_id, N:1); no duplican filas de PRECIO.
-- Uso: propuesta "procedencia por registro" (13-oct-2026, BI).
SELECT
    COUNT(*)                                                                    AS registros,
    COUNT(e.pagina_id)                                                          AS con_pagina_id,
    COUNT(p.id)                                                                 AS con_pagina_existente,
    COUNT(*) FILTER (WHERE p.folleto_id = e.folleto_id)                         AS pagina_mismo_folleto,
    COUNT(*) FILTER (WHERE COALESCE(p.archivo_imagen, '') <> '')                AS con_archivo_imagen,
    COUNT(*) FILTER (WHERE COALESCE(f.url_origen, '') <> '')                    AS con_url_origen,
    COUNT(*) FILTER (WHERE COALESCE(f.titulo, '') <> '')                        AS con_titulo,
    COUNT(*) FILTER (WHERE f.fecha_inicio IS NOT NULL AND f.fecha_fin IS NOT NULL) AS con_vigencia,
    COUNT(*) FILTER (WHERE e.bbox_x IS NOT NULL AND e.bbox_y IS NOT NULL
                       AND e.bbox_ancho > 0 AND e.bbox_alto > 0)                AS con_bbox,
    COUNT(DISTINCT e.folleto_id)                                                AS folletos,
    COUNT(DISTINCT e.pagina_id)                                                 AS paginas
FROM extracciones e
JOIN folletos f     ON f.id = e.folleto_id
LEFT JOIN paginas p ON p.id = e.pagina_id
WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
