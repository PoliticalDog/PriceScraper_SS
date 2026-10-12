"""
Consultas analiticas de SOLO LECTURA contra PostgreSQL (skill consulta-analitica).

    venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --sql "SELECT ..."
    venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --archivo consulta.sql [--max 200] [--json]
    venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --sql "SELECT ..." --contar
    venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --columnas extracciones

Tres capas de proteccion:
1. Conecta con DATABASE_URL_RO (rol pricescraper_ro, solo SELECT). Nunca cae a DATABASE_URL.
2. La sesion se abre READ ONLY y con statement_timeout.
3. Solo acepta UNA sentencia que empiece con SELECT, WITH o EXPLAIN.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
TIMEOUT_MS = 60_000
INICIO_PERMITIDO = re.compile(r"^\s*(select|with|explain)\b", re.I)
ESCRITURA = re.compile(r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|copy|vacuum"
                       r"|reindex|cluster|refresh|comment|call|do|set|reset|lock)\b", re.I)


def _sin_literales(sql: str) -> str:
    """Quita literales y comentarios para revisar solo las palabras clave."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def validar(sql: str) -> str | None:
    """Motivo de rechazo, o None si la consulta es de solo lectura."""
    limpio = _sin_literales(sql).strip().rstrip(";").strip()
    if not limpio:
        return "Consulta vacia."
    if ";" in limpio:
        return "Una sola sentencia por llamada."
    if not INICIO_PERMITIDO.match(limpio):
        return "Solo se aceptan consultas que empiecen con SELECT, WITH o EXPLAIN."
    m = ESCRITURA.search(limpio)
    if m:
        return f"Palabra clave no permitida en una consulta analitica: {m.group(1).upper()}."
    return None


def _url_ro() -> str:
    from dotenv import load_dotenv
    load_dotenv(RAIZ / ".env", encoding="utf-8")
    url = os.getenv("DATABASE_URL_RO", "").strip()
    if not url:
        raise SystemExit("Falta DATABASE_URL_RO en .env (rol de solo lectura). No se usa la conexion de escritura.")
    return url


def ejecutar(sql: str, maximo: int):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(_url_ro(), row_factory=dict_row) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {TIMEOUT_MS}")
            cur.execute(sql)
            columnas = [d.name for d in cur.description] if cur.description else []
            filas = cur.fetchmany(maximo + 1)
    return columnas, filas[:maximo], len(filas) > maximo


def _texto(v) -> str:
    return "NULL" if v is None else str(v)


def imprimir(columnas, filas, truncado: bool) -> None:
    anchos = [min(40, max([len(c)] + [len(_texto(f[c])) for f in filas])) for c in columnas]
    print(" | ".join(c.ljust(a) for c, a in zip(columnas, anchos)))
    print("-+-".join("-" * a for a in anchos))
    for f in filas:
        print(" | ".join(_texto(f[c])[:a].ljust(a) for c, a in zip(columnas, anchos)))
    print(f"\n{len(filas)} filas" + (" (truncado: usa --max para ver mas)" if truncado else ""))


def main() -> int:
    p = argparse.ArgumentParser(description="Consultas de solo lectura para BI.")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--sql")
    g.add_argument("--archivo", type=Path)
    g.add_argument("--columnas", metavar="TABLA_O_VISTA", help="columnas y tipos desde information_schema")
    p.add_argument("--max", type=int, default=200)
    p.add_argument("--contar", action="store_true", help="devuelve solo COUNT(*) de la consulta (para revisar joins)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    if a.columnas:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", a.columnas):
            print("Nombre de tabla invalido.", file=sys.stderr)
            return 2
        sql = ("SELECT column_name, data_type, is_nullable FROM information_schema.columns "
               f"WHERE table_schema = 'public' AND table_name = '{a.columnas}' ORDER BY ordinal_position")
    else:
        sql = a.sql if a.sql is not None else a.archivo.read_text(encoding="utf-8")

    motivo = validar(sql)
    if motivo:
        print(f"Rechazada: {motivo}", file=sys.stderr)
        return 2
    if a.contar:
        sql = f"SELECT COUNT(*) AS filas FROM ({sql.strip().rstrip(';')}) AS s"

    columnas, filas, truncado = ejecutar(sql, a.max)
    if a.json:
        print(json.dumps({"columnas": columnas, "filas": filas, "truncado": truncado}, default=str, ensure_ascii=False))
    else:
        imprimir(columnas, filas, truncado)
    return 0


if __name__ == "__main__":
    sys.exit(main())
