"""Herramienta de SOLO LECTURA (no es prueba). Experimento nombre partido, iteracion 2 (25-oct-2026).

Sobre el NLP de produccion regenerado en memoria (extractor del arbol, con A2) compara, con las mismas regiones ROI:
  HEAD   construir_registros_pagina de `git show HEAD:load/load.py`
  v1     el arbol con _tipo_corte_pila -> None y _pilas_sin_cruces -> identidad (version anterior, 24-oct)
  corte  el arbol con _pilas_sin_cruces -> identidad (solo el corte por promocion/vigencia/oferta)
  final  el arbol tal cual (corte + pilas sin cruces)
Cuenta nombres que cambian v1 -> final, por corte (y por tipo de patron) y por la proteccion de pila, con
ejemplos, y los registros con nombre de catalogo (exacto/fuzzy) en cada version. No escribe nada.

    venv/Scripts/python.exe tests/_herramienta_asoc_produccion2.py <dir_tiendeo> [<dir_ofertomat> ...]
"""
import importlib
import importlib.util
import json
import os
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

N = importlib.import_module("load.load")
TIPO_ORIG = N._tipo_corte_pila
# _pilas_sin_cruces se descarto el 25-oct; si no existe, "corte" y "final" son la misma version
CRUCES_ORIG = getattr(N, "_pilas_sin_cruces", None)
CORTES = defaultdict(list)  # _idx del bloque elegido -> [(tipo, texto de la linea)]
ACTUAL = [None]


def modulo_head():
    fuente = subprocess.run(["git", "show", "HEAD:load/load.py"], cwd=RAIZ, capture_output=True,
                            text=True, encoding="utf-8", check=True).stdout
    spec = importlib.util.spec_from_loader("load.load_head", loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "load"
    sys.modules["load.load_head"] = modulo
    exec(compile(fuente, "HEAD:load/load.py", "exec"), modulo.__dict__)
    return modulo


PILA_ORIG = N._pila_lineas


def pila_instrumentada(prod, productos, ajenos):
    ACTUAL[0] = prod.get("_idx")
    return PILA_ORIG(prod, productos, ajenos)


def tipo_instrumentado(prod):
    t = TIPO_ORIG(prod)
    if t:
        CORTES[ACTUAL[0]].append((t, prod.get("texto", "")))
    return t


def correr(pag, regiones, norm, corte, cruces):
    N._tipo_corte_pila = tipo_instrumentado if corte else (lambda prod: None)
    if CRUCES_ORIG is not None:
        N._pilas_sin_cruces = CRUCES_ORIG if cruces else (lambda pilas, precios_de: {k: l for k, (_, l) in pilas.items()})
    N._pila_lineas = pila_instrumentada
    try:
        return N.construir_registros_pagina(pag, regiones, norm)["precios"]
    finally:
        N._tipo_corte_pila, N._pila_lineas = TIPO_ORIG, PILA_ORIG
        if CRUCES_ORIG is not None:
            N._pilas_sin_cruces = CRUCES_ORIG


def nombre(reg):
    p = reg["producto"]
    return None if p is None else p.get("_nombre_norm")


def es_catalogo(reg):
    p = reg["producto"]
    r = p.get("_resultado_unido") or p.get("_resultado")
    return r is not None and r.metodo in ("exacto", "fuzzy", "fuzzy_bajo")


def main(raices):
    viejo = modulo_head()
    norm, ext = Normalizador(), RegexExtractor()
    regs, catalogo = Counter(), Counter()
    cambia_total, por_corte, por_cruce = Counter(), Counter(), Counter()
    por_tipo = Counter()
    ej_tipo, ej_cruce = defaultdict(list), []
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
                if tienda in N.TIENDAS_ROI_HIBRIDO:
                    try:
                        cand = N.candidatas_roi_pagina(fuente, tienda, folleto, pag["pagina"])
                        regiones = None if cand is None else N.regiones_con_precio(cand, pag.get("precios", []))
                    except Exception:
                        regiones = None
                h = viejo.construir_registros_pagina(pag, regiones, norm)["precios"]
                v1 = correr(pag, regiones, norm, False, False)
                CORTES.clear()
                c = correr(pag, regiones, norm, True, False)
                cortes_pag = dict(CORTES)
                f = correr(pag, regiones, norm, True, True)
                for rh, r1, rc, rf in zip(h, v1, c, f):
                    if rh["precio"].get("valor") is None or nombre(rf) is None:
                        continue
                    regs[tienda] += 1
                    catalogo["HEAD"] += es_catalogo(rh)
                    catalogo["v1"] += es_catalogo(r1)
                    catalogo["final"] += es_catalogo(rf)
                    clave = f"{tienda}/{folleto}/{pag['pagina']} ${rf['precio'].get('valor')}"
                    if nombre(r1) != nombre(rf):
                        cambia_total[tienda] += 1
                    if nombre(r1) != nombre(rc):
                        por_corte[tienda] += 1
                        tipos = cortes_pag.get(r1["producto"].get("_idx")) or [("?", "")]
                        tipo, linea = tipos[0]
                        por_tipo[tipo] += 1
                        ej_tipo[tipo].append(f"{clave}: {nombre(r1)!r} -> {nombre(rc)!r}  [corta en {linea!r}]")
                    if nombre(rc) != nombre(rf):
                        por_cruce[tienda] += 1
                        quitado = set(nombre(rc).lower().split()) - set(nombre(rf).lower().split())
                        ganan = [f"${o['precio'].get('valor')} {nombre(o)!r}" for o in f
                                 if o is not rf and nombre(o) and quitado & set(nombre(o).lower().split())]
                        ej_cruce.append(f"{clave}: {nombre(rc)!r} -> {nombre(rf)!r}  | se la quedan: {'; '.join(ganan[:2])}")
    print(f"folletos: {n_fol} | {time.time() - t0:.0f}s")
    print(f"{'tienda':18s} {'regs':>6s} {'v1->final':>9s} {'corte':>6s} {'cruces':>7s}")
    for t in sorted(regs):
        print(f"{t:18s} {regs[t]:6d} {cambia_total[t]:9d} {por_corte[t]:6d} {por_cruce[t]:7d}")
    print(f"{'TOTAL':18s} {sum(regs.values()):6d} {sum(cambia_total.values()):9d} {sum(por_corte.values()):6d}"
          f" {sum(por_cruce.values()):7d}")
    print("Registros cambiados por corte, por tipo de patron:", dict(por_tipo))
    print("Registros con nombre de catalogo:", dict(catalogo))
    todos = "--todos" in sys.argv
    for tipo, lst in sorted(ej_tipo.items()):
        print(f"\n== corte {tipo} ({len(lst)})")
        paso = 1 if todos else max(1, len(lst) // 5)
        for e in lst[::paso][: None if todos else 5]:
            print("   ", e)
    print(f"\n== proteccion de pila ({len(ej_cruce)})")
    paso = 1 if todos else max(1, len(ej_cruce) // 15)
    for e in ej_cruce[::paso][: None if todos else 15]:
        print("   ", e)


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("--")])
