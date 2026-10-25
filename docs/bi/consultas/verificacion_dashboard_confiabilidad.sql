-- Verificacion del Panel 1 construido: es _SQL_CONFIABILIDAD de dashboard/queries.py (confiabilidad_por_tienda) con
-- los parametros por defecto sustituidos (tiendas, desde, hasta = NULL). Debe dar las mismas 20 filas que
-- confiabilidad_por_tienda.sql (registros, pct_catalogo, pct_sin_categoria, conf_ocr_*). Si cambia la SQL de
-- queries.py hay que actualizar este archivo.
WITH base AS (
    SELECT e.id, e.tienda_id, e.folleto_id, e.pagina_id, e.texto_norm, e.valor, e.confianza_ocr,
           e.categoria_nlp, COALESCE(e.metodo_norm, p.metodo_norm) AS metodo_norm
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND (NULL::date IS NULL OR f.fecha_inicio >= NULL::date)
      AND (NULL::date IS NULL OR f.fecha_inicio <= NULL::date)
),
dup AS (
    SELECT tienda_id, SUM(n - 1) AS sobrantes
    FROM (SELECT tienda_id, folleto_id, pagina_id, texto_norm, valor, COUNT(*) AS n
          FROM base GROUP BY 1, 2, 3, 4, 5 HAVING COUNT(*) > 1) d
    GROUP BY tienda_id
),
agg AS (
    SELECT tienda_id,
           COUNT(*)                                                                 AS registros,
           COUNT(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo')) AS reg_catalogo,
           COUNT(*) FILTER (WHERE metodo_norm = 'heuristico')                       AS reg_heuristico,
           COUNT(*) FILTER (WHERE COALESCE(categoria_nlp, '') = '')                 AS reg_sin_categoria,
           COUNT(*) FILTER (WHERE valor < 1 OR valor > 100000)                      AS reg_atipicos,
           AVG(confianza_ocr)                                                       AS conf_ocr_media,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY confianza_ocr)               AS conf_ocr_mediana,
           COUNT(DISTINCT folleto_id)                                               AS folletos
    FROM base GROUP BY tienda_id
)
SELECT t.slug                                                                     AS tienda_slug,
       COALESCE(a.registros, 0)                                                   AS registros,
       COALESCE(a.reg_catalogo, 0)                                                AS reg_catalogo,
       COALESCE(a.reg_sin_categoria, 0)                                           AS reg_sin_categoria,
       ROUND(100.0 * a.reg_catalogo      / NULLIF(a.registros, 0), 1)::float8     AS pct_catalogo,
       ROUND(100.0 * a.reg_heuristico    / NULLIF(a.registros, 0), 1)::float8     AS pct_heuristico,
       ROUND(100.0 * a.reg_sin_categoria / NULLIF(a.registros, 0), 1)::float8     AS pct_sin_categoria,
       ROUND(a.conf_ocr_media::numeric, 3)::float8                                AS conf_ocr_media,
       ROUND(a.conf_ocr_mediana::numeric, 3)::float8                              AS conf_ocr_mediana,
       ROUND(100.0 * COALESCE(d.sobrantes, 0) / NULLIF(a.registros, 0), 1)::float8 AS pct_duplicados,
       COALESCE(a.reg_atipicos, 0)                                                AS atipicos
FROM tiendas t
LEFT JOIN agg a ON a.tienda_id = t.id
LEFT JOIN dup d ON d.tienda_id = t.id
WHERE (NULL::text[] IS NULL OR t.nombre = ANY(NULL::text[]))
ORDER BY registros DESC, t.nombre
