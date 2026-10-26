"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento precio sin "$" / rotulo, 25-oct-2026.

Corre el RegexExtractor de HEAD (cargado en memoria con `git show HEAD:nlp/regex_extractor.py`) dos veces sobre
los ocr_resultado.json de produccion: tal cual, y con el filtro 2b (aa7f88d) desactivado en memoria
(_alto_como_texto y _continua_nombre devuelven False). Para cada pagina cuenta los PRECIO de las dos versiones y
guarda los que el filtro quita, con el contexto que sirve para separarlos del ruido: alto relativo a la mediana de
texto de la pagina, motivo (alto / continua), rotulo justo encima, vecinos cercanos, precios con "$" de la pagina.
Tambien cuenta, por tienda, el texto del bloque justo encima de cada PRECIO que HEAD conserva (rotulo de casilla).
No escribe nada fuera de <salida.json>.

    venv/Scripts/python.exe tests/_herramienta_sin_signo_paginas.py <salida.json> <dir_tiendeo> [<dir_ofertomat> ...]
"""
import importlib.util
import json
import logging
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
logging.disable(logging.INFO)

from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def cargar_modulo_head(nombre):
    fuente = subprocess.run(["git", "show", "HEAD:nlp/regex_extractor.py"], cwd=RAIZ, capture_output=True,
                            text=True, encoding="utf-8", check=True).stdout
    spec = importlib.util.spec_from_loader(nombre, loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "nlp"
    sys.modules[nombre] = modulo
    exec(compile(fuente, "HEAD:nlp/regex_extractor.py", "exec"), modulo.__dict__)
    return modulo


def extractores():
    head = cargar_modulo_head("nlp.regex_extractor_head").RegexExtractor()
    mod_sin = cargar_modulo_head("nlp.regex_extractor_sin2b")
    mod_sin.RegexExtractor._alto_como_texto = lambda self, bbox, bloques: False
    mod_sin.RegexExtractor._continua_nombre = lambda self, bbox, bloques, factor_escala=1.0: False
    return head, mod_sin.RegexExtractor()


def precios(resultados):
    out = {}
    for r in resultados:
        for e in r.precios:
            b = e.bbox or {}
            out[(r.imagen, e.texto_raw, b.get("x"), b.get("y"))] = (e.valor, b)
    return out


PATRON_LETRAS = re.compile(r"[^\W\d_]{3}")


def mediana_texto(bloques):
    altos = sorted(b["bbox"]["alto"] for b in bloques if b.get("bbox") and PATRON_LETRAS.search(b.get("texto", "")))
    if not altos:
        return None
    m = len(altos) // 2
    return altos[m] if len(altos) % 2 else (altos[m - 1] + altos[m]) / 2


def bloque_encima(bbox, bloques):
    """Bloque mas cercano justo encima con traslape horizontal (hueco <= 2x su alto)."""
    mejor, dist = None, None
    for o in bloques:
        ob = o.get("bbox")
        if not ob or ob is bbox or (ob.get("x"), ob.get("y")) == (bbox.get("x"), bbox.get("y")):
            continue
        if min(bbox["x"] + bbox["ancho"], ob["x"] + ob["ancho"]) <= max(bbox["x"], ob["x"]):
            continue
        hueco = bbox["y"] - (ob["y"] + ob["alto"])
        if -0.5 * ob["alto"] <= hueco <= 2 * max(ob["alto"], bbox["alto"]):
            if dist is None or hueco < dist:
                mejor, dist = o, hueco
    return mejor


def vecinos(bbox, bloques, radio):
    cx, cy = bbox["x"] + bbox["ancho"] / 2, bbox["y"] + bbox["alto"] / 2
    out = []
    for o in bloques:
        ob = o.get("bbox")
        if not ob or (ob.get("x"), ob.get("y")) == (bbox.get("x"), bbox.get("y")):
            continue
        dx = max(ob["x"] - (bbox["x"] + bbox["ancho"]), bbox["x"] - (ob["x"] + ob["ancho"]), 0)
        dy = max(ob["y"] - (bbox["y"] + bbox["alto"]), bbox["y"] - (ob["y"] + ob["alto"]), 0)
        d = (dx * dx + dy * dy) ** 0.5
        if d <= radio:
            out.append((round(d), o.get("texto", ""), ob["alto"]))
    return sorted(out)[:8]


def main(salida, raices):
    head, sin2b = extractores()
    t0 = time.time()
    paginas = []
    rotulo_head = defaultdict(Counter)
    n_folletos = 0
    for raiz in raices:
        fuente = Path(raiz).name
        for ocr_path in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n_folletos += 1
            if n_folletos % 50 == 0:
                print(f"  {n_folletos} folletos, {time.time() - t0:.0f}s", flush=True)
            bloques_por_pag = {p["pagina"]: p["bloques"] for p in ocr.get("paginas", [])}
            rh, rs = clasificar_paginas_ocr(ocr, head), clasificar_paginas_ocr(ocr, sin2b)
            ph, ps = precios(rh), precios(rs)
            por_pag_h, por_pag_s = Counter(k[0] for k in ph), Counter(k[0] for k in ps)
            con_signo = Counter(k[0] for k in ph if "$" in (k[1] or ""))
            for k, (v, b) in ph.items():
                arriba = bloque_encima(b, bloques_por_pag.get(k[0], []))
                if arriba is not None:
                    rotulo_head[tienda][re.sub(r"\s+", " ", arriba.get("texto", "")).strip()[:30]] += 1
            perdidos_por_pag = defaultdict(list)
            for k, (v, b) in ps.items():
                if k in ph:
                    continue
                bloques = bloques_por_pag.get(k[0], [])
                med = mediana_texto(bloques)
                es_alto = bool(med) and b.get("alto", 0) < 1.3 * med
                arriba = bloque_encima(b, bloques)
                perdidos_por_pag[k[0]].append({
                    "texto": k[1], "valor": v, "bbox": b,
                    "ratio_alto": round(b.get("alto", 0) / med, 2) if med else None,
                    "motivo": "alto" if es_alto else "continua",
                    "encima": arriba.get("texto") if arriba else None,
                    "encima_alto": arriba["bbox"]["alto"] if arriba else None,
                    "vecinos": vecinos(b, bloques, 3 * b.get("alto", 0)),
                })
            for r in rs:
                pag = r.imagen
                if por_pag_h[pag] == por_pag_s[pag] and not perdidos_por_pag.get(pag):
                    continue
                paginas.append({
                    "fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": pag,
                    "precios_head": por_pag_h[pag], "precios_sin2b": por_pag_s[pag],
                    "precios_con_signo_head": con_signo[pag],
                    "mediana_texto": mediana_texto(bloques_por_pag.get(pag, [])),
                    "n_bloques": len(bloques_por_pag.get(pag, [])),
                    "perdidos": perdidos_por_pag.get(pag, []),
                })
    cero = [p for p in paginas if p["precios_head"] == 0 and p["precios_sin2b"] > 0]
    por_tienda = Counter(p["tienda"] for p in cero)
    perd_tienda = Counter()
    for p in paginas:
        perd_tienda[p["tienda"]] += len(p["perdidos"])
    print(f"folletos: {n_folletos}  ({time.time() - t0:.0f}s)")
    print(f"PRECIO perdidos por el filtro: {sum(perd_tienda.values())}")
    print(f"paginas que el filtro deja en cero: {len(cero)}")
    print(f"{'tienda':18s} {'pag_cero':>8s} {'precios_perdidos':>16s} {'perdidos_en_pag_cero':>20s}")
    for t in sorted(perd_tienda, key=lambda t: -por_tienda[t]):
        en_cero = sum(len(p["perdidos"]) for p in cero if p["tienda"] == t)
        print(f"{t:18s} {por_tienda[t]:8d} {perd_tienda[t]:16d} {en_cero:20d}")
    Path(salida).write_text(json.dumps({
        "paginas": paginas,
        "rotulo_encima_precio_head": {t: c.most_common(40) for t, c in rotulo_head.items()},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print("guardado:", salida)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
