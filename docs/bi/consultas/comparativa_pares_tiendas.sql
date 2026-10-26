-- Comparativa: pares de tiendas que comparten grupo en la clave actual (texto_norm, categoria_nlp) y que tan
-- seguido el precio es IDENTICO en las dos (senal de que comparten folleto / politica de precios, no de que
-- sean competidores). Base de la propuesta de "cadena" (docs/bi/metricas.md seccion 8, 25-oct-2026).
-- Grano: par de tiendas (a < b). Un grupo cuenta una vez por par.
WITH base AS (
    SELECT e.texto_norm, COALESCE(e.categoria_nlp, '') AS cat, t.slug, e.valor
    FROM extracciones e
    JOIN tiendas t ON t.id = e.tienda_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
gt AS (   -- grupo x tienda: conjunto de valores
    SELECT texto_norm, cat, slug, ARRAY_AGG(DISTINCT valor) AS valores
    FROM base
    GROUP BY texto_norm, cat, slug
),
pares AS (
    SELECT a.slug AS tienda_a, b.slug AS tienda_b,
           (a.valores && b.valores) AS algun_precio_igual
    FROM gt a
    JOIN gt b ON b.texto_norm = a.texto_norm AND b.cat = a.cat AND b.slug > a.slug
)
SELECT tienda_a, tienda_b,
       COUNT(*)                                   AS grupos_compartidos,
       COUNT(*) FILTER (WHERE algun_precio_igual) AS con_precio_igual,
       ROUND(100.0 * COUNT(*) FILTER (WHERE algun_precio_igual) / COUNT(*), 1) AS pct_precio_igual
FROM pares
GROUP BY tienda_a, tienda_b
ORDER BY grupos_compartidos DESC
