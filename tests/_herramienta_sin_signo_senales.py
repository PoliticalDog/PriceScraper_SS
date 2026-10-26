"""Herramienta de SOLO LECTURA (no es prueba). Sobre los PRECIO que el filtro 2b quita (salida de
_herramienta_sin_signo_paginas.py), cuenta por tienda cuantos tienen cada senal candidata de precio real:

  S1 "$" suelto: un vecino cuyo texto es solo "$" (el OCR leyo el signo como bloque aparte) a <= 1x su alto.
  S2 unidad de venta: un vecino "kilo"/"kg"/"c/u"/"clu"/"pieza"/"pza" a <= 1x su alto.
  S3 rotulo: el bloque justo encima coincide con PATRON_ROTULO_PRECIO (arbol de trabajo).

y lista los casos con alguna senal.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_senales.py <diag.json>
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from nlp.regex_extractor import RegexExtractor  # noqa: E402

S1 = re.compile(r"^\W*\$\W*$")
S2 = re.compile(r"^\W*(?:kilo|kg|c/u|clu|cu|c/.|pieza|pza)\W*$", re.IGNORECASE)


def main(diag):
    ex = RegexExtractor()
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    cuenta = Counter()
    total = Counter()
    casos = []
    for p in d["paginas"]:
        for q in p["perdidos"]:
            total[p["tienda"]] += 1
            alto = q["bbox"]["alto"]
            s1 = any(S1.match(v[1]) and v[0] <= alto for v in q["vecinos"])
            s2 = any(S2.match(v[1]) and v[0] <= alto for v in q["vecinos"])
            s3 = bool(q["encima"]) and bool(ex.PATRON_ROTULO_PRECIO.match(ex._limpiar_texto(q["encima"])))
            for nombre, s in (("S1", s1), ("S2", s2), ("S3", s3)):
                if s:
                    cuenta[(p["tienda"], nombre)] += 1
            if s1 or s2 or s3:
                casos.append((p["tienda"], p["folleto"], p["pagina"], q["texto"], q["valor"], q["ratio_alto"],
                              q["motivo"], "S1" * s1 + "S2" * s2 + "S3" * s3,
                              [v[1] for v in q["vecinos"][:4]], p["precios_head"] == 0))
    print(f"{'tienda':18s} {'quitados':>8s} {'S1 $':>6s} {'S2 unid':>8s} {'S3 rot':>7s}")
    for t in sorted(total, key=lambda t: -total[t]):
        print(f"{t:18s} {total[t]:8d} {cuenta[(t, 'S1')]:6d} {cuenta[(t, 'S2')]:8d} {cuenta[(t, 'S3')]:7d}")
    print(f"casos con alguna senal: {len(casos)}")
    for c in casos:
        print("  ", c)


if __name__ == "__main__":
    main(sys.argv[1])
