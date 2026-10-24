-- Precios del dashboard por forma del texto OCR del bloque de precio (que regla del NLP lo pudo leer)
-- con_simbolo: trae "$"; fusionado: entero+centavos en 2 bloques; espurio: empieza con 5/6/8/s/S (posible "$" mal leido);
-- miles: N,NNN sin "$"; bare_N: N digitos puros sin "$" (reglas B-2/B-3/B-4/B-5)
WITH p AS (
    SELECT e.id, e.texto_raw, e.valor, NULLIF(TRIM(e.categoria_nlp), '') IS NOT NULL AS con_cat,
           CASE
               WHEN e.texto_raw LIKE '%$%' THEN 'con_simbolo'
               WHEN e.texto_raw LIKE '%+%' THEN 'fusionado'
               WHEN e.texto_raw ~ '^\s*\d{2}\s*$' THEN 'bare_2'
               WHEN e.texto_raw ~ '^\s*\d{3}\s*$' THEN 'bare_3'
               WHEN e.texto_raw ~ '^\s*[568sS]\d' THEN 'espurio_o_bare'
               WHEN e.texto_raw ~ '^\s*\d{4}\s*$' THEN 'bare_4'
               WHEN e.texto_raw ~ '^\s*\d{5}\s*$' THEN 'bare_5'
               WHEN e.texto_raw ~ '^\s*\d{1,3},\d{3}' THEN 'miles'
               ELSE 'otro'
           END AS forma
    FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
)
SELECT forma, COUNT(*) AS precios, COUNT(*) FILTER (WHERE con_cat) AS con_categoria,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS pct
FROM p GROUP BY forma ORDER BY precios DESC
