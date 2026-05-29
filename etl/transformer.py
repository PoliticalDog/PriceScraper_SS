"""
etl/transformer.py
Módulo ETL — Transformación y carga de datos NLP a PostgreSQL.
PriceScraper MX

Lee los nlp_resultado.json generados por el módulo NLP,
normaliza los datos con Pandas y los carga en PostgreSQL
usando SQLAlchemy.

Tablas objetivo:
  tiendas   → catálogo de tiendas por fuente
  folletos  → metadata de cada folleto scrapeado
  paginas   → páginas individuales por folleto
  precios   → registro append-only de precios detectados
"""

import re
import logging
import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import pandas as pd
from sqlalchemy import (
    create_engine, text,
    Column, Integer, String, Float, Date, DateTime,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import declarative_base, Session, relationship
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)

Base = declarative_base()
DATA_PROCESSED = Path("data/processed")


# ── Modelos SQLAlchemy ────────────────────────────────────────────────────────

class Tienda(Base):
    __tablename__ = "tiendas"

    id      = Column(Integer, primary_key=True, autoincrement=True)
    nombre  = Column(String(100), nullable=False)
    slug    = Column(String(100), nullable=False)  # "bodega_aurrera"
    fuente  = Column(String(50),  nullable=False)  # "tiendeo" | "ofertomat"

    __table_args__ = (
        UniqueConstraint("slug", "fuente", name="uq_tienda_slug_fuente"),
    )

    folletos = relationship("Folleto", back_populates="tienda")

    def __repr__(self):
        return f"<Tienda {self.nombre} ({self.fuente})>"


class Folleto(Base):
    __tablename__ = "folletos"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    tienda_id        = Column(Integer, ForeignKey("tiendas.id"), nullable=False)
    folleto_id_fuente = Column(String(50), nullable=False)  # ID original de Tiendeo
    titulo           = Column(String(255))
    fecha_inicio     = Column(Date)
    fecha_fin        = Column(Date)
    url_folleto      = Column(String(500))
    fecha_scraping   = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("folleto_id_fuente", "tienda_id",
                         name="uq_folleto_fuente_tienda"),
    )

    tienda  = relationship("Tienda", back_populates="folletos")
    paginas = relationship("Pagina", back_populates="folleto")
    precios = relationship("Precio", back_populates="folleto")

    def __repr__(self):
        return f"<Folleto {self.folleto_id_fuente} — {self.titulo}>"


class Pagina(Base):
    __tablename__ = "paginas"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id     = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    numero_pagina  = Column(Integer, nullable=False)
    nombre_archivo = Column(String(100))  # "pagina_001.webp"
    ruta_imagen    = Column(String(500))  # ruta relativa en disco

    __table_args__ = (
        UniqueConstraint("folleto_id", "numero_pagina", name="uq_pagina_folleto"),
    )

    folleto = relationship("Folleto", back_populates="paginas")
    precios = relationship("Precio", back_populates="pagina")


class Precio(Base):
    """
    Tabla append-only de precios detectados.
    Nunca se hace UPDATE — cada nueva detección es un INSERT nuevo.
    Esto permite análisis de tendencias históricas.
    """
    __tablename__ = "precios"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    folleto_id      = Column(Integer, ForeignKey("folletos.id"), nullable=False)
    pagina_id       = Column(Integer, ForeignKey("paginas.id"), nullable=True)
    texto_producto  = Column(String(300))        # nombre del producto (texto OCR normalizado)
    precio_actual   = Column(Float, nullable=False)
    precio_anterior = Column(Float, nullable=True)   # "Antes: $X" — puede ser None
    texto_ocr_precio = Column(String(100))       # texto raw del OCR para auditoría
    confianza_ocr   = Column(Float)              # confianza del bloque OCR
    bbox_x          = Column(Integer)            # posición del precio en la imagen
    bbox_y          = Column(Integer)
    bbox_ancho      = Column(Integer)
    bbox_alto       = Column(Integer)
    fecha_registro  = Column(DateTime, default=datetime.utcnow)

    folleto = relationship("Folleto", back_populates="precios")
    pagina  = relationship("Pagina",  back_populates="precios")

    def __repr__(self):
        return f"<Precio ${self.precio_actual} — {self.texto_producto}>"


# ── Transformer principal ─────────────────────────────────────────────────────

class Transformer:
    """
    Lee nlp_resultado.json de cada folleto y carga los datos en PostgreSQL.

    Flujo por folleto:
      1. Leer nlp_resultado.json
      2. Upsert tienda (crear si no existe)
      3. Upsert folleto (crear si no existe)
      4. Insertar páginas (skip si ya existen)
      5. Insertar precios (siempre INSERT — append-only)
    """

    def __init__(self, db_url: str):
        """
        Args:
            db_url: URL de conexión SQLAlchemy.
                    PostgreSQL: "postgresql://usuario:password@localhost:5432/pricescraper"
                    SQLite:     "sqlite:///data/pricescraper.db"
        """
        self.engine = create_engine(db_url, echo=False)
        self._crear_tablas()
        logger.info(f"[ETL] Conectado a BD: {db_url.split('@')[-1] if '@' in db_url else db_url}")

    def _crear_tablas(self):
        """Crea todas las tablas si no existen."""
        Base.metadata.create_all(self.engine)
        logger.info("[ETL] Tablas verificadas/creadas.")

    # ── Método principal ──────────────────────────────────────────────────────

    def cargar_folleto(self, ruta_nlp: Path, metadata_folleto: dict = None) -> dict:
        """
        Carga un nlp_resultado.json completo en la BD.

        Args:
            ruta_nlp:         Ruta al nlp_resultado.json
            metadata_folleto: Dict opcional con titulo, fecha_inicio, fecha_fin,
                              url_folleto (del folletos_procesados.json del scraper)

        Returns:
            Dict con resumen de registros insertados.
        """
        with open(ruta_nlp, encoding="utf-8") as f:
            nlp_data = json.load(f)

        fuente     = nlp_data.get("fuente", "")
        slug       = nlp_data.get("tienda", "")
        folleto_id = nlp_data.get("folleto_id", "")

        logger.info(f"\n[ETL] Cargando: {fuente}/{slug}/{folleto_id}")

        meta = metadata_folleto or {}

        with Session(self.engine) as session:
            # 1. Upsert tienda
            tienda = self._upsert_tienda(session, slug, fuente)

            # 2. Upsert folleto
            folleto = self._upsert_folleto(
                session, tienda, folleto_id,
                titulo=meta.get("titulo", ""),
                fecha_inicio=self._parsear_fecha(meta.get("fecha_inicio")),
                fecha_fin=self._parsear_fecha(meta.get("fecha_fin")),
                url_folleto=meta.get("url_folleto", ""),
            )

            # 3. Insertar páginas y precios
            total_precios   = 0
            total_sin_prod  = 0

            for pag_data in nlp_data.get("paginas", []):
                nombre_archivo = pag_data.get("pagina", "")
                num_pagina     = self._extraer_numero_pagina(nombre_archivo)

                pagina = self._upsert_pagina(session, folleto, num_pagina, nombre_archivo)

                # Construir DataFrame de precios de esta página
                df = self._construir_dataframe_precios(pag_data)

                if df.empty:
                    continue

                # Cargar cada precio
                for _, row in df.iterrows():
                    try:
                        precio_obj = Precio(
                            folleto_id       = folleto.id,
                            pagina_id        = pagina.id,
                            texto_producto   = row["texto_producto"],
                            precio_actual    = row["precio_actual"],
                            precio_anterior  = row["precio_anterior"],
                            texto_ocr_precio = row["texto_ocr"],
                            confianza_ocr    = row["confianza"],
                            bbox_x           = row["bbox_x"],
                            bbox_y           = row["bbox_y"],
                            bbox_ancho       = row["bbox_ancho"],
                            bbox_alto        = row["bbox_alto"],
                        )
                        session.add(precio_obj)
                        total_precios += 1

                        if not row["texto_producto"]:
                            total_sin_prod += 1

                    except Exception as e:
                        logger.warning(f"[ETL] Error insertando precio: {e}")

            session.commit()

        resumen = {
            "fuente":         fuente,
            "tienda":         slug,
            "folleto_id":     folleto_id,
            "precios_cargados": total_precios,
            "sin_producto":   total_sin_prod,
        }
        logger.info(f"[ETL] ✅ {folleto_id} → {total_precios} precios insertados "
                   f"({total_sin_prod} sin producto asociado)")
        return resumen

    # ── Upserts ───────────────────────────────────────────────────────────────

    def _upsert_tienda(self, session: Session, slug: str, fuente: str) -> Tienda:
        """Retorna la tienda existente o la crea si no existe."""
        tienda = session.query(Tienda).filter_by(slug=slug, fuente=fuente).first()
        if not tienda:
            nombre = slug.replace("_", " ").title()
            tienda = Tienda(nombre=nombre, slug=slug, fuente=fuente)
            session.add(tienda)
            session.flush()
            logger.info(f"[ETL] Nueva tienda: {nombre} ({fuente})")
        return tienda

    def _upsert_folleto(
        self, session: Session, tienda: Tienda,
        folleto_id_fuente: str, titulo: str,
        fecha_inicio: Optional[date], fecha_fin: Optional[date],
        url_folleto: str,
    ) -> Folleto:
        """Retorna el folleto existente o lo crea si no existe."""
        folleto = session.query(Folleto).filter_by(
            tienda_id=tienda.id,
            folleto_id_fuente=folleto_id_fuente
        ).first()

        if not folleto:
            folleto = Folleto(
                tienda_id=tienda.id,
                folleto_id_fuente=folleto_id_fuente,
                titulo=titulo,
                fecha_inicio=fecha_inicio,
                fecha_fin=fecha_fin,
                url_folleto=url_folleto,
            )
            session.add(folleto)
            session.flush()
            logger.info(f"[ETL] Nuevo folleto: {folleto_id_fuente} — {titulo}")
        return folleto

    def _upsert_pagina(
        self, session: Session, folleto: Folleto,
        numero_pagina: int, nombre_archivo: str
    ) -> Pagina:
        """Retorna la página existente o la crea si no existe."""
        pagina = session.query(Pagina).filter_by(
            folleto_id=folleto.id,
            numero_pagina=numero_pagina
        ).first()

        if not pagina:
            ruta = (DATA_PROCESSED / folleto.tienda.fuente /
                    folleto.tienda.slug / folleto.folleto_id_fuente /
                    nombre_archivo)
            pagina = Pagina(
                folleto_id=folleto.id,
                numero_pagina=numero_pagina,
                nombre_archivo=nombre_archivo,
                ruta_imagen=str(ruta),
            )
            session.add(pagina)
            session.flush()
        return pagina

    # ── Construcción del DataFrame ─────────────────────────────────────────────

    def _construir_dataframe_precios(self, pag_data: dict) -> pd.DataFrame:
        """
        Construye un DataFrame de precios a partir de los datos de una página.

        Estrategia de asociación producto-precio:
          - Por ahora: tomar el último PRODUCTO antes de cada PRECIO en el JSON
            (orden espacial aproximado — mejorar con bbox en futuras versiones)
          - precio_anterior: buscar en precios_anteriores por proximidad de bbox
        """
        precios    = pag_data.get("precios", [])
        productos  = pag_data.get("productos", [])
        precios_ant = pag_data.get("precios_anteriores", [])

        if not precios:
            return pd.DataFrame()

        filas = []
        for precio in precios:
            # Asociar el precio con el producto más cercano por bbox_y
            producto_texto = self._asociar_producto(precio, productos)

            # Buscar precio anterior más cercano por bbox
            precio_ant_valor = self._buscar_precio_anterior(precio, precios_ant)

            bbox = precio.get("bbox", {})
            filas.append({
                "texto_producto": producto_texto,
                "precio_actual":  precio.get("valor", 0.0),
                "precio_anterior": precio_ant_valor,
                "texto_ocr":      precio.get("texto", ""),
                "confianza":      precio.get("confianza", 0.0),
                "bbox_x":         bbox.get("x", 0),
                "bbox_y":         bbox.get("y", 0),
                "bbox_ancho":     bbox.get("ancho", 0),
                "bbox_alto":      bbox.get("alto", 0),
            })

        df = pd.DataFrame(filas)

        # Normalizar texto del producto
        df["texto_producto"] = df["texto_producto"].apply(self._normalizar_texto)

        # Filtrar precios inválidos (0 o negativos)
        df = df[df["precio_actual"] > 0]

        return df

    def _asociar_producto(self, precio: dict, productos: list) -> str:
        """
        Asocia un precio con el producto más probable.

        Estrategia actual: producto cuyo bbox_y sea el más cercano
        y esté ARRIBA del precio (bbox_y menor).
        """
        if not productos:
            return ""

        precio_y = precio.get("bbox", {}).get("y", 0)
        precio_x = precio.get("bbox", {}).get("x", 0)

        mejor_producto = ""
        menor_distancia = float("inf")

        for prod in productos:
            prod_bbox = prod.get("bbox", {})
            prod_y = prod_bbox.get("y", 0)
            prod_x = prod_bbox.get("x", 0)

            # Solo considerar productos que estén cerca horizontalmente
            diff_x = abs(prod_x - precio_x)
            if diff_x > 400:  # tolerancia horizontal ~400px
                continue

            # Calcular distancia vertical — preferir productos arriba del precio
            diff_y = precio_y - prod_y
            if 0 < diff_y < menor_distancia:
                menor_distancia = diff_y
                mejor_producto = prod.get("texto", "")

        return mejor_producto

    def _buscar_precio_anterior(self, precio: dict, precios_ant: list) -> Optional[float]:
        """
        Busca el precio anterior más cercano al precio actual por bbox.
        Retorna el valor float o None si no encuentra ninguno cercano.
        """
        if not precios_ant:
            return None

        precio_x = precio.get("bbox", {}).get("x", 0)
        precio_y = precio.get("bbox", {}).get("y", 0)

        mejor_valor  = None
        menor_dist   = float("inf")

        for pa in precios_ant:
            pa_bbox = pa.get("bbox", {})
            pa_x    = pa_bbox.get("x", 0)
            pa_y    = pa_bbox.get("y", 0)

            # Distancia euclidiana entre precio actual y precio anterior
            dist = ((precio_x - pa_x) ** 2 + (precio_y - pa_y) ** 2) ** 0.5

            if dist < menor_dist and dist < 300:  # tolerancia 300px
                menor_dist  = dist
                mejor_valor = pa.get("valor")

        return mejor_valor

    # ── Utilidades ────────────────────────────────────────────────────────────

    def _normalizar_texto(self, texto: str) -> str:
        """Limpia y normaliza el texto del producto para la BD."""
        if not texto:
            return ""
        # Eliminar caracteres de ruido OCR residuales
        texto = re.sub(r"[%@€£¥°©®™]", "", texto)
        # Normalizar espacios
        texto = re.sub(r"\s+", " ", texto).strip()
        # Capitalizar primera letra
        return texto[:1].upper() + texto[1:] if texto else ""

    def _parsear_fecha(self, fecha_str: Optional[str]) -> Optional[date]:
        """Convierte string 'YYYY-MM-DD' a objeto date."""
        if not fecha_str:
            return None
        try:
            return datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def _extraer_numero_pagina(self, nombre_archivo: str) -> int:
        """Extrae número de página de 'pagina_001.webp' → 1."""
        match = re.search(r"(\d+)", nombre_archivo)
        return int(match.group(1)) if match else 0

    # ── Consultas de verificación ─────────────────────────────────────────────

    def resumen_bd(self) -> dict:
        """Retorna un resumen del estado actual de la BD."""
        with Session(self.engine) as session:
            return {
                "tiendas":  session.query(Tienda).count(),
                "folletos": session.query(Folleto).count(),
                "paginas":  session.query(Pagina).count(),
                "precios":  session.query(Precio).count(),
            }

    def precios_por_tienda(self) -> pd.DataFrame:
        """DataFrame con conteo de precios por tienda — útil para validación."""
        query = """
            SELECT t.nombre, t.fuente,
                   COUNT(p.id) as total_precios,
                   AVG(p.precio_actual) as precio_promedio,
                   MIN(p.precio_actual) as precio_min,
                   MAX(p.precio_actual) as precio_max
            FROM precios p
            JOIN folletos f ON p.folleto_id = f.id
            JOIN tiendas t  ON f.tienda_id  = t.id
            GROUP BY t.nombre, t.fuente
            ORDER BY total_precios DESC
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn)