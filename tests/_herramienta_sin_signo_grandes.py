"""Herramienta de SOLO LECTURA (no es prueba). Para la misma muestra de _herramienta_sin_signo_muestra.py
(misma semilla y n), lista los bloques con digitos de cada pagina con alto >= 1.3x la mediana de texto y su
tipo en HEAD: sirve para separar "el OCR no leyo el precio" (c) de "lo leyo y otra regla lo descarta" (d).

    venv/Scripts/python.exe tests/_herramienta_sin_signo_grandes.py <diag.json> <semilla> <n> <dir_processed> [<tienda>]

Con <tienda>, en vez de la muestra lista TODAS las paginas en cero de esa tienda.
"""
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _herramienta_sin_signo_bloques import tipos  # noqa: E402
from _herramienta_sin_signo_paginas import extractores, mediana_texto  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def muestra(diag, semilla, n):
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    cero = sorted((p for p in d["paginas"] if p["precios_head"] == 0 and p["precios_sin2b"] > 0),
                  key=lambda p: (p["fuente"], p["tienda"], p["folleto"], p["pagina"]))
    por_tienda = defaultdict(list)
    for p in cero:
        por_tienda[p["tienda"]].append(p)
    rng = random.Random(semilla)
    out = []
    for t in sorted(por_tienda):
        k = max(1, round(n * len(por_tienda[t]) / len(cero)))
        out += rng.sample(por_tienda[t], min(k, len(por_tienda[t])))
    return out


def todas_de_tienda(diag, tienda):
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    return sorted((p for p in d["paginas"] if p["precios_head"] == 0 and p["precios_sin2b"] > 0
                   and p["tienda"] == tienda), key=lambda p: (p["folleto"], p["pagina"]))


def main(diag, semilla, n, dir_processed, tienda=None):
    head, _ = extractores()
    paginas = todas_de_tienda(diag, tienda) if tienda else muestra(diag, semilla, n)
    for i, p in enumerate(paginas, 1):
        ocr = json.loads((Path(dir_processed) / p["fuente"] / p["tienda"] / p["folleto"] / "ocr_resultado.json")
                         .read_text(encoding="utf-8"))
        ocr = {**ocr, "paginas": [q for q in ocr["paginas"] if q["pagina"] == p["pagina"]]}
        th = tipos(clasificar_paginas_ocr(ocr, head), p["pagina"])
        bloques = ocr["paginas"][0]["bloques"]
        med = mediana_texto(bloques) or 1
        grandes = [f"{b['texto']!r}({b['bbox']['alto'] / med:.1f}x {th.get((b['bbox']['x'], b['bbox']['y']), '-')})"
                   for b in sorted(bloques, key=lambda b: (b["bbox"]["y"], b["bbox"]["x"]))
                   if re.search(r"\d", b["texto"]) and b["bbox"]["alto"] >= 1.3 * med]
        print(f"{i:02d} {p['tienda']}/{p['folleto']}/{p['pagina']}: " + "; ".join(grandes))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
