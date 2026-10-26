"""Herramienta de SOLO LECTURA (no es prueba). Lista los PRECIO que el filtro 2b quita en una tienda (salida de
_herramienta_sin_signo_paginas.py), ordenados por alto relativo, con rotulo encima y vecinos, y un resumen por
motivo y por tramo de alto relativo.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_perdidos.py <diag.json> <tienda> [<ratio_min>]
"""
import json
import sys
from collections import Counter
from pathlib import Path


def main(diag, tienda, ratio_min):
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    filas = [(p, q) for p in d["paginas"] if p["tienda"] == tienda for q in p["perdidos"]]
    tramos = Counter()
    for p, q in filas:
        r = q["ratio_alto"] or 0
        tramo = "<0.8" if r < 0.8 else "0.8-1.0" if r < 1.0 else "1.0-1.15" if r < 1.15 else "1.15-1.3" if r < 1.3 else ">=1.3"
        tramos[(q["motivo"], tramo)] += 1
    print(f"{tienda}: {len(filas)} PRECIO quitados; por motivo y alto relativo:", dict(sorted(tramos.items())))
    for p, q in sorted(filas, key=lambda f: -(f[1]["ratio_alto"] or 0)):
        if (q["ratio_alto"] or 0) < ratio_min:
            continue
        vec = "; ".join(f"{v[1]!r}({v[2]})" for v in q["vecinos"][:4])
        print(f"  {p['folleto']}/{p['pagina']} {q['texto']!r}->{q['valor']} alto={q['bbox']['alto']} r={q['ratio_alto']} "
              f"{q['motivo']} encima={q['encima']!r}({q['encima_alto']}) cero={p['precios_head'] == 0} | {vec}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 0.0)
