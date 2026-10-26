-- Medicion de la vista propuesta (comparativa_clave_flexible_propuesta.sql) SIN crearla: misma consulta con la
-- funcion y la cadena en linea. GENERADO por tests/_herramienta_bi_claves_comparativa.py. Esperado (25-oct-2026):
-- 132 grupos y 1,343 registros (= clave kar de candidatas.sql).
WITH cad(slug, cadena) AS (
    VALUES ('soriana_hiper', 'soriana'), ('soriana_mercado', 'soriana'),
           ('walmart', 'walmart'), ('walmart_express', 'walmart')
),
vista AS (
WITH base AS (
    SELECT e.id, (
    WITH n AS (SELECT ' ' || btrim(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
            translate(lower(regexp_replace(regexp_replace(lower(e.texto_norm), '\ymedio\s+(?:kilos?|kgs?)\y', '500 g', 'g'), '\y1\s*/\s*2\s*(?:kilos?|kgs?)\y', '500 g', 'g')), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc'),
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
               WHEN e.texto_norm = ANY (ARRAY['Aceite de aguacate', 'Aceite de canola', 'Aceite de coco', 'Aceite de maíz', 'Aceite de oliva', 'Aceite de soya', 'Aceite vegetal', 'Acondicionador', 'Aderezos', 'Agua natural', 'Aire acondicionado', 'Arroz', 'Atún en agua', 'Audifonos', 'Avena', 'Azúcar', 'Bocina Bluetooth', 'Bolsas de basura', 'Cafetera', 'Café', 'Cereal', 'Cerveza', 'Chorizo', 'Chía', 'Cloro', 'Crema', 'Croquetas para gato', 'Croquetas para perro', 'Desodorante', 'Detergente', 'Esponja', 'Estufa', 'FIFA', 'Frijol negro', 'Frijol pinto', 'Galletas', 'Harina de trigo', 'Jamón', 'Jugo', 'Ketchup', 'Laptop', 'Lavadora', 'Leche deslactosada', 'Leche entera', 'Leche light', 'Lenteja', 'Licuadora', 'Mantequilla', 'Mario Kart', 'Mayonesa', 'Microondas', 'PS5', 'Pan de caja', 'Pantalón', 'Papel de cocina', 'Papel higiénico', 'Pasta dental', 'Pasta para sopa', 'Pañales', 'Pijama', 'Playera', 'Queso Oaxaca', 'Queso fresco', 'Rastrillo', 'Refresco', 'Refrigerador', 'Sal', 'Salchicha', 'Salsa', 'Secadora', 'Shampoo', 'Smart TV', 'Smartphone', 'Spider-Man', 'Suavizante de telas', 'Tenis', 'Tinte para cabello', 'Toallitas húmedas', 'Tortillas de maíz', 'Ventilador', 'Vestido', 'Vinagre', 'Vino tinto', 'Yogurt']) THEN NULL
               WHEN contenido >= 2 OR (contenido = 1 AND palabra = ANY (ARRAY['melon', 'sandia', 'papa', 'jicama', 'chile', 'cebolla', 'tomate', 'jitomate', 'aguacate', 'limon', 'zanahoria', 'elote', 'brocoli', 'lechuga', 'pepino', 'manzana', 'platano', 'naranja', 'fresa', 'frambuesa', 'arandano', 'zarzamora', 'uva', 'uvas', 'pina', 'mango', 'durazno', 'cereza', 'mandarina', 'pera', 'tuna', 'acelga', 'espinaca', 'calabacita', 'calabaza', 'chayote', 'cilantro', 'champinones', 'tomatillo', 'cebollita', 'aguacatito', 'apio', 'hass', 'pimiento', 'morron', 'poblano', 'chilaca'])) THEN clave
           END
    FROM k
) AS clave, e.texto_norm, e.categoria_nlp, e.valor, e.tienda_id,
           t.nombre AS tienda, COALESCE(cad.cadena, t.slug) AS cadena
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    LEFT JOIN cad ON cad.slug = t.slug
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
GROUP BY b.clave, d.ratio_medianas
)
SELECT COUNT(*) AS grupos, SUM(num_registros) AS registros, SUM(num_textos) AS textos,
       COUNT(*) FILTER (WHERE num_cadenas >= 3) AS grupos_3cad,
       COUNT(*) FILTER (WHERE precio_sospechoso) AS grupos_precio_sospechoso
FROM vista
