"""Herramienta de SOLO LECTURA (no es prueba). Experimento "digito leido como $" + escala, 25-oct-2026.

Compara el RegexExtractor base (HEAD + "$" suelto, copia en _herramienta_digito_signo_base_regex.txt) con el del arbol
de trabajo sobre los ocr_resultado.json de produccion (tiendeo + ofertomat): PRECIO creados, perdidos y que cambian
de valor, por tienda; y una muestra estratificada de creados (random.Random(semilla), proporcional por tienda con
minimo 1) en mosaicos de recortes (rojo = el bloque) para revisarla contra la imagen. Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_digito_signo_produccion.py <dir_processed> <dir_raw> <dir_salida> <semilla> <n>
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_digito_signo_comun import cargar_base  # noqa: E402
from _herramienta_digito_signo_muestra import mosaicos  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def precios(resultados, anchos):
    out = {}
    for r in resultados:
        for e in r.precios:
            b = e.bbox or {}
            out[(r.imagen, e.texto_raw, b.get("x"), b.get("y"))] = (e.valor, b, anchos.get(r.imagen))
    return out


def main(dir_processed, dir_raw, dir_salida, semilla, n):
    base = cargar_base().RegexExtractor()
    nuevo = RegexExtractor()
    total, crea, pierde, cambia = Counter(), Counter(), Counter(), Counter()
    creados, perdidos, cambiados = [], [], []
    t0, nf = time.time(), 0
    for fuente in ("tiendeo", "ofertomat"):
        for ocr_path in sorted((Path(dir_processed) / fuente).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            nf += 1
            if nf % 100 == 0:
                print(f"  {nf} folletos, {time.time() - t0:.0f}s", flush=True)
            anchos = {p["pagina"]: p.get("ancho_pagina") for p in ocr.get("paginas", [])}
            pb = precios(clasificar_paginas_ocr(ocr, base), anchos)
            pn = precios(clasificar_paginas_ocr(ocr, nuevo), anchos)
            total[tienda] += len(pb)
            for k in pb.keys() | pn.keys():
                v = pn.get(k) or pb.get(k)
                fila = {"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": k[0], "texto": k[1],
                        "bbox": v[1], "ancho_pagina": v[2]}
                if k in pb and k in pn:
                    if pb[k][0] != pn[k][0]:
                        cambia[tienda] += 1
                        cambiados.append({**fila, "antes": pb[k][0], "ahora": pn[k][0]})
                elif k in pn:
                    crea[tienda] += 1
                    creados.append({**fila, "valor": pn[k][0]})
                else:
                    pierde[tienda] += 1
                    perdidos.append({**fila, "valor": pb[k][0]})
    print(f"folletos: {nf} ({time.time() - t0:.0f}s)")
    print(f"{'tienda':18s} {'precios base':>12s} {'creados':>8s} {'perdidos':>8s} {'cambian':>8s}")
    for t in sorted(set(crea) | set(pierde) | set(cambia)):
        print(f"{t:18s} {total[t]:12d} {crea[t]:8d} {pierde[t]:8d} {cambia[t]:8d}")
    print(f"{'TOTAL':18s} {sum(total.values()):12d} {sum(crea.values()):8d} {sum(pierde.values()):8d} "
          f"{sum(cambia.values()):8d}")
    print("perdidos:", [(p["tienda"], p["folleto"], p["pagina"], p["texto"], p["valor"]) for p in perdidos])
    print("cambian:", [(p["tienda"], p["folleto"], p["pagina"], p["texto"], p["antes"], p["ahora"]) for p in cambiados])
    print("creados (texto):", Counter(c["texto"] for c in creados).most_common(25))
    print("creados con centavos:", sum(1 for c in creados if c["valor"] != int(c["valor"])))

    por = defaultdict(list)
    for c in sorted(creados, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"], c["bbox"]["x"])):
        por[c["tienda"]].append(c)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por):
        k = max(1, round(n * len(por[t]) / max(1, len(creados))))
        muestra += rng.sample(por[t], min(k, len(por[t])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"P{i:02d}"
        print(f"{c['id']} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} -> {c['valor']}")
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "creados.json").write_text(json.dumps(creados, ensure_ascii=False), encoding="utf-8")
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
