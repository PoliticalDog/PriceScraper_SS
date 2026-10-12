"""
Catalogo de disenos por tienda (solo dev): donde queda el nombre del producto respecto a su precio.

Para cada articulo del GT con precio se ubica su bloque de precio (NLP, monto igual) y su bloque
de nombre (OCR, similitud de tokens con el nombre GT); si hay varios candidatos se toma el par mas
cercano. La posicion del nombre se clasifica en arriba / fila_izq / fila_der / debajo.

Sirve para ver que tiendas (y que folletos) comparten diseno antes de proponer una regla, y para
volver a medirlo despues de cada cambio. Es descriptivo: no entra en las metricas ni en el juez.
Nunca corre sobre holdout (veria su contenido).
"""
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .comparar import precio_igual, similitud_nombre, tokens_tienda

RAIZ_CATALOGO = Path("data/processed/_eval/catalogo")
SIM_NOMBRE = 0.5      # nombre "completo" en un bloque (= UMBRAL_PRODUCTO del juez)
SIM_PARCIAL = 0.3     # parte del nombre en un bloque (nombre partido en varias lineas)
POSICIONES = ("arriba", "fila_izq", "fila_der", "debajo")
LOCALIZADO = ("completo", "parcial")


def caja(bloque: dict) -> dict:
    bb = bloque.get("bbox") or {}
    x, y, w, h = bb.get("x", 0), bb.get("y", 0), bb.get("ancho", 0), bb.get("alto", 0)
    return {"x": x, "y": y, "w": w, "h": h, "cx": x + w / 2, "cy": y + h / 2, "x2": x + w, "y2": y + h}


def posicion(p: dict, n: dict) -> str:
    """Posicion del nombre n respecto al precio p (cajas de caja())."""
    traslape = min(p["y2"], n["y2"]) - max(p["y"], n["y"])
    if traslape > 0.3 * max(1, min(p["h"], n["h"])):
        return "fila_izq" if n["cx"] < p["cx"] else "fila_der"
    if n["cy"] < p["y"]:
        return "arriba"
    if n["cy"] > p["y2"]:
        return "debajo"
    return "fila_izq" if n["cx"] < p["cx"] else "fila_der"


def alcanzable_cercania(p: dict, n: dict) -> bool:
    """El nombre entra en los candidatos de load.asociar_por_cercania(admitir_debajo=True)?"""
    from load.load import MARGEN_DEBAJO_PRECIO
    if abs(n["x"] - p["x"]) > 400:
        return False
    dy = p["y"] - n["y"]
    return dy > 0 or -dy <= p["h"] + MARGEN_DEBAJO_PRECIO


def medir_pagina(pg, pp, regiones) -> list[dict]:
    """Una fila por articulo del GT con precio: estado (completo/parcial/sin_precio_nlp/sin_nombre_ocr) y geometria."""
    ancho = pp.ocr.get("ancho_pagina") or 1
    bloques = pp.ocr.get("bloques", [])
    precios = pp.nlp.get("precios", [])
    ignorar = tokens_tienda(pg.tienda)
    filas = []
    for a in (a for a in pg.articulos if a.precio is not None):
        fila = {"tienda": pg.tienda, "folleto": pg.folleto, "pagina": pg.pagina, "id": a.id,
                "producto": a.producto, "precio": a.precio, "roi_pagina": bool(regiones)}
        cand_p = [caja(p) for p in precios if precio_igual(p.get("valor"), a.precio)]
        sims = [(similitud_nombre(a.producto, b.get("texto"), ignorar), caja(b), b.get("texto")) for b in bloques]
        mejor = max((s for s, _, _ in sims), default=0)
        cand_n = [(s, c, t) for s, c, t in sims if s >= SIM_PARCIAL and s >= mejor - 0.1]
        fila["n_bloques_nombre"] = sum(1 for s, _, _ in sims if s >= SIM_PARCIAL)
        if not cand_p:
            fila["estado"] = "sin_precio_nlp"
        elif not cand_n:
            fila["estado"] = "sin_nombre_ocr"
        else:
            d, p, (s, n, t) = min(((math.dist((p["cx"], p["cy"]), (n["cx"], n["cy"])), p, (s, n, t))
                                   for p in cand_p for s, n, t in cand_n), key=lambda x: x[0])
            fila.update({
                "estado": "completo" if s >= SIM_NOMBRE else "parcial",
                "sim": round(s, 2), "texto_nombre": t, "posicion": posicion(p, n),
                "dx_rel": round((n["cx"] - p["cx"]) / ancho, 3),            # fraccion del ancho de pagina
                "dy_altos": round((n["cy"] - p["cy"]) / max(1, p["h"]), 2),  # en altos del bloque de precio
                "dist_rel": round(d / ancho, 3),
                "alcanzable_cercania": alcanzable_cercania(p, n),
                "precios_mismo_monto": len(cand_p),
            })
        filas.append(fila)
    return filas


def construir(paginas_gt, fuente) -> dict:
    articulos, paginas = [], []
    for pg in paginas_gt:
        if not any(a.precio is not None for a in pg.articulos):
            continue
        pp = fuente.pagina(pg)
        if pp.nlp is None or pp.ocr is None:
            continue
        regiones = fuente._regiones(pg, pp.nlp)
        paginas.append({"tienda": pg.tienda, "folleto": pg.folleto, "pagina": pg.pagina,
                        "articulos": sum(a.precio is not None for a in pg.articulos), "roi": bool(regiones)})
        articulos.extend(medir_pagina(pg, pp, regiones))
    return {"articulos": articulos, "paginas": paginas}


def resumen(cat: dict) -> dict:
    """Por tienda: estados, distribucion de posiciones, alcanzables, ROI; por folleto: posicion dominante."""
    por_t, pags_t, por_f = defaultdict(list), defaultdict(list), defaultdict(list)
    for f in cat["articulos"]:
        por_t[f["tienda"]].append(f)
        if f["estado"] in LOCALIZADO:
            por_f[(f["tienda"], f["folleto"])].append(f)
    for p in cat["paginas"]:
        pags_t[p["tienda"]].append(p)

    tiendas = {}
    for t in sorted(por_t):
        fs, pags = por_t[t], pags_t[t]
        loc = [f for f in fs if f["estado"] in LOCALIZADO]
        dist = sorted(f["dist_rel"] for f in loc)
        folletos = {}
        for (tt, fol), ffs in sorted(por_f.items()):
            if tt == t:
                dom, n = Counter(f["posicion"] for f in ffs).most_common(1)[0]
                folletos[fol] = {"posicion": dom, "fraccion": round(n / len(ffs), 2), "n": len(ffs)}
        tiendas[t] = {
            "folletos": len({p["folleto"] for p in pags}), "paginas": len(pags), "articulos": len(fs),
            "estados": dict(Counter(f["estado"] for f in fs)), "localizados": len(loc),
            "posiciones": {x: sum(f["posicion"] == x for f in loc) for x in POSICIONES},
            "parciales": sum(f["estado"] == "parcial" for f in loc),
            "alcanzables": sum(f["alcanzable_cercania"] for f in loc),
            "paginas_roi": sum(p["roi"] for p in pags),
            "dist_mediana": dist[len(dist) // 2] if dist else None,
            "por_folleto": folletos,
        }
    return tiendas


def _pct(n, d) -> str:
    return f"{100 * n / d:4.0f}%" if d else "   - "


def imprimir(tiendas: dict) -> None:
    print(f"{'tienda':<16}{'fol':>4}{'pag':>4}{'art':>5}{'sin$':>6}{'loc':>6} | " + "".join(f"{x:>9}" for x in POSICIONES)
          + f" |{'parcial':>8}{'alcanz':>8}{'roi_pag':>8}{'dist':>6}")
    for t, m in tiendas.items():
        loc = m["localizados"]
        print(f"{t:<16}{m['folletos']:>4}{m['paginas']:>4}{m['articulos']:>5}"
              f"{_pct(m['estados'].get('sin_precio_nlp', 0), m['articulos']):>6}{_pct(loc, m['articulos']):>6} | "
              + "".join(f"{_pct(m['posiciones'][x], loc):>9}" for x in POSICIONES)
              + f" |{_pct(m['parciales'], loc):>8}{_pct(m['alcanzables'], loc):>8}{_pct(m['paginas_roi'], m['paginas']):>8}"
              + (f"{m['dist_mediana']:>6.2f}" if m["dist_mediana"] is not None else "     -"))
    print("  sin$: articulos sin precio con el monto correcto en el NLP | loc: nombre y precio ubicados\n"
          "  posiciones: del nombre respecto al precio, sobre los ubicados | alcanz: entra en asociar_por_cercania\n"
          "  roi_pag: paginas con regiones de producto confiables | dist: mediana nombre-precio en anchos de pagina")
    print("\nPor folleto (posicion dominante, % y n ubicados):")
    for t, m in tiendas.items():
        print(f"  {t:<16} " + " | ".join(f"{fol}: {v['posicion']} {v['fraccion'] * 100:.0f}% (n={v['n']})"
                                         for fol, v in m["por_folleto"].items()))


def guardar(cat: dict, tiendas: dict, meta: dict) -> Path:
    v = meta["codigo"]
    RAIZ_CATALOGO.mkdir(parents=True, exist_ok=True)
    ruta = RAIZ_CATALOGO / (f"{datetime.now():%Y%m%d_%H%M%S}_{v['commit'] or 'sin-git'}"
                            f"{'-sucio' if v['cambios_sin_commit'] else ''}.json")
    json.dump({"meta": meta, "tiendas": tiendas, **cat}, open(ruta, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return ruta
