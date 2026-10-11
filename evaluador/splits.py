"""
Particion dev/holdout del GT, por folleto y estratificada por tienda.

Por folleto y no por pagina: las paginas de un folleto comparten diseno y errores de OCR,
asi que repartirlas filtraria el holdout. Regla (version 1):
  1. Tiendas con 3-5 folletos -> 1 a holdout; con 6 o mas -> 2.
  2. Se elige el folleto con numero de articulos mas cercano a la mediana de su tienda.
  3. Si la tienda tiene precios anteriores etiquetados, el de holdout debe tener al menos uno.
  4. Desempate determinista (sha256 de semilla + folleto). El resultado se guarda en
     splits.json (versionado en git) y NO se regenera: los folletos nuevos se agregan con
     la misma regla subiendo la version.
"""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from .gt import PaginaGT

RUTA_SPLITS = Path(__file__).parent / "splits.json"
SEMILLA = "pricescraper-eval-v1"
VERSION = 1


def _desempate(folleto: str) -> str:
    return hashlib.sha256(f"{SEMILLA}:{folleto}".encode()).hexdigest()


def generar(paginas: list[PaginaGT]) -> dict:
    stats = defaultdict(lambda: {"articulos": 0, "antes": 0})
    for pg in paginas:
        s = stats[(pg.tienda, pg.folleto)]
        s["articulos"] += len(pg.articulos)
        s["antes"] += sum(a.precio_anterior is not None for a in pg.articulos)

    por_tienda = defaultdict(list)
    for (tienda, folleto), s in stats.items():
        por_tienda[tienda].append((folleto, s))

    dev, holdout = [], []
    for tienda, folletos in sorted(por_tienda.items()):
        n_holdout = 2 if len(folletos) >= 6 else 1
        med = median(s["articulos"] for _, s in folletos)
        tiene_antes = any(s["antes"] for _, s in folletos)
        candidatos = [f for f in folletos if f[1]["antes"]] if tiene_antes else folletos
        candidatos = sorted(candidatos, key=lambda f: (abs(f[1]["articulos"] - med), _desempate(f[0])))
        elegidos = {f for f, _ in candidatos[:n_holdout]}
        for folleto, _ in sorted(folletos):
            (holdout if folleto in elegidos else dev).append(f"{tienda}/{folleto}")
    return {
        "version": VERSION, "semilla": SEMILLA,
        "regla": "por folleto, estratificado por tienda: 1 a holdout (2 si la tienda tiene 6+ folletos), "
                 "el mas cercano a la mediana de articulos, con precio anterior si la tienda los tiene",
        "dev": dev, "holdout": holdout,
    }


def cargar(ruta: Path = RUTA_SPLITS) -> dict:
    if not ruta.exists():
        raise FileNotFoundError(f"No existe {ruta}: generalo una vez con `python -m evaluador splits --generar`")
    return json.load(open(ruta, encoding="utf-8"))


def filtrar(paginas: list[PaginaGT], split: str, particion: dict) -> list[PaginaGT]:
    if split == "todo":
        return paginas
    folletos = set(particion[split])
    return [pg for pg in paginas if f"{pg.tienda}/{pg.folleto}" in folletos]
