-- Contexto de nombres sin categoria: para un precio de ejemplo de cada nombre, los bloques
-- mas cercanos de la misma pagina (cualquier tipo), para identificar a que producto pertenece la marca
WITH nombres(producto) AS (
    VALUES ('Carranco 400 G'),('Los Pastores 200 G'),('Bionda 400 G'),('Vios'),('Dama'),('Foca'),
           ('Chimex'),('Mimarca'),('Bida'),('Soriano'),('Campeón'),('Brut'),('Dice'),('Bofana'),
           ('Duisboni'),('Portales 300 G'),('El Cuatro 1 Kg'),('Excelsior 300 G'),('Bogamar'),
           ('Zwan'),('Valley Foods'),('Story'),('Premier'),('Ensueno'),('Absorsec con 120 Pieza'),
           ('Akonno'),('Pienna'),('Fulprotect'),('Nutri'),('Elite'),('Regio'),('Formula'),('Pacific'),
           ('Rancho Don Francisco Selecta'),('Frida Kahlo Reserva'),('Sabalito'),('Mi Capricho 300 G'),
           ('Limpiador'),('Para Asar'),('Cangrejo'),('Enchiladas'),('Grano'),('Caballero'),('Protector')
), ejemplo AS (
    SELECT DISTINCT ON (n.producto) n.producto, e.id, e.pagina_id, e.bbox_x, e.bbox_y
    FROM nombres n JOIN extracciones e ON e.texto_norm = n.producto AND e.tipo = 'PRECIO' AND e.valor IS NOT NULL
    ORDER BY n.producto, e.id
)
SELECT x.producto, v.tipo, LEFT(v.texto_raw, 60) AS texto_vecino
FROM ejemplo x
CROSS JOIN LATERAL (
    SELECT o.tipo, o.texto_raw
    FROM extracciones o
    WHERE o.pagina_id = x.pagina_id AND o.id <> x.id
    ORDER BY (o.bbox_x - x.bbox_x)^2 + (o.bbox_y - x.bbox_y)^2
    LIMIT 4
) v
ORDER BY x.producto
