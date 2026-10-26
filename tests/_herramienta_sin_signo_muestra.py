"""Herramienta de SOLO LECTURA (no es prueba). Muestra estratificada de las paginas que el filtro 2b deja sin
ningun precio (salida de _herramienta_sin_signo_paginas.py) y una copia reducida de cada imagen con los precios
quitados marcados en rojo (valor encima), para clasificarlas a ojo. Solo escribe en <dir_salida>.

Estratos: tienda. Cada tienda recibe max(1, round(n * paginas_tienda / total)) paginas, elegidas con
random.Random(semilla).sample sobre la lista ordenada (fuente, tienda, folleto, pagina).

    venv/Scripts/python.exe tests/_herramienta_sin_signo_muestra.py <diag.json> <dir_salida> <semilla> <n> <dir_processed> <dir_raw>
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw


def main(diag, dir_salida, semilla, n, dir_processed, dir_raw):
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    cero = sorted((p for p in d["paginas"] if p["precios_head"] == 0 and p["precios_sin2b"] > 0),
                  key=lambda p: (p["fuente"], p["tienda"], p["folleto"], p["pagina"]))
    por_tienda = defaultdict(list)
    for p in cero:
        por_tienda[p["tienda"]].append(p)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por_tienda):
        k = max(1, round(n * len(por_tienda[t]) / len(cero)))
        muestra += rng.sample(por_tienda[t], min(k, len(por_tienda[t])))
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    anchos = {}
    for i, p in enumerate(muestra, 1):
        clave = (p["fuente"], p["tienda"], p["folleto"])
        if clave not in anchos:
            ocr = json.loads((Path(dir_processed) / p["fuente"] / p["tienda"] / p["folleto"] / "ocr_resultado.json")
                             .read_text(encoding="utf-8"))
            anchos[clave] = {q["pagina"]: q.get("ancho_pagina") for q in ocr["paginas"]}
        img_path = Path(dir_raw) / p["fuente"] / p["tienda"] / p["folleto"] / p["pagina"]
        nombre = f"{i:02d}_{p['tienda']}_{p['folleto']}_{Path(p['pagina']).stem}.jpg"
        print(f"{i:02d} {p['fuente']}/{p['tienda']}/{p['folleto']}/{p['pagina']} perdidos={len(p['perdidos'])} "
              f"bloques={p['n_bloques']} mediana={p['mediana_texto']}")
        for q in p["perdidos"]:
            vec = "; ".join(f"{v[1]!r}({v[2]})" for v in q["vecinos"][:5])
            print(f"     {q['texto']!r} -> {q['valor']} alto={q['bbox']['alto']} r={q['ratio_alto']} "
                  f"{q['motivo']} encima={q['encima']!r}({q['encima_alto']}) | {vec}")
        try:
            img = Image.open(img_path).convert("RGB")
        except OSError:
            print("     (sin imagen)", img_path)
            continue
        ancho_ocr = anchos[clave].get(p["pagina"]) or img.width
        esc = img.width / ancho_ocr
        dib = ImageDraw.Draw(img)
        for q in p["perdidos"]:
            b = q["bbox"]
            x0, y0 = b["x"] * esc, b["y"] * esc
            x1, y1 = (b["x"] + b["ancho"]) * esc, (b["y"] + b["alto"]) * esc
            dib.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=max(3, int(4 * esc)))
            dib.text((x0, max(0, y0 - 14 * esc)), f"{q['valor']}", fill=(255, 0, 0))
        img.thumbnail((1000, 1600))
        img.save(out / nombre, quality=80)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6])
