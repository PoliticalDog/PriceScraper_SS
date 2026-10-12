-- Validacion independiente del Panel 2 (otro camino):
--   folletos vigentes y paginas vigentes salen de la VISTA v_calidad_pipeline (paginas_procesadas ya agregada por la vista),
--   precios vigentes salen de la VISTA v_precios_actuales (vigencia_desde/vigencia_hasta), no de extracciones/paginas.
--   Las anomalias de fecha se excluyen con un NOT EXISTS escrito como condiciones positivas sobre folletos
--   (en lugar del CASE de la consulta principal).
-- Debe cuadrar por tienda con cobertura_frescura_por_tienda.sql en folletos_vigentes, paginas_vigentes y precios_vigentes.
-- Totales esperados 12-oct-2026: 52 folletos vigentes, 532 paginas, 1,858 precios.
WITH anomalos AS (
    SELECT f.folleto_id_fuente
    FROM folletos f
    WHERE f.fecha_inicio IS NULL OR f.fecha_fin IS NULL
       OR f.fecha_fin < f.fecha_inicio
       OR f.fecha_inicio + 365 < f.scrapeado_at::date
       OR f.fecha_inicio - 30 > f.scrapeado_at::date
       OR f.fecha_fin > f.fecha_inicio + 120
),
vig AS (
    SELECT q.tienda, COUNT(*) AS folletos_vigentes, SUM(q.paginas_procesadas) AS paginas_vigentes
    FROM v_calidad_pipeline q
    JOIN folletos f ON f.id = q.folleto_id
    WHERE f.fecha_inicio <= CURRENT_DATE AND f.fecha_fin >= CURRENT_DATE
      AND NOT EXISTS (SELECT 1 FROM anomalos a WHERE a.folleto_id_fuente = q.folleto_id_fuente)
    GROUP BY q.tienda
),
pv AS (
    SELECT v.tienda, COUNT(*) AS precios_vigentes
    FROM v_precios_actuales v
    WHERE v.vigencia_desde <= CURRENT_DATE AND v.vigencia_hasta >= CURRENT_DATE
      AND NOT EXISTS (SELECT 1 FROM anomalos a WHERE a.folleto_id_fuente = v.folleto_id_fuente)
    GROUP BY v.tienda
)
SELECT COALESCE(vig.tienda, pv.tienda) AS tienda,
       COALESCE(vig.folletos_vigentes, 0) AS folletos_vigentes,
       COALESCE(vig.paginas_vigentes, 0)  AS paginas_vigentes,
       COALESCE(pv.precios_vigentes, 0)   AS precios_vigentes
FROM vig FULL JOIN pv ON pv.tienda = vig.tienda
ORDER BY folletos_vigentes DESC
