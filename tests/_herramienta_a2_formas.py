"""Herramienta de SOLO LECTURA (no es prueba: pytest no la recoge). Experimento Regla A2, 24-oct-2026.

Cuenta los bloques OCR de produccion que hoy entran por la Regla A2 (PATRON_DIGITO_ESPURIO_DECIMAL)
y los agrupa por forma: separador, digitos tras el separador y si el resto son letras.

    venv/Scripts/python.exe tests/_herramienta_a2_formas.py <dir_tiendeo> [<dir_ofertomat> ...]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

A2 = re.compile(r"^[568sS](\d{1,3}[.,]\d{2})[a-zA-Z0-9]{0,4}$")
FORMA = re.compile(r"^([568sS])(\d{1,3})([.,])(\d+)(.*)$")


def main(raices):
    por_forma = Counter()
    por_tienda = defaultdict(Counter)
    ejemplos = defaultdict(list)
    for raiz in raices:
        for ocr in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            tienda = ocr.parent.parent.name
            try:
                datos = json.loads(ocr.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for p in datos.get("paginas", []):
                for b in p.get("bloques", []):
                    t = b.get("texto", "").strip()
                    if not A2.match(t):
                        continue
                    m = FORMA.match(t)
                    resto = m.group(5)
                    clave = f"sep'{m.group(3)}' dig_tras_sep={len(m.group(4))} resto={resto or '-'}"
                    if resto:
                        clave = f"sep'{m.group(3)}' dig_tras_sep={len(m.group(4))} resto=letras"
                    por_forma[clave] += 1
                    por_tienda[tienda][clave] += 1
                    if len(ejemplos[clave]) < 15:
                        ejemplos[clave].append(f"{tienda}/{ocr.parent.name} p{p.get('pagina')} {t!r}")
    for k, n in por_forma.most_common():
        print(f"{n:6d}  {k}")
        for e in ejemplos[k]:
            print("            ", e)
    print()
    for tienda, c in sorted(por_tienda.items()):
        print(tienda, dict(c))
    # Superindice tras N,NNN en los bloques que toma la Regla A2-miles
    a2m = re.compile(r"^[568sS](\d{1,3},\d{3})(?=[a-zA-Z]*\d)([a-zA-Z0-9]{1,3})$")
    sup = Counter()
    for raiz in raices:
        for ocr in sorted(Path(raiz).glob("*/*/ocr_resultado.json")):
            datos = json.loads(ocr.read_text(encoding="utf-8"))
            for p in datos.get("paginas", []):
                for b in p.get("bloques", []):
                    m = a2m.match(b.get("texto", "").strip())
                    if m:
                        sup[(ocr.parent.parent.name, m.group(2))] += 1
    print("\nsuperindice A2-miles (tienda, resto): n")
    for k, n in sup.most_common():
        print("  ", k, n)


if __name__ == "__main__":
    main(sys.argv[1:])
