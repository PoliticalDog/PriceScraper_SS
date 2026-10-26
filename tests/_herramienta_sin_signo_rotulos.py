"""Herramienta de SOLO LECTURA (no es prueba). Cuenta, por tienda, los textos de bloque completos de los OCR de
produccion que coinciden con PATRON_ROTULO_PRECIO (del arbol de trabajo y del de HEAD) y los que se parecen a
"precio" / "bodega" / "preciazo" sin coincidir, para acotar el patron con datos.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_rotulos.py <dir_tiendeo> [<dir_ofertomat> ...]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _herramienta_sin_signo_paginas import cargar_modulo_head  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402

PARECIDO = re.compile(r"pr[eé]c|bod[eé]g|preci|s[uú]per|^\W*de[g@]a\W*$", re.IGNORECASE)


def main(raices):
    nuevo = RegexExtractor()
    head = cargar_modulo_head("nlp.regex_extractor_head").RegexExtractor()
    coincide_h, coincide_n, parecido = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for raiz in raices:
        for ocr_path in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda = ocr_path.parent.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for p in ocr.get("paginas", []):
                for b in p["bloques"]:
                    t = nuevo._limpiar_texto(b.get("texto", ""))
                    h = bool(head.PATRON_ROTULO_PRECIO.match(t))
                    n = bool(nuevo.PATRON_ROTULO_PRECIO.match(t))
                    if h:
                        coincide_h[tienda][t] += 1
                    if n:
                        coincide_n[tienda][t] += 1
                    if not h and not n and PARECIDO.search(t) and len(t) <= 25:
                        parecido[tienda][t] += 1
    for nombre, tabla in (("COINCIDE HEAD", coincide_h), ("COINCIDE ARBOL", coincide_n), ("PARECIDO SIN COINCIDIR", parecido)):
        print(f"===== {nombre}")
        for t in sorted(tabla, key=lambda t: -sum(tabla[t].values())):
            print(f"  {t}: {sum(tabla[t].values())}  ->  " + ", ".join(f"{k!r}:{v}" for k, v in tabla[t].most_common(25)))
    solo_h = {(t, k) for t in coincide_h for k in coincide_h[t] if k not in coincide_n.get(t, {})}
    print("===== solo HEAD (dejan de coincidir):", sorted(solo_h)[:80])


if __name__ == "__main__":
    main(sys.argv[1:])
