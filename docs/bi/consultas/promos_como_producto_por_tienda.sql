-- Impacto por tienda: registros del dashboard (= v_precios_actuales) cuyo nombre es promo/condicion/servicio/vigencia
-- (promo_total) o unidad de presentacion (unidad), y cuanto bajaria el ruido si se excluyeran.
-- Grano: tienda (+ fila total ROLLUP). Esperado 12-oct-2026 total: 28,634; promo_total 1,662 (5.80%); unidad 1,250; no-producto 10.17%.
-- Tras recarga 2f616c3+6d0670b: total 27,760; promo_total 213 (0.77%); unidad 1,267; no-producto 5.33%.
-- Tras recarga 01c2420 (13-oct): promo_total 222 (0.80%); unidad 694 (casa_ley 365); no-producto 3.30%.
-- Misma clasificacion (CTE base/clas) que promos_como_producto.sql; si cambia una, cambia la otra.
-- Universo = lo que ve el dashboard (= v_precios_actuales):
--   extracciones tipo='PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL  (28,634 filas)
-- El texto_norm del PRECIO es el _nombre_norm del PRODUCTO asociado (load.py); metodo_norm vive en la fila PRODUCTO
-- (LEFT JOIN 1:1 por producto_extraccion_id -> PK, no duplica: 28,634 antes y despues).
-- Clasificacion por regex sobre texto_norm en minusculas y sin acentos; primera regla que coincide gana:
--   servicio > msi_financiamiento > lealtad_puntos > vigencia > precio_generico > condicion_compra > unidad_presentacion
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
SELECT t.slug AS tienda,
       count(*) AS registros_dashboard,
       count(*) FILTER (WHERE patron = 'msi_financiamiento') AS msi,
       count(*) FILTER (WHERE patron = 'lealtad_puntos') AS lealtad,
       count(*) FILTER (WHERE patron = 'precio_generico') AS precio_gen,
       count(*) FILTER (WHERE patron = 'condicion_compra') AS condicion,
       count(*) FILTER (WHERE patron IN ('servicio', 'vigencia')) AS serv_vig,
       count(*) FILTER (WHERE patron NOT IN ('unidad_presentacion')) AS promo_total,
       round(100.0 * count(*) FILTER (WHERE patron NOT IN ('unidad_presentacion')) / count(*), 2) AS pct_promo,
       count(*) FILTER (WHERE patron = 'unidad_presentacion') AS unidad,
       round(100.0 * count(*) FILTER (WHERE patron IS NOT NULL) / count(*), 2) AS pct_no_producto,
       count(*) FILTER (WHERE metodo_norm = 'heuristico') AS heuristico,
       round(100.0 * count(*) FILTER (WHERE patron IS NOT NULL) / nullif(count(*) FILTER (WHERE metodo_norm = 'heuristico'), 0), 2) AS pct_del_heuristico
FROM clas c
JOIN tiendas t ON t.id = c.tienda_id
GROUP BY ROLLUP (t.slug)
ORDER BY (t.slug IS NULL), promo_total DESC
