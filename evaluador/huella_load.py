"""
Huella de load: lo que Loader._procesar_pagina escribiria en PostgreSQL, sin tocar la BD.

Corre el codigo real de load con un cursor falso que registra cada INSERT/UPDATE con
sus parametros. Sirve para comprobar que un refactor de load.py no cambia nada:
se guarda la huella antes, se guarda despues y se comparan.

    python -m evaluador.huella_load guardar data/processed/_eval/huella_antes.jsonl.gz
    python -m evaluador.huella_load comparar huella_antes.jsonl.gz huella_despues.jsonl.gz
"""
import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from load.load import Loader, rutas_nlp

logger = logging.getLogger(__name__)


class CursorFalso:
    """Imita lo que load espera de un cursor psycopg (fetchone con dict) y registra las escrituras."""

    def __init__(self):
        self.ops: list[list] = []
        self._fila = None
        self._siguiente_id = 1
        self._canonicos: dict[str, int] = {}
        self._eventos: set[tuple] = set()

    def _nuevo_id(self) -> int:
        self._siguiente_id += 1
        return self._siguiente_id

    def execute(self, sql: str, params=None):
        sql_norm = re.sub(r"\s+", " ", sql).strip()
        params = [self._normalizar(p) for p in (params or ())]
        self.ops.append([sql_norm.split(" (")[0][:60], params])

        self._fila = None
        if "RETURNING id" not in sql_norm:
            return
        if sql_norm.startswith("INSERT INTO productos_canonicos"):
            nombre = params[0]
            self._canonicos.setdefault(nombre, self._nuevo_id())
            self._fila = {"id": self._canonicos[nombre]}
        elif sql_norm.startswith("INSERT INTO eventos_promo"):
            llave = (params[0], params[2])  # (folleto_id, nombre_evento): ON CONFLICT DO NOTHING
            if llave not in self._eventos:
                self._eventos.add(llave)
                self._fila = {"id": self._nuevo_id()}
        else:
            self._fila = {"id": self._nuevo_id()}

    def fetchone(self):
        return self._fila

    @staticmethod
    def _normalizar(p):
        # procesado_at = datetime.utcnow(): lo unico no determinista de una pagina
        if isinstance(p, (datetime, date)):
            return "<fecha>"
        return p


def guardar(salida: Path, limite: int | None = None) -> None:
    loader = Loader.desde_conexion(None)
    rutas = rutas_nlp()[:limite] if limite else rutas_nlp()
    salida.parent.mkdir(parents=True, exist_ok=True)
    n_paginas = n_ops = 0
    with gzip.open(salida, "wt", encoding="utf-8") as f:
        for i, ruta in enumerate(rutas, 1):
            nlp = json.load(open(ruta, encoding="utf-8"))
            fuente, slug_raw, folleto_id = ruta.parts[-4], ruta.parts[-3], ruta.parts[-2]
            ocr_por_pagina = {p.get("pagina"): p for p in loader._leer_ocr(ruta).get("paginas", [])}
            for pag in nlp.get("paginas", []):
                cur = CursorFalso()
                regiones = loader._detectar_regiones_pagina(fuente, slug_raw, folleto_id, pag)
                contadores = loader._procesar_pagina(cur, 1, 1, pag, regiones, ocr_por_pagina.get(pag.get("pagina")))
                f.write(json.dumps({
                    "folleto": f"{fuente}/{slug_raw}/{folleto_id}", "pagina": pag.get("pagina"),
                    "contadores": contadores, "ops": cur.ops,
                }, ensure_ascii=False, default=str) + "\n")
                n_paginas += 1
                n_ops += len(cur.ops)
            if i % 50 == 0:
                print(f"  {i}/{len(rutas)} folletos", flush=True)
    print(f"Huella guardada: {salida} | {len(rutas)} folletos, {n_paginas} paginas, {n_ops} escrituras")


def _leer(ruta: Path) -> dict:
    with gzip.open(ruta, "rt", encoding="utf-8") as f:
        return {(d["folleto"], d["pagina"]): d for d in map(json.loads, f)}


def comparar(a: Path, b: Path) -> int:
    ha, hb = _leer(a), _leer(b)
    solo_a, solo_b = ha.keys() - hb.keys(), hb.keys() - ha.keys()
    distintas = [k for k in ha.keys() & hb.keys() if ha[k] != hb[k]]
    huella = lambda h: hashlib.sha256(json.dumps([h[k] for k in sorted(h)], sort_keys=True).encode()).hexdigest()[:16]
    print(f"A: {len(ha)} paginas (sha {huella(ha)}) | B: {len(hb)} paginas (sha {huella(hb)})")
    print(f"Solo en A: {len(solo_a)} | solo en B: {len(solo_b)} | paginas con escrituras distintas: {len(distintas)}")
    for k in sorted(distintas)[:10]:
        oa, ob = ha[k]["ops"], hb[k]["ops"]
        primera = next((i for i, (x, y) in enumerate(zip(oa, ob)) if x != y), min(len(oa), len(ob)))
        print(f"  {k}: primera diferencia en escritura #{primera}")
        print(f"     A: {oa[primera] if primera < len(oa) else '(fin)'}")
        print(f"     B: {ob[primera] if primera < len(ob) else '(fin)'}")
    iguales = not (solo_a or solo_b or distintas)
    print("EQUIVALENTES" if iguales else "DIFERENTES")
    return 0 if iguales else 1


def main() -> int:
    # Normalizador._extraer_marca desempata marcas del mismo largo segun el orden de un set
    # ("Gamesa y Quaker" -> Gamesa o Quaker): sin semilla fija la huella cambia entre corridas
    if os.environ.get("PYTHONHASHSEED") != "0":
        return subprocess.call([sys.executable, "-m", "evaluador.huella_load", *sys.argv[1:]],
                               env={**os.environ, "PYTHONHASHSEED": "0"})
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("guardar")
    g.add_argument("salida", type=Path)
    g.add_argument("--limite", type=int, help="solo los primeros N folletos (prueba rapida)")
    c = sub.add_parser("comparar")
    c.add_argument("a", type=Path)
    c.add_argument("b", type=Path)
    args = p.parse_args()
    if args.cmd == "guardar":
        guardar(args.salida, args.limite)
        return 0
    return comparar(args.a, args.b)


if __name__ == "__main__":
    sys.exit(main())
