# Carga y visualización experimental de SQLite

import sys
import re
import json
import logging
import sqlite3
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Logging
Path("data").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("sqlite_exp")


# -------------------- Importar modelos del db_builder --------------------
sys.path.insert(0, str(Path(__file__).parent))
try:
    from load.db_builder import (
        get_engine, crear_tablas, verificar_tablas,
        Tienda, Folleto, Pagina, Extraccion, EventoPromo,
        TIPOS_EXTRACCION, FUENTES,
    )
except ImportError:
    logger.error("No se encontró etl/db_builder.py")
    logger.error("Asegúrate de que el archivo existe en etl/db_builder.py")
    sys.exit(1)

# -------------------- Config --------------------
DB_PATH        = Path("data/pricescraper.db")
DATA_PROCESSED = Path("data/processed")



# ------------------- Cargador SQLite -------------------

#  Lee nlp_resultado.json y carga en SQLite
class CargadorSQLite:
    def __init__(self):
        self.engine = None

    # ------------------- Init -------------------

    def crear_bd(self) -> bool:
        try:
            self.engine = get_engine(DB_PATH)
            crear_tablas(self.engine)
            return True
        except Exception as e:
            logger.error(f"[BD] Error: {e}")
            return False

    def _check(self) -> bool:
        if not self.engine:
            logger.error("[BD] ⚠️  BD no inicializada. Usa opción 1 primero.")
            return False
        return True

    # ------------------- Descubrimiento -------------------

    def listar_nlp(self, raiz: Path = DATA_PROCESSED) -> list[Path]:
        return sorted(raiz.rglob("nlp_resultado.json"))

    def listar_subcarpetas(self) -> list[Path]:
        if not DATA_PROCESSED.exists():
            return []
        return sorted([p for p in DATA_PROCESSED.iterdir() if p.is_dir()])

    # ------------------- Carga principal -------------------

    def cargar_archivo(self, ruta_nlp: Path) -> dict:
        """
        Carga un nlp_resultado.json completo en la BD.

        Genera extracciones por cada entidad NLP (PRODUCTO, PRECIO,
        PRECIO_ANTERIOR, AHORRO, PROMO, ATRIBUTO, EVENTO_PROMO).
        Asocia producto→precio por bbox para rellenar valor_anterior
        en la extracción de tipo PRECIO.
        """
        with open(ruta_nlp, encoding="utf-8") as f:
            data = json.load(f)

        fuente     = data.get("fuente", "tiendeo")
        slug_raw   = data.get("tienda", "")
        folleto_id = data.get("folleto_id", "")

        contadores = {t: 0 for t in TIPOS_EXTRACCION}
        contadores["eventos"] = 0

        with Session(self.engine) as session:
            tienda  = self._upsert_tienda(session, slug_raw, fuente)
            folleto = self._upsert_folleto(session, tienda, folleto_id, fuente, data)

            for pag_data in data.get("paginas", []):
                nombre_img = pag_data.get("pagina", "")
                num_pag    = self._num_pagina(nombre_img)

                # Métricas NLP de la página
                pagina = self._upsert_pagina(
                    session, folleto, num_pag, nombre_img, pag_data
                )

                productos    = pag_data.get("productos", [])
                precios      = pag_data.get("precios", [])
                precios_ant  = pag_data.get("precios_anteriores", [])
                ahorros      = pag_data.get("ahorros", [])
                promos       = pag_data.get("promos", [])
                eventos      = pag_data.get("eventos_promo", [])
                atributos    = pag_data.get("atributos", [])

                # Insertar productos
                for p in productos:
                    session.add(self._hacer_extraccion(
                        pagina, folleto, tienda, "PRODUCTO", p
                    ))
                    contadores["PRODUCTO"] += 1

                # Insertar precios — con asociación bbox a precio_anterior
                for p in precios:
                    valor_ant = self._precio_anterior_bbox(p, precios_ant)
                    ext = self._hacer_extraccion(
                        pagina, folleto, tienda, "PRECIO", p
                    )
                    ext.valor_anterior = valor_ant
                    session.add(ext)
                    contadores["PRECIO"] += 1

                # Insertar precios anteriores
                for p in precios_ant:
                    session.add(self._hacer_extraccion(
                        pagina, folleto, tienda, "PRECIO_ANTERIOR", p
                    ))
                    contadores["PRECIO_ANTERIOR"] += 1

                # Insertar ahorros
                for p in ahorros:
                    session.add(self._hacer_extraccion(
                        pagina, folleto, tienda, "AHORRO", p
                    ))
                    contadores["AHORRO"] += 1

                # Insertar promos
                for p in promos:
                    session.add(self._hacer_extraccion(
                        pagina, folleto, tienda, "PROMO", p
                    ))
                    contadores["PROMO"] += 1

                # Insertar atributos
                for p in atributos:
                    session.add(self._hacer_extraccion(
                        pagina, folleto, tienda, "ATRIBUTO", p
                    ))
                    contadores["ATRIBUTO"] += 1

                # Insertar eventos promo como EventoPromo
                for ev in eventos:
                    nombre_ev = self._normalizar_evento(ev.get("texto", ""))
                    existing = session.query(EventoPromo).filter_by(
                        folleto_id=folleto.id, nombre_evento=nombre_ev
                    ).first()
                    if not existing:
                        session.add(EventoPromo(
                            folleto_id    = folleto.id,
                            tienda_id     = tienda.id,
                            nombre_evento = nombre_ev,
                            texto_raw     = ev.get("texto", ""),
                            fecha_inicio  = folleto.fecha_inicio,
                            fecha_fin     = folleto.fecha_fin,
                        ))
                        contadores["eventos"] += 1

            session.commit()

        return {
            "fuente":     fuente,
            "tienda":     slug_raw,
            "folleto_id": folleto_id,
            "contadores": contadores,
        }

    def cargar_lote(self, archivos: list[Path]) -> dict:
        totales = {t: 0 for t in TIPOS_EXTRACCION}
        totales["eventos"] = 0
        ok = err = 0

        for i, archivo in enumerate(archivos, 1):
            try:
                ruta_rel = archivo.relative_to(DATA_PROCESSED) \
                           if DATA_PROCESSED in archivo.parents else archivo
            except ValueError:
                ruta_rel = archivo

            logger.info(f"[{i}/{len(archivos)}] {ruta_rel}")
            try:
                r = self.cargar_archivo(archivo)
                ok += 1
                c = r["contadores"]
                for k, v in c.items():
                    totales[k] = totales.get(k, 0) + v
                logger.info(
                    f"  ✅ prod:{c['PRODUCTO']} prec:{c['PRECIO']} "
                    f"pant:{c['PRECIO_ANTERIOR']} ahor:{c['AHORRO']} "
                    f"prmo:{c['PROMO']} evnt:{c['eventos']}"
                )
            except Exception as e:
                logger.error(f"  ❌ Error: {e}")
                err += 1

        return {"cargados": ok, "errores": err, "totales": totales}

    # ── Upserts ───────────────────────────────────────────────────────────────

    def _upsert_tienda(self, session, slug_raw: str, fuente: str) -> Tienda:
        # Corrección conocida: soriana aparece como 'walmart' en el campo tienda
        slug = slug_raw.strip().lower().replace(" ", "_").replace("-", "_")
        t = session.query(Tienda).filter_by(slug=slug).first()
        if not t:
            nombre = slug_raw.replace("_", " ").title()
            t = Tienda(nombre=nombre, slug=slug,
                       fuente_slug=slug_raw, activa=True)
            session.add(t)
            session.flush()
            logger.info(f"  Nueva tienda: '{t.nombre}'")
        return t

    def _upsert_folleto(self, session, tienda, folleto_id,
                        fuente, data) -> Folleto:
        f = session.query(Folleto).filter_by(
            fuente=fuente, folleto_id_fuente=folleto_id
        ).first()
        if not f:
            fuente_val = fuente if fuente in FUENTES else "tiendeo"
            f = Folleto(
                tienda_id         = tienda.id,
                folleto_id_fuente = folleto_id,
                fuente            = fuente_val,
                total_paginas     = data.get("total_paginas", 0),
                perfil_ocr        = data.get("perfil_imagen", "color_normal"),
                motor_ocr         = data.get("motor_ocr", "easyocr"),
                estado            = "done",
                scrapeado_at      = datetime.utcnow(),
            )
            session.add(f)
            session.flush()
            logger.info(f"  Nuevo folleto: {fuente}:{folleto_id}")
        return f

    def _upsert_pagina(self, session, folleto, num_pag,
                       nombre_img, pag_data) -> Pagina:
        p = session.query(Pagina).filter_by(
            folleto_id=folleto.id, numero_pagina=num_pag
        ).first()
        if not p:
            r = pag_data.get("resumen_pagina", {})
            p = Pagina(
                folleto_id        = folleto.id,
                numero_pagina     = num_pag,
                archivo_imagen    = nombre_img,
                total_productos   = len(pag_data.get("productos", [])),
                total_precios     = len(pag_data.get("precios", [])),
                total_promos      = len(pag_data.get("promos", [])),
                total_atributos   = len(pag_data.get("atributos", [])),
                procesado_at      = datetime.utcnow(),
            )
            session.add(p)
            session.flush()
        return p

    # ── Construcción de extracciones ──────────────────────────────────────────

    def _hacer_extraccion(self, pagina, folleto, tienda,
                          tipo: str, bloque: dict) -> Extraccion:
        bbox  = bloque.get("bbox", {})
        texto = bloque.get("texto", bloque.get("texto_norm", ""))
        return Extraccion(
            pagina_id     = pagina.id,
            folleto_id    = folleto.id,
            tienda_id     = tienda.id,
            tipo          = tipo,
            texto_raw     = texto,
            texto_norm    = self._limpiar(texto),
            categoria_nlp = bloque.get("categoria", ""),
            valor         = bloque.get("valor"),
            confianza_ocr = bloque.get("confianza"),
            bbox_x        = bbox.get("x"),
            bbox_y        = bbox.get("y"),
            bbox_ancho    = bbox.get("ancho"),
            bbox_alto     = bbox.get("alto"),
        )

    # ── Asociación bbox precio → precio_anterior ──────────────────────────────

    def _precio_anterior_bbox(self, precio: dict,
                               precios_ant: list) -> Optional[float]:
        """
        Busca el precio anterior más cercano espacialmente al precio actual.
        Distancia máxima: 300px. Heredado del módulo original.
        """
        if not precios_ant:
            return None
        px = precio.get("bbox", {}).get("x", 0)
        py = precio.get("bbox", {}).get("y", 0)
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
    def _limpiar(texto: str) -> str:
        if not texto:
            return ""
        texto = re.sub(r"[%@€£¥°©®™]", "", texto)
        texto = re.sub(r"\s+", " ", texto).strip()
        return texto[:1].upper() + texto[1:] if texto else ""

    @staticmethod
    def _num_pagina(nombre: str) -> int:
        m = re.search(r"(\d+)", nombre)
        return int(m.group(1)) if m else 0

    @staticmethod
    def _normalizar_evento(texto: str) -> str:
        """Convierte texto OCR de evento a slug normalizado."""
        t = texto.lower().strip()
        t = re.sub(r"[^a-záéíóúñ\s]", "", t)
        t = re.sub(r"\s+", "_", t.strip())
        # Normalizar variantes OCR conocidas
        if "julio" in t and ("regalad" in t or "regalo" in t):
            return "julio_regalado"
        if "hot" in t and "sale" in t:
            return "hot_sale"
        if "buen" in t and "fin" in t:
            return "buen_fin"
        return t[:100]

    def resumen(self) -> dict:
        if not self._check():
            return {}
        return verificar_tablas(self.engine)

    def limpiar(self):
        if not self._check():
            return
        with Session(self.engine) as s:
            s.query(EventoPromo).delete()
            s.query(Extraccion).delete()
            s.query(Pagina).delete()
            s.query(Folleto).delete()
            s.query(Tienda).delete()
            s.commit()
        logger.info("[BD] 🧹 Datos eliminados (esquema conservado).")


# ─────────────────────────────────────────────────────────────────────────────
# Vistas pandas
# ─────────────────────────────────────────────────────────────────────────────

def _con() -> Optional[sqlite3.Connection]:
    if not DB_PATH.exists():
        print(f"\n  ⚠️  No existe la BD en {DB_PATH}")
        print("     Usa opción 1 para crearla.")
        return None
    return sqlite3.connect(DB_PATH)


def vista_precios():
    """Precios con contexto de tienda, folleto y vigencia — query central de BI."""
    con = _con()
    if not con:
        return
    sep = "─" * 70

    # Resumen por tabla
    print(f"\n{sep}\n  Registros en BD:\n{sep}")
    for tabla in ["tiendas", "folletos", "paginas", "extracciones",
                  "eventos_promo", "alertas"]:
        try:
            n = pd.read_sql(
                f"SELECT COUNT(*) AS total FROM {tabla}", con
            ).iloc[0, 0]
            print(f"  {tabla:<18}: {n:>7,} registros")
        except Exception:
            print(f"  {tabla:<18}: (no existe)")

    # Precios con vigencia — vista principal para BI
    print(f"\n{sep}\n  Precios con vigencia (últimos 25):\n{sep}")
    try:
        df = pd.read_sql("""
            SELECT
                t.nombre                    AS tienda,
                f.folleto_id_fuente         AS folleto,
                f.fecha_inicio,
                f.fecha_fin,
                p.numero_pagina             AS pag,
                e.texto_norm                AS texto,
                e.valor                     AS precio,
                e.valor_anterior            AS antes,
                ROUND(e.valor_anterior - e.valor, 2)
                                            AS descuento,
                e.confianza_ocr             AS conf
            FROM extracciones e
            JOIN tiendas  t ON t.id = e.tienda_id
            JOIN folletos f ON f.id = e.folleto_id
            JOIN paginas  p ON p.id = e.pagina_id
            WHERE e.tipo = 'PRECIO'
              AND e.valor IS NOT NULL
            ORDER BY e.id DESC
            LIMIT 25
        """, con)

        if df.empty:
            print("  (sin precios cargados)")
        else:
            pd.set_option("display.max_columns", None)
            pd.set_option("display.width", 120)
            pd.set_option("display.max_colwidth", 28)
            pd.set_option("display.float_format", lambda x: f"{x:.2f}")
            print(df.to_string(index=False))

        total = pd.read_sql(
            "SELECT COUNT(*) FROM extracciones WHERE tipo='PRECIO'", con
        ).iloc[0, 0]
        if total > 25:
            print(f"\n  ... ({total - 25:,} precios más)")
    except Exception as e:
        print(f"  Error: {e}")

    # Resumen por tienda
    print(f"\n{sep}\n  Resumen por tienda:\n{sep}")
    try:
        df_t = pd.read_sql("""
            SELECT
                t.nombre,
                COUNT(CASE WHEN e.tipo='PRECIO'          THEN 1 END) AS precios,
                COUNT(CASE WHEN e.tipo='PRECIO_ANTERIOR' THEN 1 END) AS p_anterior,
                COUNT(CASE WHEN e.tipo='AHORRO'          THEN 1 END) AS ahorros,
                COUNT(CASE WHEN e.tipo='PRODUCTO'        THEN 1 END) AS productos,
                COUNT(CASE WHEN e.tipo='PROMO'           THEN 1 END) AS promos,
                ROUND(AVG(CASE WHEN e.tipo='PRECIO'
                               THEN e.valor END), 2)     AS precio_prom,
                MIN(CASE WHEN e.tipo='PRECIO'
                         THEN e.valor END)               AS precio_min,
                MAX(CASE WHEN e.tipo='PRECIO'
                         THEN e.valor END)               AS precio_max
            FROM extracciones e
            JOIN tiendas t ON t.id = e.tienda_id
            GROUP BY t.nombre
            ORDER BY precios DESC
        """, con)
        if df_t.empty:
            print("  (sin datos)")
        else:
            print(df_t.to_string(index=False))
    except Exception as e:
        print(f"  Error: {e}")

    print(f"{sep}\n")
    con.close()


def vista_extracciones():
    """Todas las extracciones agrupadas por tipo — útil para verificar calidad NLP."""
    con = _con()
    if not con:
        return
    sep = "─" * 70

    print(f"\n{sep}\n  Extracciones por tipo:\n{sep}")
    try:
        df = pd.read_sql("""
            SELECT
                e.tipo,
                t.nombre                AS tienda,
                e.texto_norm            AS texto,
                e.valor,
                e.valor_anterior,
                e.confianza_ocr         AS conf,
                p.numero_pagina         AS pag
            FROM extracciones e
            JOIN tiendas  t ON t.id = e.tienda_id
            JOIN paginas  p ON p.id = e.pagina_id
            ORDER BY e.tipo, t.nombre, p.numero_pagina
            LIMIT 60
        """, con)
        if df.empty:
            print("  (sin extracciones)")
        else:
            pd.set_option("display.max_colwidth", 35)
            pd.set_option("display.width", 130)
            print(df.to_string(index=False))
    except Exception as e:
        print(f"  Error: {e}")

    print(f"{sep}\n")
    con.close()


def vista_eventos():
    """Eventos promocionales detectados — para análisis temporal en BI."""
    con = _con()
    if not con:
        return
    sep = "─" * 70

    print(f"\n{sep}\n  Eventos promocionales:\n{sep}")
    try:
        df = pd.read_sql("""
            SELECT
                t.nombre        AS tienda,
                ev.nombre_evento,
                ev.texto_raw,
                ev.fecha_inicio,
                ev.fecha_fin
            FROM eventos_promo ev
            JOIN tiendas t ON t.id = ev.tienda_id
            ORDER BY ev.fecha_inicio DESC
        """, con)
        if df.empty:
            print("  (sin eventos detectados)")
        else:
            print(df.to_string(index=False))
    except Exception as e:
        print(f"  Error: {e}")

    print(f"{sep}\n")
    con.close()


# ─────────────────────────────────────────────────────────────────────────────
# Menús
# ─────────────────────────────────────────────────────────────────────────────

def menu_principal() -> int:
    existe = "✅" if DB_PATH.exists() else "❌ no existe"
    print("\n" + "═" * 65)
    print("   PriceScraper MX — SQLite Experimental")
    print(f"   BD: {DB_PATH}  [{existe}]")
    print("═" * 65)
    print("   1 → Crear BD y tablas")
    print("   2 → Cargar TODOS los nlp_resultado.json")
    print("   3 → Cargar carpeta específica")
    print("   4 → Vista rápida — precios con vigencia")
    print("   5 → Vista detallada — extracciones por tipo")
    print("   6 → Vista eventos promo")
    print("   7 → Limpiar todos los datos (conserva esquema)")
    print("   0 → Salir")
    print("─" * 65)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_carpeta(cargador: CargadorSQLite):
    subcarpetas = cargador.listar_subcarpetas()
    if not subcarpetas:
        logger.error(f"No se encontraron carpetas en {DATA_PROCESSED}")
        return

    print(f"\n{'─'*65}")
    print("   Carpetas disponibles en data/processed/:")
    print(f"{'─'*65}")
    for i, c in enumerate(subcarpetas, 1):
        n = len(list(c.rglob("nlp_resultado.json")))
        print(f"   {i:>3}. {c.name:<38} ({n} archivos nlp)")
    print(f"{'─'*65}")

    try:
        idx = int(input("\n   Número de carpeta: ").strip())
        if not (1 <= idx <= len(subcarpetas)):
            print("  ⚠️  Número fuera de rango.")
            return
    except ValueError:
        print("  ⚠️  Entrada inválida.")
        return

    archivos = cargador.listar_nlp(subcarpetas[idx - 1])
    if not archivos:
        logger.warning("No hay nlp_resultado.json en esa carpeta.")
        return

    print(f"\n  Se cargarán {len(archivos)} archivo(s):")
    for a in archivos:
        print(f"    · {a.relative_to(DATA_PROCESSED)}")

    if input("\n  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    _print_resumen_lote(cargador.cargar_lote(archivos))


def _print_resumen_lote(r: dict):
    t = r.get("totales", {})
    print(f"\n{'─'*65}")
    print(f"  ✅ Lote completado")
    print(f"     Folletos cargados:    {r['cargados']}")
    print(f"     Errores:              {r['errores']}")
    print(f"     Productos:            {t.get('PRODUCTO', 0):>6}")
    print(f"     Precios actuales:     {t.get('PRECIO', 0):>6}")
    print(f"     Precios anteriores:   {t.get('PRECIO_ANTERIOR', 0):>6}")
    print(f"     Ahorros:              {t.get('AHORRO', 0):>6}")
    print(f"     Promos:               {t.get('PROMO', 0):>6}")
    print(f"     Eventos promo:        {t.get('eventos', 0):>6}")
    print(f"     Atributos:            {t.get('ATRIBUTO', 0):>6}")
    print(f"{'─'*65}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 65)
    logger.info("PriceScraper MX — SQLite Experimental")
    logger.info(f"BD: {DB_PATH}")
    logger.info("=" * 65)

    cargador = CargadorSQLite()

    if DB_PATH.exists():
        cargador.crear_bd()

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  👋 Saliendo...\n")
            break

        elif opcion == 1:
            cargador.crear_bd()
            r = cargador.resumen()
            if r:
                print(f"\n  Estado → " +
                      " | ".join(f"{k}: {v}" for k, v in r.items()))

        elif opcion == 2:
            if not cargador._check():
                continue
            archivos = cargador.listar_nlp()
            if not archivos:
                logger.warning(f"No hay nlp_resultado.json en {DATA_PROCESSED}")
                continue
            print(f"\n  Archivos encontrados: {len(archivos)}")
            for a in archivos:
                try:
                    print(f"    · {a.relative_to(DATA_PROCESSED)}")
                except ValueError:
                    print(f"    · {a}")
            if input("\n  ¿Cargar todos? (s/n): ").strip().lower() != "s":
                continue
            _print_resumen_lote(cargador.cargar_lote(archivos))

        elif opcion == 3:
            if not cargador._check():
                continue
            menu_carpeta(cargador)

        elif opcion == 4:
            vista_precios()

        elif opcion == 5:
            vista_extracciones()

        elif opcion == 6:
            vista_eventos()

        elif opcion == 7:
            r = cargador.resumen()
            if not r:
                continue
            total = sum(v or 0 for v in r.values())
            print(f"  Se eliminarán {total:,} registros en total.")
            if input("  ¿Confirmar? (s/n): ").strip().lower() == "s":
                cargador.limpiar()
            else:
                print("  Cancelado.")

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