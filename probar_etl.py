"""
probar_etl.py
Orquestador del módulo ETL — Carga de datos a PostgreSQL/SQLite.
PriceScraper MX

Lee los nlp_resultado.json de data/processed/ y los carga
en la base de datos usando el Transformer.

Uso: python probar_etl.py

Menú:
  1 → Cargar un folleto específico   (modo prueba)
  2 → Cargar todos los pendientes    (modo batch)
  3 → Ver resumen de la BD
  0 → Salir
"""

import sys
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))
file_handler = RotatingFileHandler(
    "logs/etl.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("etl")

sys.path.insert(0, str(Path(__file__).parent))

from etl.transformer import Transformer

DATA_PROCESSED    = Path("data/processed")
FOLLETOS_REGISTRO = Path("data/folletos_procesados.json")

# ── Configuración de BD ───────────────────────────────────────────────────────
# Cambiar a PostgreSQL cuando esté instalado:
# DB_URL = "postgresql://postgres:password@localhost:5432/pricescraper"
DB_URL = "sqlite:///data/pricescraper.db"


# ── Helpers ───────────────────────────────────────────────────────────────────

def cargar_registro_scraper() -> dict:
    """
    Carga el registro del scraper (folletos_procesados.json)
    para obtener metadata de cada folleto (titulo, fechas, url).
    """
    if not FOLLETOS_REGISTRO.exists():
        return {}
    with open(FOLLETOS_REGISTRO, encoding="utf-8") as f:
        datos = json.load(f)
    # Indexar por "fuente:folleto_id" para búsqueda rápida
    return datos


def obtener_metadata(registro: dict, fuente: str, folleto_id: str) -> dict:
    """Busca la metadata de un folleto en el registro del scraper."""
    clave = f"{fuente}:{folleto_id}"
    return registro.get(clave, {})


def encontrar_nlp_pendientes() -> list[Path]:
    """
    Encuentra todos los nlp_resultado.json disponibles en data/processed/.
    Un folleto está 'cargado en BD' si aparece en el log de ETL.
    Por simplicidad usamos un archivo de control propio.
    """
    return sorted([
        p for p in DATA_PROCESSED.rglob("nlp_resultado.json")
    ])


def cargar_control_etl() -> set:
    """
    Carga el set de folletos ya cargados en BD.
    Usa un archivo JSON simple como control.
    """
    ruta = Path("data/etl_cargados.json")
    if not ruta.exists():
        return set()
    with open(ruta, encoding="utf-8") as f:
        return set(json.load(f))


def marcar_cargado_etl(clave: str):
    """Registra un folleto como ya cargado en BD."""
    ruta = Path("data/etl_cargados.json")
    cargados = cargar_control_etl()
    cargados.add(clave)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(list(cargados), f, ensure_ascii=False)


# ── Menús ─────────────────────────────────────────────────────────────────────

def menu_principal() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper MX — Módulo ETL")
    print("═" * 55)
    print("   1 → Cargar folleto específico   (modo prueba)")
    print("   2 → Cargar todos los pendientes (modo batch)")
    print("   3 → Ver resumen de la BD")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_folleto(cargados: set) -> Path | None:
    """Lista los nlp_resultado.json disponibles para cargar."""
    archivos = encontrar_nlp_pendientes()

    if not archivos:
        logger.error("No se encontraron nlp_resultado.json en data/processed/")
        logger.error("Ejecuta primero: python probar_nlp.py")
        return None

    print("\n" + "─" * 65)
    print("   Folletos con NLP disponible:")
    print(f"   {'#':>3}  {'RUTA':<48}  {'ESTADO ETL'}")
    print("─" * 65)

    for i, archivo in enumerate(archivos, 1):
        ruta_rel = archivo.parent.relative_to(DATA_PROCESSED)
        partes   = ruta_rel.parts
        clave    = f"{partes[0]}:{partes[2]}" if len(partes) >= 3 else str(ruta_rel)
        estado   = "✅ cargado" if clave in cargados else "pendiente"
        print(f"   {i:>3}. {str(ruta_rel):<48}  {estado}")

    print("─" * 65)
    try:
        idx = int(input("\n   Número de folleto: ").strip())
        if 1 <= idx <= len(archivos):
            return archivos[idx - 1]
    except ValueError:
        pass
    return None


# ── Modos ─────────────────────────────────────────────────────────────────────

def modo_prueba(transformer: Transformer, registro: dict, cargados: set):
    """Carga un folleto específico para verificar que el ETL funciona."""
    archivo = menu_folleto(cargados)
    if not archivo:
        return

    # Extraer fuente y folleto_id de la ruta
    partes = archivo.parent.relative_to(DATA_PROCESSED).parts
    fuente     = partes[0] if len(partes) > 0 else ""
    folleto_id = partes[2] if len(partes) > 2 else ""

    meta = obtener_metadata(registro, fuente, folleto_id)

    try:
        resumen = transformer.cargar_folleto(archivo, meta)
        clave   = f"{fuente}:{folleto_id}"
        marcar_cargado_etl(clave)

        print(f"\n{'─'*55}")
        print(f"  Tienda:            {resumen['tienda']}")
        print(f"  Folleto ID:        {resumen['folleto_id']}")
        print(f"  Precios cargados:  {resumen['precios_cargados']}")
        print(f"  Sin producto:      {resumen['sin_producto']}")
        print(f"{'─'*55}")

        # Mostrar estado de la BD tras la carga
        bd = transformer.resumen_bd()
        print(f"\n  Estado actual de la BD:")
        print(f"  Tiendas:   {bd['tiendas']}")
        print(f"  Folletos:  {bd['folletos']}")
        print(f"  Páginas:   {bd['paginas']}")
        print(f"  Precios:   {bd['precios']}")

    except Exception as e:
        logger.error(f"[ETL] Error cargando {archivo}: {e}")
        raise


def modo_batch(transformer: Transformer, registro: dict, cargados: set):
    """Carga todos los nlp_resultado.json pendientes."""
    archivos  = encontrar_nlp_pendientes()
    pendientes = []

    for archivo in archivos:
        partes = archivo.parent.relative_to(DATA_PROCESSED).parts
        fuente     = partes[0] if len(partes) > 0 else ""
        folleto_id = partes[2] if len(partes) > 2 else ""
        clave      = f"{fuente}:{folleto_id}"
        if clave not in cargados:
            pendientes.append((archivo, fuente, folleto_id, clave))

    ya_cargados = len(archivos) - len(pendientes)
    logger.info(f"\n[ETL] {len(archivos)} folletos con NLP")
    logger.info(f"[ETL] ⏭️  {ya_cargados} ya cargados en BD")
    logger.info(f"[ETL] 🆕 {len(pendientes)} pendientes")

    if not pendientes:
        logger.info("[ETL] ✅ Todo está al día.")
        return

    print(f"\n  Se cargarán {len(pendientes)} folletos en la BD.")
    if input("  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    cargados_ok = 0
    errores     = 0
    total_prec  = 0

    for i, (archivo, fuente, folleto_id, clave) in enumerate(pendientes, 1):
        logger.info(f"\n[ETL] [{i}/{len(pendientes)}] {fuente}/{folleto_id}")
        try:
            meta    = obtener_metadata(registro, fuente, folleto_id)
            resumen = transformer.cargar_folleto(archivo, meta)
            marcar_cargado_etl(clave)
            cargados_ok += 1
            total_prec  += resumen["precios_cargados"]
        except Exception as e:
            logger.error(f"[ETL] Error en {folleto_id}: {e}")
            errores += 1

    # Resumen final
    bd = transformer.resumen_bd()
    logger.info("\n" + "=" * 55)
    logger.info(f"✅ Batch ETL completado")
    logger.info(f"   Folletos cargados:  {cargados_ok}")
    logger.info(f"   Errores:            {errores}")
    logger.info(f"   Precios insertados: {total_prec}")
    logger.info(f"   Estado BD → Tiendas:{bd['tiendas']} "
               f"Folletos:{bd['folletos']} Precios:{bd['precios']}")
    logger.info("=" * 55)


def modo_resumen(transformer: Transformer):
    """Muestra el estado actual de la BD."""
    bd = transformer.resumen_bd()

    print(f"\n{'═'*55}")
    print(f"   Estado de la Base de Datos")
    print(f"{'═'*55}")
    print(f"   Tiendas:   {bd['tiendas']}")
    print(f"   Folletos:  {bd['folletos']}")
    print(f"   Páginas:   {bd['paginas']}")
    print(f"   Precios:   {bd['precios']}")
    print(f"{'─'*55}")

    try:
        df = transformer.precios_por_tienda()
        if not df.empty:
            print(f"\n   Precios por tienda:")
            print(f"   {'TIENDA':<25} {'TOTAL':>7} {'PROM':>10} {'MIN':>10} {'MAX':>10}")
            print(f"   {'─'*25} {'─'*7} {'─'*10} {'─'*10} {'─'*10}")
            for _, row in df.iterrows():
                print(f"   {row['nombre']:<25} {int(row['total_precios']):>7} "
                      f"${row['precio_promedio']:>9,.2f} "
                      f"${row['precio_min']:>9,.2f} "
                      f"${row['precio_max']:>9,.2f}")
    except Exception as e:
        logger.warning(f"[ETL] No se pudo obtener resumen por tienda: {e}")

    print(f"{'═'*55}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 55)
    logger.info("PriceScraper MX — Módulo ETL")
    logger.info(f"BD: {DB_URL}")
    logger.info("=" * 55)

    # Inicializar transformer y cargar registro del scraper
    transformer = Transformer(DB_URL)
    registro    = cargar_registro_scraper()
    logger.info(f"[ETL] Registro scraper: {len(registro)} folletos")

    while True:
        cargados = cargar_control_etl()
        opcion   = menu_principal()

        if opcion == 0:
            print("\n  👋 Saliendo...\n")
            break
        elif opcion == 1:
            modo_prueba(transformer, registro, cargados)
        elif opcion == 2:
            modo_batch(transformer, registro, cargados)
        elif opcion == 3:
            modo_resumen(transformer)
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