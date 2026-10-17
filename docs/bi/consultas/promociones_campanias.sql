-- Mapa de eventos_promo.nombre_evento -> (clase, slug canonico), espejo en SQL de dashboard/promociones.py
-- (Fase 1, docs/bi/metricas.md seccion 7, 15-oct-2026). MISMAS reglas y orden: si cambian alla, cambiar aqui (lo
-- vigila tests/test_dashboard_promociones.py). Una fila por nombre_evento distinto, para revisar el mapa.
WITH ev AS (
    SELECT ep.id, ep.folleto_id, ep.nombre_evento, LOWER(BTRIM(ep.nombre_evento)) AS n
    FROM eventos_promo ep
),
cl AS (
    SELECT ev.*,
           CASE
             WHEN n IN ('julio_regalado', 'hot_sale', 'buen_fin', 'regreso_a_clases', 'navidad',
                        'halloween_dia_de_muertos', 'liquidacion', 'aniversario', 'ofertones', 'fiestas_patrias') THEN 'campania'
             WHEN n ~ '(vela|figura|bao_navidad|hojas|cumplea|diferentes_)'                 THEN 'producto'
             WHEN n ~ '(excepto|participantes|sucursales|apllcan|aplican|restriccion)'      THEN 'legal'
             WHEN n ~ 'julio_?regalad' OR n ~ 'hot_?sale' OR n ~ 'buen_?fin'
               OR n ~ '(regreso_a_clases|back_to_school)' OR n ~ '(halloween|muertos)' OR n ~ 'navid'
               OR n ~ 'liquidaci' OR n ~ 'aniversario' OR n ~ 'ofert(o)?n'
               OR n ~ 'fiestas?_?patrias'                                                  THEN 'campania'
             WHEN n ~ '(precio|supercamp|calidad_a|oferta)'                                 THEN 'lema'
             ELSE 'otro'
           END AS clase,
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
)
SELECT LEFT(nombre_evento, 45) AS nombre_evento, clase, slug, COUNT(*) AS eventos, COUNT(DISTINCT folleto_id) AS folletos
FROM cl
GROUP BY nombre_evento, clase, slug
ORDER BY clase, slug NULLS LAST, eventos DESC, nombre_evento
