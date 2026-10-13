-- Ejemplos por patron (hasta 4 por patron y tienda) con folleto/pagina, texto_raw del PRODUCTO asociado y del PRECIO,
-- mas el indicador de que el valor parece un plazo de meses (3,6,9,10,12,13,15,18,20,24,36) y no un precio.
-- Misma clasificacion (CTE base/clas) que promos_como_producto.sql; si cambia una, cambia la otra.
WITH base AS (
    SELECT e.id, e.tienda_id, e.texto_norm, e.valor, p.metodo_norm, p.texto_raw AS prod_raw, e.texto_raw AS precio_raw, e.folleto_id, e.pagina_id,
           translate(lower(e.texto_norm), 'áéíóúüñ', 'aeiouun') AS n
    FROM extracciones e
    LEFT JOIN extracciones p ON p.id = e.producto_extraccion_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
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
, plazo AS (
    SELECT patron, count(*) AS n,
           count(*) FILTER (WHERE valor IN (3, 6, 9, 10, 12, 13, 15, 18, 20, 24, 36)) AS valor_es_plazo
    FROM clas WHERE patron IS NOT NULL GROUP BY patron
),
ej AS (
    SELECT c.*, row_number() OVER (PARTITION BY patron, tienda_id ORDER BY id) AS rn
    FROM clas c WHERE patron IS NOT NULL
)
SELECT ej.patron, pl.n AS n_patron, pl.valor_es_plazo, t.slug, ej.texto_norm, ej.prod_raw, ej.valor, ej.precio_raw,
       ej.metodo_norm, f.folleto_id_fuente, pg.numero_pagina
FROM ej
JOIN plazo pl ON pl.patron = ej.patron
JOIN tiendas t ON t.id = ej.tienda_id
JOIN folletos f ON f.id = ej.folleto_id
JOIN paginas pg ON pg.id = ej.pagina_id
WHERE ej.rn <= 2
ORDER BY ej.patron, t.slug, ej.rn
