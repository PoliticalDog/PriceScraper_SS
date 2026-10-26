"""Herramienta de SOLO LECTURA (no es prueba). Experimento "digito leido como $" + escala de la pagina, 25-oct-2026.

En las paginas de dev con GT, junta los bloques "[568sS]dd" con letra de precio (alto >= 2x la mediana del texto)
que la base no clasifica como precio ni promo, y los etiqueta con el GT de la pagina:
  dd  = algun precio del GT tiene entero == los 2 ultimos digitos (el primer caracter es el "$" mal leido)
  ddd = algun precio del GT tiene entero == los 3 digitos (entero real de 3 digitos)
  ?   = ninguno (o los dos)
e imprime las senales de escala de la pagina (ver _herramienta_digito_signo_comun.senales). Se corre desde la
raiz del repo (el GT se lee con la ruta relativa del evaluador).

    venv/Scripts/python.exe tests/_herramienta_digito_signo_dev.py <dir_processed_tiendeo>
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_digito_signo_comun import (FORMA, cargar_base, centavos_derecha, mediana_texto,  # noqa: E402
                                             senales, tipos)
from evaluador import splits  # noqa: E402
from evaluador.gt import cargar_gt  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def main(dir_tiendeo):
    base = cargar_base().RegexExtractor()
    paginas = splits.filtrar(cargar_gt(), "dev", splits.cargar())
    por_folleto = defaultdict(dict)
    for pg in paginas:
        por_folleto[(pg.tienda, pg.folleto)][pg.pagina] = pg
    filas = []
    for (tienda, folleto), pags in sorted(por_folleto.items()):
        ruta = Path(dir_tiendeo) / tienda / folleto / "ocr_resultado.json"
        if not ruta.exists():
            continue
        ocr = json.loads(ruta.read_text(encoding="utf-8"))
        ocr = {**ocr, "paginas": [p for p in ocr["paginas"] if p["pagina"] in pags]}
        res = {r.imagen: r for r in clasificar_paginas_ocr(ocr, base)}
        for p in ocr["paginas"]:
            med = mediana_texto(p["bloques"])
            r = res[p["pagina"]]
            tp = tipos(r)
            gt = [a.precio for a in pags[p["pagina"]].articulos if a.precio]
            for b in p["bloques"]:
                t = b.get("texto", "").strip()
                if not (b.get("bbox") and FORMA.match(t) and med and b["bbox"]["alto"] >= 2 * med):
                    continue
                if tp.get((b["bbox"]["x"], b["bbox"]["y"])) in ("precios", "promos"):
                    continue
                dd = any(int(g) == int(t[1:]) for g in gt)
                ddd = t[0].isdigit() and any(int(g) == int(t) for g in gt)
                etiqueta = "dd" if dd and not ddd else "ddd" if ddd and not dd else "?"
                cent = centavos_derecha(b, p["bloques"])
                exacto = None
                if etiqueta == "dd":
                    v = int(t[1:]) + (int(cent) / 100 if cent else 0)
                    exacto = any(abs(g - v) < 0.005 for g in gt)
                filas.append({"tienda": tienda, "folleto": folleto, "pagina": p["pagina"], "texto": t,
                              "alto_rel": round(b["bbox"]["alto"] / med, 2), "centavos": cent,
                              "etiqueta": etiqueta, "exacto_con_cent": exacto, **senales(b, p["bloques"], r)})
    for f in filas:
        print(f"{f['tienda']:14s} {f['folleto']} {f['pagina']} {f['texto']!r:7s} cent={f['centavos']!s:4s} "
              f"{f['etiqueta']:3s} exacto={f['exacto_con_cent']!s:5s} ref={f['ref_2']}/{f['ref_3']} "
              f"sim={f['sim_2']}/{f['sim_3']} tres={f['tres_esp']}/{f['tres_tot']} r={f['alto_rel']}")
    print(Counter((f["tienda"], f["etiqueta"]) for f in filas))


if __name__ == "__main__":
    main(sys.argv[1])
