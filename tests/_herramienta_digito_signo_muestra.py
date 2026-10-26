"""Herramienta de SOLO LECTURA (no es prueba). Experimento "digito leido como $" + escala de la pagina, 25-oct-2026.

Recorre los ocr_resultado.json de produccion con el RegexExtractor base (HEAD + "$" suelto) y junta los bloques
"[568sS]dd" con letra de precio (alto >= 2x la mediana del texto de la pagina) que la base no clasifica como precio
ni promo (los 1,797 del diagnostico #263). Para cada uno guarda las senales de escala de la pagina (ver
_herramienta_digito_signo_comun.senales). Toma una muestra estratificada por tienda (random.Random(semilla),
proporcional con minimo `minimo` por tienda) y arma mosaicos de recortes (rojo = el bloque) para revisarla a ojo.
Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_digito_signo_muestra.py <dir_processed> <dir_raw> <dir_salida> <semilla> <n> <minimo>
"""
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_digito_signo_comun import (FORMA, cargar_base, centavos_derecha, mediana_texto,  # noqa: E402
                                             senales, tipos)
from nlp.salida_json import clasificar_paginas_ocr  # noqa: E402


def candidatos_produccion(dir_processed, extractor):
    out = []
    t0 = time.time()
    n = 0
    for fuente in ("tiendeo", "ofertomat"):
        for ocr_path in sorted((Path(dir_processed) / fuente).glob("*/*/ocr_resultado.json")):
            tienda, folleto = ocr_path.parent.parent.name, ocr_path.parent.name
            try:
                ocr = json.loads(ocr_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            n += 1
            if n % 100 == 0:
                print(f"  {n} folletos, {time.time() - t0:.0f}s", flush=True)
            paginas = {}
            for p in ocr.get("paginas", []):
                med = mediana_texto(p["bloques"])
                cands = [b for b in p["bloques"] if b.get("bbox") and FORMA.match(b.get("texto", "").strip())
                         and med and b["bbox"]["alto"] >= 2 * med]
                if cands:
                    paginas[p["pagina"]] = (p, cands)
            if not paginas:
                continue
            res = {r.imagen: r for r in clasificar_paginas_ocr(ocr, extractor)}
            for pag, (p, cands) in paginas.items():
                r = res[pag]
                tp = tipos(r)
                for b in cands:
                    bb = b["bbox"]
                    t = tp.get((bb["x"], bb["y"]), "-")
                    if t in ("precios", "promos"):
                        continue
                    out.append({"fuente": fuente, "tienda": tienda, "folleto": folleto, "pagina": pag,
                                "texto": b["texto"], "bbox": bb, "tipo_base": t,
                                "centavos": centavos_derecha(b, p["bloques"]),
                                "ancho_pagina": p.get("ancho_pagina"), **senales(b, p["bloques"], r)})
    print(f"folletos: {n} ({time.time() - t0:.0f}s)")
    return out


def recorte(c, dir_raw):
    img = Image.open(Path(dir_raw) / c["fuente"] / c["tienda"] / c["folleto"] / c["pagina"]).convert("RGB")
    esc = img.width / (c["ancho_pagina"] or img.width)
    b = c["bbox"]
    x0, y0, x1, y1 = b["x"] * esc, b["y"] * esc, (b["x"] + b["ancho"]) * esc, (b["y"] + b["alto"]) * esc
    ImageDraw.Draw(img).rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=max(2, int(2 * esc)))
    h = y1 - y0
    rec = img.crop((max(0, x0 - 4 * h), max(0, y0 - 2.5 * h), min(img.width, x1 + 4 * h), min(img.height, y1 + 2.5 * h)))
    rec.thumbnail((560, 420))
    return rec


def mosaicos(muestra, dir_raw, out):
    font = ImageFont.load_default()
    for i in range(0, len(muestra), 6):
        lote = muestra[i:i + 6]
        lienzo = Image.new("RGB", (2 * 570, 3 * 450), (255, 255, 255))
        d = ImageDraw.Draw(lienzo)
        for j, c in enumerate(lote):
            x, y = (j % 2) * 570, (j // 2) * 450
            try:
                lienzo.paste(recorte(c, dir_raw), (x + 5, y + 25))
            except OSError:
                pass
            d.text((x + 5, y + 5), f"{c['id']} {c['tienda']} {c['folleto']} {c['pagina']} {c['texto']!r}", fill=(0, 0, 0), font=font)
        lienzo.save(out / f"mosaico_{i // 6 + 1:02d}.jpg", quality=85)


def main(dir_processed, dir_raw, dir_salida, semilla, n, minimo):
    base = cargar_base().RegexExtractor()
    cands = candidatos_produccion(dir_processed, base)
    print(f"candidatos: {len(cands)}")
    por = defaultdict(list)
    for c in sorted(cands, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"], c["bbox"]["x"])):
        por[c["tienda"]].append(c)
    print(Counter({t: len(v) for t, v in por.items()}).most_common())
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por):
        k = max(minimo, round(n * len(por[t]) / len(cands)))
        muestra += rng.sample(por[t], min(k, len(por[t])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"M{i:02d}"
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "candidatos.json").write_text(json.dumps(cands, ensure_ascii=False), encoding="utf-8")
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    for c in muestra:
        print(f"{c['id']} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} cent={c['centavos']} "
              f"ref={c['ref_2']}/{c['ref_3']} sim={c['sim_2']}/{c['sim_3']} tres={c['tres_esp']}/{c['tres_tot']}")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6]))
