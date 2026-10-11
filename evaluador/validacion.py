"""
Validacion del juez contra una persona (fase 3): muestra de registros del dashboard que el
usuario califica viendo la imagen, y concordancia entre su veredicto y el del evaluador.

La muestra sale solo de dev (el holdout no se usa para calibrar) y mezcla veredictos del
juez: correctos, pares con producto dudoso y registros sin pareja.
"""
import base64
import hashlib
import io
import json
from pathlib import Path

from PIL import Image, ImageDraw

from .comparar import comparar_pagina
from .gt import FUENTE_GT, cargar_gt
from .pipeline import FuentePipeline
from .splits import cargar, filtrar

RAIZ_VALIDACION = Path("data/processed/_eval/validacion")
CUOTAS = {"correcto": 14, "par_incorrecto": 16, "sin_pareja": 10}


def _orden(clave: str) -> str:
    return hashlib.sha256(f"validacion-v1:{clave}".encode()).hexdigest()


def _recorte(registro, ancho_pagina: int) -> str:
    """JPEG en base64 del area del precio y su producto. Azul = precio, naranja = producto."""
    tienda, folleto, pagina = registro.pagina.split("/", 2)
    img = Image.open(Path("data/raw", FUENTE_GT, tienda, folleto, pagina)).convert("RGB")
    s = img.width / ancho_pagina
    cajas = [(registro.bbox_precio, (30, 90, 230))]
    if registro.bbox_producto:
        cajas.append((registro.bbox_producto, (235, 120, 20)))
    d = ImageDraw.Draw(img)
    xs, ys = [], []
    for b, color in cajas:
        x0, y0, x1, y1 = b["x"] * s, b["y"] * s, (b["x"] + b["ancho"]) * s, (b["y"] + b["alto"]) * s
        d.rectangle([x0, y0, x1, y1], outline=color, width=3)
        xs += [x0, x1]
        ys += [y0, y1]
    m = 90
    recorte = img.crop((max(0, min(xs) - m), max(0, min(ys) - m), min(img.width, max(xs) + m), min(img.height, max(ys) + m)))
    recorte.thumbnail((560, 560))
    buf = io.BytesIO()
    recorte.save(buf, "JPEG", quality=82)
    return base64.b64encode(buf.getvalue()).decode()


def generar_muestra() -> dict:
    fuente = FuentePipeline()
    candidatos = {k: [] for k in CUOTAS}
    for pg in filtrar(cargar_gt(), "dev", cargar()):
        pp = fuente.pagina(pg)
        res = comparar_pagina(pp)
        ancho = (pp.ocr or {}).get("ancho_pagina")
        if not ancho:
            continue
        for p in res.pares:
            grupo = "correcto" if p.basico_ok else ("par_incorrecto" if p.precio_ok else None)
            if grupo:
                candidatos[grupo].append((p.registro, ancho, {"juez_producto_ok": p.producto_ok, "juez_precio_ok": p.precio_ok,
                                                              "juez_antes_ok": p.anterior_ok, "similitud": round(p.similitud, 2)}))
        for r, codigo in res.registros_sobrantes:
            candidatos["sin_pareja"].append((r, ancho, {"juez_producto_ok": False, "juez_precio_ok": False,
                                                        "juez_antes_ok": None, "codigo": codigo}))

    casos = []
    for grupo, cuota in CUOTAS.items():
        # Un caso por tienda en cada vuelta, para que ninguna tienda llene la muestra
        por_tienda = {}
        for c in sorted(candidatos[grupo], key=lambda c: _orden(f"{c[0].pagina}#{c[0].idx}")):
            por_tienda.setdefault(c[0].pagina.split("/")[0], []).append(c)
        elegidos = []
        while len(elegidos) < cuota and any(por_tienda.values()):
            for t in sorted(por_tienda):
                if por_tienda[t] and len(elegidos) < cuota:
                    elegidos.append(por_tienda[t].pop(0))
        for r, ancho, juez in elegidos:
            casos.append({"id": f"c{len(casos) + 1:02d}", "grupo": grupo, "tienda": r.pagina.split("/")[0],
                          "pagina": r.pagina, "producto": r.producto, "precio": r.precio,
                          "precio_anterior": r.precio_anterior, "juez": juez, "imagen": _recorte(r, ancho)})
    casos.sort(key=lambda c: _orden(c["id"]))  # el orden no delata el grupo
    return {"version": 1, "casos": casos}


def concordancia(muestra: dict, respuestas: dict[str, dict], no_evaluables: set[str] = frozenset()) -> dict:
    """
    respuestas[id] = {"producto": "si"|"no"|"dudoso", "precio": "si"|"no", "antes": "si"|"no"|"na"}.
    Se compara el veredicto basico (precio + producto) del juez con el de la persona;
    los "dudoso" se reportan aparte y no cuentan. `no_evaluables`: paginas del GT sin precios
    (el juez ya no las mide), tampoco cuentan.
    """
    acuerdos, total, dudosos, desacuerdos, excluidos = 0, 0, 0, [], []
    for c in muestra["casos"]:
        r = respuestas.get(c["id"])
        if not r:
            continue
        if c["pagina"] in no_evaluables:
            excluidos.append(c["id"])
            continue
        if r.get("producto") == "dudoso":
            dudosos += 1
            continue
        humano = r.get("producto") == "si" and r.get("precio") == "si"
        juez = bool(c["juez"]["juez_producto_ok"] and c["juez"]["juez_precio_ok"])
        total += 1
        if humano == juez:
            acuerdos += 1
        else:
            desacuerdos.append({"id": c["id"], "pagina": c["pagina"], "producto": c["producto"], "precio": c["precio"],
                                "juez": juez, "humano": humano, "detalle_juez": c["juez"], "respuesta": r})
    return {"evaluados": total, "acuerdos": acuerdos, "dudosos": dudosos, "excluidos": excluidos,
            "concordancia": round(acuerdos / total, 4) if total else None, "desacuerdos": desacuerdos}


def guardar_muestra(ruta: Path | None = None) -> Path:
    ruta = ruta or RAIZ_VALIDACION / "muestra_v1.json"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    json.dump(generar_muestra(), open(ruta, "w", encoding="utf-8"), ensure_ascii=False)
    return ruta
