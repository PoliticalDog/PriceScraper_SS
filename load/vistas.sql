-- vistas BI para análisis de precios, comparativas y calidad del pipelin
-- uso: psql -U <usuario> -d <base_datos> -f vistas.sql--


-- v_precios_actuales
-- Precios extraídos con descuento calculado y metadata del folleto.
-- Para precios vigentes hoy filtrar: WHERE vigencia_hasta >= CURRENT_DATE
-- "id" agregado 23-ago-2026 (= extracciones.id, real y unico por fila) --
-- requisito de Django ORM: todo modelo managed=False necesita una PK.


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


-- v_comparativa_precios
-- Rango de precios por producto entre tiendas.
-- Solo productos con 2+ registros para que la comparativa sea significativa.
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


-- v_calidad_pipeline
-- Métricas de calidad OCR/NLP por folleto.
-- Útil para detectar folletos con baja tasa útil o mala confianza OCR.
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


-- v_historico_precios
-- Evolución de precio de un producto a lo largo del tiempo por tienda.
-- Base para gráficas de tendencia en el dashboard BI.
-- "id" agregado 23-ago-2026 (= extracciones.id) -- ver nota en v_precios_actuales.
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


-- v_folletos_vigencia
-- Una fila por folleto con su vigencia y una etiqueta de fecha dudosa (12-oct-2026, panel de cobertura).
-- Unica definicion de "vigente" para el dashboard (cobertura, precios actuales, resumen). No corrige fechas:
-- solo etiqueta, en este orden de precedencia:
--   sin_fecha                fecha_inicio o fecha_fin NULL
--   fin_antes_inicio         fecha_fin < fecha_inicio
--   inicio_antiguo           fecha_inicio < scrapeado_at - 365 dias   (ej. soriana_hiper 430896, 2022-09-01)
--   inicio_futuro_vs_scrapeo fecha_inicio > scrapeado_at + 30 dias    (ej. waldos con inicio 25-dic scrapeado en oct)
--   vigencia_larga           fecha_fin - fecha_inicio > 120 dias      (ej. bodega_aurrera "todo el anio")
-- vigente        = sin etiqueta y fecha_inicio <= hoy <= fecha_fin
-- vigente_dudoso = con etiqueta y en rango (se muestra aparte, no se suma a vigente)
-- proximo        = sin etiqueta y fecha_inicio > hoy
-- Validacion al crearla: 52 vigentes, 16 vigentes con fecha dudosa, 2 proximos (12-oct-2026).
CREATE OR REPLACE VIEW v_folletos_vigencia AS
WITH fol AS (
    SELECT
        f.id,
        f.tienda_id,
        t.slug          AS tienda_slug,
        t.nombre        AS tienda,
        f.fuente,
        f.folleto_id_fuente,
        f.titulo,
        f.fecha_inicio,
        f.fecha_fin,
        f.scrapeado_at,
        f.total_paginas,
        CASE
            WHEN f.fecha_inicio IS NULL OR f.fecha_fin IS NULL        THEN 'sin_fecha'
            WHEN f.fecha_fin < f.fecha_inicio                         THEN 'fin_antes_inicio'
            WHEN f.fecha_inicio < f.scrapeado_at::date - 365          THEN 'inicio_antiguo'
            WHEN f.fecha_inicio > f.scrapeado_at::date + 30           THEN 'inicio_futuro_vs_scrapeo'
            WHEN f.fecha_fin - f.fecha_inicio > 120                   THEN 'vigencia_larga'
        END             AS anomalia_fecha
    FROM folletos f
    JOIN tiendas t ON t.id = f.tienda_id
)
SELECT
    fol.*,
    (anomalia_fecha IS NULL     AND fecha_inicio <= CURRENT_DATE AND fecha_fin >= CURRENT_DATE) AS vigente,
    (anomalia_fecha IS NOT NULL AND fecha_inicio <= CURRENT_DATE AND fecha_fin >= CURRENT_DATE) AS vigente_dudoso,
    (anomalia_fecha IS NULL     AND fecha_inicio > CURRENT_DATE)                                AS proximo
FROM fol;

COMMENT ON VIEW v_folletos_vigencia IS
    'Vigencia por folleto con etiqueta de fecha dudosa (anomalia_fecha). Unica definicion de vigente para el dashboard.';


-- v_eventos_activos
-- Campañas promocionales vigentes hoy.
-- "id" agregado 23-ago-2026 -- MIN(ep.id), NO ep.id en el GROUP BY: un primer
-- intento agrego ep.id directo al GROUP BY y esto rompio la agregacion (la
-- vista paso de ~44 filas agrupadas por texto de campana a 131, una por fila
-- cruda de eventos_promo, perdiendo el COUNT sumado entre folletos) --
-- detectado comparando el conteo de la vista contra SELECT COUNT(*) FROM
-- eventos_promo antes de comitear. MIN(ep.id) da un id estable por grupo sin
-- tocar que columnas definen el agrupamiento.
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


-- v_comparativa_precios_v2 + clave_comparativa (fase 1, aprobada por la persona 26-oct-2026).
-- Fuente: docs/bi/consultas/comparativa_clave_flexible_propuesta.sql (generado por
-- tests/_herramienta_bi_claves_comparativa.py; si cambia el catalogo, regenerar ahi y copiar aqui).
-- Requiere tiendas.cadena (load/schema.sql). v_comparativa_precios (arriba) sigue siendo la del panel.
-- 2) Clave de comparacion del texto (kar): minusculas, sin acentos ni puntuacion, unidades unificadas
--    (1 Kg = 1kg = 1 kilo; medio kilo = 500 g), sin relleno, palabras unicas y ordenadas. NULL si el texto es
--    un generico de catalogo (Refresco, Galletas, Smart TV...) o no tiene >= 2 palabras de contenido (salvo
--    una fruta/verdura sola: "Pepino", "Jicama").
CREATE OR REPLACE FUNCTION clave_comparativa(p_texto text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT (
    WITH n AS (SELECT ' ' || btrim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
            translate(lower(regexp_replace(regexp_replace(lower(p_texto), '\ymedio\s+(?:kilos?|kgs?)\y', '500 g', 'g'), '\y1\s*/\s*2\s*(?:kilos?|kgs?)\y', '500 g', 'g')), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc'),
            '(\d),(\d{3})\y', '\1\2', 'g'),
            '(\d),(\d{1,2})\y', '\1.\2', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:kilogramos?|kilos?|kgs?)\y', '\1kg', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:gramos?|grms?|grs?|gr|g)\y', '\1g', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:mililitros?|mls?)\y', '\1ml', 'g'),
            '(\d+(?:\.\d+)?)\s*(?:litros?|lts?|lt|l)\y', '\1l', 'g'),
            '(\d+)\s*(?:piezas?|pzas?|pzs?|pz)\y', '\1pza', 'g'),
            '\y(?:kilogramos?|kilos?|kgs?)\y', 'kg', 'g'),
            '\y(?:piezas?|pzas?|pzs?)\y', 'pza', 'g'),
            '[^a-z0-9.]+', ' ', 'g'),
            '(?<![0-9])\.|\.(?![0-9])', ' ', 'g')) || ' ' AS t1),
    tok AS (
        SELECT w FROM n, regexp_split_to_table(btrim(regexp_replace(n.t1, '\y(?:de|del|la|las|el|los|con|en|para|y|o|0|a|al|por|un|una|e|c|u|cada|uno|ejemplo|precio|oferta)\y', ' ', 'g')), '\s+') AS w
        WHERE w <> ''
    ),
    k AS (
        SELECT string_agg(DISTINCT w, ' ' ORDER BY w) AS clave,
               COUNT(DISTINCT w) FILTER (WHERE w !~ '^([0-9.]+(kg|g|ml|l|pza)?|kg|g|ml|l|pza)$') AS contenido,
               MAX(w) FILTER (WHERE w !~ '^([0-9.]+(kg|g|ml|l|pza)?|kg|g|ml|l|pza)$') AS palabra
        FROM tok
    )
    SELECT CASE
               WHEN p_texto = ANY (ARRAY['Aceite de aguacate', 'Aceite de canola', 'Aceite de coco', 'Aceite de maíz', 'Aceite de oliva', 'Aceite de soya', 'Aceite vegetal', 'Acondicionador', 'Aderezos', 'Agua natural', 'Aire acondicionado', 'Arroz', 'Atún en agua', 'Audifonos', 'Avena', 'Azúcar', 'Bocina Bluetooth', 'Bolsas de basura', 'Cafetera', 'Café', 'Cereal', 'Cerveza', 'Chorizo', 'Chía', 'Cloro', 'Crema', 'Croquetas para gato', 'Croquetas para perro', 'Desodorante', 'Detergente', 'Esponja', 'Estufa', 'FIFA', 'Frijol negro', 'Frijol pinto', 'Galletas', 'Harina de trigo', 'Jamón', 'Jugo', 'Ketchup', 'Laptop', 'Lavadora', 'Leche deslactosada', 'Leche entera', 'Leche light', 'Lenteja', 'Licuadora', 'Mantequilla', 'Mario Kart', 'Mayonesa', 'Microondas', 'PS5', 'Pan de caja', 'Pantalón', 'Papel de cocina', 'Papel higiénico', 'Pasta dental', 'Pasta para sopa', 'Pañales', 'Pijama', 'Playera', 'Queso Oaxaca', 'Queso fresco', 'Rastrillo', 'Refresco', 'Refrigerador', 'Sal', 'Salchicha', 'Salsa', 'Secadora', 'Shampoo', 'Smart TV', 'Smartphone', 'Spider-Man', 'Suavizante de telas', 'Tenis', 'Tinte para cabello', 'Toallitas húmedas', 'Tortillas de maíz', 'Ventilador', 'Vestido', 'Vinagre', 'Vino tinto', 'Yogurt']) THEN NULL
               WHEN contenido >= 2 OR (contenido = 1 AND palabra = ANY (ARRAY['melon', 'sandia', 'papa', 'jicama', 'chile', 'cebolla', 'tomate', 'jitomate', 'aguacate', 'limon', 'zanahoria', 'elote', 'brocoli', 'lechuga', 'pepino', 'manzana', 'platano', 'naranja', 'fresa', 'frambuesa', 'arandano', 'zarzamora', 'uva', 'uvas', 'pina', 'mango', 'durazno', 'cereza', 'mandarina', 'pera', 'tuna', 'acelga', 'espinaca', 'calabacita', 'calabaza', 'chayote', 'cilantro', 'champinones', 'tomatillo', 'cebollita', 'aguacatito', 'apio', 'hass', 'pimiento', 'morron', 'poblano', 'chilaca'])) THEN clave
           END
    FROM k
)
$$;

-- 3) Vista nueva (la actual v_comparativa_precios no se toca hasta que la persona apruebe cambiar el panel).
CREATE OR REPLACE VIEW v_comparativa_precios_v2 AS
WITH base AS (
    SELECT e.id, clave_comparativa(e.texto_norm) AS clave, e.texto_norm, e.categoria_nlp, e.valor, e.tienda_id,
           t.nombre AS tienda, COALESCE(t.cadena, t.slug) AS cadena
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND e.valor BETWEEN 1 AND 100000
),
grp AS (
    SELECT clave FROM base WHERE clave IS NOT NULL GROUP BY clave HAVING COUNT(DISTINCT cadena) >= 2
),
por_cadena AS (
    SELECT b.clave, b.cadena, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.valor) AS mediana
    FROM base b JOIN grp USING (clave)
    GROUP BY b.clave, b.cadena
),
disp AS (
    SELECT clave, MAX(mediana) / NULLIF(MIN(mediana), 0) AS ratio_medianas FROM por_cadena GROUP BY clave
)
SELECT MIN(b.id)                                                       AS id,   -- PK para Django (managed=False)
       b.clave                                                         AS clave,
       MODE() WITHIN GROUP (ORDER BY b.texto_norm)                     AS producto,
       COUNT(DISTINCT b.texto_norm)                                    AS num_textos,
       MODE() WITHIN GROUP (ORDER BY NULLIF(BTRIM(b.categoria_nlp), '')) AS categoria,
       MIN(b.valor)                                                    AS precio_min,
       MAX(b.valor)                                                    AS precio_max,
       ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY b.valor)::numeric, 2) AS precio_mediana,
       ROUND(d.ratio_medianas::numeric, 2)                             AS ratio_medianas_cadena,
       (d.ratio_medianas > 10)                                         AS precio_sospechoso,
       COUNT(*)                                                        AS num_registros,
       COUNT(DISTINCT b.tienda_id)                                     AS num_tiendas,
       COUNT(DISTINCT b.cadena)                                        AS num_cadenas,
       STRING_AGG(DISTINCT b.tienda, ', ' ORDER BY b.tienda)           AS tiendas
FROM base b
JOIN grp USING (clave)
JOIN disp d USING (clave)
GROUP BY b.clave, d.ratio_medianas;

COMMENT ON VIEW v_comparativa_precios_v2 IS
    'Comparativa por clave flexible (clave_comparativa del texto) en >= 2 cadenas. Ver docs/bi/metricas.md sec. 8.';
