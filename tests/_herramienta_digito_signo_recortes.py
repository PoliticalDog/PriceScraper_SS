"""Herramienta de SOLO LECTURA (no es prueba). Experimento "digito leido como $" + escala, 25-oct-2026.

Mosaicos de recortes (rojo = el bloque) para casos dados como tienda/folleto/pagina/texto (el primer bloque de la
pagina con ese texto). Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_digito_signo_recortes.py <dir_processed_tiendeo> <dir_raw> <dir_salida> <caso> [<caso> ...]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_digito_signo_muestra import mosaicos  # noqa: E402


def main(dir_tiendeo, dir_raw, dir_salida, casos):
    out = []
    for i, caso in enumerate(casos, 1):
        tienda, folleto, pagina, texto = caso.split("/")
        ocr = json.loads((Path(dir_tiendeo) / tienda / folleto / "ocr_resultado.json").read_text(encoding="utf-8"))
        pg = next(q for q in ocr["paginas"] if q["pagina"] == pagina)
        b = next(x for x in pg["bloques"] if x["texto"].strip() == texto)
        out.append({"id": f"C{i:02d}", "fuente": "tiendeo", "tienda": tienda, "folleto": folleto, "pagina": pagina,
                    "texto": texto, "bbox": b["bbox"], "ancho_pagina": pg.get("ancho_pagina")})
    destino = Path(dir_salida)
    destino.mkdir(parents=True, exist_ok=True)
    mosaicos(out, dir_raw, destino)
    for c in out:
        print(c["id"], c["tienda"], c["folleto"], c["pagina"], c["texto"], c["bbox"])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
