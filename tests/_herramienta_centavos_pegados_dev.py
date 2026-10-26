"""Herramienta de SOLO LECTURA (no es prueba). Experimento "soriana: centavos pegados x100", 25-oct-2026.

En las paginas de dev con GT, toma los PRECIO de la base (HEAD) con valor >= 100 cuyo texto no lleva coma ni punto
y los etiqueta con el GT de la pagina:
  x100 = algun precio del GT tiene entero == valor // 100 (los 2 ultimos digitos son centavos pegados)
  real = algun precio del GT tiene entero == entero del valor
  ?    = ninguno (o los dos)
e imprime la geometria del bloque (alto relativo a la mediana del texto de la pagina, ancho/alto por caracter).
Se corre desde la raiz del repo (el GT se lee con la ruta relativa del evaluador).

    venv/Scripts/python.exe tests/_herramienta_centavos_pegados_dev.py <dir_processed_tiendeo>
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_centavos_comun import cargar_base  # noqa: E402
from evaluador import splits  # noqa: E402
from evaluador.gt import cargar_gt  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402

LETRAS = re.compile(r"[^\W\d_]{3}")


def mediana_texto(bloques):
    altos = sorted(b["bbox"]["alto"] for b in bloques if b.get("bbox") and LETRAS.search(b.get("texto", "")))
    if not altos:
        return None
    m = len(altos) // 2
    return altos[m] if len(altos) % 2 else (altos[m - 1] + altos[m]) / 2


def forma(texto):
    return re.sub(r"\d", "d", texto)


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
            gt = [a.precio for a in pags[p["pagina"]].articulos if a.precio]
            for e in r.precios:
                v, t = e.valor, e.texto_raw.strip()
                if v is None or v < 100 or "," in t or "." in t or "+" in t:
                    continue
                x100 = any(int(g) == int(v // 100) for g in gt)
                real = any(int(g) == int(v) for g in gt)
                et = "x100" if x100 and not real else "real" if real and not x100 else "?"
                b = e.bbox or {}
                nd = len(re.sub(r"\D", "", t))
                filas.append({"tienda": tienda, "folleto": folleto, "pagina": p["pagina"], "texto": t, "valor": v,
                              "et": et, "alto_rel": round(b.get("alto", 0) / med, 2) if med else None,
                              "ancho_car": round(b.get("ancho", 0) / max(1, b.get("alto", 1)) / max(1, len(t)), 3),
                              "forma": forma(t)})
    for f in sorted(filas, key=lambda f: (f["et"], f["tienda"], f["forma"])):
        print(f"{f['et']:5s} {f['tienda']:15s} {f['folleto']} {f['pagina']} {f['texto']!r:12s} {f['valor']:>9} "
              f"forma={f['forma']:8s} alto_rel={f['alto_rel']} ancho_car={f['ancho_car']}")
    print(Counter((f["et"], f["tienda"]) for f in filas))
    print(Counter((f["et"], f["forma"]) for f in filas))


if __name__ == "__main__":
    main(sys.argv[1])
