-- Clave (a) "texto normalizado" de la Comparativa: ejemplos de textos que se juntan (docs/bi/metricas.md sec. 8).
-- Muestra claves con >= 2 texto_norm distintos y >= 2 cadenas.
WITH cad(slug, cadena) AS (
    VALUES ('soriana_hiper', 'soriana'), ('soriana_mercado', 'soriana'),
           ('walmart', 'walmart'), ('walmart_express', 'walmart')
),
base AS (
    SELECT e.id, e.texto_norm, e.valor, COALESCE(cad.cadena, t.slug) AS cadena,
           translate(lower(e.texto_norm), 'áàäâãéèëêíìïîóòöôõúùüûñç', 'aaaaaeeeeiiiiooooouuuunc') AS t0
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    LEFT JOIN cad ON cad.slug = t.slug
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
n1 AS (
    SELECT id, texto_norm, valor, cadena,
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(regexp_replace(
        regexp_replace(regexp_replace(regexp_replace(regexp_replace(t0,
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
            '(?<![0-9])\.|\.(?![0-9])', ' ', 'g') AS t1
    FROM base
),
ka AS (
    SELECT id, texto_norm, valor, cadena,
           (SELECT string_agg(DISTINCT w, ' ' ORDER BY w)
              FROM regexp_split_to_table(
                     regexp_replace(t1, '\y(?:de|del|la|las|el|los|con|en|para|y|o|0|a|al|por|un|una|e|c|u)\y', ' ', 'g'),
                     '\s+') AS w
             WHERE w <> '') AS clave
    FROM n1
)
SELECT clave, COUNT(*) AS regs, COUNT(DISTINCT cadena) AS cadenas, COUNT(DISTINCT texto_norm) AS textos,
       LEFT(STRING_AGG(DISTINCT texto_norm, ' | '), 160) AS ejemplos
FROM ka
GROUP BY clave
HAVING COUNT(DISTINCT cadena) >= 2 AND COUNT(DISTINCT texto_norm) >= 2
ORDER BY regs DESC
