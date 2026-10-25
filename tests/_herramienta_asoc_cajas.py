"""Herramienta de SOLO LECTURA (no es prueba). Bloques producto aceptados y precios del NLP (en memoria) cerca de un punto.

    venv/Scripts/python.exe tests/_herramienta_asoc_cajas.py <tienda> <folleto> <pagina> <x> <y> [<radio>]
"""
import os
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if os.environ.get("PYTHONHASHSEED") != "0":
    sys.exit(subprocess.call([sys.executable, *sys.argv], env={**os.environ, "PYTHONHASHSEED": "0"}, cwd=RAIZ))
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
import logging  # noqa: E402

logging.disable(logging.WARNING)
from evaluador.gt import cargar_gt  # noqa: E402
from evaluador.pipeline import FuentePipeline  # noqa: E402


def main(tienda, folleto, pagina, x, y, radio="400"):
    x, y, radio = int(x), int(y), int(radio)
    pg = next(p for p in cargar_gt() if p.tienda == tienda and p.folleto == folleto and p.pagina == pagina)
    pp = FuentePipeline(nlp="memoria").pagina(pg)
    cerca = lambda b: abs(b["x"] - x) <= radio and abs(b["y"] - y) <= radio  # noqa: E731
    print("PRODUCTOS aceptados")
    for p in sorted(pp.productos_aceptados, key=lambda p: (p["bbox"]["y"], p["bbox"]["x"])):
        if cerca(p["bbox"]):
            print(f"  {p['texto']!r:45s} {p['bbox']} conf={p.get('confianza')}")
    print("PRECIOS")
    for p in pp.nlp.get("precios", []):
        if cerca(p["bbox"]):
            print(f"  {p['texto']!r:20s} {p['valor']} {p['bbox']}")
    print("REGISTROS")
    for r in pp.registros:
        if cerca(r.bbox_precio):
            print(f"  ${r.precio} -> {r.producto!r} (OCR {r.producto_texto!r})")


if __name__ == "__main__":
    main(*sys.argv[1:7])
