-- Avisos del filtro "Folleto" y de Errores de carga (docs/bi/metricas.md seccion 6, 14-oct-2026).
-- Reproduce queries.estado_folleto (no_existe / sin_precios / con_precios) y queries.errores_ocultos_por_estado
-- (Estado = "abiertos", sin otros filtros salvo el folleto) para: 999999 (no existe), 413679 (existe sin precios),
-- 430658 (con precios) y 413647 (con precios y 1 error de carga resuelto). La fila '(vacio)' es el filtro de folleto
-- vacio: no hay aviso de folleto, pero si el de errores ocultos de la pagina de Errores por defecto.
WITH ids(folleto) AS (VALUES ('999999'), ('413679'), ('430658'), ('413647')),
est AS (
    SELECT i.folleto,
           (SELECT COUNT(*) FROM folletos f WHERE f.folleto_id_fuente = i.folleto)                 AS folletos,
           (SELECT COUNT(*) FROM v_precios_actuales v WHERE v.folleto_id_fuente = i.folleto)       AS registros,
           (SELECT COUNT(*) FROM errores_carga ec WHERE ec.folleto_id_fuente = i.folleto)          AS errores_carga,
           (SELECT COUNT(*) FROM errores_carga ec WHERE ec.folleto_id_fuente = i.folleto
              AND NOT ec.resuelto)                                                                 AS errores_visibles_abiertos,
           (SELECT COUNT(*) FROM errores_carga ec WHERE ec.folleto_id_fuente = i.folleto
              AND ec.resuelto)                                                                     AS errores_ocultos_resueltos
    FROM ids i
)
SELECT folleto,
       CASE WHEN folletos = 0 THEN 'no_existe' WHEN registros = 0 THEN 'sin_precios' ELSE 'con_precios' END AS estado,
       folletos, registros, errores_carga, errores_visibles_abiertos, errores_ocultos_resueltos
FROM est
UNION ALL
SELECT '(vacio)', NULL, NULL, NULL,
       (SELECT COUNT(*) FROM errores_carga),
       (SELECT COUNT(*) FROM errores_carga WHERE NOT resuelto),
       (SELECT COUNT(*) FROM errores_carga WHERE resuelto)
