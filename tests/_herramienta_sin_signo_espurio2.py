"""Herramienta de SOLO LECTURA (no es prueba). Cuenta, por tienda, los bloques de produccion con forma de "$" mal
leido + entero de 2 digitos ("835", "545", "s99": ^[568sS]\\d{2}$) que el RegexExtractor de HEAD descarta, con alto
>= 2x la mediana del texto de la pagina (letra de precio), y cuantos llevan centavos "00"/"90"/"99" pegados a la
derecha (tiendas_3b "829"+"00"). Para dimensionar la siguiente hipotesis; no cambia nada.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_espurio2.py <dir_tiendeo> [<dir_ofertomat> ...]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _herramienta_sin_signo_bloques import tipos  # noqa: E402
from _herramienta_sin_signo_paginas import cargar_modulo_head, mediana_texto  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402

FORMA = re.compile(r"^[568sS]\d{2}$")
CENTAVOS = re.compile(r"^\W*(00|90|99|50)\W*$")


def main(raices):
    head = cargar_modulo_head("nlp.regex_extractor_head").RegexExtractor()
    cuenta, con_cent, paginas = Counter(), Counter(), defaultdict(set)
    ejemplos = defaultdict(list)
    for raiz in raices:
        for ocr_path in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            candidatos = []
            for p in ocr.get("paginas", []):
                med = mediana_texto(p["bloques"])
                for b in p["bloques"]:
                    if FORMA.match(b.get("texto", "").strip()) and med and b["bbox"]["alto"] >= 2 * med:
                        candidatos.append((p["pagina"], b))
            if not candidatos:
                continue
            res = clasificar_paginas_ocr(ocr, head)
            tipos_pag = {}
            for pag in {c[0] for c in candidatos}:
                tipos_pag[pag] = tipos(res, pag)
            bloques_pag = {p["pagina"]: p["bloques"] for p in ocr["paginas"]}
            for pag, b in candidatos:
                bb = b["bbox"]
                t = tipos_pag[pag].get((bb["x"], bb["y"]), "-")
                if t.startswith("precio") or t.startswith("promos"):
                    continue
                cuenta[tienda] += 1
                paginas[tienda].add((folleto, pag))
                cent = any(CENTAVOS.match(o.get("texto", "")) and 0 <= o["bbox"]["x"] - (bb["x"] + bb["ancho"]) <= 0.5 * bb["alto"]
                           and abs(o["bbox"]["y"] - bb["y"]) <= 0.3 * bb["alto"] for o in bloques_pag[pag])
                con_cent[tienda] += cent
                if len(ejemplos[tienda]) < 6:
                    ejemplos[tienda].append(f"{folleto}/{pag} {b['texto']!r}{' +cent' if cent else ''} ({t})")
    print(f"{'tienda':18s} {'bloques':>8s} {'con_cent':>8s} {'paginas':>8s}")
    for t in sorted(cuenta, key=lambda t: -cuenta[t]):
        print(f"{t:18s} {cuenta[t]:8d} {con_cent[t]:8d} {len(paginas[t]):8d}   {ejemplos[t]}")
    print(f"{'TOTAL':18s} {sum(cuenta.values()):8d} {sum(con_cent.values()):8d}")


if __name__ == "__main__":
    main(sys.argv[1:])
