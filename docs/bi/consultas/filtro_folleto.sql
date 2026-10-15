-- Filtro "Folleto" (docs/bi/metricas.md seccion 6, 14-oct-2026).
-- Reproduce, por panel, el predicado que ejecuta el dashboard (SQL generado por el ORM en queries.filtrar_folleto /
-- queries._en_folleto y la regla _SQL_FOLLETO de Confiabilidad) para folletos de prueba: 430658 (la_comer),
-- 413647 (walmart, con 1 error de carga) y 999999 (no existe: todo debe dar 0 sin error).
-- Cuadra con docs/bi/consultas/filtro_folleto_validacion.sql.
WITH ids(folleto) AS (VALUES ('430658'), ('413647'), ('999999'))
SELECT i.folleto,
       -- Precios (tabla) y Resumen "Precios detectados"
       (SELECT COUNT(*) FROM v_precios_actuales v WHERE v.folleto_id_fuente = i.folleto)            AS precios,
       -- ... de ellos con categoria (Resumen Top categorias = suma de barras)
       (SELECT COUNT(*) FROM v_precios_actuales v WHERE v.folleto_id_fuente = i.folleto
          AND NOT (TRIM(v.categoria) IS NULL OR TRIM(v.categoria) = ''))                            AS top_categorias_suma,
       -- Historico (todos los productos del folleto; el panel exige un producto)
       (SELECT COUNT(*) FROM v_historico_precios h WHERE h.folleto_id_fuente = i.folleto)           AS historico,
       -- Comparativa: grupos (texto, categoria) en 2+ tiendas con registro en el folleto (EXISTS del ORM)
       (SELECT COUNT(*) FROM v_comparativa_precios c
         WHERE c.num_tiendas >= 2
           AND EXISTS (SELECT 1 FROM extracciones u0 JOIN folletos u1 ON u0.folleto_id = u1.id
                       WHERE u1.folleto_id_fuente = i.folleto AND u0.texto_norm = c.producto
                         AND u0.tipo = 'PRECIO' AND u0.valor IS NOT NULL
                         AND COALESCE(u0.categoria_nlp, '') = COALESCE(c.categoria, '')))           AS comparativa,
       -- Confiabilidad: base de _SQL_CONFIABILIDAD con _SQL_FOLLETO
       (SELECT COUNT(*) FROM extracciones e
          JOIN extracciones p ON p.id = e.producto_extraccion_id
          JOIN folletos f ON f.id = e.folleto_id
         WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
           AND f.folleto_id_fuente = i.folleto)                                                     AS confiabilidad_registros,
       (SELECT COUNT(*) FROM tiendas t
         WHERE EXISTS (SELECT 1 FROM folletos fx WHERE fx.tienda_id = t.id
                         AND fx.folleto_id_fuente = i.folleto))                                     AS confiabilidad_tiendas,
       -- Calidad: tabla operativa por folleto
       (SELECT COUNT(*) FROM v_calidad_pipeline q WHERE q.folleto_id_fuente = i.folleto)            AS calidad_filas,
       -- Errores de carga (todos los estados)
       (SELECT COUNT(*) FROM errores_carga ec WHERE ec.folleto_id_fuente = i.folleto)               AS errores,
       -- Explorador: extracciones de todos los tipos (la pagina muestra hasta 200)
       (SELECT COUNT(*) FROM extracciones e JOIN folletos f ON f.id = e.folleto_id
         WHERE f.folleto_id_fuente = i.folleto)                                                     AS explorador_extracciones
FROM ids i
ORDER BY i.folleto
