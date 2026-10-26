"""Herramienta de SOLO LECTURA (no es prueba). Vuelca los bloques de una pagina con su tipo segun el
RegexExtractor del arbol de trabajo, el de HEAD y HEAD sin el filtro 2b, y el alto relativo a la mediana de texto.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_bloques.py <ocr_resultado.json> <pagina> [--solo-num]
"""
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _herramienta_sin_signo_paginas import extractores, mediana_texto  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def tipos(resultados, pagina):
    out = {}
    for r in resultados:
        if r.imagen != pagina:
            continue
        for attr in ("productos", "precios", "precios_anteriores", "ahorros", "promos", "eventos_promo",
                     "atributos", "descartes"):
            for e in getattr(r, attr):
                b = e.bbox or {}
                out[(b.get("x"), b.get("y"))] = f"{attr[:6]}:{e.valor if e.valor is not None else ''}"
    return out


def main(ruta, pagina, solo_num):
    ocr = json.loads(Path(ruta).read_text(encoding="utf-8"))
    ocr = {**ocr, "paginas": [p for p in ocr["paginas"] if p["pagina"] == pagina]}
    head, sin2b = extractores()
    nuevo = RegexExtractor()
    th, ts, tn = (tipos(clasificar_paginas_ocr(ocr, x), pagina) for x in (head, sin2b, nuevo))
    bloques = ocr["paginas"][0]["bloques"]
    med = mediana_texto(bloques)
    print(f"{pagina}: {len(bloques)} bloques, mediana texto {med}, ancho {ocr['paginas'][0].get('ancho_pagina')}")
    for b in sorted(bloques, key=lambda b: (b["bbox"]["y"], b["bbox"]["x"])):
        bb = b["bbox"]
        if solo_num and not re.search(r"[\d$]", b["texto"]):
            continue
        k = (bb["x"], bb["y"])
        r = bb["alto"] / med if med else 0
        print(f"  ({bb['x']:5d},{bb['y']:5d}) {bb['ancho']:4d}x{bb['alto']:<4d} r={r:4.2f} "
              f"H={th.get(k, '-'):14s} S={ts.get(k, '-'):14s} N={tn.get(k, '-'):14s} {b['texto']!r}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--solo-num" in sys.argv)
