"""
diagnostico_encoding.py
Identifica exactamente qué archivo y línea causa el error de encoding.
"""
import sys
import traceback
from pathlib import Path

archivos = [
    Path(".env"),
    Path("load/db_builder.py"),
    Path("load/schema.sql"),
    Path("load/load.py"),
    Path("load/__init__.py"),
    Path("probar_load.py"),
]

print("Verificando encoding de archivos...\n")
for ruta in archivos:
    if not ruta.exists():
        print(f"  [NO EXISTE] {ruta}")
        continue
    try:
        contenido = ruta.read_text(encoding="utf-8")
        print(f"  [OK  UTF-8] {ruta}")
    except UnicodeDecodeError as e:
        print(f"  [ERROR    ] {ruta}  ← {e}")
        # Mostrar el carácter problemático
        raw = ruta.read_bytes()
        pos = e.start
        print(f"             byte={hex(raw[pos])} en posición {pos}")
        print(f"             contexto: ...{raw[max(0,pos-20):pos+20]}...")

print("\nDone.")
