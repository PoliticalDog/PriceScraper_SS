-- Validacion independiente del Panel 1 (otro camino): parte de la VISTA v_precios_actuales (no de extracciones),
-- agrupa por tienda_slug de la vista (no por tienda_id) y obtiene metodo_norm con un EXISTS correlacionado sobre la
-- fila PRODUCTO en lugar de un JOIN. Categoria vacia se lee de la columna "categoria" de la vista.
-- Debe cuadrar fila por fila con confiabilidad_por_tienda.sql en registros, reg_catalogo, reg_sin_categoria y conf media.
SELECT v.tienda_slug,
       COUNT(*)                                                    AS registros,
       SUM(CASE WHEN EXISTS (
               SELECT 1 FROM extracciones e
               JOIN extracciones p ON p.id = e.producto_extraccion_id
               WHERE e.id = v.id AND p.metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo'))
           THEN 1 ELSE 0 END)                                      AS reg_catalogo,
       SUM(CASE WHEN v.categoria IS NULL OR v.categoria = '' THEN 1 ELSE 0 END) AS reg_sin_categoria,
       ROUND(AVG(v.confianza_ocr)::numeric, 3)                    AS conf_ocr_media
FROM v_precios_actuales v
GROUP BY v.tienda_slug
ORDER BY registros DESC
