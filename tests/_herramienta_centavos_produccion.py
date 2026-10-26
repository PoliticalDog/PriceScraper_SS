"""Herramienta de SOLO LECTURA (no es prueba). Experimentos de centavos del 25-oct-2026.

Compara una copia base del RegexExtractor (<copia_base>, .txt del modulo) con el del arbol de trabajo sobre los
ocr_resultado.json de produccion (tiendeo + ofertomat): PRECIO creados, perdidos y que cambian de valor, por tienda;
las formas de texto (digitos -> d) mas frecuentes de cada grupo; y una muestra estratificada por tienda
(random.Random(semilla), proporcional con minimo 1) de cambios (o de perdidos, con grupo=perdidos) en mosaicos de
recortes (rojo = el bloque) para revisarla contra la imagen. Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_centavos_produccion.py <dir_processed> <dir_raw> <dir_salida> <copia_base> <semilla> <n> <grupo>
grupo: cambiados | perdidos | creados
"""
import json
import random
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_centavos_comun import cargar_base  # noqa: E402
from _herramienta_digito_signo_muestra import mosaicos  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def forma(texto):
    return re.sub(r"\d", "d", texto.strip())


def precios(resultados, anchos):
    out = {}
    for r in resultados:
        for e in r.precios:
            b = e.bbox or {}
            out[(r.imagen, e.texto_raw, b.get("x"), b.get("y"))] = (e.valor, b, anchos.get(r.imagen))
    return out


def main(dir_processed, dir_raw, dir_salida, copia_base, semilla, n, grupo):
    base = cargar_base(copia_base, "nlp.regex_base_prod").RegexExtractor()
    nuevo = RegexExtractor()
    total, crea, pierde, cambia = Counter(), Counter(), Counter(), Counter()
    grandes_base, grandes_nuevo = Counter(), Counter()
    filas = {"creados": [], "perdidos": [], "cambiados": []}
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
            grandes_base[tienda] += sum(1 for v in pb.values() if v[0] is not None and v[0] >= 1000)
            grandes_nuevo[tienda] += sum(1 for v in pn.values() if v[0] is not None and v[0] >= 1000)
            for k in pb.keys() | pn.keys():
                v = pn.get(k) or pb.get(k)
                fila = {"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": k[0], "texto": k[1],
                        "bbox": v[1], "ancho_pagina": v[2]}
                if k in pb and k in pn:
                    if pb[k][0] != pn[k][0]:
                        cambia[tienda] += 1
                        filas["cambiados"].append({**fila, "antes": pb[k][0], "valor": pn[k][0]})
                elif k in pn:
                    crea[tienda] += 1
                    filas["creados"].append({**fila, "valor": pn[k][0]})
                else:
                    pierde[tienda] += 1
                    filas["perdidos"].append({**fila, "valor": pb[k][0]})
    print(f"folletos: {nf} ({time.time() - t0:.0f}s)")
    print(f"{'tienda':16s} {'precios base':>12s} {'creados':>8s} {'perdidos':>8s} {'cambian':>8s} {'>=1000 base':>11s} "
          f"{'>=1000 nuevo':>12s}")
    for t in sorted(total, key=lambda t: -(crea[t] + pierde[t] + cambia[t])):
        if crea[t] or pierde[t] or cambia[t]:
            print(f"{t:16s} {total[t]:12d} {crea[t]:8d} {pierde[t]:8d} {cambia[t]:8d} {grandes_base[t]:11d} "
                  f"{grandes_nuevo[t]:12d}")
    print(f"{'TOTAL':16s} {sum(total.values()):12d} {sum(crea.values()):8d} {sum(pierde.values()):8d} "
          f"{sum(cambia.values()):8d} {sum(grandes_base.values()):11d} {sum(grandes_nuevo.values()):12d}")
    for g, lista in filas.items():
        print(f"{g}: formas", Counter(forma(c["texto"]) for c in lista).most_common(20))
    cambios = filas["cambiados"]
    print("cambiados: valor/antes", Counter(round(c["valor"] / c["antes"], 4) if c["antes"] else None
                                            for c in cambios).most_common(8))

    por = defaultdict(list)
    lista = filas[grupo]
    for c in sorted(lista, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"], c["bbox"]["x"])):
        por[c["tienda"]].append(c)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por):
        k = max(1, round(n * len(por[t]) / max(1, len(lista))))
        muestra += rng.sample(por[t], min(k, len(por[t])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"C{i:02d}"
        print(f"{c['id']} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} {c.get('antes')} -> {c['valor']}")
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "filas.json").write_text(json.dumps(filas, ensure_ascii=False), encoding="utf-8")
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6]), sys.argv[7])
