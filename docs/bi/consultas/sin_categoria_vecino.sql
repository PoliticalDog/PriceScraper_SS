-- Precios sin categoria cuyo vecino PRODUCTO mas cercano (misma pagina, <= 200 px del bloque de producto
-- asociado) si tiene categoria: potencial de heredar la categoria del bloque vecino en el load
WITH sin_cat AS (
    SELECT p.id, p.tienda_id, pr.pagina_id, pr.id AS prod_id, pr.bbox_x, pr.bbox_y
    FROM extracciones p
    JOIN extracciones pr ON pr.id = p.producto_extraccion_id
    WHERE p.tipo = 'PRECIO' AND p.valor IS NOT NULL AND p.texto_norm IS NOT NULL
      AND NULLIF(TRIM(p.categoria_nlp), '') IS NULL
)
SELECT COUNT(*) AS sin_cat,
       COUNT(v.categoria_nlp) AS con_vecino_categorizado,
       ROUND(100.0 * COUNT(v.categoria_nlp) / COUNT(*), 1) AS pct
FROM sin_cat s
LEFT JOIN LATERAL (
    SELECT o.categoria_nlp
    FROM extracciones o
    WHERE o.pagina_id = s.pagina_id AND o.id <> s.prod_id AND o.tipo = 'PRODUCTO'
      AND NULLIF(TRIM(o.categoria_nlp), '') IS NOT NULL
      AND ABS(o.bbox_x - s.bbox_x) <= 200 AND ABS(o.bbox_y - s.bbox_y) <= 200
    ORDER BY (o.bbox_x - s.bbox_x)^2 + (o.bbox_y - s.bbox_y)^2
    LIMIT 1
) v ON TRUE
