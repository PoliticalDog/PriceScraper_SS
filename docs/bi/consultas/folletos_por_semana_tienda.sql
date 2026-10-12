-- Panel 2 (PROPUESTA) - Vista temporal: folletos por semana (lunes ISO de fecha_inicio) y tienda.
-- Grano: semana x tienda (solo combinaciones con >= 1 folleto; el front rellena ceros).
-- Excluye folletos con fecha_inicio no confiable (inicio_antiguo, inicio_futuro_vs_scrapeo, sin_fecha, fin_antes_inicio):
--   hoy 7 de 694. vigencia_larga SI entra (su inicio es plausible).
-- Rango: :desde/:hasta al construir; aqui fecha_inicio >= 2026-01-01 y <= CURRENT_DATE + 30 (incluye proximos).
-- Validacion: SUM(folletos) de esta consulta = COUNT(*) de folletos con el mismo filtro (ver total con ROLLUP abajo).
WITH fol AS (
    SELECT f.id, f.tienda_id, f.fecha_inicio, f.scrapeado_at
    FROM folletos f
    WHERE f.fecha_inicio IS NOT NULL AND f.fecha_fin IS NOT NULL
      AND f.fecha_fin >= f.fecha_inicio
      AND f.fecha_inicio >= f.scrapeado_at::date - 365
      AND f.fecha_inicio <= f.scrapeado_at::date + 30
      AND f.fecha_inicio >= DATE '2026-01-01'
      AND f.fecha_inicio <= CURRENT_DATE + 30
)
SELECT DATE_TRUNC('week', fol.fecha_inicio)::date AS semana,
       t.slug                                      AS tienda_slug,
       COUNT(*)                                    AS folletos
FROM fol
JOIN tiendas t ON t.id = fol.tienda_id
GROUP BY ROLLUP (DATE_TRUNC('week', fol.fecha_inicio)::date, t.slug)
ORDER BY semana NULLS LAST, tienda_slug NULLS LAST
