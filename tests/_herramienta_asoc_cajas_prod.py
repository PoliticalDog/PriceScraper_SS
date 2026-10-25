"""Herramienta de SOLO LECTURA (no es prueba). Como _herramienta_asoc_cajas.py pero para cualquier pagina de
produccion (NLP regenerado en memoria, ROI si la tienda la usa). Imprime productos aceptados, precios y registros
cerca de un punto.

    venv/Scripts/python.exe tests/_herramienta_asoc_cajas_prod.py <dir_fuente> <tienda> <folleto> <pagina> <x> <y> [<radio>]
"""
import importlib
import json
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
from nlp.normalizador import Normalizador  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr, resultado_nlp  # noqa: E402

L = importlib.import_module("load.load")


def main(raiz, tienda, folleto, pagina, x, y, radio="400"):
    x, y, radio = int(x), int(y), int(radio)
    fuente = Path(raiz).name
    ocr = json.loads((Path(raiz) / tienda / folleto / "ocr_resultado.json").read_text(encoding="utf-8"))
    nlp = json.loads(json.dumps(resultado_nlp(ocr, clasificar_paginas_ocr(ocr, RegexExtractor())), ensure_ascii=False))
    pag = next(p for p in nlp["paginas"] if p["pagina"] == pagina)
    regiones = None
    if tienda in L.TIENDAS_ROI_HIBRIDO:
        cand = L.candidatas_roi_pagina(fuente, tienda, folleto, pagina)
        regiones = None if cand is None else L.regiones_con_precio(cand, pag.get("precios", []))
    norm = Normalizador()
    regs = L.construir_registros_pagina(pag, regiones, norm)
    cerca = lambda b: abs(b["x"] - x) <= radio and abs(b["y"] - y) <= radio  # noqa: E731
    print("PRODUCTOS aceptados")
    for p in sorted(regs["productos"], key=lambda p: (p["bbox"]["y"], p["bbox"]["x"])):
        if cerca(p["bbox"]):
            print(f"  {p['texto']!r:45s} {p['bbox']}")
    print("PRECIOS -> REGISTRO")
    for r in regs["precios"]:
        if cerca(r["precio"]["bbox"]):
            prod = r["producto"]
            print(f"  {r['precio']['texto']!r:12s} {r['precio']['valor']} {r['precio']['bbox']} -> "
                  f"{None if prod is None else prod.get('texto')!r}")


if __name__ == "__main__":
    main(*sys.argv[1:8])
