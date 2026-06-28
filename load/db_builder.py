"""
load/db_builder.py
PriceScraper MX - Gestor de conexion PostgreSQL (psycopg v3)

Responsabilidades:
    1. Leer DATABASE_URL desde .env
    2. Conectar a PostgreSQL con psycopg (v3)
    3. Verificar si el schema ya existe
    4. Si no existe -> ejecutar schema.sql
    5. Exponer get_connection() y get_cursor()
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_ENV_PATH    = Path(__file__).parent.parent / ".env"
_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_TABLAS_REQUERIDAS = {
    "tiendas", "folletos", "paginas",
    "extracciones", "eventos_promo", "alertas",
}


# -- Configuracion ------------------------------------------------------------

def _cargar_url() -> str:
    load_dotenv(_ENV_PATH, encoding="utf-8")
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise ValueError(
            "DATABASE_URL no encontrada.\n"
            "Crea un archivo .env con:\n"
            "  DATABASE_URL=postgresql://pricescraper_user:123@localhost:5432/pricescraper"
        )
    return url


# -- Conexion -----------------------------------------------------------------

def get_connection() -> psycopg.Connection:
    """
    Retorna una conexion psycopg v3 a PostgreSQL.
    En el primer uso inicializa el schema si no existe.
    Rows retornadas como dicts.
    """
    url = _cargar_url()
    try:
        conn = psycopg.connect(url, row_factory=dict_row)
        logger.info("[DB] Conexion PostgreSQL establecida")
    except psycopg.OperationalError as e:
        logger.error(f"[DB] No se pudo conectar a PostgreSQL: {e}")
        raise

    _inicializar_schema(conn)
    return conn


@contextmanager
def get_cursor(conn: psycopg.Connection):
    """
    Context manager con commit/rollback automatico.

    Uso:
        with get_cursor(conn) as cur:
            cur.execute("INSERT INTO tiendas ...")
    """
    with conn.cursor(row_factory=dict_row) as cur:
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise


# -- Schema -------------------------------------------------------------------

def _inicializar_schema(conn: psycopg.Connection) -> None:
    tablas = _tablas_existentes(conn)

    if _TABLAS_REQUERIDAS.issubset(tablas):
        logger.info(f"[DB] Schema OK - {len(tablas)} tablas encontradas")
        return

    faltantes = _TABLAS_REQUERIDAS - tablas
    logger.info(f"[DB] Tablas faltantes: {faltantes}")
    logger.info(f"[DB] Inicializando schema desde {_SCHEMA_PATH.name}...")

    if not _SCHEMA_PATH.exists():
        raise FileNotFoundError(
            f"[DB] No se encontro {_SCHEMA_PATH}\n"
            "Asegurate de que schema.sql este en la carpeta load/"
        )

    sql = _SCHEMA_PATH.read_text(encoding="utf-8")

    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        logger.info("[DB] Schema inicializado correctamente")
        _log_tablas(conn)
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] Error ejecutando schema.sql: {e}")
        raise


def _tablas_existentes(conn: psycopg.Connection) -> set:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type   = 'BASE TABLE'
        """)
        return {row["table_name"] for row in cur.fetchall()}


# -- Utilidades ---------------------------------------------------------------

def verificar_conexion() -> bool:
    """Health-check: verifica que la conexion funciona."""
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        conn.close()
        logger.info("[DB] Health-check OK")
        return True
    except Exception as e:
        logger.error(f"[DB] Health-check fallo: {e}")
        return False


def resumen_bd() -> dict:
    """Conteo de registros por tabla."""
    tablas = ["tiendas", "folletos", "paginas", "extracciones", "eventos_promo", "alertas"]
    resultado = {}
    try:
        conn = get_connection()
        with conn.cursor(row_factory=dict_row) as cur:
            for tabla in tablas:
                cur.execute(f"SELECT COUNT(*) AS n FROM {tabla}")
                resultado[tabla] = cur.fetchone()["n"]
        conn.close()
    except Exception as e:
        logger.error(f"[DB] Error en resumen_bd: {e}")
    return resultado


def _log_tablas(conn: psycopg.Connection) -> None:
    tablas = _tablas_existentes(conn)
    for tabla in sorted(_TABLAS_REQUERIDAS):
        estado = "OK" if tabla in tablas else "FALTA"
        logger.info(f"[DB]   {estado}: {tabla}")