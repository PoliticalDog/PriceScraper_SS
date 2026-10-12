-- Panel 1 (PROPUESTA) - Confiabilidad del dato por tienda: parte que vive en la BD.
-- Pregunta: para cada tienda, que tan confiable es lo que el dashboard muestra como "precio de producto"?
-- Grano: una fila por tienda (20 tiendas, incluye las que no tienen registros).
-- Base: registros del dashboard = extracciones tipo PRECIO con valor y texto_norm (= v_precios_actuales, 28,634 al 12-oct-2026).
-- Join PRECIO -> PRODUCTO por producto_extraccion_id: N:1 sobre la fila PRODUCTO, no duplica filas de PRECIO
--   (verificado: 28,634 antes y despues del join; 0 precios sin fila PRODUCTO).
-- metodo_norm se lee de la fila PRODUCTO (en la fila PRECIO siempre es NULL).
-- Categoria vacia: categoria_nlp = '' o NULL (en la fila PRECIO; hoy todas son '' y coinciden con el canonico vacio).
-- Sin exclusiones: describe el dato tal como lo ve el dashboard. Duplicados exactos y atipicos se reportan como columnas
--   auxiliares, no se restan.
-- Filtro de fecha opcional al construir: f.fecha_inicio BETWEEN :desde AND :hasta (aqui sin filtro).
-- La precision/recall del evaluador NO esta en la BD: se une en Django desde el JSON de la corrida (ver docs/bi/metricas.md).
WITH base AS (
    SELECT e.id, e.tienda_id, e.folleto_id, e.pagina_id, e.texto_norm, e.valor, e.confianza_ocr,
           e.categoria_nlp, p.metodo_norm
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
dup AS (  -- filas sobrantes de duplicados exactos (mismo folleto+pagina+texto+valor), por tienda
    SELECT tienda_id, SUM(n - 1) AS sobrantes
    FROM (SELECT tienda_id, folleto_id, pagina_id, texto_norm, valor, COUNT(*) AS n
          FROM base GROUP BY 1, 2, 3, 4, 5 HAVING COUNT(*) > 1) d
    GROUP BY tienda_id
),
agg AS (
    SELECT tienda_id,
           COUNT(*)                                                             AS registros,
           COUNT(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo')) AS reg_catalogo,
           COUNT(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy'))            AS reg_catalogo_alto,
           COUNT(*) FILTER (WHERE metodo_norm = 'heuristico')                    AS reg_heuristico,
           COUNT(*) FILTER (WHERE COALESCE(categoria_nlp, '') = '')              AS reg_sin_categoria,
           COUNT(*) FILTER (WHERE valor < 1 OR valor > 100000)                   AS reg_atipicos,
           AVG(confianza_ocr)                                                    AS conf_ocr_media,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY confianza_ocr)            AS conf_ocr_mediana,
           COUNT(DISTINCT folleto_id)                                            AS folletos
    FROM base GROUP BY tienda_id
)
SELECT t.slug                                                             AS tienda_slug,
       t.nombre                                                           AS tienda,
       COALESCE(a.registros, 0)                                           AS registros,
       COALESCE(a.folletos, 0)                                            AS folletos_con_precio,
       ROUND(100.0 * a.reg_catalogo      / NULLIF(a.registros, 0), 1)     AS pct_catalogo,
       ROUND(100.0 * a.reg_catalogo_alto / NULLIF(a.registros, 0), 1)     AS pct_catalogo_exacto_fuzzy,
       ROUND(100.0 * a.reg_heuristico    / NULLIF(a.registros, 0), 1)     AS pct_heuristico,
       ROUND(100.0 * a.reg_sin_categoria / NULLIF(a.registros, 0), 1)     AS pct_sin_categoria,
       ROUND(a.conf_ocr_media::numeric, 3)                                AS conf_ocr_media,
       ROUND(a.conf_ocr_mediana::numeric, 3)                              AS conf_ocr_mediana,
       ROUND(100.0 * COALESCE(d.sobrantes, 0) / NULLIF(a.registros, 0), 1) AS pct_duplicados,
       COALESCE(a.reg_atipicos, 0)                                        AS atipicos
FROM tiendas t
LEFT JOIN agg a ON a.tienda_id = t.id
LEFT JOIN dup d ON d.tienda_id = t.id
ORDER BY registros DESC
