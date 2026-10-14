-- Validacion independiente de procedencia_cobertura.sql: parte de v_precios_actuales (no de extracciones con filtros
-- propios) y resuelve folleto por la clave natural (fuente, folleto_id_fuente) en lugar de folleto_id, y la pagina
-- con EXISTS (no puede duplicar). Deben cuadrar: registros, con_archivo_imagen, con_url_origen, con_titulo.
SELECT
    COUNT(*)                                                                     AS registros,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM extracciones e JOIN paginas p ON p.id = e.pagina_id
        WHERE e.id = v.id AND COALESCE(p.archivo_imagen, '') <> ''))             AS con_archivo_imagen,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM folletos f
        WHERE f.fuente = v.fuente AND f.folleto_id_fuente = v.folleto_id_fuente
          AND COALESCE(f.url_origen, '') <> ''))                                 AS con_url_origen,
    COUNT(*) FILTER (WHERE EXISTS (
        SELECT 1 FROM folletos f
        WHERE f.fuente = v.fuente AND f.folleto_id_fuente = v.folleto_id_fuente
          AND COALESCE(f.titulo, '') <> ''))                                     AS con_titulo,
    (SELECT COUNT(*) FROM (SELECT fuente, folleto_id_fuente FROM folletos
                           GROUP BY 1, 2 HAVING COUNT(*) > 1) d)                 AS claves_folleto_repetidas
FROM v_precios_actuales v
