"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento asociacion_producto, 24-oct-2026.

Simula, sin cambiar load, que pasaria si el nombre del registro fuera la PILA de lineas producto contiguas
(misma columna) del bloque elegido, hacia arriba y/o hacia abajo, en vez de una sola linea. Re-normaliza el
texto unido y recalcula la similitud contra el articulo GT emparejado (sin re-emparejar: aproximado).

    venv/Scripts/python.exe tests/_herramienta_asoc_sim.py [--tienda T] [--ejemplos N]
"""
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if os.environ.get("PYTHONHASHSEED") != "0":
    sys.exit(subprocess.call([sys.executable, *sys.argv], env={**os.environ, "PYTHONHASHSEED": "0"}, cwd=RAIZ))
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
import logging  # noqa: E402

logging.disable(logging.WARNING)

import importlib  # noqa: E402

from evaluador import splits  # noqa: E402
from evaluador.comparar import comparar_pagina, similitud_nombre, tokens_tienda  # noqa: E402
from evaluador.gt import cargar_gt  # noqa: E402
from evaluador.pipeline import FuentePipeline  # noqa: E402

L = importlib.import_module("load.load")
MAX = L.MAX_LINEAS_DESCRIPCION


def pila(prod, productos, ajenos, arriba=True, abajo=True):
    lineas = [prod]
    if arriba:
        actual = prod
        while len(lineas) <= MAX:
            tope = L._alto_tope(lineas)
            enc = [o for o in productos if all(o is not l for l in lineas) and L._linea_encima(o, actual, tope)]
            if not enc:
                break
            sig = max(enc, key=lambda o: o["bbox"]["y"] + o["bbox"]["alto"])
            if L._es_banda(sig, lineas, productos) or id(sig) in ajenos:
                break
            lineas.append(sig)
            actual = sig
    lineas.reverse()
    if abajo:
        actual = prod
        while len(lineas) <= MAX:
            deb = [o for o in productos if all(o is not l for l in lineas)
                   and L._linea_encima(actual, o, min(actual["bbox"]["alto"], o["bbox"]["alto"]))]
            if not deb:
                break
            sig = min(deb, key=lambda o: o["bbox"]["y"])
            if id(sig) in ajenos:
                break
            lineas.append(sig)
            actual = sig
    return lineas


def main():
    args = sys.argv[1:]
    tienda = args[args.index("--tienda") + 1] if "--tienda" in args else None
    n_ej = int(args[args.index("--ejemplos") + 1]) if "--ejemplos" in args else 3
    paginas = splits.filtrar(cargar_gt(), "dev", splits.cargar())
    if tienda:
        paginas = [p for p in paginas if p.tienda == tienda]
    fuente = FuentePipeline(nlp="memoria")
    norm = fuente.normalizador
    variantes = {"arriba": (True, False), "abajo": (False, True), "ambas": (True, True)}
    cuenta = {v: defaultdict(Counter) for v in variantes}
    ejemplos = {v: defaultdict(list) for v in variantes}
    for pg in paginas:
        pp = fuente.pagina(pg)
        res = comparar_pagina(pp)
        ign = tokens_tienda(pg.tienda)
        prods = pp.productos_aceptados
        por_bbox = {}
        for p in prods:
            por_bbox.setdefault(tuple(sorted(p["bbox"].items())), p)
        elegidos = defaultdict(set)  # id(bloque) -> precios que lo eligieron
        for r in pp.registros:
            if r.bbox_producto:
                b = por_bbox.get(tuple(sorted(r.bbox_producto.items())))
                if b is not None:
                    elegidos[id(b)].add(r.idx)
        for par in res.pares:
            if not par.precio_ok:
                continue
            r = par.registro
            b = por_bbox.get(tuple(sorted((r.bbox_producto or {}).items())))
            if b is None:
                continue  # ya unido con su unidad u otro caso
            ajenos = {k for k, idxs in elegidos.items() if idxs - {r.idx}}
            antes_ok = par.similitud >= 0.5
            for v, (ar, ab) in variantes.items():
                lineas = pila(b, prods, ajenos, ar, ab)
                if len(lineas) == 1:
                    continue
                texto = " ".join(l["texto"].strip() for l in lineas)
                rn = norm.normalizar(texto)
                nombre = texto if rn.descartado else (rn.nombre_canonico or texto)
                s = similitud_nombre(par.articulo.producto, nombre, ign)
                despues_ok = s >= 0.5
                if antes_ok == despues_ok:
                    cuenta[v][pg.tienda]["igual_" + ("ok" if antes_ok else "mal")] += 1
                    continue
                clave = "gana" if despues_ok else "pierde"
                cuenta[v][pg.tienda][clave] += 1
                ejemplos[v][clave].append(f"{r.pagina} ${r.precio} GT={par.articulo.producto!r}\n"
                                          f"        {r.producto!r} -> {nombre!r}")
    for v in variantes:
        print(f"\n### variante {v}")
        tot = Counter()
        for t, c in sorted(cuenta[v].items()):
            tot.update(c)
            print(f"  {t:16s} gana {c['gana']:3d} pierde {c['pierde']:3d} | cambia sin efecto ok {c['igual_ok']:3d} mal {c['igual_mal']:3d}")
        print(f"  {'TOTAL':16s} gana {tot['gana']:3d} pierde {tot['pierde']:3d} | cambia sin efecto ok {tot['igual_ok']:3d} mal {tot['igual_mal']:3d}")
        for clave in ("pierde", "gana"):
            print(f"  -- {clave}")
            for e in ejemplos[v][clave][: n_ej if clave == "gana" else 40]:
                print("     ", e)


if __name__ == "__main__":
    main()
