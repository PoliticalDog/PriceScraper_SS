"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento Regla A2-miles, 24-oct-2026.

Corre el RegexExtractor de HEAD (cargado en memoria con `git show HEAD:nlp/regex_extractor.py`) y el del
arbol de trabajo sobre los ocr_resultado.json de produccion, y compara precios y precios anteriores por
bloque: cuantos cambian de valor, cuantos se crean o se pierden, por tienda, con ejemplos. No escribe nada.

    venv/Scripts/python.exe tests/_herramienta_a2_produccion.py <dir_tiendeo> [<dir_ofertomat> ...]
"""
import importlib.util
import json
import logging
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
logging.disable(logging.INFO)

from nlp.regex_extractor import RegexExtractor as ExtractorNuevo  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def extractor_head():
    fuente = subprocess.run(["git", "show", "HEAD:nlp/regex_extractor.py"], cwd=RAIZ, capture_output=True,
                            text=True, encoding="utf-8", check=True).stdout
    spec = importlib.util.spec_from_loader("nlp.regex_extractor_head", loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "nlp"
    sys.modules["nlp.regex_extractor_head"] = modulo
    exec(compile(fuente, "HEAD:nlp/regex_extractor.py", "exec"), modulo.__dict__)
    return modulo.RegexExtractor()


def entidades(resultados):
    """{(pagina, tipo, texto_raw, x, y): valor} de precios y precios anteriores."""
    out = {}
    for r in resultados:
        for tipo, lista in (("PRECIO", r.precios), ("ANTES", r.precios_anteriores)):
            for e in lista:
                b = e.bbox or {}
                out[(r.imagen, tipo, e.texto_raw, b.get("x"), b.get("y"))] = e.valor
    return out


def precios_con_simbolo(resultados_pagina):
    return [e.valor for e in resultados_pagina.precios if "$" in (e.texto_raw or "") and e.valor]


def main(raices):
    viejo, nuevo = extractor_head(), ExtractorNuevo()
    cambia, crea, pierde = Counter(), Counter(), Counter()
    total_head = Counter()
    ejemplos = defaultdict(list)
    fuera_escala = []
    n_folletos = 0
    for raiz in raices:
        for ocr_path in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n_folletos += 1
            rv, rn = clasificar_paginas_ocr(ocr, viejo), clasificar_paginas_ocr(ocr, nuevo)
            ev, en = entidades(rv), entidades(rn)
            total_head[tienda] += sum(1 for k in ev if k[1] == "PRECIO")
            ref_pagina = {r.imagen: precios_con_simbolo(r) for r in rn}
            for k in ev.keys() | en.keys():
                if k in ev and k in en:
                    if ev[k] != en[k]:
                        cambia[tienda] += 1
                        ejemplos[tienda].append(f"{folleto}/{k[0]} {k[1]} {k[2]!r}: {ev[k]} -> {en[k]}")
                        ref = ref_pagina.get(k[0]) or []
                        if ref and en[k] and en[k] > 3 * max(ref):
                            fuera_escala.append(f"{tienda}/{folleto}/{k[0]} {k[2]!r} -> {en[k]} (max $ pagina {max(ref)})")
                elif k in en:
                    crea[tienda] += 1
                    ejemplos[tienda].append(f"{folleto}/{k[0]} {k[1]} {k[2]!r}: (nuevo) {en[k]}")
                else:
                    pierde[tienda] += 1
                    ejemplos[tienda].append(f"{folleto}/{k[0]} {k[1]} {k[2]!r}: {ev[k]} -> (perdido)")
    print(f"folletos: {n_folletos}")
    print(f"{'tienda':18s} {'precios HEAD':>12s} {'cambian':>8s} {'nuevos':>7s} {'perdidos':>8s}")
    for t in sorted(set(cambia) | set(crea) | set(pierde)):
        print(f"{t:18s} {total_head[t]:12d} {cambia[t]:8d} {crea[t]:7d} {pierde[t]:8d}")
    print(f"{'TOTAL':18s} {sum(total_head.values()):12d} {sum(cambia.values()):8d} "
          f"{sum(crea.values()):7d} {sum(pierde.values()):8d}")
    print("\nValor nuevo > 3x el maximo precio con '$' de la pagina:", len(fuera_escala))
    for f in fuera_escala[:30]:
        print("  ", f)
    print("\nEjemplos por tienda (hasta 8):")
    for t, lst in sorted(ejemplos.items()):
        print(t)
        for e in lst[:8]:
            print("   ", e)


if __name__ == "__main__":
    main(sys.argv[1:])
