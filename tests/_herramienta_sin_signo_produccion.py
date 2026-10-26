"""Herramienta de SOLO LECTURA (no es prueba). Experimento "$" suelto, 25-oct-2026.

Compara el RegexExtractor de HEAD (git show) con el del arbol de trabajo sobre los ocr_resultado.json de
produccion: PRECIO creados, perdidos y que cambian de valor, por tienda; cuantas de las paginas que el filtro 2b
deja en cero (diag.json de _herramienta_sin_signo_paginas.py) recuperan algun precio; y una muestra estratificada
de precios creados (random.Random(semilla), proporcional por tienda, minimo 1) con la imagen recortada alrededor
del precio (rojo) para revisarla a ojo. Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_produccion.py <diag.json> <dir_salida> <semilla> <n> <dir_processed> <dir_raw>
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _herramienta_sin_signo_paginas import cargar_modulo_head, precios  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def main(diag, dir_salida, semilla, n, dir_processed, dir_raw):
    head = cargar_modulo_head("nlp.regex_extractor_head").RegexExtractor()
    nuevo = RegexExtractor()
    d = json.loads(Path(diag).read_text(encoding="utf-8"))
    cero = {(p["fuente"], p["tienda"], p["folleto"], p["pagina"]) for p in d["paginas"]
            if p["precios_head"] == 0 and p["precios_sin2b"] > 0}
    total_head, crea, pierde, cambia = Counter(), Counter(), Counter(), Counter()
    creados, perdidos, cambiados = [], [], []
    recuperadas = set()
    t0 = time.time()
    n_folletos = 0
    for fuente in ("tiendeo", "ofertomat"):
        for ocr_path in sorted((Path(dir_processed) / fuente).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n_folletos += 1
            if n_folletos % 100 == 0:
                print(f"  {n_folletos} folletos, {time.time() - t0:.0f}s", flush=True)
            ph, pn = precios(clasificar_paginas_ocr(ocr, head)), precios(clasificar_paginas_ocr(ocr, nuevo))
            total_head[tienda] += len(ph)
            for k in ph.keys() | pn.keys():
                fila = {"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": k[0], "texto": k[1],
                        "bbox": (pn.get(k) or ph.get(k))[1]}
                if k in ph and k in pn:
                    if ph[k][0] != pn[k][0]:
                        cambia[tienda] += 1
                        cambiados.append({**fila, "antes": ph[k][0], "ahora": pn[k][0]})
                elif k in pn:
                    crea[tienda] += 1
                    creados.append({**fila, "valor": pn[k][0]})
                    if (fuente, tienda, folleto, k[0]) in cero:
                        recuperadas.add((fuente, tienda, folleto, k[0]))
                else:
                    pierde[tienda] += 1
                    perdidos.append({**fila, "valor": ph[k][0]})
    print(f"folletos: {n_folletos} ({time.time() - t0:.0f}s)")
    print(f"{'tienda':18s} {'precios HEAD':>12s} {'creados':>8s} {'perdidos':>8s} {'cambian':>8s}")
    for t in sorted(set(crea) | set(pierde) | set(cambia)):
        print(f"{t:18s} {total_head[t]:12d} {crea[t]:8d} {pierde[t]:8d} {cambia[t]:8d}")
    print(f"{'TOTAL':18s} {sum(total_head.values()):12d} {sum(crea.values()):8d} {sum(pierde.values()):8d} "
          f"{sum(cambia.values()):8d}")
    print(f"paginas en cero por el filtro: {len(cero)}; recuperan algun precio: {len(recuperadas)}")
    for r in sorted(recuperadas):
        print("   ", "/".join(r))
    print("perdidos:", [(p["tienda"], p["folleto"], p["pagina"], p["texto"], p["valor"]) for p in perdidos])
    print("cambian:", [(p["tienda"], p["folleto"], p["pagina"], p["texto"], p["antes"], p["ahora"]) for p in cambiados])
    print("creados (valor):", Counter(round(c["valor"], 2) for c in creados).most_common(30))

    por_tienda = defaultdict(list)
    for c in sorted(creados, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["texto"], c["bbox"]["x"])):
        por_tienda[c["tienda"]].append(c)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por_tienda):
        k = max(1, round(n * len(por_tienda[t]) / max(1, len(creados))))
        muestra += rng.sample(por_tienda[t], min(k, len(por_tienda[t])))
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    anchos = {}
    for i, c in enumerate(muestra, 1):
        clave = (c["fuente"], c["tienda"], c["folleto"])
        if clave not in anchos:
            ocr = json.loads((Path(dir_processed) / clave[0] / clave[1] / clave[2] / "ocr_resultado.json")
                             .read_text(encoding="utf-8"))
            anchos[clave] = {q["pagina"]: q.get("ancho_pagina") for q in ocr["paginas"]}
        print(f"M{i:02d} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} -> {c['valor']} bbox={c['bbox']}")
        try:
            img = Image.open(Path(dir_raw) / c["fuente"] / c["tienda"] / c["folleto"] / c["pagina"]).convert("RGB")
        except OSError:
            continue
        esc = img.width / (anchos[clave].get(c["pagina"]) or img.width)
        b = c["bbox"]
        x0, y0, x1, y1 = b["x"] * esc, b["y"] * esc, (b["x"] + b["ancho"]) * esc, (b["y"] + b["alto"]) * esc
        ImageDraw.Draw(img).rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=max(3, int(3 * esc)))
        m = 4 * (y1 - y0)
        recorte = img.crop((max(0, x0 - 1.5 * m), max(0, y0 - m), min(img.width, x1 + 1.5 * m), min(img.height, y1 + m)))
        recorte.thumbnail((700, 700))
        recorte.save(out / f"M{i:02d}_{c['tienda']}_{c['folleto']}_{Path(c['pagina']).stem}.jpg", quality=85)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6])
