"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento nombre partido, 24-oct-2026.

Regenera en memoria el NLP de produccion con el RegexExtractor del arbol (HEAD + regla A2-miles) y arma los
registros de cada pagina con construir_registros_pagina de HEAD (cargado con `git show HEAD:load/load.py`) y
con el del arbol de trabajo, con las MISMAS regiones ROI para ambos. Cuenta por tienda los registros del
dashboard (precio con producto) cuyo nombre cambia, los creados y los perdidos, y da ejemplos. No escribe nada.

    venv/Scripts/python.exe tests/_herramienta_asoc_produccion.py [--sin-roi] <dir_tiendeo> [<dir_ofertomat> ...]
"""
import importlib
import importlib.util
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if os.environ.get("PYTHONHASHSEED") != "0":
    sys.exit(subprocess.call([sys.executable, *sys.argv], env={**os.environ, "PYTHONHASHSEED": "0"}, cwd=RAIZ))
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
import logging  # noqa: E402

logging.disable(logging.WARNING)

from nlp.normalizador import Normalizador  # noqa: E402
from nlp.regex_extractor import RegexExtractor  # noqa: E402
from nlp.salida_json import clasificar_paginas_ocr, resultado_nlp  # noqa: E402

NUEVO = importlib.import_module("load.load")


def modulo_head():
    fuente = subprocess.run(["git", "show", "HEAD:load/load.py"], cwd=RAIZ, capture_output=True,
                            text=True, encoding="utf-8", check=True).stdout
    spec = importlib.util.spec_from_loader("load.load_head", loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "load"
    sys.modules["load.load_head"] = modulo
    exec(compile(fuente, "HEAD:load/load.py", "exec"), modulo.__dict__)
    return modulo


def nombre(reg):
    p = reg["producto"]
    return None if p is None else p.get("_nombre_norm")


def metodo(reg):
    """'canonico' (exacto/fuzzy del catalogo) o 'heuristico' (texto del folleto) del nombre mostrado."""
    p = reg["producto"]
    r = p.get("_resultado_unido") or p.get("_resultado")
    return "canonico" if r is not None and r.metodo in ("exacto", "fuzzy", "fuzzy_bajo") else "heuristico"


def main(args):
    usar_roi = "--sin-roi" not in args
    raices = [a for a in args if not a.startswith("--")]
    viejo = modulo_head()
    norm, ext = Normalizador(), RegexExtractor()
    total, cambia, crea, pierde, largos = Counter(), Counter(), Counter(), Counter(), Counter()
    ejemplos = defaultdict(list)
    todos = []
    n_fol, t0 = 0, time.time()
    for raiz in raices:
        fuente = Path(raiz).name
        for ocr_path in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n_fol += 1
            if n_fol % 50 == 0:
                print(f"  ... {n_fol} folletos, {time.time() - t0:.0f}s", flush=True)
            nlp = json.loads(json.dumps(resultado_nlp(ocr, clasificar_paginas_ocr(ocr, ext)), ensure_ascii=False))
            for pag in nlp.get("paginas", []):
                regiones = None
                if usar_roi and tienda in NUEVO.TIENDAS_ROI_HIBRIDO:
                    try:
                        cand = NUEVO.candidatas_roi_pagina(fuente, tienda, folleto, pag["pagina"])
                        regiones = None if cand is None else NUEVO.regiones_con_precio(cand, pag.get("precios", []))
                    except Exception:
                        regiones = None
                a = viejo.construir_registros_pagina(pag, regiones, norm)["precios"]
                b = NUEVO.construir_registros_pagina(pag, regiones, norm)["precios"]
                for ra, rb in zip(a, b):
                    if ra["precio"].get("valor") is None:
                        continue
                    na, nb = nombre(ra), nombre(rb)
                    total[tienda] += na is not None
                    if na is not None and nb is not None and na != nb:
                        cambia[tienda] += 1
                        txt = f"{folleto}/{pag['pagina']} ${ra['precio'].get('valor')}: {na!r} -> {nb!r}"
                        ejemplos[tienda].append(txt)
                        todos.append(f"{tienda}/{txt}")
                        largos["> 100 caracteres"] += len(nb) > 100
                        largos["> 150 caracteres"] += len(nb) > 150
                        largos["> 300 caracteres"] += len(nb) > 300
                        largos[f"metodo {metodo(ra)} -> {metodo(rb)}"] += 1
                        ca, cb = bool(ra["producto"].get("categoria")), bool(rb["producto"].get("categoria"))
                        largos[f"categoria {'si' if ca else 'no'} -> {'si' if cb else 'no'}"] += 1
                    elif na is None and nb is not None:
                        crea[tienda] += 1
                    elif na is not None and nb is None:
                        pierde[tienda] += 1
    print(f"folletos: {n_fol} | ROI: {'si' if usar_roi else 'no'} | {time.time() - t0:.0f}s")
    print(f"{'tienda':18s} {'regs HEAD':>9s} {'cambian':>8s} {'%':>6s} {'creados':>8s} {'perdidos':>9s}")
    for t in sorted(total):
        pct = 100 * cambia[t] / total[t] if total[t] else 0
        print(f"{t:18s} {total[t]:9d} {cambia[t]:8d} {pct:6.1f} {crea[t]:8d} {pierde[t]:9d}")
    tt = sum(total.values())
    print(f"{'TOTAL':18s} {tt:9d} {sum(cambia.values()):8d} {100 * sum(cambia.values()) / max(tt, 1):6.1f}"
          f" {sum(crea.values()):8d} {sum(pierde.values()):9d}")
    print("Sobre los nombres que cambian:")
    for k, v in sorted(largos.items()):
        print(f"   {k}: {v}")
    print("\nEjemplos por tienda (5, repartidos):")
    for t, lst in sorted(ejemplos.items()):
        print(t)
        paso = max(1, len(lst) // 5)
        for e in lst[::paso][:5]:
            print("   ", e)
    print("\nMuestra aleatoria (semilla 0) de 60 cambios para revision a mano:")
    random.Random(0).shuffle(todos)
    for e in todos[:60]:
        print("   ", e)


if __name__ == "__main__":
    main(sys.argv[1:])
