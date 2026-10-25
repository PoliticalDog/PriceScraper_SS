"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento Regla A2, 24-oct-2026.

Lista los ejemplos de error de una corrida del evaluador cuyo texto de precio tiene la forma del bug de A2
(digito espurio + coma + 3 o mas digitos, o coma de miles con sufijo que mezcla letra y digito).

    venv/Scripts/python.exe tests/_herramienta_a2_dev.py <corrida.json>
"""
import json
import re
import sys

PAT = re.compile(r"^[568sS]\d{1,3}[.,]\d{3,}|^[568sS]\d{1,3},\d{3}[a-zA-Z]*\d")


def bloques_dev(d, raiz_tiendeo):
    """Bloques OCR de los folletos que aparecen en el detalle de la corrida (solo dev)."""
    from pathlib import Path
    folletos = set()
    for seccion in d["detalle"].values():
        for clave in (seccion if isinstance(seccion, dict) else {}):
            partes = clave.split("|")[0].split("/")
            if len(partes) >= 2:
                folletos.add((partes[0], partes[1]))
    print("folletos dev:", len(folletos))
    for tienda, folleto in sorted(folletos):
        ocr = Path(raiz_tiendeo) / tienda / folleto / "ocr_resultado.json"
        if not ocr.exists():
            continue
        datos = json.loads(ocr.read_text(encoding="utf-8"))
        for p in datos.get("paginas", []):
            for b in p.get("bloques", []):
                t = b.get("texto", "").strip()
                if PAT.match(t):
                    print("  OCR dev", tienda, folleto, p.get("pagina"), repr(t), b.get("bbox"))


def main(ruta, raiz_tiendeo=None):
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    if raiz_tiendeo:
        bloques_dev(d, raiz_tiendeo)
    for cod, por_tienda in d["ejemplos_error"].items():
        for tienda, casos in por_tienda.items():
            for c in casos:
                r = c.get("registro") or {}
                e = c.get("esperado") or {}
                if PAT.match(str(r.get("precio_texto", ""))):
                    print(cod, tienda, r.get("pagina"), repr(r.get("precio_texto")), r.get("precio"),
                          "esperado", e.get("precio"), e.get("producto"))


if __name__ == "__main__":
    main(*sys.argv[1:3])
