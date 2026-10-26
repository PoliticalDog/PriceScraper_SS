-- Comparativa: linea base de la clave actual (texto_norm, categoria_nlp) de v_comparativa_precios
-- (docs/bi/metricas.md seccion 8, 25-oct-2026).
-- "cadena" NO existe en la tabla tiendas: se propone aqui como mapeo fijo (CTE cad). Soriana Hiper y Soriana
-- Mercado comparten precio en ~50% de sus grupos (comparativa_pares_tiendas.sql); Walmart y Walmart Express son
-- la misma marca. Bodega Aurrera y Sam's Club se dejan como cadena propia (otro formato y otra politica de
-- precio, aunque sean del mismo grupo Walmex): la persona decide.
-- Columnas: grupos/registros de la vista (>= 2 tiendas), cuantos tienen >= 2 cadenas, registros en esos grupos,
-- pares de cadenas distintos y la dispersion max/min (mediana y % con max/min > 3).
WITH cad(slug, cadena) AS (
    VALUES ('soriana_hiper', 'soriana'), ('soriana_mercado', 'soriana'),
           ('walmart', 'walmart'), ('walmart_express', 'walmart')
),
base AS (
    SELECT e.id, e.texto_norm, e.categoria_nlp, e.valor, e.tienda_id,
           COALESCE(cad.cadena, t.slug) AS cadena
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    LEFT JOIN cad ON cad.slug = t.slug
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
grp AS (
    SELECT texto_norm, categoria_nlp,
           COUNT(*) AS registros,
           COUNT(DISTINCT tienda_id) AS tiendas,
           COUNT(DISTINCT cadena) AS cadenas,
           MAX(valor) / NULLIF(MIN(valor), 0) AS max_min
    FROM base
    GROUP BY texto_norm, categoria_nlp
    HAVING COUNT(DISTINCT tienda_id) > 1
),
pares AS (   -- pares de cadenas distintos que aparecen juntos en algun grupo con >= 2 cadenas
    SELECT DISTINCT a.cadena AS ca, b.cadena AS cb
    FROM (SELECT DISTINCT texto_norm, COALESCE(categoria_nlp, '') c, cadena FROM base) a
    JOIN (SELECT DISTINCT texto_norm, COALESCE(categoria_nlp, '') c, cadena FROM base) b
      ON b.texto_norm = a.texto_norm AND b.c = a.c AND b.cadena > a.cadena
)
SELECT
    (SELECT COUNT(*) FROM grp)                                        AS grupos_vista,
    (SELECT SUM(registros) FROM grp)                                  AS registros_vista,
    (SELECT COUNT(*) FROM grp WHERE cadenas >= 2)                     AS grupos_2cadenas,
    (SELECT SUM(registros) FROM grp WHERE cadenas >= 2)               AS registros_2cadenas,
    (SELECT COUNT(*) FROM grp WHERE cadenas >= 3)                     AS grupos_3cadenas,
    (SELECT COUNT(*) FROM pares)                                      AS pares_cadenas,
    (SELECT ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY max_min)::numeric, 2)
       FROM grp WHERE cadenas >= 2)                                   AS mediana_max_min_2cad,
    (SELECT ROUND(100.0 * COUNT(*) FILTER (WHERE max_min > 3) / COUNT(*), 1)
       FROM grp WHERE cadenas >= 2)                                   AS pct_max_min_gt3_2cad
