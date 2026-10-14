-- Proxy de "nombre de la casilla vecina": nombres heuristicos que se repiten en 2+ precios de la MISMA pagina con
-- valores distintos (si el valor es igual es mas bien duplicado exacto; se cuenta aparte).
-- Universo: registros del dashboard (= v_precios_actuales) con producto heuristico (metodo_norm='heuristico').
-- Grano: tienda (+ total ROLLUP). Grupo = (pagina_id, texto_norm). Join PRECIO->PRODUCTO 1:1 (no duplica).
-- Limitacion: un mismo producto con dos presentaciones/precios en la pagina (ej. "Leche 1 L" y "Leche 2 L" que
-- quedan como "Leche") tambien cuenta; es un proxy, no un error confirmado.
-- Medido 13-oct-2026 (BD recargada con 01c2420): 6,944 de 23,607 heuristicos (29.4%) en 2,968 grupos. No hay foto
-- anterior en BD (recarga completa): solo "despues".
WITH h AS (
    SELECT e.id, e.tienda_id, e.pagina_id, e.texto_norm, e.valor
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL AND p.metodo_norm = 'heuristico'
),
g AS (
    SELECT tienda_id, pagina_id, texto_norm, count(*) AS n, count(DISTINCT valor) AS valores
    FROM h GROUP BY 1, 2, 3
)
SELECT t.slug AS tienda,
       sum(n) AS registros_heur,
       sum(n) FILTER (WHERE valores >= 2) AS reg_en_grupo_valores_distintos,
       round(100.0 * sum(n) FILTER (WHERE valores >= 2) / sum(n), 1) AS pct_vecino,
       count(*) FILTER (WHERE valores >= 2) AS grupos_valores_distintos,
       sum(n - valores) AS reg_duplicado_mismo_valor,
       max(n) AS max_repeticiones_en_pagina
FROM g JOIN tiendas t ON t.id = g.tienda_id
GROUP BY ROLLUP (t.slug)
ORDER BY (t.slug IS NULL), pct_vecino DESC NULLS LAST
