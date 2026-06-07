"""
db_builder.py
PriceScraper MX — Constructor del modelo de base de datos

Crea y gestiona el schema de SQLite (prueba) → PostgreSQL (producción).
Módulo independiente: no depende del ETL ni del NLP.
Importable desde cualquier parte del pipeline.

Tablas:
    tiendas        → cadenas comerciales
    folletos       → folletos scrapeados con vigencia
    paginas        → páginas individuales de cada folleto
    extracciones   → entidades NLP (PRECIO, PRODUCTO, PROMO, etc.)
    eventos_promo  → campañas (Julio Regalado, Hot Sale, etc.)
    alertas        → monitoreo de precios por tienda/producto

Uso directo:
    python db_builder.py

Uso como módulo:
    from etl.db_builder import get_engine, crear_tablas, TIPOS_EXTRACCION
"""

import logging
from pathlib import Path
from datetime import datetime

from sqlalchemy import (
    create_engine, Column, Integer, BigInteger, String, Float,
    Boolean, Date, DateTime, Text, Enum, UniqueConstraint,
    ForeignKey, Index, event
)
from sqlalchemy.orm import declarative_base, relationship, Session

logger = logging.getLogger(__name__)

# ── Ruta por defecto ───────────────────────────────────────────────────────────
DB_PATH_DEFAULT = Path("data/pricescraper.db")

# ── Tipos válidos de extracción NLP ───────────────────────────────────────────
TIPOS_EXTRACCION = (
    "PRODUCTO",
    "PRECIO",
    "PRECIO_ANTERIOR",
    "AHORRO",
    "PROMO",
    "EVENTO_PROMO",
    "ATRIBUTO",
    "DESCARTE",
)

# ── Fuentes válidas ───────────────────────────────────────────────────────────
FUENTES = ("tiendeo", "ofertomat")

# ── Estados de folleto ────────────────────────────────────────────────────────
ESTADOS_FOLLETO = ("pending", "processing", "done", "error")

Base = declarative_base()


# ─────────────────────────────────────────────────────────────────────────────
# Modelos ORM
# ─────────────────────────────────────────────────────────────────────────────

class Tienda(Base):
    """
    Cadena comercial.
    fuente_slug: valor tal como llega del scraper (puede ser 'walmart' para Soriana).
    nombre:      nombre corregido y legible ('Soriana Híper').
    slug:        identificador normalizado para URLs y lookups ('soriana_hiper').
    """
    __tablename__ = "tiendas"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    nombre      = Column(String(100), nullable=False)
    slug        = Column(String(60), nullable=False, unique=True)
    fuente_slug = Column(String(60), nullable=True)   # valor raw del scraper
    activa      = Column(Boolean, default=True, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    folletos      = relationship("Folleto",      back_populates="tienda")
    extracciones  = relationship("Extraccion",   back_populates="tienda")
    eventos_promo = relationship("EventoPromo",  back_populates="tienda")
    alertas       = relationship("Alerta",       back_populates="tienda")

    def __repr__(self):
        return f"<Tienda id={self.id} slug='{self.slug}'>"


class Folleto(Base):
    """
    Folleto scrapeado. Un folleto = un PDF/conjunto de páginas de una tienda.

    folleto_id_fuente: ID en Tiendeo o Ofertomat (no se cruzan entre fuentes).
    perfil_ocr/motor_ocr: trazabilidad de investigación — con qué config se procesó.
    fecha_fin null: permitido para Ofertomat (no expone fecha_fin).
    """
    __tablename__ = "folletos"
    __table_args__ = (
        UniqueConstraint("fuente", "folleto_id_fuente", name="uq_folleto_fuente_id"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    tienda_id         = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    folleto_id_fuente = Column(String(30), nullable=False)
    fuente            = Column(Enum(*FUENTES, name="fuente_enum"), nullable=False)
    titulo            = Column(String(200), nullable=True)
    fecha_inicio      = Column(Date, nullable=True)
    fecha_fin         = Column(Date, nullable=True)   # null para Ofertomat
    url_origen        = Column(Text, nullable=True)
    total_paginas     = Column(Integer, default=0)
    perfil_ocr        = Column(String(40), nullable=True)   # ej: color_normal
    motor_ocr         = Column(String(20), nullable=True)   # ej: easyocr
    scrapeado_at      = Column(DateTime, nullable=True)
    estado            = Column(
        Enum(*ESTADOS_FOLLETO, name="estado_folleto_enum"),
        default="pending", nullable=False
    )
    created_at        = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    tienda        = relationship("Tienda",      back_populates="folletos")
    paginas       = relationship("Pagina",      back_populates="folleto",
                                 cascade="all, delete-orphan")
    extracciones  = relationship("Extraccion",  back_populates="folleto")
    eventos_promo = relationship("EventoPromo", back_populates="folleto")

    # Índices frecuentes para BI
    __table_args__ = (
        UniqueConstraint("fuente", "folleto_id_fuente", name="uq_folleto_fuente_id"),
        Index("ix_folleto_tienda_fecha", "tienda_id", "fecha_inicio"),
        Index("ix_folleto_fuente",       "fuente"),
        Index("ix_folleto_estado",       "estado"),
    )

    def __repr__(self):
        return f"<Folleto id={self.id} fuente='{self.fuente}' id_fuente='{self.folleto_id_fuente}'>"


class Pagina(Base):
    """
    Página individual de un folleto.
    Guarda métricas del OCR y del NLP para análisis de calidad.
    """
    __tablename__ = "paginas"
    __table_args__ = (
        UniqueConstraint("folleto_id", "numero_pagina", name="uq_pagina_folleto_num"),
    )

    id                = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id        = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    numero_pagina     = Column(Integer, nullable=False)
    archivo_imagen    = Column(String(100), nullable=True)   # ej: pagina_002.webp
    # Métricas OCR
    total_bloques_ocr = Column(Integer, default=0)
    confianza_ocr_prom= Column(Float, nullable=True)
    # Métricas NLP
    total_productos   = Column(Integer, default=0)
    total_precios     = Column(Integer, default=0)
    total_promos      = Column(Integer, default=0)
    total_atributos   = Column(Integer, default=0)
    tasa_util         = Column(Float, nullable=True)
    procesado_at      = Column(DateTime, nullable=True)

    # Relaciones
    folleto      = relationship("Folleto",     back_populates="paginas")
    extracciones = relationship("Extraccion",  back_populates="pagina",
                                cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Pagina folleto={self.folleto_id} pag={self.numero_pagina}>"


class Extraccion(Base):
    """
    Entidad extraída por el NLP de un bloque OCR.

    Cubre todos los tipos: PRODUCTO, PRECIO, PRECIO_ANTERIOR, AHORRO,
    PROMO, EVENTO_PROMO, ATRIBUTO.

    valor:          precio actual, ahorro, etc. (float, nullable)
    valor_anterior: precio antes del descuento (float, nullable)
                    — el ETL lo vincula por proximidad bbox cuando tipo=PRECIO
                      y hay un PRECIO_ANTERIOR cercano en la misma página.
    bbox_*:         coordenadas del bloque en la imagen preprocesada.
                    Usados por el ETL para la asociación posicional producto→precio.

    tienda_id / folleto_id desnormalizados para queries de BI sin JOINs profundos.
    """
    __tablename__ = "extracciones"

    id             = Column(BigInteger().with_variant(Integer, "sqlite"),
                            primary_key=True, autoincrement=True)
    pagina_id      = Column(Integer, ForeignKey("paginas.id"),   nullable=False)
    folleto_id     = Column(Integer, ForeignKey("folletos.id"),  nullable=False)
    tienda_id      = Column(Integer, ForeignKey("tiendas.id"),   nullable=False)

    # Clasificación NLP
    tipo           = Column(Enum(*TIPOS_EXTRACCION, name="tipo_extraccion_enum"),
                            nullable=False)
    texto_raw      = Column(Text, nullable=False)       # texto OCR original
    texto_norm     = Column(String(300), nullable=True) # texto limpio (post _limpiar_texto)
    categoria_nlp  = Column(String(60), nullable=True)  # categoría del catálogo (alimentos, etc.)

    # Valores numéricos
    valor          = Column(Float, nullable=True)  # precio actual / monto ahorro
    valor_anterior = Column(Float, nullable=True)  # precio anterior (vinculado por bbox)
    texto_promo    = Column(String(300), nullable=True)  # texto de la promoción

    # Calidad OCR
    confianza_ocr  = Column(Float, nullable=True)  # 0.0 – 1.0

    # Posición en la imagen (para asociación posicional producto→precio)
    bbox_x         = Column(Integer, nullable=True)
    bbox_y         = Column(Integer, nullable=True)
    bbox_ancho     = Column(Integer, nullable=True)
    bbox_alto      = Column(Integer, nullable=True)

    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    pagina   = relationship("Pagina",   back_populates="extracciones")
    folleto  = relationship("Folleto",  back_populates="extracciones")
    tienda   = relationship("Tienda",   back_populates="extracciones")

    # Índices para BI
    __table_args__ = (
        Index("ix_ext_tipo",              "tipo"),
        Index("ix_ext_tienda_tipo",       "tienda_id", "tipo"),
        Index("ix_ext_folleto_pagina",    "folleto_id", "pagina_id"),
        Index("ix_ext_valor",             "valor"),
        Index("ix_ext_confianza",         "confianza_ocr"),
    )

    def __repr__(self):
        val = f" ${self.valor:.2f}" if self.valor else ""
        return f"<Extraccion [{self.tipo}]{val} '{self.texto_norm[:30] if self.texto_norm else ''}'>"


class EventoPromo(Base):
    """
    Campaña promocional detectada en un folleto.
    Ej: 'Julio Regalado', 'Hot Sale', 'Buen Fin', 'Precio Bajo'.

    Separada de Extraccion porque es metadata de campaña con vigencia propia
    — no tiene valor numérico pero sí tiene relevancia temporal para el BI.
    """
    __tablename__ = "eventos_promo"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id    = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    tienda_id     = Column(Integer, ForeignKey("tiendas.id"),  nullable=False)
    nombre_evento = Column(String(100), nullable=False)  # normalizado: 'julio_regalado'
    texto_raw     = Column(String(200), nullable=True)   # texto original OCR
    # Vigencia heredada del folleto (puede refinarse si se detecta en el texto)
    fecha_inicio  = Column(Date, nullable=True)
    fecha_fin     = Column(Date, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    folleto = relationship("Folleto", back_populates="eventos_promo")
    tienda  = relationship("Tienda",  back_populates="eventos_promo")

    __table_args__ = (
        UniqueConstraint("folleto_id", "nombre_evento", name="uq_evento_folleto"),
        Index("ix_evento_nombre",    "nombre_evento"),
        Index("ix_evento_tienda",    "tienda_id"),
        Index("ix_evento_fechas",    "fecha_inicio", "fecha_fin"),
    )

    def __repr__(self):
        return f"<EventoPromo '{self.nombre_evento}' tienda={self.tienda_id}>"


class Alerta(Base):
    """
    Monitoreo de precios por tienda y producto normalizado.

    slug_producto: texto normalizado del producto a monitorear
                   (sin tabla de productos normalizada aún — fase 2 lo migra a FK).
    umbral_precio: se dispara cuando precio <= umbral.
    """
    __tablename__ = "alertas"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    tienda_id      = Column(Integer, ForeignKey("tiendas.id"), nullable=True)
    slug_producto  = Column(String(200), nullable=False)
    umbral_precio  = Column(Float, nullable=False)
    activa         = Column(Boolean, default=True, nullable=False)
    disparada_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relaciones
    tienda = relationship("Tienda", back_populates="alertas")

    __table_args__ = (
        Index("ix_alerta_tienda_producto", "tienda_id", "slug_producto"),
        Index("ix_alerta_activa",          "activa"),
    )

    def __repr__(self):
        return f"<Alerta '{self.slug_producto}' umbral=${self.umbral_precio} activa={self.activa}>"


# ─────────────────────────────────────────────────────────────────────────────
# Funciones de gestión
# ─────────────────────────────────────────────────────────────────────────────

def get_engine(db_path: Path = None, echo: bool = False):
    """
    Crea y retorna el engine de SQLAlchemy.

    Args:
        db_path: Ruta al archivo SQLite. None → usa DB_PATH_DEFAULT.
                 Para PostgreSQL en producción:
                 usar create_engine('postgresql://user:pass@host/db') directamente.
        echo:    Si True, imprime todas las queries SQL (debug).

    Returns:
        Engine de SQLAlchemy configurado.
    """
    if db_path is None:
        db_path = DB_PATH_DEFAULT

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{db_path}",
        echo=echo,
        connect_args={"check_same_thread": False},
    )

    # Activar WAL y foreign keys en SQLite para mejor concurrencia e integridad
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    logger.info(f"[DB] Engine SQLite: {db_path}")
    return engine


def crear_tablas(engine) -> None:
    """
    Crea todas las tablas si no existen (CREATE TABLE IF NOT EXISTS).
    Idempotente — seguro de llamar múltiples veces.
    """
    Base.metadata.create_all(engine)
    logger.info("[DB] ✅ Tablas creadas/verificadas")
    _log_tablas(engine)


def eliminar_tablas(engine) -> None:
    """
    Elimina todas las tablas. DESTRUCTIVO — solo para desarrollo/reset.
    """
    Base.metadata.drop_all(engine)
    logger.info("[DB] 🗑️  Todas las tablas eliminadas")


def verificar_tablas(engine) -> dict:
    """
    Verifica qué tablas existen y cuántos registros tienen.

    Returns:
        Dict {nombre_tabla: conteo_filas}
    """
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    tablas_existentes = inspector.get_table_names()

    resultado = {}
    modelos = [Tienda, Folleto, Pagina, Extraccion, EventoPromo, Alerta]

    with Session(engine) as session:
        for modelo in modelos:
            nombre = modelo.__tablename__
            if nombre in tablas_existentes:
                count = session.execute(
                    text(f"SELECT COUNT(*) FROM {nombre}")
                ).scalar()
                resultado[nombre] = count
            else:
                resultado[nombre] = None  # tabla no existe

    return resultado


def _log_tablas(engine) -> None:
    """Imprime el estado de las tablas en el log."""
    estado = verificar_tablas(engine)
    for tabla, count in estado.items():
        if count is None:
            logger.warning(f"[DB]   ✗ {tabla} — no existe")
        else:
            logger.info(f"[DB]   ✓ {tabla}: {count} registros")


def get_session(engine) -> Session:
    """Retorna una sesión de SQLAlchemy lista para usar."""
    return Session(engine)


# ─────────────────────────────────────────────────────────────────────────────
# CLI interactivo
# ─────────────────────────────────────────────────────────────────────────────

def _menu() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper MX — Constructor de BD")
    print("═" * 55)
    print("   1 → Crear tablas (si no existen)")
    print("   2 → Verificar estado de tablas")
    print("   3 → Eliminar TODAS las tablas  ⚠️")
    print("   4 → Recrear schema completo     ⚠️")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def main():
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler()],
    )

    # Permitir ruta custom por argumento: python db_builder.py data/mi_db.db
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH_DEFAULT
    engine = get_engine(db_path)

    while True:
        opcion = _menu()

        if opcion == 0:
            print("\n  👋 Saliendo...\n")
            break

        elif opcion == 1:
            crear_tablas(engine)
            print(f"\n  ✅ Schema creado en: {db_path}")

        elif opcion == 2:
            estado = verificar_tablas(engine)
            print(f"\n{'─'*45}")
            print(f"  {'TABLA':<20} {'REGISTROS':>10}")
            print(f"{'─'*45}")
            for tabla, count in estado.items():
                estado_str = f"{count:>10,}" if count is not None else "  NO EXISTE"
                print(f"  {tabla:<20} {estado_str}")
            print(f"{'─'*45}")

        elif opcion == 3:
            confirm = input("\n  ⚠️  Escriba 'ELIMINAR' para confirmar: ").strip()
            if confirm == "ELIMINAR":
                eliminar_tablas(engine)
                print("  🗑️  Tablas eliminadas.")
            else:
                print("  Cancelado.")

        elif opcion == 4:
            confirm = input("\n  ⚠️  Esto borra y recrea todo. Escriba 'RECREAR': ").strip()
            if confirm == "RECREAR":
                eliminar_tablas(engine)
                crear_tablas(engine)
                print(f"  ✅ Schema recreado en: {db_path}")
            else:
                print("  Cancelado.")

        else:
            print("  ⚠️  Opción no válida.")

        try:
            if input("\n  ¿Otra operación? (s/n): ").strip().lower() != "s":
                print("\n  👋 Saliendo...\n")
                break
        except EOFError:
            break


if __name__ == "__main__":
    main()