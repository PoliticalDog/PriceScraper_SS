"""Herramienta de SOLO LECTURA (no es prueba). Experimento "centavos sueltos 90/99", 25-oct-2026.

Recorre los ocr_resultado.json de produccion (tiendeo + ofertomat) con dos copias del RegexExtractor (A y B, rutas a
copias .txt del modulo; "-" = el del arbol de trabajo) y cuenta por tienda los PRECIO cuyo texto es solo 2 digitos
(valor 90 y 99 aparte). Con la copia B clasifica la causa de cada PRECIO "dd":
  fusion_no_consumida  = el bloque es el de centavos de una fusion de _detectar_precios_fusionados de la pagina
  centavos_a_escala    = el bloque son los centavos que la Regla A-escala sumo a otro bloque (_centavos_superindice)
  superindice_sin_par  = tiene la geometria de superindice (_es_superindice_de) de un bloque numerico a su izquierda
                         que no se fusiono (entero de 3+ digitos, "$" + 3 digitos, B-4, etc.)
  otro                 = nada de lo anterior
Toma una muestra estratificada por causa y tienda (random.Random(semilla)) de los "90"/"99" y arma mosaicos.
Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_centavos_sueltos_causa.py <dir_processed> <dir_raw> <dir_salida> <copia_A> <copia_B> <semilla> <n>
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

DD = re.compile(r"^\d{2}$")
NUMERICO = re.compile(r"^[\$sS]?\s?[\d,.]{1,7}$")


def extractor(ruta, nombre):
    return RegexExtractor() if ruta == "-" else cargar_base(ruta, nombre).RegexExtractor()


def causa(ex, b, bloques, fe):
    bb = b["bbox"]
    for e, c, _ in ex._detectar_precios_fusionados(bloques, fe):
        if c is b:
            return "fusion_no_consumida"
    for o in bloques:
        ob = o.get("bbox")
        if not ob or o is b:
            continue
        t = o.get("texto", "").strip()
        if ex.PATRON_DIGITO_SIGNO.match(t) and ex._es_superindice_de(ob, bb, fe, forma_nueva=True):
            return "centavos_a_escala"
    for o in bloques:
        ob = o.get("bbox")
        if not ob or o is b:
            continue
        if NUMERICO.match(o.get("texto", "").strip()) and ex._es_superindice_de(ob, bb, fe):
            return "superindice_sin_par"
    return "otro"


def main(dir_processed, dir_raw, dir_salida, ruta_a, ruta_b, semilla, n):
    ea = extractor(ruta_a, "nlp.regex_a")
    eb = extractor(ruta_b, "nlp.regex_b")
    cuenta = {k: defaultdict(Counter) for k in ("A", "B")}
    total = {k: Counter() for k in ("A", "B")}
    causas = defaultdict(Counter)
    casos = []
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
            paginas = {p["pagina"]: p for p in ocr.get("paginas", [])}
            for k, ex in (("A", ea), ("B", eb)):
                for r in clasificar_paginas_ocr(ocr, ex):
                    p = paginas[r.imagen]
                    fe = (p.get("ancho_pagina") or ex.ANCHO_REFERENCIA_UMBRALES) / ex.ANCHO_REFERENCIA_UMBRALES
                    for e in r.precios:
                        total[k][tienda] += 1
                        t = e.texto_raw.strip()
                        if not DD.match(t):
                            continue
                        clave = "90" if e.valor == 90 else "99" if e.valor == 99 else "dd"
                        cuenta[k][tienda][clave] += 1
                        if k != "B":
                            continue
                        b = next((x for x in p["bloques"] if x.get("bbox") == e.bbox and x.get("texto") == e.texto_raw),
                                 None)
                        if b is None:
                            continue
                        c = causa(ex, b, p["bloques"], fe)
                        causas[tienda][(clave, c)] += 1
                        if clave in ("90", "99"):
                            casos.append({"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": r.imagen,
                                          "texto": t, "valor": e.valor, "bbox": e.bbox, "causa": c,
                                          "ancho_pagina": p.get("ancho_pagina")})
    print(f"folletos: {nf} ({time.time() - t0:.0f}s)")
    print(f"{'tienda':16s} {'precios A':>9s} {'90 A':>5s} {'99 A':>5s} {'dd A':>5s} | {'precios B':>9s} {'90 B':>5s} "
          f"{'99 B':>5s} {'dd B':>5s}")
    for t in sorted(total["B"], key=lambda t: -(cuenta["B"][t]["90"] + cuenta["B"][t]["99"])):
        a, b = cuenta["A"][t], cuenta["B"][t]
        print(f"{t:16s} {total['A'][t]:9d} {a['90']:5d} {a['99']:5d} {a['dd']:5d} | {total['B'][t]:9d} {b['90']:5d} "
              f"{b['99']:5d} {b['dd']:5d}")
    print("causas (B) por tienda:")
    for t in sorted(causas, key=lambda t: -sum(causas[t].values())):
        print(f"  {t:16s} {sorted(causas[t].items())}")
    tot = Counter()
    for t in causas:
        tot.update(causas[t])
    print("causas (B) total:", sorted(tot.items()))

    por = defaultdict(list)
    for c in sorted(casos, key=lambda c: (c["causa"], c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"])):
        por[(c["causa"], c["tienda"])].append(c)
    rng = random.Random(semilla)
    muestra = []
    for k in sorted(por):
        m = max(1, round(n * len(por[k]) / max(1, len(casos))))
        muestra += rng.sample(por[k], min(m, len(por[k])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"S{i:02d}"
        print(f"{c['id']} {c['causa']:20s} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} bbox={c['bbox']}")
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "casos.json").write_text(json.dumps(casos, ensure_ascii=False), encoding="utf-8")
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], int(sys.argv[6]), int(sys.argv[7]))
