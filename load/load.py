# Lee nlp_resultado.json (con o sin campo norm{} del normalizador),
# asocia productos↔precios por proximidad bbox y carga en SQLite/PostgreSQL.

import json
import logging
import math
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from .db_builder import (
    get_engine, crear_tablas,
    Tienda, Folleto, Pagina, Extraccion, EventoPromo,
)

logger = logging.getLogger(__name__)

DATA_PROCESSED = Path("data/processed")


CORRECCION_TIENDAS: dict[tuple[str, str], tuple[str, str]] = {
    ("tiendeo", "walmart"): ("soriana", "Soriana"),
}


# ------------------ Loader principal ------------------

class Loader:
    """
    Carga nlp_resultado.json en la base de datos.

    Args:
        db_path: Ruta al archivo SQLite (string o Path).
                 Para PostgreSQL pasa db_url directamente al engine externo
                 y usa Loader.desde_engine(engine).
    """

    def __init__(self, db_path: str | Path = "data/pricescraper.db"):
        self.engine = get_engine(Path(db_path))
        crear_tablas(self.engine)
        logger.info(f"[Load] BD lista: {db_path}")

    @classmethod
    def desde_engine(cls, engine) -> "Loader":
        """Factory para usar un engine ya creado (útil en el ETL completo)."""
        instance = cls.__new__(cls)
        instance.engine = engine
        crear_tablas(engine)
        return instance

    # ------------------ API pública ------------------

    def cargar_folleto(
        self,
        ruta_nlp: Path,
        metadata: dict | None = None,
    ) -> dict:
        """
        Carga un nlp_resultado.json completo en la BD.

        Args:
            ruta_nlp: Ruta al nlp_resultado.json
            metadata: Dict opcional con claves:
                        titulo, fecha_inicio (YYYY-MM-DD), fecha_fin (YYYY-MM-DD),
                        url_origen, perfil_ocr, motor_ocr, scrapeado_at

        Returns:
            Dict con resumen de registros insertados/omitidos.
        """
        ruta_nlp = Path(ruta_nlp)
        if not ruta_nlp.exists():
            raise FileNotFoundError(f"[Load] No existe: {ruta_nlp}")

        with open(ruta_nlp, encoding="utf-8") as f:
            nlp = json.load(f)

        fuente     = nlp.get("fuente", "")
        slug_raw   = nlp.get("tienda", "")
        folleto_id = nlp.get("folleto_id", "")

        # Corregir slug erróneo si aplica
        slug, nombre_tienda = self._corregir_tienda(fuente, slug_raw)

        logger.info(f"[Load] -- {fuente}/{slug}/{folleto_id} --------------")

        meta = metadata or {}
        resumen = {
            "fuente": fuente, "tienda": slug, "folleto_id": folleto_id,
            "extracciones_insertadas": 0,
            "precios_sin_producto": 0,
            "eventos_insertados": 0,
            "paginas_procesadas": 0,
            "errores": 0,
        }

        with Session(self.engine) as session:

            # 1. Upsert tienda
            tienda = self._upsert_tienda(session, slug, nombre_tienda, fuente, slug_raw)

            # 2. Upsert folleto
            folleto = self._upsert_folleto(session, tienda, folleto_id, fuente, meta)

            # 3. Páginas + extracciones
            for pag_data in nlp.get("paginas", []):
                try:
                    r = self._procesar_pagina(session, tienda, folleto, pag_data)
                    resumen["extracciones_insertadas"] += r["extracciones"]
                    resumen["precios_sin_producto"]    += r["sin_producto"]
                    resumen["eventos_insertados"]      += r["eventos"]
                    resumen["paginas_procesadas"]      += 1
                except Exception as e:
                    logger.error(f"[Load] Error en página {pag_data.get('pagina','?')}: {e}")
                    resumen["errores"] += 1

            session.commit()

        logger.info(
            f"[Load] ✅ {folleto_id} → "
            f"{resumen['extracciones_insertadas']} extracciones | "
            f"{resumen['precios_sin_producto']} sin producto | "
            f"{resumen['eventos_insertados']} eventos"
        )
        return resumen

    def cargar_batch(
        self,
        data_processed: Path = DATA_PROCESSED,
        forzar: bool = False,
    ) -> dict:
        """
        Carga todos los nlp_resultado.json encontrados bajo data_processed/.

        Args:
            data_processed: Carpeta raíz donde buscar nlp_resultado.json
            forzar:         Si True, recarga folletos aunque ya estén en BD.
                            Si False (default), salta folletos ya cargados.

        Returns:
            Dict con totales del batch.
        """
        data_processed = Path(data_processed)
        rutas = sorted(data_processed.rglob("nlp_resultado.json"))

        if not rutas:
            logger.warning(f"[Load] Sin nlp_resultado.json en {data_processed}")
            return {}

        logger.info(f"[Load] {len(rutas)} folletos encontrados")

        totales = {
            "procesados": 0, "omitidos": 0, "errores": 0,
            "extracciones_total": 0, "eventos_total": 0,
        }

        for i, ruta in enumerate(rutas, 1):
            carpeta = ruta.parent
            ruta_rel = carpeta.relative_to(data_processed)

            # Buscar metadata si existe folletos_procesados.json en la carpeta padre
            meta = self._leer_metadata(carpeta)

            # Saltar si ya está cargado (verificar por folleto_id en BD)
            if not forzar and self._ya_cargado(ruta):
                logger.info(f"[Load] ⏭️  [{i}/{len(rutas)}] Ya cargado: {ruta_rel}")
                totales["omitidos"] += 1
                continue

            logger.info(f"[Load] [{i}/{len(rutas)}] {ruta_rel}")
            try:
                r = self.cargar_folleto(ruta, meta)
                totales["procesados"]         += 1
                totales["extracciones_total"] += r["extracciones_insertadas"]
                totales["eventos_total"]      += r["eventos_insertados"]
            except Exception as e:
                logger.error(f"[Load] ✗ Error en {ruta_rel}: {e}")
                totales["errores"] += 1

        logger.info(
            f"[Load] ══ Batch completo ══ "
            f"procesados:{totales['procesados']} "
            f"omitidos:{totales['omitidos']} "
            f"errores:{totales['errores']} | "
            f"extracciones:{totales['extracciones_total']} "
            f"eventos:{totales['eventos_total']}"
        )
        return totales

    # ------------------ Procesamiento de página ------------------

    def _procesar_pagina(
        self,
        session: Session,
        tienda: Tienda,
        folleto: Folleto,
        pag_data: dict,
    ) -> dict:
        """
        Procesa una página del JSON y hace los INSERTs correspondientes.
        Retorna contadores locales de la página.
        """
        nombre_pag = pag_data.get("pagina", "")
        num_pagina = self._extraer_numero_pagina(nombre_pag)

        pagina = self._upsert_pagina(session, folleto, num_pagina, nombre_pag)

        productos      = pag_data.get("productos", [])
        precios        = pag_data.get("precios", [])
        precios_ant    = pag_data.get("precios_anteriores", [])
        promos         = pag_data.get("promos", [])
        eventos_promo  = pag_data.get("eventos_promo", [])
        atributos      = pag_data.get("atributos", [])

        contadores = {"extracciones": 0, "sin_producto": 0, "eventos": 0}

        #  ------------------  Precios con producto y precio_anterior asociados ------------------
        for precio in precios:
            producto_match = self._asociar_producto(precio, productos)
            precio_ant_val = self._buscar_precio_anterior(precio, precios_ant)

            # Usar nombre canónico si el producto ya pasó por normalizador
            texto_norm = self._texto_normalizado(producto_match)
            texto_raw  = producto_match.get("texto", "") if producto_match else ""

            bbox = precio.get("bbox", {})

            try:
                ext = Extraccion(
                    pagina_id     = pagina.id,
                    folleto_id    = folleto.id,
                    tienda_id     = tienda.id,
                    tipo          = "PRECIO",
                    texto_raw     = precio.get("texto", ""),
                    texto_norm    = texto_norm or texto_raw or None,
                    categoria_nlp = producto_match.get("categoria", "") if producto_match else None,
                    valor         = precio.get("valor"),
                    valor_anterior= precio_ant_val,
                    confianza_ocr = precio.get("confianza"),
                    bbox_x        = bbox.get("x"),
                    bbox_y        = bbox.get("y"),
                    bbox_ancho    = bbox.get("ancho"),
                    bbox_alto     = bbox.get("alto"),
                )
                session.add(ext)
                contadores["extracciones"] += 1

                if not texto_norm and not texto_raw:
                    contadores["sin_producto"] += 1

            except Exception as e:
                logger.warning(f"[Load] Error insertando precio: {e}")

        # ------------------ Promociones ------------------
        for promo in promos:
            bbox = promo.get("bbox", {})
            try:
                ext = Extraccion(
                    pagina_id     = pagina.id,
                    folleto_id    = folleto.id,
                    tienda_id     = tienda.id,
                    tipo          = "PROMO",
                    texto_raw     = promo.get("texto", ""),
                    texto_norm    = promo.get("texto", ""),
                    confianza_ocr = promo.get("confianza"),
                    bbox_x        = bbox.get("x"),
                    bbox_y        = bbox.get("y"),
                    bbox_ancho    = bbox.get("ancho"),
                    bbox_alto     = bbox.get("alto"),
                )
                session.add(ext)
                contadores["extracciones"] += 1
            except Exception as e:
                logger.warning(f"[Load] Error insertando promo: {e}")

        # ------------------ Eventos promo -----------------------------------------------------
        for evento in eventos_promo:
            texto_evento = evento.get("texto", "")
            nombre_norm  = self._normalizar_nombre_evento(texto_evento)

            # Extraccion
            bbox = evento.get("bbox", {})
            try:
                ext = Extraccion(
                    pagina_id     = pagina.id,
                    folleto_id    = folleto.id,
                    tienda_id     = tienda.id,
                    tipo          = "EVENTO_PROMO",
                    texto_raw     = texto_evento,
                    texto_norm    = nombre_norm,
                    confianza_ocr = evento.get("confianza"),
                    bbox_x        = bbox.get("x"),
                    bbox_y        = bbox.get("y"),
                    bbox_ancho    = bbox.get("ancho"),
                    bbox_alto     = bbox.get("alto"),
                )
                session.add(ext)
                contadores["extracciones"] += 1
            except Exception as e:
                logger.warning(f"[Load] Error insertando evento (extraccion): {e}")

            # Tabla eventos_promo (upsert por folleto + nombre)
            try:
                ev = self._upsert_evento_promo(session, folleto, tienda, nombre_norm, texto_evento)
                if ev:
                    contadores["eventos"] += 1
            except Exception as e:
                logger.warning(f"[Load] Error insertando evento (tabla): {e}")

        # ------------------ Actualizar métricas de la página ------------------
        pagina.total_productos = len(productos)
        pagina.total_precios   = len(precios)
        pagina.total_promos    = len(promos) + len(eventos_promo)
        pagina.total_atributos = len(atributos)
        pagina.procesado_at    = datetime.utcnow()

        return contadores

    # ------------------ Asociación bbox ------------------

    def _asociar_producto(self, precio: dict, productos: list) -> dict | None:
        """
        Asocia un precio con el producto más probable por proximidad bbox.

        Criterio: producto más cercano verticalmente que esté ARRIBA del precio
        y dentro de 400px de tolerancia horizontal.

        Returns:
            Dict del producto (con posible campo norm{}) o None si no encuentra.
        """
        if not productos:
            return None

        precio_x = precio.get("bbox", {}).get("x", 0)
        precio_y = precio.get("bbox", {}).get("y", 0)

        mejor     = None
        menor_dist = float("inf")

        for prod in productos:
            prod_bbox = prod.get("bbox", {})
            prod_x = prod_bbox.get("x", 0)
            prod_y = prod_bbox.get("y", 0)

            # Tolerancia horizontal
            if abs(prod_x - precio_x) > 400:
                continue

            # Solo productos ARRIBA del precio (diff_y positivo)
            diff_y = precio_y - prod_y
            if 0 < diff_y < menor_dist:
                menor_dist = diff_y
                mejor = prod

        return mejor

    def _buscar_precio_anterior(self, precio: dict, precios_ant: list) -> Optional[float]:
        """
        Busca el precio anterior más cercano por distancia euclidiana (≤ 300px).

        Returns:
            Valor float del precio anterior, o None si no hay ninguno cercano.
        """
        if not precios_ant:
            return None

        precio_x = precio.get("bbox", {}).get("x", 0)
        precio_y = precio.get("bbox", {}).get("y", 0)

        mejor_valor = None
        menor_dist  = float("inf")

        for pa in precios_ant:
            pa_bbox = pa.get("bbox", {})
            pa_x    = pa_bbox.get("x", 0)
            pa_y    = pa_bbox.get("y", 0)

            dist = math.sqrt((precio_x - pa_x) ** 2 + (precio_y - pa_y) ** 2)

            if dist < menor_dist and dist <= 300:
                menor_dist  = dist
                mejor_valor = pa.get("valor")

        return mejor_valor

    # ------------------ Upserts ------------------

    def _upsert_tienda(
        self,
        session: Session,
        slug: str,
        nombre: str,
        fuente: str,
        fuente_slug: str,
    ) -> Tienda:
        tienda = session.query(Tienda).filter_by(slug=slug).first()
        if not tienda:
            tienda = Tienda(
                nombre      = nombre,
                slug        = slug,
                fuente_slug = fuente_slug,
                activa      = True,
            )
            session.add(tienda)
            session.flush()
            logger.info(f"[Load] Nueva tienda: {nombre} (slug={slug})")
        return tienda

    def _upsert_folleto(
        self,
        session: Session,
        tienda: Tienda,
        folleto_id_fuente: str,
        fuente: str,
        meta: dict,
    ) -> Folleto:
        folleto = session.query(Folleto).filter_by(
            fuente=fuente,
            folleto_id_fuente=folleto_id_fuente,
        ).first()

        if not folleto:
            folleto = Folleto(
                tienda_id         = tienda.id,
                folleto_id_fuente = folleto_id_fuente,
                fuente            = fuente,
                titulo            = meta.get("titulo"),
                fecha_inicio      = self._parsear_fecha(meta.get("fecha_inicio")),
                fecha_fin         = self._parsear_fecha(meta.get("fecha_fin")),
                url_origen        = meta.get("url_origen"),
                perfil_ocr        = meta.get("perfil_ocr"),
                motor_ocr         = meta.get("motor_ocr", "easyocr"),
                scrapeado_at      = self._parsear_datetime(meta.get("scrapeado_at")),
                estado            = "done",
            )
            session.add(folleto)
            session.flush()
            logger.info(f"[Load] Nuevo folleto: {folleto_id_fuente}")
        return folleto

    def _upsert_pagina(
        self,
        session: Session,
        folleto: Folleto,
        numero_pagina: int,
        nombre_archivo: str,
    ) -> Pagina:
        pagina = session.query(Pagina).filter_by(
            folleto_id    = folleto.id,
            numero_pagina = numero_pagina,
        ).first()

        if not pagina:
            pagina = Pagina(
                folleto_id     = folleto.id,
                numero_pagina  = numero_pagina,
                archivo_imagen = nombre_archivo,
            )
            session.add(pagina)
            session.flush()
        return pagina

    def _upsert_evento_promo(
        self,
        session: Session,
        folleto: Folleto,
        tienda: Tienda,
        nombre_evento: str,
        texto_raw: str,
    ) -> EventoPromo | None:
        """Inserta el evento si no existe ya para este folleto."""
        existente = session.query(EventoPromo).filter_by(
            folleto_id    = folleto.id,
            nombre_evento = nombre_evento,
        ).first()

        if existente:
            return None

        ev = EventoPromo(
            folleto_id    = folleto.id,
            tienda_id     = tienda.id,
            nombre_evento = nombre_evento,
            texto_raw     = texto_raw,
            fecha_inicio  = folleto.fecha_inicio,
            fecha_fin     = folleto.fecha_fin,
        )
        session.add(ev)
        session.flush()
        return ev

    # ------------------ Utilidades ------------------

    def _corregir_tienda(self, fuente: str, slug_raw: str) -> tuple[str, str]:
        """
        Aplica la tabla de corrección de slugs erróneos del scraper.
        Si no hay corrección, genera el nombre desde el slug.
        """
        if (fuente, slug_raw) in CORRECCION_TIENDAS:
            slug_correcto, nombre = CORRECCION_TIENDAS[(fuente, slug_raw)]
            logger.info(
                f"[Load] Corrección tienda: '{slug_raw}' → '{slug_correcto}'"
            )
            return slug_correcto, nombre

        nombre = slug_raw.replace("_", " ").title()
        return slug_raw, nombre

    def _texto_normalizado(self, producto: dict | None) -> str:
        """
        Extrae el mejor texto disponible de un producto.
        Prioriza nombre_canonico del normalizador si existe y no fue descartado.
        """
        if not producto:
            return ""

        norm = producto.get("norm", {})
        if norm and not norm.get("descartado", False):
            nombre = norm.get("nombre_canonico", "")
            if nombre:
                return nombre

        return producto.get("texto", "")

    def _normalizar_nombre_evento(self, texto: str) -> str:
        """
        Convierte texto OCR de evento promo en slug normalizado.
        Ej: "Julio Regalado 2025" → "julio_regalado"
        """
        texto = texto.lower().strip()
        # Quitar año al final
        texto = re.sub(r"\s*\d{4}$", "", texto)
        # Quitar caracteres no alfanuméricos excepto espacios
        texto = re.sub(r"[^a-záéíóúüñ\s]", "", texto)
        # Espacios → guión bajo
        texto = re.sub(r"\s+", "_", texto.strip())
        return texto[:100]

    def _parsear_fecha(self, fecha_str: str | None) -> Optional[date]:
        if not fecha_str:
            return None
        try:
            return datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def _parsear_datetime(self, dt_str: str | None) -> Optional[datetime]:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None

    def _extraer_numero_pagina(self, nombre_archivo: str) -> int:
        """'pagina_003.webp' → 3"""
        match = re.search(r"(\d+)", nombre_archivo)
        return int(match.group(1)) if match else 0

    def _ya_cargado(self, ruta_nlp: Path) -> bool:
        """
        Verifica si el folleto de este JSON ya existe en BD.
        Lee fuente y folleto_id del JSON sin cargar todo.
        """
        try:
            with open(ruta_nlp, encoding="utf-8") as f:
                data = json.load(f)
            fuente     = data.get("fuente", "")
            folleto_id = data.get("folleto_id", "")
            if not fuente or not folleto_id:
                return False
            with Session(self.engine) as session:
                existe = session.query(Folleto).filter_by(
                    fuente=fuente,
                    folleto_id_fuente=folleto_id,
                ).first()
                return existe is not None
        except Exception:
            return False

    def _leer_metadata(self, carpeta: Path) -> dict:
        """
        Busca metadata del folleto en folletos_procesados.json de la carpeta padre.
        Si no existe, retorna dict vacío.
        """
        # El scraper guarda folletos_procesados.json un nivel arriba de la carpeta del folleto
        for candidato in [
            carpeta.parent / "folletos_procesados.json",
            carpeta / "metadata.json",
        ]:
            if candidato.exists():
                try:
                    with open(candidato, encoding="utf-8") as f:
                        data = json.load(f)
                    folleto_id = carpeta.name
                    # folletos_procesados.json es una lista de dicts
                    if isinstance(data, list):
                        for item in data:
                            if item.get("folleto_id") == folleto_id:
                                return item
                    elif isinstance(data, dict):
                        return data
                except Exception:
                    pass
        return {}

    # ------------------ Consultas de verificación ------------------

    def resumen_bd(self) -> dict:
        """Estado actual de la BD — útil para validación post-carga."""
        from sqlalchemy import text
        tablas = ["tiendas", "folletos", "paginas", "extracciones", "eventos_promo", "alertas"]
        resultado = {}
        with Session(self.engine) as session:
            for tabla in tablas:
                try:
                    count = session.execute(text(f"SELECT COUNT(*) FROM {tabla}")).scalar()
                    resultado[tabla] = count
                except Exception:
                    resultado[tabla] = None
        return resultado
