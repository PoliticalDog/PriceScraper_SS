"""Herramienta de SOLO LECTURA (no es prueba). Lista ejemplos_error de una corrida del evaluador.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_ejemplos.py <corrida.json> <tienda1,tienda2> <codigo> [...]
"""
import json
import sys

d = json.load(open(sys.argv[1], encoding="utf-8"))
ej = d.get("ejemplos_error", {})
for cod in sys.argv[3:]:
    for t in sys.argv[2].split(","):
        lst = ej.get(cod, {}).get(t, [])
        print(f"== {cod} {t} ({len(lst)})")
        for e in lst:
            print(json.dumps(e, ensure_ascii=False)[:700])
