"""Herramienta de SOLO LECTURA (no es prueba). Imprime ejemplos_error[<codigo>] de una corrida del evaluador.

    venv/Scripts/python.exe tests/_herramienta_asoc_ver.py <corrida.json> <codigo>
"""
import json
import sys


def main(ruta, codigo):
    d = json.load(open(ruta, encoding="utf-8"))
    for tienda, casos in d["ejemplos_error"].get(codigo, {}).items():
        for c in casos:
            r, e = c.get("registro") or {}, c.get("esperado") or {}
            print(tienda, r.get("pagina"), r.get("precio"), repr(r.get("producto")), "| OCR", repr(r.get("producto_texto")),
                  "| GT", e.get("producto"), e.get("precio"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
