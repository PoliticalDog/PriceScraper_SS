-- Palabras mas frecuentes en los nombres de producto de precios sin categoria (v_precios_actuales)
-- Grano: palabra (minusculas, >= 4 letras); registros = precios que la contienen, productos = nombres distintos
WITH sin_cat AS (
    SELECT id, LOWER(producto) AS producto
    FROM v_precios_actuales
    WHERE NULLIF(TRIM(categoria), '') IS NULL
), palabras AS (
    SELECT DISTINCT s.id, s.producto, w AS palabra
    FROM sin_cat s, regexp_split_to_table(s.producto, '[^a-záéíóúñü]+') AS w
    WHERE LENGTH(w) >= 4
)
SELECT palabra, COUNT(*) AS registros, COUNT(DISTINCT producto) AS productos
FROM palabras
GROUP BY palabra
ORDER BY registros DESC
