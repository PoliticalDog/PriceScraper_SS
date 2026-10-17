-- Validacion de la Fase 1 de promociones (docs/bi/metricas.md seccion 7, 15-oct-2026).
-- Camino A = el del dashboard: EXISTS sobre eventos_promo por la llave natural del folleto (fuente, folleto_id_fuente)
--            desde v_precios_actuales (filtro "Promocion" en Precios/Historico).
-- Camino B = independiente: desde la tabla base extracciones, folleto_id IN (folletos con campania) y su complemento
--            con NOT IN, sin vistas ni EXISTS.
-- Pagina Promociones: filas (folleto, slug) y precios por folleto contados una vez, recalculados con GROUP BY.
-- El mapa de clase/slug es el mismo de promociones_campanias.sql (solo se usa clase = campania).
WITH ev AS (
    SELECT ep.id, ep.folleto_id, LOWER(BTRIM(ep.nombre_evento)) AS n FROM eventos_promo ep
),
cl AS (
    SELECT ev.*,
           CASE
             WHEN n IN ('julio_regalado', 'hot_sale', 'buen_fin', 'regreso_a_clases', 'navidad',
                        'halloween_dia_de_muertos', 'liquidacion', 'aniversario', 'ofertones', 'fiestas_patrias') THEN n
             WHEN n ~ '(vela|figura|bao_navidad|hojas|cumplea|diferentes_)'                 THEN NULL
             WHEN n ~ '(excepto|participantes|sucursales|apllcan|aplican|restriccion)'      THEN NULL
             WHEN n ~ 'julio_?regalad'                    THEN 'julio_regalado'
             WHEN n ~ 'hot_?sale'                         THEN 'hot_sale'
             WHEN n ~ 'buen_?fin'                         THEN 'buen_fin'
             WHEN n ~ '(regreso_a_clases|back_to_school)' THEN 'regreso_a_clases'
             WHEN n ~ '(halloween|muertos)'               THEN 'halloween_dia_de_muertos'
             WHEN n ~ 'navid'                             THEN 'navidad'
             WHEN n ~ 'liquidaci'                         THEN 'liquidacion'
             WHEN n ~ 'aniversario'                       THEN 'aniversario'
             WHEN n ~ 'ofert(o)?n'                        THEN 'ofertones'
             WHEN n ~ 'fiestas?_?patrias'                 THEN 'fiestas_patrias'
           END AS slug
    FROM ev
),
camp AS (SELECT * FROM cl WHERE slug IS NOT NULL),
base AS (
    SELECT e.id, e.folleto_id FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
fol_camp AS (SELECT DISTINCT folleto_id FROM camp),
filas_pagina AS (SELECT DISTINCT folleto_id, slug FROM camp)
SELECT 'A registros (vista)' AS medida, (SELECT COUNT(*) FROM v_precios_actuales) AS todos,
       (SELECT COUNT(*) FROM v_precios_actuales v WHERE EXISTS (
           SELECT 1 FROM camp c JOIN folletos f ON f.id = c.folleto_id
           WHERE f.fuente = v.fuente AND f.folleto_id_fuente = v.folleto_id_fuente)) AS con_promo,
       (SELECT COUNT(*) FROM v_precios_actuales v WHERE NOT EXISTS (
           SELECT 1 FROM camp c JOIN folletos f ON f.id = c.folleto_id
           WHERE f.fuente = v.fuente AND f.folleto_id_fuente = v.folleto_id_fuente)) AS sin_promo
UNION ALL
SELECT 'B registros (tabla base)', (SELECT COUNT(*) FROM base),
       (SELECT COUNT(*) FROM base WHERE folleto_id IN (SELECT folleto_id FROM fol_camp)),
       (SELECT COUNT(*) FROM base WHERE folleto_id NOT IN (SELECT folleto_id FROM fol_camp))
UNION ALL
SELECT 'B registros con etiqueta (agregado por folleto antes de unir)',
       (SELECT COUNT(*) FROM base b LEFT JOIN (SELECT folleto_id, ARRAY_AGG(DISTINCT slug) AS s FROM camp GROUP BY 1) x
          ON x.folleto_id = b.folleto_id), NULL, NULL
UNION ALL
-- Comparativa (min. 2 tiendas): mismo EXISTS anidado que genera el ORM (modo "comparativa")
SELECT 'Comparativa: grupos (con = algun registro en folleto con campania)',
       (SELECT COUNT(*) FROM v_comparativa_precios c WHERE c.num_tiendas >= 2),
       (SELECT COUNT(*) FROM v_comparativa_precios c WHERE c.num_tiendas >= 2 AND EXISTS (
           SELECT 1 FROM extracciones v0 WHERE v0.texto_norm = c.producto AND v0.tipo = 'PRECIO' AND v0.valor IS NOT NULL
             AND COALESCE(v0.categoria_nlp, '') = COALESCE(c.categoria, '')
             AND EXISTS (SELECT 1 FROM camp u0 WHERE u0.folleto_id = v0.folleto_id))),
       (SELECT COUNT(*) FROM v_comparativa_precios c WHERE c.num_tiendas >= 2 AND NOT EXISTS (
           SELECT 1 FROM extracciones v0 WHERE v0.texto_norm = c.producto AND v0.tipo = 'PRECIO' AND v0.valor IS NOT NULL
             AND COALESCE(v0.categoria_nlp, '') = COALESCE(c.categoria, '')
             AND EXISTS (SELECT 1 FROM camp u0 WHERE u0.folleto_id = v0.folleto_id)))
UNION ALL
-- Comparativa por otro camino: agrega extracciones por (texto, categoria) con BOOL_OR
SELECT 'Comparativa B: grupos recalculados con BOOL_OR',
       COUNT(*), COUNT(*) FILTER (WHERE en_camp), COUNT(*) FILTER (WHERE NOT en_camp)
FROM (SELECT e.texto_norm, e.categoria_nlp, BOOL_OR(e.folleto_id IN (SELECT folleto_id FROM fol_camp)) AS en_camp
      FROM extracciones e WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      GROUP BY e.texto_norm, e.categoria_nlp HAVING COUNT(DISTINCT e.tienda_id) >= 2) g
UNION ALL
SELECT 'Pagina: filas (folleto, campania) / folletos / precios en esos folletos',
       (SELECT COUNT(*) FROM filas_pagina), (SELECT COUNT(*) FROM fol_camp),
       (SELECT COUNT(*) FROM base WHERE folleto_id IN (SELECT folleto_id FROM fol_camp))
UNION ALL
SELECT 'Pagina: campanias distintas / tiendas / folletos vigentes hoy',
       (SELECT COUNT(DISTINCT slug) FROM camp),
       (SELECT COUNT(DISTINCT f.tienda_id) FROM fol_camp fc JOIN folletos f ON f.id = fc.folleto_id),
       (SELECT COUNT(*) FROM fol_camp fc JOIN v_folletos_vigencia v ON v.id = fc.folleto_id WHERE v.vigente)
