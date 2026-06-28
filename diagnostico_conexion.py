"""
diagnostico_conexion.py
Prueba la conexión a PostgreSQL paso a paso con traceback completo.
"""
import sys
import traceback
from pathlib import Path

# 1. Leer .env manualmente
print("1. Leyendo .env...")
env_path = Path(".env")
env_vars = {}
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env_vars[k.strip()] = v.strip()

db_url = env_vars.get("DATABASE_URL", "")
print(f"   DATABASE_URL = {db_url}")

# 2. Intentar conexión con psycopg2
print("\n2. Conectando con psycopg2...")
try:
    import psycopg2
    conn = psycopg2.connect(db_url)
    print("   ✅ Conexión exitosa")
    cur = conn.cursor()
    cur.execute("SELECT version()")
    print(f"   PostgreSQL: {cur.fetchone()[0]}")
    conn.close()
except Exception as e:
    print(f"   ✗ Error: {e}")
    print("\n   Traceback completo:")
    traceback.print_exc()
