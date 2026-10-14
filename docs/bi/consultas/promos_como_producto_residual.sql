-- Residuo tras 2f616c3 + 6d0670b (BD recargada 12-oct-2026, 27,760 registros de dashboard): rotulos de promocion,
-- financiamiento, lealtad, pago o condicion que el clasificador de promos_como_producto.sql NO detecta porque son
-- variantes OCR nuevas ("Puncos", "Tererala", "Geses Sln", "Incereses", "Prccio Rcqule") o rotulos no cubiertos
-- (Bbva, Comision, PayPal, cupon, "Waldo's Premia", "Maximo 10 Kg por cliente", "Por Cada").
-- Se mantiene aparte para no romper la comparabilidad antes/despues de promos_como_producto.sql.
-- Excluidos a proposito: "Precissimo" (marca propia de Soriana; solo es nombre pobre si va solo) y "Kiwo"
-- (marca de motos/scooters en Waldo's), "Ia Solo" y "Ganas" (fragmentos sin significado claro).
-- No se solapa con promos_como_producto.sql (sus variantes "Heses"/"Intcrcscs" ya las cuenta aquel).
-- Grano: patron x tienda x texto_norm (+ ROLLUP). Esperado 12-oct-2026: 84 registros
--   (msi_pago 42, lealtad 19, precio_generico 16, condicion 7).
WITH base AS (
    SELECT e.id, e.tienda_id, e.texto_norm, e.valor,
           translate(lower(e.texto_norm), 'áéíóúüñ', 'aeiouun') AS n
    FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
),
clas AS (
    SELECT b.*,
        CASE
        WHEN n ~ '^(geses|incereses)' OR n ~ '(tarjera|^bbva$|comision|paypal|aplazo|kueski|cupon|paysoo|^transfer$)'
            THEN 'msi_pago_variante'
        WHEN n ~ '^(pu[nh]?[ct]?os|punos|puncos)$' OR n ~ '^t[eo]r[eo][gr]al' OR n ~ 'premia$'
            THEN 'lealtad_variante'
        WHEN n ~ '^(prccio|por cada$)'
            THEN 'precio_generico_variante'
        WHEN n ~ '(maximo .*por cliente|^maximo$)'
            THEN 'condicion_variante'
        END AS patron
    FROM base b
)
SELECT c.patron, t.slug AS tienda, c.texto_norm, count(*) AS registros
FROM clas c JOIN tiendas t ON t.id = c.tienda_id
WHERE c.patron IS NOT NULL
GROUP BY ROLLUP ((c.patron), (t.slug, c.texto_norm))
ORDER BY c.patron NULLS LAST, registros DESC
