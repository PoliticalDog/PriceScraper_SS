"""Herramienta de SOLO LECTURA (no es prueba). Guarda de centavos pegados (condicion de QA, Engram #275), 25-oct-2026.

Para cada caso tienda/folleto/pagina/texto imprime el bloque del precio y los bloques a menos de <radio> px de su
centro (texto + bbox), para escribir las pruebas con cajas reales.

    venv/Scripts/python.exe tests/_herramienta_centavos_pegados_casillas.py <dir_processed> <radio> <tienda/folleto/pagina/texto> ...
"""
import json
import math
import sys
from pathlib import Path


def main(dir_processed, radio, casos):
    for caso in casos:
        tienda, folleto, pagina, texto = caso.split("/", 3)
        ruta = next((Path(dir_processed) / f / tienda / folleto / "ocr_resultado.json" for f in ("tiendeo", "ofertomat")
                     if (Path(dir_processed) / f / tienda / folleto / "ocr_resultado.json").exists()), None)
        if ruta is None:
            print("== no existe", caso)
            continue
        ocr = json.loads(ruta.read_text(encoding="utf-8"))
        pg = next(p for p in ocr["paginas"] if p["pagina"].startswith(pagina))
        precios = [b for b in pg["bloques"] if b.get("texto", "").strip() == texto]
        print(f"== {caso} ancho={pg.get('ancho_pagina')} coincidencias={len(precios)}")
        for pb in precios:
            bb = pb["bbox"]
            cx, cy = bb["x"] + bb["ancho"] / 2, bb["y"] + bb["alto"] / 2
            print(f"  PRECIO {pb['texto']!r} {bb}")
            for b in pg["bloques"]:
                ob = b.get("bbox")
                if not ob or b is pb:
                    continue
                d = math.hypot(ob["x"] + ob["ancho"] / 2 - cx, ob["y"] + ob["alto"] / 2 - cy)
                if d <= radio:
                    print(f"    {d:5.0f} {b['texto']!r} {ob}")


if __name__ == "__main__":
    main(sys.argv[1], float(sys.argv[2]), sys.argv[3:])
