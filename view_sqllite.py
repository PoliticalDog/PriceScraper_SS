# Vista rapida de los datos almacenados en SQLite para verificar que se están guardando correctamente

import sqlite3, pandas as pd

# Conexión a la base de datos SQLite
con = sqlite3.connect("data/pricescraper.db")

# Ver todas las tablas
print(pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con))

# Ver precios cargados
print(pd.read_sql("""
    SELECT t.nombre, f.folleto_id_fuente, p.numero_pagina,
           pr.texto_producto, pr.precio_actual, pr.precio_anterior,
           pr.texto_ocr_precio, pr.confianza_ocr
    FROM precios pr
    JOIN folletos f ON pr.folleto_id = f.id
    JOIN tiendas t  ON f.tienda_id   = t.id
    JOIN paginas p  ON pr.pagina_id  = p.id
    ORDER BY pr.id
""", con))

con.close()