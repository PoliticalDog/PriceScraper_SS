-- Calidad de eventos_promo (nivel A: campania del folleto). Evaluacion 14-oct-2026, sin cambios en la BD.
-- Clasifica nombre_evento con reglas BI explicitas (no es el normalizador del pipeline):
--   campania  : temporada o campania comercial reconocible (julio regalado, hot sale, buen fin, regreso a clases /
--               back to school, navidad, halloween/muertos, liquidacion)
--   lema      : eslogan permanente de la tienda ("precios bajos todos los dias", "la supercampeona...", "precio especial")
--   legal     : texto legal/condiciones ("excepto codigos de liquidacion", "tiendas participantes", "sucursales")
--   producto  : nombre de un articulo que contiene la palabra de temporada (vela/figura/banio navidad, hojas)
-- y devuelve cuantos eventos, folletos y registros del dashboard caen en cada clase.
WITH ev AS (
    SELECT ep.*,
           CASE
             WHEN nombre_evento ~ '(vela|figura|bao_navidad|hojas)'                         THEN 'producto'
             WHEN nombre_evento ~ '(excepto|participantes|sucursales|apllcan)'              THEN 'legal'
             WHEN nombre_evento ~ '(julio_?regalado|hot_sale|buen_fin|regreso_a_clases|back_to_school|navidad|halloween|muertos|liquidacion)'
                                                                                            THEN 'campania'
             WHEN nombre_evento ~ '(precio|supercamp|calidad_a|super_oferta)'               THEN 'lema'
             ELSE 'otro'
           END AS clase
    FROM eventos_promo ep
),
reg AS (
    -- registros del dashboard (= v_precios_actuales) por folleto, desde la tabla base
    SELECT e.folleto_id, COUNT(*) AS registros FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
    GROUP BY e.folleto_id
)
SELECT clase,
       COUNT(*)                                   AS eventos,
       COUNT(DISTINCT nombre_evento)              AS nombres_distintos,
       COUNT(DISTINCT ev.folleto_id)              AS folletos,
       COUNT(DISTINCT ev.tienda_id)               AS tiendas,
       (SELECT COALESCE(SUM(r.registros), 0) FROM reg r
         WHERE r.folleto_id IN (SELECT e2.folleto_id FROM ev e2 WHERE e2.clase = ev.clase)) AS registros_en_esos_folletos,
       STRING_AGG(DISTINCT LEFT(nombre_evento, 30), ' | ')  AS ejemplos
FROM ev
GROUP BY clase
ORDER BY eventos DESC
