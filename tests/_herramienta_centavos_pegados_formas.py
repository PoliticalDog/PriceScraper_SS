"""Herramienta de SOLO LECTURA (no es prueba). Experimento "soriana: centavos pegados x100", 25-oct-2026.

Recorre los ocr_resultado.json de produccion (tiendeo + ofertomat) con el RegexExtractor base (HEAD, copia en
_herramienta_centavos_base_regex.txt) y cuenta, por tienda, los PRECIO con valor >= 1000 segun la forma del texto
(digitos -> d). Junta los PRECIO cuyo texto es "$" + 3 a 5 digitos sin separador, toma una muestra estratificada por
tienda (random.Random(semilla), proporcional con minimo `minimo`) y arma mosaicos de recortes (rojo = el bloque) para
revisarla contra la imagen. Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_centavos_pegados_formas.py <dir_processed> <dir_raw> <dir_salida> <semilla> <n> <minimo>
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
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402

SIGNO_DIGITOS = re.compile(r"^\$\s?\d{3,5}$")


def forma(texto):
    return re.sub(r"\d", "d", texto.strip())


def main(dir_processed, dir_raw, dir_salida, semilla, n, minimo):
    base = cargar_base().RegexExtractor()
    grandes = defaultdict(Counter)
    total = Counter()
    signo = []
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
            for r in clasificar_paginas_ocr(ocr, base):
                for e in r.precios:
                    total[tienda] += 1
                    t = e.texto_raw.strip()
                    if e.valor is not None and e.valor >= 1000:
                        grandes[tienda][forma(t)] += 1
                    if SIGNO_DIGITOS.match(t):
                        signo.append({"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": r.imagen,
                                      "texto": t, "valor": e.valor, "bbox": e.bbox, "ancho_pagina": anchos.get(r.imagen)})
    print(f"folletos: {nf} ({time.time() - t0:.0f}s)")
    print("PRECIO >= 1000 por tienda y forma (top 8):")
    for t in sorted(grandes, key=lambda t: -sum(grandes[t].values())):
        print(f"  {t:16s} total={total[t]:6d} >=1000={sum(grandes[t].values()):5d} {grandes[t].most_common(8)}")
    print('"$" + digitos sin separador, por tienda y forma:')
    por_forma = defaultdict(Counter)
    for s in signo:
        por_forma[s["tienda"]][forma(s["texto"]).replace(" ", "")] += 1
    for t in sorted(por_forma, key=lambda t: -sum(por_forma[t].values())):
        print(f"  {t:16s} {dict(por_forma[t])}")

    cuatro = [s for s in signo if re.match(r"^\$\s?\d{4}$", s["texto"])]
    por = defaultdict(list)
    for c in sorted(cuatro, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"], c["bbox"]["x"])):
        por[c["tienda"]].append(c)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por):
        k = max(minimo, round(n * len(por[t]) / max(1, len(cuatro))))
        muestra += rng.sample(por[t], min(k, len(por[t])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"F{i:02d}"
        print(f"{c['id']} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} -> {c['valor']}")
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "signo_digitos.json").write_text(json.dumps(signo, ensure_ascii=False), encoding="utf-8")
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]))
