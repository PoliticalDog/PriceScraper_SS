"""
load/load.py
PriceScraper MX - Modulo de carga ETL (NLP -> PostgreSQL)

Lee nlp_resultado.json, asocia productos-precios por proximidad bbox
e inserta en PostgreSQL usando psycopg v3.
"""

import json
import logging
import math
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from vision.preprocessor import obtener_preprocesador
from vision.region_detector import detectar_regiones, calificar_regiones, asociar_producto_por_region

from .db_builder import get_connection, get_cursor

logger = logging.getLogger(__name__)

DATA_PROCESSED = Path("data/processed")
DATA_RAW = Path("data/raw")
RUTA_REGISTRO_SCRAPER = Path("data/folletos_procesados.json")

CORRECCION_TIENDAS: dict[tuple[str, str], tuple[str, str]] = {
    ("tiendeo", "walmart"): ("soriana", "Soriana"),
}

# Tiendas donde el benchmark hibrido (sources/vision/06_hibrido_roi_asociacion_producto_precio.md)
# confirmo mejora real sin regresion: usa el slug CRUDO de scraping (tal como
# aparece en data/raw/<fuente>/<slug>/), no el slug corregido de CORRECCION_TIENDAS.
# NO agregar tiendas aqui sin correr antes probar_hibrido_roi.py -- fuera de
# estas 4, ROI no detecta suficientes regiones confiables para ser util
# (ver sources/vision/05_benchmark_roi_deteccion_regiones.md).
TIENDAS_ROI_HIBRIDO = {"walmart", "chedraui", "soriana_hiper", "soriana_mercado"}

_preprocesador_roi = None


def _obtener_preprocesador_roi():
    global _preprocesador_roi
    if _preprocesador_roi is None:
        _preprocesador_roi = obtener_preprocesador("color_normal")
    return _preprocesador_roi


class Loader:
    """
    Carga nlp_resultado.json en PostgreSQL.
    Uso recomendado como context manager:

        with Loader() as loader:
            loader.cargar_folleto(ruta)
    """

    def __init__(self):
        self.conn = get_connection()
        logger.info("[Load] Loader inicializado")

    @classmethod
    def desde_conexion(cls, conn) -> "Loader":
        instance = cls.__new__(cls)
        instance.conn = conn
        return instance

    def cerrar(self):
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("[Load] Conexion cerrada")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # -- API publica ----------------------------------------------------------

    def cargar_folleto(self, ruta_nlp: Path, metadata: dict | None = None) -> dict:
        ruta_nlp = Path(ruta_nlp)
        if not ruta_nlp.exists():
            raise FileNotFoundError(f"[Load] No existe: {ruta_nlp}")

        with open(ruta_nlp, encoding="utf-8") as f:
            nlp = json.load(f)

        fuente     = nlp.get("fuente", "")
        slug_raw   = nlp.get("tienda", "")
        folleto_id = nlp.get("folleto_id", "")
        meta       = metadata or self._leer_metadata(fuente, folleto_id)
        slug, nombre_tienda = self._corregir_tienda(fuente, slug_raw)

        logger.info(f"[Load] -- {fuente}/{slug}/{folleto_id} --")

        resumen = {
            "fuente": fuente, "tienda": slug, "folleto_id": folleto_id,
            "extracciones_insertadas": 0, "precios_sin_producto": 0,
            "eventos_insertados": 0, "paginas_procesadas": 0, "errores": 0,
        }

        try:
            with get_cursor(self.conn) as cur:
                tienda_id     = self._upsert_tienda(cur, slug, nombre_tienda, slug_raw)
                folleto_id_bd = self._upsert_folleto(cur, tienda_id, folleto_id, fuente, meta)

                for pag_data in nlp.get("paginas", []):
                    try:
                        regiones_confiables = self._detectar_regiones_pagina(fuente, slug_raw, folleto_id, pag_data)
                        r = self._procesar_pagina(cur, tienda_id, folleto_id_bd, pag_data, regiones_confiables)
                        resumen["extracciones_insertadas"] += r["extracciones"]
                        resumen["precios_sin_producto"]    += r["sin_producto"]
                        resumen["eventos_insertados"]      += r["eventos"]
                        resumen["paginas_procesadas"]      += 1
                    except Exception as e:
                        logger.error(f"[Load] Error en pagina {pag_data.get('pagina','?')}: {e}")
                        resumen["errores"] += 1

        except Exception as e:
            logger.error(f"[Load] Error cargando {folleto_id}: {e}")
            raise

        logger.info(
            f"[Load] OK {folleto_id} -> "
            f"{resumen['extracciones_insertadas']} extracciones | "
            f"{resumen['precios_sin_producto']} sin producto | "
            f"{resumen['eventos_insertados']} eventos"
        )
        return resumen

    def cargar_batch(self, data_processed: Path = DATA_PROCESSED, forzar: bool = False) -> dict:
        data_processed = Path(data_processed)
        rutas = sorted(data_processed.rglob("nlp_resultado.json"))

        if not rutas:
            logger.warning(f"[Load] Sin nlp_resultado.json en {data_processed}")
            return {}

        logger.info(f"[Load] {len(rutas)} folletos encontrados")
        totales = {"procesados": 0, "omitidos": 0, "errores": 0,
                   "extracciones_total": 0, "eventos_total": 0}

        for i, ruta in enumerate(rutas, 1):
            ruta_rel = ruta.parent.relative_to(data_processed)

            if not forzar and self._ya_cargado(ruta):
                logger.info(f"[Load] [{i}/{len(rutas)}] Ya cargado: {ruta_rel}")
                totales["omitidos"] += 1
                continue

            logger.info(f"[Load] [{i}/{len(rutas)}] {ruta_rel}")
            try:
                r = self.cargar_folleto(ruta)
                totales["procesados"]         += 1
                totales["extracciones_total"] += r["extracciones_insertadas"]
                totales["eventos_total"]      += r["eventos_insertados"]
            except Exception as e:
                logger.error(f"[Load] Error en {ruta_rel}: {e}")
                totales["errores"] += 1

        logger.info(
            f"[Load] Batch completo: "
            f"procesados={totales['procesados']} "
            f"omitidos={totales['omitidos']} "
            f"errores={totales['errores']} | "
            f"extracciones={totales['extracciones_total']} "
            f"eventos={totales['eventos_total']}"
        )
        return totales

    # -- Procesamiento de pagina ----------------------------------------------

    def _detectar_regiones_pagina(self, fuente: str, slug_raw: str, folleto_id: str, pag_data: dict) -> list[dict] | None:
        """
        Corre deteccion ROI solo para las tiendas grid-friendly validadas
        (TIENDAS_ROI_HIBRIDO). Devuelve None si la tienda no aplica, si no
        existe la imagen original, o si algo falla -- en todos esos casos el
        llamador debe hacer fallback puro al metodo de distancia (mismo
        comportamiento que antes de esta integracion).
        """
        if slug_raw not in TIENDAS_ROI_HIBRIDO:
            return None

        nombre_pag = pag_data.get("pagina", "")
        ruta_imagen = DATA_RAW / fuente / slug_raw / folleto_id / nombre_pag
        if not ruta_imagen.exists():
            return None

        try:
            imagen_proc = _obtener_preprocesador_roi().procesar(ruta_imagen)
            candidatas = detectar_regiones(imagen_proc)
            precios = pag_data.get("precios", [])
            bloques_precio = [{"texto": p.get("texto", ""), "bbox": p.get("bbox", {})} for p in precios]
            regiones = calificar_regiones(candidatas, bloques_precio)
            return [r for r in regiones if r["tiene_precio"]]
        except Exception as e:
            logger.warning(f"[Load] ROI fallo en {slug_raw}/{folleto_id}/{nombre_pag}: {e} -- fallback a distancia")
            return None

    def _procesar_pagina(self, cur, tienda_id: int, folleto_id: int, pag_data: dict,
                         regiones_confiables: list[dict] | None = None) -> dict:
        nombre_pag = pag_data.get("pagina", "")
        num_pagina = self._extraer_numero_pagina(nombre_pag)
        pagina_id  = self._upsert_pagina(cur, folleto_id, num_pagina, nombre_pag)

        productos     = pag_data.get("productos", [])
        precios       = pag_data.get("precios", [])
        precios_ant   = pag_data.get("precios_anteriores", [])
        promos        = pag_data.get("promos", [])
        eventos_promo = pag_data.get("eventos_promo", [])
        atributos     = pag_data.get("atributos", [])

        contadores = {"extracciones": 0, "sin_producto": 0, "eventos": 0}

        # Precios
        for precio in precios:
            producto_match = None
            if regiones_confiables:
                producto_match = asociar_producto_por_region(precio, productos, regiones_confiables)
            if producto_match is None:
                producto_match = self._asociar_producto(precio, productos)
            precio_ant_val = self._buscar_precio_anterior(precio, precios_ant)
            texto_norm     = self._texto_normalizado(producto_match)
            texto_raw_prod = producto_match.get("texto", "") if producto_match else ""
            bbox           = precio.get("bbox", {})

            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, categoria_nlp,
                    valor, valor_anterior, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "PRECIO",
                precio.get("texto", ""),
                texto_norm or texto_raw_prod or None,
                producto_match.get("categoria") if producto_match else None,
                precio.get("valor"), precio_ant_val, precio.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
            ))
            contadores["extracciones"] += 1
            if not texto_norm and not texto_raw_prod:
                contadores["sin_producto"] += 1

        # Promos
        for promo in promos:
            bbox = promo.get("bbox", {})
            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "PROMO", promo.get("texto", ""), promo.get("texto", ""),
                promo.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
            ))
            contadores["extracciones"] += 1

        # Eventos promo
        for evento in eventos_promo:
            texto_evento = evento.get("texto", "")
            nombre_norm  = self._normalizar_nombre_evento(texto_evento)
            bbox         = evento.get("bbox", {})

            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "EVENTO_PROMO", texto_evento, nombre_norm,
                evento.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
            ))
            contadores["extracciones"] += 1

            if self._upsert_evento_promo(cur, folleto_id, tienda_id, nombre_norm, texto_evento):
                contadores["eventos"] += 1

        # Actualizar metricas de pagina
        cur.execute("""
            UPDATE paginas SET
                total_productos = %s, total_precios = %s,
                total_promos = %s, total_atributos = %s, procesado_at = %s
            WHERE id = %s
        """, (
            len(productos), len(precios),
            len(promos) + len(eventos_promo), len(atributos),
            datetime.utcnow(), pagina_id,
        ))

        return contadores

    # -- Asociacion bbox ------------------------------------------------------

    def _asociar_producto(self, precio: dict, productos: list) -> dict | None:
        if not productos:
            return None

        precio_x = precio.get("bbox", {}).get("x", 0)
        precio_y = precio.get("bbox", {}).get("y", 0)
        mejor, menor_dist = None, float("inf")

        for prod in productos:
            prod_bbox = prod.get("bbox", {})
            prod_x    = prod_bbox.get("x", 0)
            prod_y    = prod_bbox.get("y", 0)

            if abs(prod_x - precio_x) > 400:
                continue

            diff_y = precio_y - prod_y
            if 0 < diff_y < menor_dist:
                menor_dist = diff_y
                mejor = prod

        return mejor

    def _buscar_precio_anterior(self, precio: dict, precios_ant: list) -> Optional[float]:
        if not precios_ant:
            return None

        precio_x = precio.get("bbox", {}).get("x", 0)
        precio_y = precio.get("bbox", {}).get("y", 0)
        mejor_valor, menor_dist = None, float("inf")

        for pa in precios_ant:
            pa_bbox = pa.get("bbox", {})
            dist = math.sqrt(
                (precio_x - pa_bbox.get("x", 0)) ** 2 +
                (precio_y - pa_bbox.get("y", 0)) ** 2
            )
            if dist <= 300 and dist < menor_dist:
                menor_dist  = dist
                mejor_valor = pa.get("valor")

        return mejor_valor

    # -- Upserts SQL ----------------------------------------------------------

    def _upsert_tienda(self, cur, slug: str, nombre: str, fuente_slug: str) -> int:
        cur.execute("""
            INSERT INTO tiendas (nombre, slug, fuente_slug, activa)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (slug) DO NOTHING
            RETURNING id
        """, (nombre, slug, fuente_slug))

        row = cur.fetchone()
        if row:
            logger.info(f"[Load] Nueva tienda: {nombre} (slug={slug})")
            return row["id"]

        cur.execute("SELECT id FROM tiendas WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]

    def _upsert_folleto(self, cur, tienda_id: int, folleto_id_fuente: str,
                        fuente: str, meta: dict) -> int:
        cur.execute("""
            INSERT INTO folletos (
                tienda_id, folleto_id_fuente, fuente,
                titulo, fecha_inicio, fecha_fin, url_origen,
                perfil_ocr, motor_ocr, scrapeado_at, estado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fuente, folleto_id_fuente) DO NOTHING
            RETURNING id
        """, (
            tienda_id, folleto_id_fuente, fuente,
            meta.get("titulo"),
            self._parsear_fecha(meta.get("fecha_inicio")),
            self._parsear_fecha(meta.get("fecha_fin")),
            meta.get("url_origen"),
            meta.get("perfil_ocr"),
            meta.get("motor_ocr", "easyocr"),
            self._parsear_datetime(meta.get("scrapeado_at")),
            "done",
        ))

        row = cur.fetchone()
        if row:
            logger.info(f"[Load] Nuevo folleto: {folleto_id_fuente}")
            return row["id"]

        cur.execute("""
            SELECT id FROM folletos WHERE fuente = %s AND folleto_id_fuente = %s
        """, (fuente, folleto_id_fuente))
        return cur.fetchone()["id"]

    def _upsert_pagina(self, cur, folleto_id: int, numero_pagina: int,
                       archivo_imagen: str) -> int:
        cur.execute("""
            INSERT INTO paginas (folleto_id, numero_pagina, archivo_imagen)
            VALUES (%s, %s, %s)
            ON CONFLICT (folleto_id, numero_pagina) DO NOTHING
            RETURNING id
        """, (folleto_id, numero_pagina, archivo_imagen))

        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute("""
            SELECT id FROM paginas WHERE folleto_id = %s AND numero_pagina = %s
        """, (folleto_id, numero_pagina))
        return cur.fetchone()["id"]

    def _upsert_evento_promo(self, cur, folleto_id: int, tienda_id: int,
                             nombre_evento: str, texto_raw: str) -> bool:
        cur.execute("""
            INSERT INTO eventos_promo (folleto_id, tienda_id, nombre_evento, texto_raw)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (folleto_id, nombre_evento) DO NOTHING
            RETURNING id
        """, (folleto_id, tienda_id, nombre_evento, texto_raw))
        return cur.fetchone() is not None

    # -- Utilidades -----------------------------------------------------------

    def _corregir_tienda(self, fuente: str, slug_raw: str) -> tuple[str, str]:
        if (fuente, slug_raw) in CORRECCION_TIENDAS:
            slug_correcto, nombre = CORRECCION_TIENDAS[(fuente, slug_raw)]
            logger.info(f"[Load] Correccion tienda: '{slug_raw}' -> '{slug_correcto}'")
            return slug_correcto, nombre
        return slug_raw, slug_raw.replace("_", " ").title()

    def _texto_normalizado(self, producto: dict | None) -> str:
        if not producto:
            return ""
        norm = producto.get("norm", {})
        if norm and not norm.get("descartado", False):
            nombre = norm.get("nombre_canonico", "")
            if nombre:
                return nombre
        return producto.get("texto", "")

    def _normalizar_nombre_evento(self, texto: str) -> str:
        texto = texto.lower().strip()
        texto = re.sub(r"\s*\d{4}$", "", texto)
        texto = re.sub(r"[^a-z\s]", "", texto)
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
        match = re.search(r"(\d+)", nombre_archivo)
        return int(match.group(1)) if match else 0

    def _ya_cargado(self, ruta_nlp: Path) -> bool:
        try:
            with open(ruta_nlp, encoding="utf-8") as f:
                data = json.load(f)
            fuente     = data.get("fuente", "")
            folleto_id = data.get("folleto_id", "")
            if not fuente or not folleto_id:
                return False
            with get_cursor(self.conn) as cur:
                cur.execute("""
                    SELECT 1 FROM folletos
                    WHERE fuente = %s AND folleto_id_fuente = %s
                """, (fuente, folleto_id))
                return cur.fetchone() is not None
        except Exception:
            return False

    # Lee la metadata (titulo, vigencia, url) del registro del scraper (data/folletos_procesados.json,
    # ver scraper/registro.py), keyed por "fuente:folleto_id". "procesado_at" ahi es el momento
    # del scrape (no confundir con paginas.procesado_at en la BD, que es el momento del OCR).
    def _leer_metadata(self, fuente: str, folleto_id: str) -> dict:
        if not RUTA_REGISTRO_SCRAPER.exists():
            return {}
        try:
            with open(RUTA_REGISTRO_SCRAPER, encoding="utf-8") as f:
                registro = json.load(f)
        except Exception:
            return {}

        entrada = registro.get(f"{fuente}:{folleto_id}")
        if not entrada:
            return {}

        return {
            "titulo":       entrada.get("titulo"),
            "fecha_inicio": entrada.get("fecha_inicio"),
            "fecha_fin":    entrada.get("fecha_fin"),
            "scrapeado_at": entrada.get("procesado_at"),
            "url_origen":   entrada.get("url_folleto"),
        }