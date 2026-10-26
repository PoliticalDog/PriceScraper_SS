"""Solo lectura: productos de produccion cuya categoria sale UNICAMENTE por la tolerancia de "una letra basura al
inicio del token" de catalogo_productos (p. ej. "IQUESO" -> queso, pero tambien "Apollo" -> pollo).
Uso: python tests/_herramienta_doc_letra_inicial.py [N_ejemplos]"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nlp import catalogo_productos as cp  # noqa: E402

L = cp._LETRA
casos = Counter()
for fuente in ("tiendeo", "ofertomat"):
    for ruta in Path("data/processed", fuente).glob("*/*/nlp_resultado.json"):
        for pag in json.loads(ruta.read_text(encoding="utf-8"))["paginas"]:
            for prod in pag["productos"]:
                t = prod["texto"].lower()
                for _, _, nombre, pat in cp._PATRONES:
                    m = pat.search(t)
                    if m:
                        ini = m.start()
                        # coincidio por la rama (?<=^[letra]) o (?<=[^letra][letra]): una letra pegada antes
                        if ini >= 1 and re.match(rf"[{L}]", t[ini - 1]) and not t[max(0, ini - 2):ini].endswith("de"):
                            token = re.findall(rf"[{L}]+", t[max(0, ini - 1):])[0]
                            casos[(token, nombre)] += 1
                        break
total = sum(casos.values())
print(f"{total} productos categorizados solo por la letra inicial tolerada; {len(casos)} tokens distintos")
for (token, nombre), n in casos.most_common(int(sys.argv[1]) if len(sys.argv) > 1 else 40):
    print(f"{n:5d}  {token:20s} -> {nombre}")
