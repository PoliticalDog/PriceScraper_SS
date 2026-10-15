-- Filtro "Con / sin categoria" (docs/bi/metricas.md seccion 5, 14-oct-2026).
-- Reproduce, panel por panel, los predicados que ejecuta el dashboard (SQL generado por el ORM en
-- queries.filtrar_con_categoria y la regla _SQL_CON_CATEGORIA de las consultas crudas):
--   sin categoria  <=>  TRIM(categoria) IS NULL OR TRIM(categoria) = ''      (= COALESCE(BTRIM(x), '') = '')
--   con categoria  <=>  NOT (lo anterior)
-- Debe cumplirse con + sin = todos en cada panel (columna cuadra = true).
WITH p AS (
    -- Resumen "Precios detectados" y tabla de Precios (v_precios_actuales)
    SELECT 'resumen_precios_detectados' AS panel,
           COUNT(*) AS todos,
           COUNT(*) FILTER (WHERE NOT (TRIM(categoria) IS NULL OR TRIM(categoria) = '')) AS con_cat,
           COUNT(*) FILTER (WHERE TRIM(categoria) IS NULL OR TRIM(categoria) = '')       AS sin_cat
    FROM v_precios_actuales
    UNION ALL
    -- Resumen "Top categorias": suma de todas las barras (categoria del canonico) sobre PRECIO
    SELECT 'resumen_top_categorias_suma',
           COUNT(*),
           COUNT(*) FILTER (WHERE NOT (TRIM(e.categoria_nlp) IS NULL OR TRIM(e.categoria_nlp) = '')),
           COUNT(*) FILTER (WHERE TRIM(e.categoria_nlp) IS NULL OR TRIM(e.categoria_nlp) = '')
    FROM extracciones e
    JOIN productos_canonicos pc ON pc.id = e.producto_canonico_id
    WHERE e.tipo = 'PRECIO' AND pc.categoria IS NOT NULL AND pc.categoria <> ''
    UNION ALL
    -- Comparativa (tabla, "Min. tiendas" = 2 por defecto en la UI)
    SELECT 'comparativa_filas_min2',
           COUNT(*),
           COUNT(*) FILTER (WHERE NOT (TRIM(categoria) IS NULL OR TRIM(categoria) = '')),
           COUNT(*) FILTER (WHERE TRIM(categoria) IS NULL OR TRIM(categoria) = '')
    FROM v_comparativa_precios
    WHERE num_tiendas >= 2
    UNION ALL
    -- Historico (v_historico_precios, todos los productos)
    SELECT 'historico_registros',
           COUNT(*),
           COUNT(*) FILTER (WHERE NOT (TRIM(categoria) IS NULL OR TRIM(categoria) = '')),
           COUNT(*) FILTER (WHERE TRIM(categoria) IS NULL OR TRIM(categoria) = '')
    FROM v_historico_precios
    UNION ALL
    -- Calidad / Confiabilidad: base de _SQL_CONFIABILIDAD (PRECIO -> PRODUCTO N:1, -> folletos N:1)
    SELECT 'confiabilidad_registros',
           COUNT(*),
           COUNT(*) FILTER (WHERE COALESCE(BTRIM(e.categoria_nlp), '') <> ''),
           COUNT(*) FILTER (WHERE COALESCE(BTRIM(e.categoria_nlp), '') = '')
    FROM extracciones e
    JOIN extracciones pr ON pr.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
    UNION ALL
    -- Cobertura: precios en folletos vigentes (CTE pre de _SQL_COBERTURA unida a v_folletos_vigencia)
    SELECT 'cobertura_precios_vigentes',
           COUNT(*),
           COUNT(*) FILTER (WHERE COALESCE(BTRIM(e.categoria_nlp), '') <> ''),
           COUNT(*) FILTER (WHERE COALESCE(BTRIM(e.categoria_nlp), '') = '')
    FROM extracciones e
    JOIN v_folletos_vigencia v ON v.id = e.folleto_id AND v.vigente
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
)
SELECT panel, todos, con_cat, sin_cat, (con_cat + sin_cat = todos) AS cuadra
FROM p
