-- Diagnostico: nombres de "producto" del dashboard que en realidad son promociones, condiciones, servicios,
-- vigencias o unidades de presentacion (12-oct-2026, bi-specialist).
-- Grano: una fila por patron. Universo = lo que ve el dashboard (= v_precios_actuales):
--   extracciones tipo='PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL  (28,634 filas)
-- El texto_norm del PRECIO es el _nombre_norm del PRODUCTO asociado (load.py); metodo_norm vive en la fila PRODUCTO
-- (LEFT JOIN 1:1 por producto_extraccion_id -> PK, no duplica: 28,634 antes y despues).
-- Clasificacion por regex sobre texto_norm en minusculas y sin acentos; primera regla que coincide gana:
--   servicio > msi_financiamiento > lealtad_puntos > vigencia > precio_generico > condicion_compra > unidad_presentacion
-- Esperado 12-oct-2026: unidad_presentacion 1,250 | lealtad_puntos 485 | precio_generico 444 | condicion_compra 334 |
--   msi_financiamiento 325 | servicio 61 | vigencia 13 | producto 25,722 (100% de los no-producto son heuristicos).
-- Tras recarga 2f616c3+6d0670b (27,760 registros): unidad 1,267 | precio_generico 79 | condicion 67 | msi 36 | servicio 14 |
--   lealtad 12 | vigencia 5 | producto 26,280. Variantes OCR nuevas no cubiertas aqui: promos_como_producto_residual.sql.
-- Tras recarga 01c2420 (13-oct, 27,760): unidad 694 | precio_generico 80 | condicion 71 | msi 36 | servicio 16 | lealtad 14 |
--   vigencia 5 | producto 26,844 (promo total 222).
-- "unidad_presentacion" no es promo, pero tampoco es producto (Carton, Pieza, Paquete...): se reporta aparte.
-- Esperado 12-oct-2026: ver ruta promos_como_producto_validacion.sql (mismo total por otro camino).
WITH base AS (
    SELECT e.id, e.tienda_id, e.texto_norm, e.valor, p.metodo_norm,
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
SELECT coalesce(patron, '~producto') AS patron,
       count(*) AS registros,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_dashboard,
       count(DISTINCT tienda_id) AS tiendas,
       count(*) FILTER (WHERE metodo_norm = 'heuristico') AS heuristico,
       count(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo')) AS catalogo,
       count(DISTINCT texto_norm) AS textos_distintos,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY valor) AS mediana_valor,
       (array_agg(texto_norm ORDER BY texto_norm))[1] AS ejemplo_min
FROM clas
GROUP BY 1
ORDER BY (coalesce(patron, '~producto') = '~producto'), registros DESC
