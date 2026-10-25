"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento asociacion_producto, 24-oct-2026.

Reconstruye en memoria las paginas dev (mismo camino que `evaluador correr --nlp memoria`) y clasifica cada
par con error asociacion_producto (precio bien leido, producto equivocado) por subtipo de causa:

  N   el bloque elegido SI tenia el nombre (texto OCR sim>=0.5) y el normalizador lo cambio (fuzzy/canonico)
  A*  habia un bloque producto aceptado con el nombre correcto y se eligio otro:
        A-attr   el elegido es atributo/presentacion (unidad, medida, talla, "6 menus")
        A-marca  el elegido es solo la marca
        A-vecino el elegido esta mas cerca de OTRO precio (pertenece a otra casilla)
        A-otro   resto (ruido, encabezado, fragmento)
  D   el nombre esta en un bloque PRODUCTO del NLP que el normalizador descarta o es ilegible
  T   el nombre se clasifico como ATRIBUTO;  P  como PROMO
  C   el nombre esta en el OCR pero se clasifico como otra cosa (descarte, precio)
  S   ningun bloque solo tiene el nombre, pero la union de 2-4 bloques cercanos si (nombre partido)
  O   no se encuentra (OCR ilegible, GT con nombre no impreso, etc.)

    venv/Scripts/python.exe tests/_herramienta_asoc_diag.py [--tienda T] [--ejemplos N]
"""
import math
import os
import re
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

from evaluador import splits  # noqa: E402
from evaluador.comparar import comparar_pagina, similitud_nombre, tokens_tienda  # noqa: E402
from evaluador.gt import cargar_gt  # noqa: E402
from evaluador.pipeline import FuentePipeline  # noqa: E402
from nlp.normalizador import MARCAS_CONOCIDAS  # noqa: E402

UMBRAL = 0.5
PAT_ATRIBUTO = re.compile(
    r"\b\d+[\d.,/]*\s*(?:kg|g|gr|grs|gramos|ml|l|lt|lts|litros?|oz|pzas?|piezas?|pulgadas?|cm|mm|m|w|hp|gb|tb|"
    r"mah|v|menus?|velocidades|puertas|quemadores|niveles|capas|rollos|hojas|metros?)\b|"
    r"\d+\s*[\"”']|\btalla\b|\bmodelo\b|\bmod\.|\bcapacidad\b|\bcontenido\b|\bbaja en\b|\bideal para\b|"
    r"^(?:pieza|piezas|carton|cartón|gramos|kg|paquete)\W*$",
    re.IGNORECASE,
)


def centro(b):
    return b.get("x", 0) + b.get("ancho", 0) / 2, b.get("y", 0) + b.get("alto", 0) / 2


def dist(b1, b2):
    (x1, y1), (x2, y2) = centro(b1), centro(b2)
    return math.hypot(x1 - x2, y1 - y2)


def precio_mas_cercano(bbox, precios):
    return min(precios, key=lambda p: dist(bbox, p.get("bbox", {}))) if precios else None


def es_marca(texto):
    t = re.sub(r"[^a-záéíóúñ ]", " ", (texto or "").lower()).split()
    return bool(t) and " ".join(t) in MARCAS_CONOCIDAS


def rel(b, bp):
    """Posicion del bloque b respecto al precio bp: dx, dy (bordes sup. izq.)."""
    return round(b.get("x", 0) - bp.get("x", 0)), round(b.get("y", 0) - bp.get("y", 0))


def clasificar(par, pp, ign):
    r, a = par.registro, par.articulo
    g = a.producto
    nlp = pp.nlp or {}
    precios = nlp.get("precios", [])
    bp = r.bbox_precio or {}
    sim = lambda t: similitud_nombre(g, t, ign)  # noqa: E731
    info = {"gt": g, "precio": r.precio, "reg": r.producto, "reg_txt": r.producto_texto,
            "bbox_reg": r.bbox_producto, "bbox_precio": bp, "pagina": r.pagina}
    if r.producto_texto and sim(r.producto_texto) >= UMBRAL:
        return "N", info
    acept = [(max(sim(p.get("_nombre_norm")), sim(p.get("texto"))), p) for p in pp.productos_aceptados]
    acept.sort(key=lambda t: -t[0])
    if acept and acept[0][0] >= UMBRAL:
        bueno = acept[0][1]
        info["bueno"] = bueno.get("texto")
        info["bueno_rel"] = rel(bueno.get("bbox", {}), bp)
        info["reg_rel"] = rel(r.bbox_producto or {}, bp)
        cerc_bueno = precio_mas_cercano(bueno.get("bbox", {}), precios)
        info["bueno_de_otro"] = cerc_bueno is not None and cerc_bueno.get("bbox") != bp
        txt = r.producto_texto or ""
        if PAT_ATRIBUTO.search(txt):
            return "A-attr", info
        if es_marca(txt):
            return "A-marca", info
        cerc = precio_mas_cercano(r.bbox_producto or {}, precios)
        if cerc is not None and cerc.get("bbox") != bp:
            return "A-vecino", info
        return "A-otro", info
    for p in nlp.get("productos", []):
        if sim(p.get("texto")) >= UMBRAL:
            info["bueno"] = p.get("texto")
            return "D", info
    for p in nlp.get("atributos", []):
        if sim(p.get("texto")) >= UMBRAL:
            info["bueno"] = p.get("texto")
            info["bueno_rel"] = rel(p.get("bbox", {}), bp)
            return "T", info
    for p in nlp.get("promos", []):
        if sim(p.get("texto")) >= UMBRAL:
            info["bueno"] = p.get("texto")
            return "P", info
    bloques = (pp.ocr or {}).get("bloques", [])
    for b in bloques:
        if sim(b.get("texto")) >= UMBRAL:
            info["bueno"] = b.get("texto")
            return "C", info
    # Nombre partido: union de los bloques aceptados cercanos (radio 450 px) con algun token del GT
    cerca = [p for p in pp.productos_aceptados if dist(p.get("bbox", {}), bp) <= 450]
    utiles = [p for p in cerca if sim(p.get("texto")) > 0]
    utiles.sort(key=lambda p: (p.get("bbox", {}).get("y", 0), p.get("bbox", {}).get("x", 0)))
    if len(utiles) >= 2:
        union = " ".join(p.get("texto", "") for p in utiles[:4])
        if sim(union) >= UMBRAL:
            info["bueno"] = union
            return "S", info
    return "O", info


def main():
    args = sys.argv[1:]
    tienda = args[args.index("--tienda") + 1] if "--tienda" in args else None
    n_ej = int(args[args.index("--ejemplos") + 1]) if "--ejemplos" in args else 4
    paginas = splits.filtrar(cargar_gt(), "dev", splits.cargar())
    if tienda:
        paginas = [p for p in paginas if p.tienda == tienda]
    fuente = FuentePipeline(nlp="memoria")
    conteo = defaultdict(Counter)
    ejemplos = defaultdict(list)
    extra = Counter()
    for pg in paginas:
        pp = fuente.pagina(pg)
        res = comparar_pagina(pp)
        ign = tokens_tienda(pg.tienda)
        for par in res.pares:
            if par.error != "asociacion_producto":
                continue
            sub, info = clasificar(par, pp, ign)
            conteo[sub][pg.tienda] += 1
            if sub.startswith("A") and info.get("bueno_de_otro"):
                extra["A con el nombre bueno mas cerca de OTRO precio"] += 1
            if PAT_ATRIBUTO.search(info.get("reg_txt") or ""):
                extra["elegido con forma de atributo (cualquier subtipo)"] += 1
            ejemplos[sub].append(info)
    tiendas = sorted({t for c in conteo.values() for t in c})
    print(f"{'subtipo':10s} {'total':>5s}  " + " ".join(f"{t[:8]:>8s}" for t in tiendas))
    tot = 0
    for sub in sorted(conteo):
        c = conteo[sub]
        tot += sum(c.values())
        print(f"{sub:10s} {sum(c.values()):5d}  " + " ".join(f"{c.get(t, 0):8d}" for t in tiendas))
    print(f"{'TOTAL':10s} {tot:5d}")
    for k, v in extra.items():
        print(f"  {k}: {v}")
    for sub in sorted(ejemplos):
        print(f"\n== {sub} ({len(ejemplos[sub])})")
        vistos = Counter()
        for e in ejemplos[sub]:
            t = e["pagina"].split("/")[0]
            if vistos[t] >= n_ej:
                continue
            vistos[t] += 1
            print(f"  {e['pagina']} ${e['precio']} GT={e['gt']!r}")
            print(f"      reg={e['reg']!r} (OCR {e['reg_txt']!r}) rel={e.get('reg_rel')}  bueno={e.get('bueno')!r}"
                  f" rel={e.get('bueno_rel')} de_otro={e.get('bueno_de_otro')}")
            print(f"      bbox_precio={e['bbox_precio']} bbox_reg={e['bbox_reg']}")


if __name__ == "__main__":
    main()
