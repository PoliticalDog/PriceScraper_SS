"""Solo lectura: efecto en produccion de _NO_SON_PRODUCTO (catalogo) y de la marca como palabra completa
(normalizador), comparando con la logica anterior sobre los PRODUCTO de los nlp_resultado.json de produccion."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nlp import catalogo_productos as cp  # noqa: E402
from nlp.normalizador import MARCAS_CONOCIDAS, Normalizador  # noqa: E402


def categoria_antes(texto):
    t = texto.lower()
    for _, clave, nombre, pat in cp._PATRONES:
        if pat.search(t):
            return nombre
    for _, _, nombre, pat in cp._PATRONES_MARCA:
        if pat.search(t):
            return nombre
    return ""


def marca_antes(texto):
    t = texto.lower()
    return next((m.title() for m in sorted(MARCAS_CONOCIDAS, key=len, reverse=True) if m in t), None)


n = Normalizador()
cat, mar, total = Counter(), Counter(), 0
for fuente in ("tiendeo", "ofertomat"):
    for ruta in Path("data/processed", fuente).glob("*/*/nlp_resultado.json"):
        for pag in json.loads(ruta.read_text(encoding="utf-8"))["paginas"]:
            for prod in pag["productos"]:
                total += 1
                t = prod["texto"]
                a, d = categoria_antes(t), cp.buscar_categoria(t)[1]
                if a != d:
                    cat[(t[:45], a, d)] += 1
                ma, md = marca_antes(t), n._extraer_marca(t)
                if ma != md:
                    mar[(ma, md)] += 1
print(f"{total} PRODUCTO; categoria cambia en {sum(cat.values())}, marca cambia en {sum(mar.values())}")
for (t, a, d), k in cat.most_common(25):
    print(f"  cat {k:3d}  {t!r:48s} {a or '-'} -> {d or '-'}")
for (a, d), k in mar.most_common(15):
    print(f"  marca {k:4d}  {a} -> {d}")
