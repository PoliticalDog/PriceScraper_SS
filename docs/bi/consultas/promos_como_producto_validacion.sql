-- Validacion independiente de promos_como_producto.sql: mismo clasificador, pero desde la vista v_precios_actuales
-- (columna producto, sin join a la fila PRODUCTO) y el metodo_norm contado con EXISTS en vez de LEFT JOIN.
-- Debe cuadrar fila a fila con promos_como_producto.sql (registros y heuristico).
-- Esperado 12-oct-2026: total 28,634; no-producto 2,912 (promo/condicion/servicio/vigencia 1,662 + unidad 1,250),
-- todos heuristicos (0 de catalogo).
WITH base AS (
    SELECT v.id, translate(lower(v.producto), 'áéíóúüñ', 'aeiouun') AS n,
           EXISTS (SELECT 1 FROM extracciones e JOIN extracciones p ON p.id = e.producto_extraccion_id
                   WHERE e.id = v.id AND p.metodo_norm = 'heuristico') AS es_heur
    FROM v_precios_actuales v
),
clas AS (
    SELECT b.*,
        CASE
        WHEN n ~ '(suscrip|\menvio\M|garantia|^meses de proteccion|^proteccion$|^recargas?\M|membres|inscribete|robo .* extravio|instalacion)'
            THEN 'servicio'
        WHEN n ~ '(^|\m)(meses|mesess?|messs|mesessin|mesessis|mesesses|heses|hesessin)(\M|$)|inter[e]?s[e]?s|intcrcscs|interescs|\mmsi\M|^omsi|quincenas?|\mpagos?\M|solo pa[cg]o|\mpagala|pagando con|tarjeta|\mcredito|contado'
            THEN 'msi_financiamiento'
        WHEN (n ~ '(^|\m)(t|oco)?pu[nh]tos\M' AND n !~ 'pres[il]') OR n ~ '(monedero|bonific|regala|^teregal|^toregal|t[il]cket|acumular?\M|^saldo al)'
            THEN 'lealtad_puntos'
        WHEN n ~ '(vigencia|vigcncla|del? ?[0-9]{1,2} ?de ?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)|al ?[0-9]{1,2} ?de ?(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)|^[0-9]{1,2} al [0-9])'
            THEN 'vigencia'
        WHEN n ~ '^(i?desde|hasta( ?[,$_]| ?[0-9]+$|$)|p?preciazo|promo ahorro|descuento|multiahorro|ahorra|ahorros?$|precio (regular|reqular|individual|indiviclual)|estos precios|los precios|el precio|al precio|oferta|en ofertal?$|rebaj|super rebajados|grandes ahorros|de ahorro|delahorro|pesos ?de ?descuento|obten hasta|super$|00 ahorras|ahorras desde)'
             OR n ~ 'precio mas bajo'
            THEN 'precio_generico'
        WHEN n ~ '(d[cle]{1,2} ?compra|decompra|en la compra|comprando|compra un[oa]|haz una compra|primera compra|todas tus compras|^comprar$|ll.vate|\mlleva\M|^ylleva|\m[2-4] ?x ?[1-3]\M|segundo|amit[a]?d|^eliges$|escoge|^adicional(es)?\M|participantes|seleccionad|aplica|apfican|apflcan|restricci|no incluyen?\M|existencias|exclusiv|busca los|v.lid|departamento|misma linea|^cada$|^incluye$)'
            THEN 'condicion_compra'
        WHEN n ~ '^(cart.n|carron|garton|canton|crton|caron|piezas?|plezas|paquete( de)?|paquere|paqucte|pequete|gramos|productos?|pack|individual|rollos|variedad( de)?|saco|grande pieza|[0-9]+ pzas)$'
            THEN 'unidad_presentacion'
        END AS patron
    FROM base b
)
SELECT coalesce(patron, '~producto') AS patron, count(*) AS registros,
       count(*) FILTER (WHERE es_heur) AS heuristico
FROM clas
GROUP BY ROLLUP (1)
ORDER BY 1
