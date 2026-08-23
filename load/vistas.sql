-- =============================================================================
-- PriceScraper MX — vistas.sql
-- Vistas BI para análisis de precios, comparativas y calidad del pipeline
--
-- Requiere que schema.sql ya haya sido ejecutado.
--
-- Uso:
--   psql -U <usuario> -d <base_datos> -f vistas.sql
--
-- Todas las vistas usan CREATE OR REPLACE — se pueden actualizar sin DROP.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- v_precios_actuales
-- Precios extraídos con descuento calculado y metadata del folleto.
-- Para precios vigentes hoy filtrar: WHERE vigencia_hasta >= CURRENT_DATE
-- "id" agregado 23-ago-2026 (= extracciones.id, real y unico por fila) --
-- requisito de Django ORM: todo modelo managed=False necesita una PK.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_precios_actuales AS
SELECT
    t.nombre                                                    AS tienda,
    t.slug                                                      AS tienda_slug,
    e.texto_norm                                                AS producto,
    e.categoria_nlp                                             AS categoria,
    e.valor                                                     AS precio_actual,
    e.valor_anterior                                            AS precio_anterior,
    CASE
        WHEN e.valor_anterior IS NOT NULL
         AND e.valor_anterior > e.valor
        THEN ROUND(
            ((e.valor_anterior - e.valor) / e.valor_anterior * 100)::NUMERIC, 1
        )
    END                                                         AS descuento_pct,
    f.fecha_inicio                                              AS vigencia_desde,
    f.fecha_fin                                                 AS vigencia_hasta,
    f.fuente,
    f.folleto_id_fuente,
    e.confianza_ocr,
    e.created_at,
    e.id                                                         AS id
FROM extracciones e
JOIN tiendas  t ON t.id = e.tienda_id
JOIN folletos f ON f.id = e.folleto_id
WHERE e.tipo  = 'PRECIO'
  AND e.valor IS NOT NULL
  AND e.texto_norm IS NOT NULL;

COMMENT ON VIEW v_precios_actuales IS
    'Precios con descuento calculado y metadata de folleto. '
    'Filtrar WHERE vigencia_hasta >= CURRENT_DATE para precios activos.';


-- -----------------------------------------------------------------------------
-- v_comparativa_precios
-- Rango de precios por producto entre tiendas.
-- Solo productos con 2+ registros para que la comparativa sea significativa.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_comparativa_precios AS
SELECT
    e.texto_norm                                AS producto,
    e.categoria_nlp                             AS categoria,
    MIN(e.valor)                                AS precio_min,
    MAX(e.valor)                                AS precio_max,
    ROUND(AVG(e.valor)::NUMERIC, 2)             AS precio_promedio,
    MAX(e.valor) - MIN(e.valor)                 AS diferencia,
    COUNT(*)                                    AS num_registros,
    COUNT(DISTINCT e.tienda_id)                 AS num_tiendas,
    STRING_AGG(DISTINCT t.nombre, ', '
        ORDER BY t.nombre)                      AS tiendas
FROM extracciones e
JOIN tiendas t ON t.id = e.tienda_id
WHERE e.tipo      = 'PRECIO'
  AND e.valor     IS NOT NULL
  AND e.texto_norm IS NOT NULL
GROUP BY e.texto_norm, e.categoria_nlp
HAVING COUNT(DISTINCT e.tienda_id) > 1;

COMMENT ON VIEW v_comparativa_precios IS
    'Rango de precios por producto entre tiendas. '
    'Solo productos presentes en 2+ tiendas.';


-- -----------------------------------------------------------------------------
-- v_calidad_pipeline
-- Métricas de calidad OCR/NLP por folleto.
-- Útil para detectar folletos con baja tasa útil o mala confianza OCR.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_calidad_pipeline AS
SELECT
    f.id                                            AS folleto_id,
    t.nombre                                        AS tienda,
    f.folleto_id_fuente,
    f.fuente,
    f.fecha_inicio,
    f.total_paginas,
    COUNT(DISTINCT p.id)                            AS paginas_procesadas,
    SUM(p.total_productos)                          AS total_productos,
    SUM(p.total_precios)                            AS total_precios,
    SUM(p.total_promos)                             AS total_promos,
    ROUND(AVG(p.confianza_ocr_prom)::NUMERIC, 3)   AS confianza_ocr_prom,
    ROUND(AVG(p.tasa_util)::NUMERIC, 3)             AS tasa_util_prom,
    f.perfil_ocr,
    f.motor_ocr,
    f.estado,
    f.scrapeado_at
FROM folletos f
JOIN tiendas  t ON t.id = f.tienda_id
LEFT JOIN paginas p ON p.folleto_id = f.id
GROUP BY
    f.id, t.nombre, f.folleto_id_fuente, f.fuente,
    f.fecha_inicio, f.total_paginas, f.perfil_ocr,
    f.motor_ocr, f.estado, f.scrapeado_at;

COMMENT ON VIEW v_calidad_pipeline IS
    'Métricas de calidad OCR/NLP por folleto. '
    'Detecta folletos con baja tasa_util_prom o confianza_ocr_prom.';


-- -----------------------------------------------------------------------------
-- v_historico_precios
-- Evolución de precio de un producto a lo largo del tiempo por tienda.
-- Base para gráficas de tendencia en el dashboard BI.
-- "id" agregado 23-ago-2026 (= extracciones.id) -- ver nota en v_precios_actuales.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_historico_precios AS
SELECT
    t.nombre                AS tienda,
    t.slug                  AS tienda_slug,
    e.texto_norm            AS producto,
    e.categoria_nlp         AS categoria,
    f.fecha_inicio          AS fecha,
    e.valor                 AS precio,
    e.valor_anterior        AS precio_anterior,
    f.folleto_id_fuente,
    f.fuente,
    e.id                     AS id
FROM extracciones e
JOIN tiendas  t ON t.id = e.tienda_id
JOIN folletos f ON f.id = e.folleto_id
WHERE e.tipo      = 'PRECIO'
  AND e.valor     IS NOT NULL
  AND e.texto_norm IS NOT NULL
  AND f.fecha_inicio IS NOT NULL
ORDER BY e.texto_norm, t.slug, f.fecha_inicio;

COMMENT ON VIEW v_historico_precios IS
    'Evolución de precio por producto y tienda ordenada por fecha. '
    'Base para gráficas de tendencia en el dashboard.';


-- -----------------------------------------------------------------------------
-- v_eventos_activos
-- Campañas promocionales vigentes hoy.
-- "id" agregado 23-ago-2026 -- MIN(ep.id), NO ep.id en el GROUP BY: un primer
-- intento agrego ep.id directo al GROUP BY y esto rompio la agregacion (la
-- vista paso de ~44 filas agrupadas por texto de campana a 131, una por fila
-- cruda de eventos_promo, perdiendo el COUNT sumado entre folletos) --
-- detectado comparando el conteo de la vista contra SELECT COUNT(*) FROM
-- eventos_promo antes de comitear. MIN(ep.id) da un id estable por grupo sin
-- tocar que columnas definen el agrupamiento.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_eventos_activos AS
SELECT
    ep.nombre_evento,
    t.nombre            AS tienda,
    ep.fecha_inicio,
    ep.fecha_fin,
    ep.texto_raw,
    COUNT(e.id)         AS num_precios_asociados,
    MIN(ep.id)          AS id
FROM eventos_promo ep
JOIN tiendas t ON t.id = ep.tienda_id
LEFT JOIN extracciones e
    ON  e.folleto_id = ep.folleto_id
    AND e.tipo       = 'PRECIO'
WHERE ep.fecha_fin IS NULL
   OR ep.fecha_fin >= CURRENT_DATE
GROUP BY
    ep.nombre_evento, t.nombre,
    ep.fecha_inicio, ep.fecha_fin, ep.texto_raw
ORDER BY ep.fecha_inicio DESC;

COMMENT ON VIEW v_eventos_activos IS
    'Campañas promocionales vigentes hoy con conteo de precios asociados.';


-- =============================================================================
-- FIN vistas.sql
-- =============================================================================
