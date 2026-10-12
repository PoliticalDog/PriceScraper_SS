-- Conciliacion corrida del evaluador <-> BD (Panel 1, PROPUESTA).
-- Pregunta: la corrida del evaluador que se muestra en el panel mide el MISMO dato que esta cargado en la BD?
-- Corrida: data/processed/_eval/runs/20261012_141917_e4184da_dev.json (commit e4184da, cambios_sin_commit=false).
-- Las 158 paginas (folleto_id_fuente, numero_pagina) de abajo son las paginas evaluadas de esa corrida
-- (claves de detalle.articulos y detalle.registros). Se regeneran desde el JSON al cambiar de corrida.
-- Esperado: reg_bd por tienda = metricas.tiendas.<slug>.conteos.registros_dashboard del JSON y
--           pags_bd por tienda = metricas.tiendas.<slug>.conteos.paginas. Total 1,401 registros / 158 paginas.
-- Resultado 12-oct-2026: cuadra exacto en las 14 tiendas medidas (1,401 / 158).
-- Join: ev -> folletos (1 folleto por folleto_id_fuente en estas 56 claves) -> paginas (1:1 por numero_pagina)
--       -> extracciones LEFT (N por pagina; se cuenta e.id, no filas, y pags con DISTINCT).
WITH ev(fid, np) AS (VALUES
 ('416306',2),('416306',4),('416306',5),('416306',6),('416306',7),('423210',1),('423210',2),('423210',4),('423210',5),
 ('423210',6),('423212',1),('423212',2),('423212',3),('423212',5),('423212',7),('417118',1),('417118',2),('417118',4),
 ('417118',5),('417118',6),('417943',1),('417943',2),('417943',3),('422604',1),('422604',3),('422604',4),('422604',5),
 ('422604',6),('423003',1),('423003',2),('423003',3),('423003',4),('423361',2),('423361',3),('423361',4),('422328',1),
 ('422328',2),('422328',3),('424405',1),('424405',2),('424405',3),('424410',1),('424410',2),('424410',3),('414967',1),
 ('416057',7),('416057',9),('416057',13),('416057',15),('416057',17),('417087',1),('417087',2),('428354',4),('428354',5),
 ('428354',7),('428354',13),('428354',15),('416210',1),('424460',2),('424460',3),('424460',4),('424460',5),('424850',1),
 ('424850',2),('426190',1),('426190',2),('426799',1),('426799',5),('426799',27),('428284',1),('428284',2),('411547',10),
 ('411547',34),('413216',4),('413216',5),('413216',10),('413216',25),('413216',26),('425961',6),('425961',15),
 ('425961',17),('425961',18),('425961',44),('422016',1),('422016',2),('422016',3),('422016',4),('423338',6),('423338',10),
 ('423338',11),('423338',14),('423338',16),('423341',3),('423341',10),('423341',14),('423341',15),('418012',1),
 ('418012',2),('423046',1),('423046',2),('423050',1),('423050',2),('420268',1),('421762',2),('421762',3),('421762',4),
 ('421900',2),('421900',4),('416269',1),('416269',2),('416269',3),('416269',4),('416269',5),('422326',3),('422326',13),
 ('422326',14),('422326',15),('417963',1),('417963',3),('417963',5),('417963',6),('417963',8),('417964',1),('417964',2),
 ('417964',3),('417965',1),('417965',2),('417965',3),('414801',1),('418310',1),('418310',2),('419897',4),('419897',9),
 ('419897',11),('419897',13),('419897',16),('428040',1),('428040',2),('428040',3),('428040',4),('413247',2),('413247',3),
 ('413247',4),('413247',5),('419764',1),('419764',2),('419764',3),('419764',4),('413251',1),('413251',2),('413251',3),
 ('413251',4),('413647',3),('413647',8),('413647',10),('413647',11),('413647',15),('423249',4))
SELECT t.slug                 AS tienda_slug,
       COUNT(e.id)            AS reg_bd,
       COUNT(DISTINCT pg.id)  AS pags_bd
FROM ev
JOIN folletos f  ON f.folleto_id_fuente = ev.fid
JOIN tiendas  t  ON t.id = f.tienda_id
JOIN paginas  pg ON pg.folleto_id = f.id AND pg.numero_pagina = ev.np
LEFT JOIN extracciones e
       ON e.pagina_id = pg.id AND e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
GROUP BY ROLLUP (t.slug)
ORDER BY 1
