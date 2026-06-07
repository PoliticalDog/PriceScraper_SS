"""
probar_sqlite.py
Módulo de prueba — Creación y carga de SQLite desde nlp_resultado.json reales.
PriceScraper MX

Lee los nlp_resultado.json de data/processed/ y los carga en data/pricescraper.db
usando los mismos modelos y lógica que el Transformer principal.

Uso: python probar_sqlite.py

Menú:
  1 → Crear BD y tablas
  2 → Cargar TODOS los nlp_resultado.json de data/processed/
  3 → Cargar carpeta específica de data/processed/
  4 → Vista rápida (verificar datos cargados)
  5 → Limpiar todos los datos (conserva esquema)
  0 → Salir
"""

import sys
import re
import json
import logging
import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# ── Logging ───────────────────────────────────────────────────────────────────
Path("data").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("sqlite_test")

# ── Dependencias ──────────────────────────────────────────────────────────────
try:
    import pandas as pd
    from sqlalchemy import (
        create_engine, text,
        Column, Integer, String, Float, Date, DateTime,
        ForeignKey, UniqueConstraint,
    )
    from sqlalchemy.orm import declarative_base, Session, relationship
except ImportError as e:
    logger.error(f"Dependencia faltante: {e}")
    logger.error("Instala con: pip install sqlalchemy pandas")
    sys.exit(1)

# ── Config ─────────────────────────────────────────────────────────────────────
DB_PATH        = Path("data/pricescraper.db")
DB_URL         = f"sqlite:///{DB_PATH}"
DATA_PROCESSED = Path("data/processed")

Base = declarative_base()


# ══════════════════════════════════════════════════════════════════════════════
# Modelos (espejo exacto de etl/transformer.py)
# ══════════════════════════════════════════════════════════════════════════════

class Tienda(Base):
    __tablename__ = "tiendas"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    slug   = Column(String(100), nullable=False)
    fuente = Column(String(50),  nullable=False)
    __table_args__ = (
        UniqueConstraint("slug", "fuente", name="uq_tienda_slug_fuente"),
    )
    folletos = relationship("Folleto", back_populates="tienda")


class Folleto(Base):
    __tablename__ = "folletos"
    id                = Column(Integer, primary_key=True, autoincrement=True)
    tienda_id         = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    folleto_id_fuente = Column(String(50),  nullable=False)
    titulo            = Column(String(255))
    fecha_inicio      = Column(Date)
    fecha_fin         = Column(Date)
    url_folleto       = Column(String(500))
    fecha_scraping    = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (
        UniqueConstraint("folleto_id_fuente", "tienda_id",
                         name="uq_folleto_fuente_tienda"),
    )
    tienda  = relationship("Tienda",  back_populates="folletos")
    paginas = relationship("Pagina",  back_populates="folleto")
    precios = relationship("Precio",  back_populates="folleto")


class Pagina(Base):
    __tablename__ = "paginas"
    id             = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id     = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    numero_pagina  = Column(Integer, nullable=False)
    nombre_archivo = Column(String(100))
    ruta_imagen    = Column(String(500))
    __table_args__ = (
        UniqueConstraint("folleto_id", "numero_pagina", name="uq_pagina_folleto"),
    )
    folleto = relationship("Folleto", back_populates="paginas")
    precios = relationship("Precio",  back_populates="pagina")


class Precio(Base):
    __tablename__ = "precios"
    id               = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id       = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    pagina_id        = Column(Integer, ForeignKey("paginas.id"), nullable=True)
    texto_producto   = Column(String(300))
    precio_actual    = Column(Float, nullable=False)
    precio_anterior  = Column(Float, nullable=True)
    texto_ocr_precio = Column(String(100))
    confianza_ocr    = Column(Float)
    bbox_x           = Column(Integer)
    bbox_y           = Column(Integer)
    bbox_ancho       = Column(Integer)
    bbox_alto        = Column(Integer)
    fecha_registro   = Column(DateTime, default=datetime.utcnow)
    folleto = relationship("Folleto", back_populates="precios")
    pagina  = relationship("Pagina",  back_populates="precios")


# ══════════════════════════════════════════════════════════════════════════════
# Motor de carga
# ══════════════════════════════════════════════════════════════════════════════

class CargadorSQLite:
    """Lee nlp_resultado.json y los carga en SQLite."""

    def __init__(self):
        self.engine = None

    # ── Conexión / DDL ────────────────────────────────────────────────────────

    def crear_bd(self) -> bool:
        """Crea el engine y todas las tablas."""
        try:
            self.engine = create_engine(DB_URL, echo=False)
            Base.metadata.create_all(self.engine)
            logger.info(f"[BD] ✅ BD lista en: {DB_PATH}")
            for t in ["tiendas", "folletos", "paginas", "precios"]:
                logger.info(f"       → tabla '{t}' verificada")
            return True
        except Exception as e:
            logger.error(f"[BD] Error creando BD: {e}")
            return False

    def _check(self) -> bool:
        if not self.engine:
            logger.error("[BD] ⚠️  BD no inicializada. Usa opción 1 primero.")
            return False
        return True

    # ── Descubrimiento de archivos ────────────────────────────────────────────

    def listar_nlp(self, raiz: Path = DATA_PROCESSED) -> list[Path]:
        """Retorna todos los nlp_resultado.json bajo la carpeta dada."""
        return sorted(raiz.rglob("nlp_resultado.json"))

    def listar_subcarpetas(self) -> list[Path]:
        """Retorna las subcarpetas de primer nivel en data/processed/."""
        if not DATA_PROCESSED.exists():
            return []
        return sorted([p for p in DATA_PROCESSED.iterdir() if p.is_dir()])

    # ── ETL ───────────────────────────────────────────────────────────────────

    def cargar_archivo(self, ruta_nlp: Path) -> dict:
        """
        Carga un nlp_resultado.json completo.
        Retorna dict con resumen de lo insertado.
        """
        with open(ruta_nlp, encoding="utf-8") as f:
            data = json.load(f)

        fuente     = data.get("fuente", "")
        slug       = data.get("tienda", "")
        folleto_id = data.get("folleto_id", "")

        with Session(self.engine) as session:
            tienda  = self._upsert_tienda(session, slug, fuente)
            folleto = self._upsert_folleto(session, tienda, folleto_id)

            total_precios  = 0
            total_sin_prod = 0

            for pag_data in data.get("paginas", []):
                nombre_archivo = pag_data.get("pagina", "")
                num_pagina     = self._num_pagina(nombre_archivo)
                pagina         = self._upsert_pagina(session, folleto, num_pagina,
                                                     nombre_archivo, ruta_nlp)

                precios_lista  = pag_data.get("precios", [])
                productos_lista = pag_data.get("productos", [])
                precios_ant    = pag_data.get("precios_anteriores", [])

                for precio in precios_lista:
                    valor = precio.get("valor", 0.0)
                    if not valor or valor <= 0:
                        continue

                    texto_prod  = self._asociar_producto(precio, productos_lista)
                    precio_ant  = self._precio_anterior(precio, precios_ant)
                    bbox        = precio.get("bbox", {})
                    texto_norm  = self._normalizar(texto_prod)

                    session.add(Precio(
                        folleto_id       = folleto.id,
                        pagina_id        = pagina.id,
                        texto_producto   = texto_norm,
                        precio_actual    = valor,
                        precio_anterior  = precio_ant,
                        texto_ocr_precio = precio.get("texto", ""),
                        confianza_ocr    = precio.get("confianza", 0.0),
                        bbox_x           = bbox.get("x", 0),
                        bbox_y           = bbox.get("y", 0),
                        bbox_ancho       = bbox.get("ancho", 0),
                        bbox_alto        = bbox.get("alto", 0),
                    ))
                    total_precios += 1
                    if not texto_norm:
                        total_sin_prod += 1

            session.commit()

        return {
            "fuente":           fuente,
            "tienda":           slug,
            "folleto_id":       folleto_id,
            "precios_cargados": total_precios,
            "sin_producto":     total_sin_prod,
        }

    def cargar_lote(self, archivos: list[Path]) -> dict:
        """Carga una lista de archivos nlp y retorna resumen global."""
        ok = err = total_p = 0
        for i, archivo in enumerate(archivos, 1):
            ruta_rel = archivo.relative_to(DATA_PROCESSED) \
                       if DATA_PROCESSED in archivo.parents else archivo
            logger.info(f"[{i}/{len(archivos)}] {ruta_rel}")
            try:
                r = self.cargar_archivo(archivo)
                ok      += 1
                total_p += r["precios_cargados"]
                logger.info(f"  ✅ {r['precios_cargados']} precios  "
                             f"({r['sin_producto']} sin producto)")
            except Exception as e:
                logger.error(f"  ❌ Error: {e}")
                err += 1

        return {"cargados": ok, "errores": err, "total_precios": total_p}

    # ── Upserts ───────────────────────────────────────────────────────────────

    def _upsert_tienda(self, session, slug, fuente) -> Tienda:
        t = session.query(Tienda).filter_by(slug=slug, fuente=fuente).first()
        if not t:
            t = Tienda(nombre=slug.replace("_", " ").title(),
                       slug=slug, fuente=fuente)
            session.add(t)
            session.flush()
            logger.info(f"  Nueva tienda: {t.nombre} ({fuente})")
        return t

    def _upsert_folleto(self, session, tienda, folleto_id) -> Folleto:
        f = session.query(Folleto).filter_by(
            tienda_id=tienda.id, folleto_id_fuente=folleto_id
        ).first()
        if not f:
            f = Folleto(tienda_id=tienda.id, folleto_id_fuente=folleto_id)
            session.add(f)
            session.flush()
            logger.info(f"  Nuevo folleto: {folleto_id}")
        return f

    def _upsert_pagina(self, session, folleto, num, nombre, ruta_nlp) -> Pagina:
        p = session.query(Pagina).filter_by(
            folleto_id=folleto.id, numero_pagina=num
        ).first()
        if not p:
            ruta_img = str(ruta_nlp.parent / nombre)
            p = Pagina(folleto_id=folleto.id, numero_pagina=num,
                       nombre_archivo=nombre, ruta_imagen=ruta_img)
            session.add(p)
            session.flush()
        return p

    # ── Lógica producto / precio anterior ─────────────────────────────────────

    def _asociar_producto(self, precio: dict, productos: list) -> str:
        if not productos:
            return ""
        px, py = precio.get("bbox", {}).get("x", 0), precio.get("bbox", {}).get("y", 0)
        mejor, menor_dist = "", float("inf")
        for prod in productos:
            b = prod.get("bbox", {})
            if abs(b.get("x", 0) - px) > 400:
                continue
            dy = py - b.get("y", 0)
            if 0 < dy < menor_dist:
                menor_dist = dy
                mejor = prod.get("texto", "")
        return mejor

    def _precio_anterior(self, precio: dict, precios_ant: list) -> Optional[float]:
        if not precios_ant:
            return None
        px, py = precio.get("bbox", {}).get("x", 0), precio.get("bbox", {}).get("y", 0)
        mejor_val, menor_dist = None, float("inf")
        for pa in precios_ant:
            b  = pa.get("bbox", {})
            dx = b.get("x", 0) - px
            dy = b.get("y", 0) - py
            d  = (dx**2 + dy**2) ** 0.5
            if d < menor_dist and d < 300:
                menor_dist = d
                mejor_val  = pa.get("valor")
        return mejor_val

    # ── Utilidades ────────────────────────────────────────────────────────────

    @staticmethod
    def _normalizar(texto: str) -> str:
        if not texto:
            return ""
        texto = re.sub(r"[%@€£¥°©®™]", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto[:1].upper() + texto[1:] if texto else ""

    @staticmethod
    def _num_pagina(nombre: str) -> int:
        m = re.search(r"(\d+)", nombre)
        return int(m.group(1)) if m else 0

    # ── Resumen BD ────────────────────────────────────────────────────────────

    def resumen(self) -> dict:
        if not self._check():
            return {}
        with Session(self.engine) as s:
            return {
                "tiendas":  s.query(Tienda).count(),
                "folletos": s.query(Folleto).count(),
                "paginas":  s.query(Pagina).count(),
                "precios":  s.query(Precio).count(),
            }

    # ── Limpiar datos ─────────────────────────────────────────────────────────

    def limpiar(self):
        if not self._check():
            return
        with Session(self.engine) as s:
            s.query(Precio).delete()
            s.query(Pagina).delete()
            s.query(Folleto).delete()
            s.query(Tienda).delete()
            s.commit()
        logger.info("[BD] 🧹 Todos los datos eliminados (esquema conservado).")


# ══════════════════════════════════════════════════════════════════════════════
# Vista rápida (verificación de datos)
# ══════════════════════════════════════════════════════════════════════════════

def vista_rapida():
    """Muestra los datos almacenados en SQLite — mismo query que el snippet de prueba."""
    if not DB_PATH.exists():
        print(f"\n  ⚠️  No existe la BD en {DB_PATH}")
        print("       Usa opción 1 para crearla y opción 2/3 para cargar datos.")
        return

    con = sqlite3.connect(DB_PATH)

    # ── Tablas ────────────────────────────────────────────────────────────────
    tablas = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)
    sep = "─" * 65
    print(f"\n{sep}")
    print("  Tablas en la BD:")
    print(f"{sep}")
    print(tablas.to_string(index=False))

    # ── Resumen por tabla ─────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("  Conteo de registros:")
    print(f"{sep}")
    for tabla in ["tiendas", "folletos", "paginas", "precios"]:
        try:
            n = pd.read_sql(f"SELECT COUNT(*) AS total FROM {tabla}", con).iloc[0, 0]
            print(f"  {tabla:<12}: {n:>6} registros")
        except Exception:
            print(f"  {tabla:<12}: (tabla no encontrada)")

    # ── Vista de precios (mismo query del snippet de prueba) ──────────────────
    print(f"\n{sep}")
    print("  Precios cargados (últimos 20):")
    print(f"{sep}")
    try:
        df = pd.read_sql("""
            SELECT t.nombre        AS tienda,
                   f.folleto_id_fuente,
                   p.numero_pagina AS pagina,
                   pr.texto_producto,
                   pr.precio_actual,
                   pr.precio_anterior,
                   pr.texto_ocr_precio,
                   pr.confianza_ocr
            FROM precios pr
            JOIN folletos f ON pr.folleto_id = f.id
            JOIN tiendas  t ON f.tienda_id   = t.id
            JOIN paginas  p ON pr.pagina_id  = p.id
            ORDER BY pr.id
            LIMIT 20
        """, con)

        if df.empty:
            print("  (sin precios cargados aún)")
        else:
            pd.set_option("display.max_columns", None)
            pd.set_option("display.width", 120)
            pd.set_option("display.max_colwidth", 30)
            pd.set_option("display.float_format", lambda x: f"{x:.2f}")
            print(df.to_string(index=False))
            total = pd.read_sql("SELECT COUNT(*) AS total FROM precios", con).iloc[0, 0]
            if total > 20:
                print(f"\n  ... ({total - 20} precios más en la BD)")

    except Exception as e:
        print(f"  Error en la consulta: {e}")

    # ── Resumen por tienda ────────────────────────────────────────────────────
    print(f"\n{sep}")
    print("  Precios por tienda:")
    print(f"{sep}")
    try:
        df_t = pd.read_sql("""
            SELECT t.nombre,
                   COUNT(pr.id)                       AS total_precios,
                   ROUND(AVG(pr.precio_actual), 2)    AS precio_prom,
                   MIN(pr.precio_actual)               AS precio_min,
                   MAX(pr.precio_actual)               AS precio_max
            FROM precios pr
            JOIN folletos f ON pr.folleto_id = f.id
            JOIN tiendas  t ON f.tienda_id   = t.id
            GROUP BY t.nombre
            ORDER BY total_precios DESC
        """, con)
        if df_t.empty:
            print("  (sin datos)")
        else:
            print(df_t.to_string(index=False))
    except Exception as e:
        print(f"  Error: {e}")

    print(f"{sep}\n")
    con.close()


# ══════════════════════════════════════════════════════════════════════════════
# Menús
# ══════════════════════════════════════════════════════════════════════════════

def menu_principal() -> int:
    existe = "✅" if DB_PATH.exists() else "❌ no existe"
    print("\n" + "═" * 65)
    print("   PriceScraper MX — Carga SQLite")
    print(f"   BD: {DB_PATH}  [{existe}]")
    print("═" * 65)
    print("   1 → Crear BD y tablas")
    print("   2 → Cargar TODOS  los nlp_resultado.json")
    print("   3 → Cargar carpeta específica de data/processed/")
    print("   4 → Vista rápida  (verificar datos cargados)")
    print("   5 → Limpiar todos los datos (conserva esquema)")
    print("   0 → Salir")
    print("─" * 65)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_carpeta_especifica(cargador: CargadorSQLite):
    """Lista subcarpetas de data/processed/ para elegir cuál cargar."""
    subcarpetas = cargador.listar_subcarpetas()

    if not subcarpetas:
        logger.error(f"No se encontraron carpetas en {DATA_PROCESSED}")
        return

    print(f"\n{'─'*65}")
    print("   Carpetas disponibles en data/processed/:")
    print(f"{'─'*65}")

    for i, carpeta in enumerate(subcarpetas, 1):
        archivos = list(carpeta.rglob("nlp_resultado.json"))
        print(f"   {i:>3}. {carpeta.name:<35}  ({len(archivos)} archivos nlp)")

    print(f"{'─'*65}")

    try:
        idx = int(input("\n   Número de carpeta: ").strip())
        if not (1 <= idx <= len(subcarpetas)):
            print("  ⚠️  Número fuera de rango.")
            return
    except ValueError:
        print("  ⚠️  Entrada inválida.")
        return

    carpeta_elegida = subcarpetas[idx - 1]
    archivos = cargador.listar_nlp(carpeta_elegida)

    if not archivos:
        logger.warning(f"No hay nlp_resultado.json en {carpeta_elegida}")
        return

    print(f"\n  Se cargarán {len(archivos)} archivo(s) de: {carpeta_elegida.name}")

    for a in archivos:
        print(f"    · {a.relative_to(DATA_PROCESSED)}")

    if input("\n  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    resumen = cargador.cargar_lote(archivos)
    _print_resumen_lote(resumen)


def _print_resumen_lote(r: dict):
    print(f"\n{'─'*65}")
    print(f"  ✅ Lote completado")
    print(f"     Folletos cargados : {r['cargados']}")
    print(f"     Errores           : {r['errores']}")
    print(f"     Precios insertados: {r['total_precios']}")
    print(f"{'─'*65}")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main():
    logger.info("=" * 65)
    logger.info("PriceScraper MX — Carga SQLite")
    logger.info(f"BD destino: {DB_PATH}")
    logger.info("=" * 65)

    cargador = CargadorSQLite()

    # Auto-conectar si la BD ya existe
    if DB_PATH.exists():
        cargador.crear_bd()

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  👋 Saliendo...\n")
            break

        elif opcion == 1:
            print("\n── Crear BD y tablas " + "─" * 44)
            cargador.crear_bd()
            r = cargador.resumen()
            if r:
                print(f"\n  Estado actual → "
                      f"Tiendas:{r['tiendas']}  Folletos:{r['folletos']}  "
                      f"Páginas:{r['paginas']}  Precios:{r['precios']}")

        elif opcion == 2:
            print("\n── Cargar TODOS los nlp_resultado.json " + "─" * 26)
            if not cargador._check():
                continue
            archivos = cargador.listar_nlp()
            if not archivos:
                logger.warning(f"No se encontraron nlp_resultado.json en {DATA_PROCESSED}")
                logger.warning("Ejecuta primero: python probar_nlp.py")
                continue

            print(f"\n  Archivos encontrados: {len(archivos)}")
            for a in archivos:
                print(f"    · {a.relative_to(DATA_PROCESSED)}")

            if input("\n  ¿Cargar todos? (s/n): ").strip().lower() != "s":
                continue

            resumen = cargador.cargar_lote(archivos)
            _print_resumen_lote(resumen)

        elif opcion == 3:
            print("\n── Cargar carpeta específica " + "─" * 36)
            if not cargador._check():
                continue
            menu_carpeta_especifica(cargador)

        elif opcion == 4:
            print("\n── Vista rápida " + "─" * 49)
            vista_rapida()

        elif opcion == 5:
            print("\n── Limpiar datos " + "─" * 48)
            r = cargador.resumen()
            if not r:
                continue
            print(f"  Se eliminarán: {r['precios']} precios, "
                  f"{r['folletos']} folletos, {r['tiendas']} tiendas.")
            if input("  ¿Confirmar? (s/n): ").strip().lower() == "s":
                cargador.limpiar()
            else:
                print("  ⚠️  Cancelado.")

        else:
            print("  ⚠️  Opción no válida.")

        try:
            if input("\n  ¿Hacer otra operación? (s/n): ").strip().lower() != "s":
                print("\n  👋 Saliendo...\n")
                break
        except EOFError:
            break


if __name__ == "__main__":
    main()
