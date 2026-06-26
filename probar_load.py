# Lee nlp_resultado.json generados por el módulo NLP y los carga
# en la base de datos SQLite (dev) / PostgreSQL (producción).

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ------------------------- Logging -------------------------
Path("logs").mkdir(exist_ok=True)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))
file_handler = RotatingFileHandler(
    "logs/load.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("load")

sys.path.insert(0, str(Path(__file__).parent))

from load.load import Loader

DATA_PROCESSED = Path("data/processed")
DB_PATH_DEFAULT = Path("data/pricescraper.db")


# ------------------------- Menús -------------------------

def menu_principal() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper — Módulo Load (ETL → BD)")
    print("═" * 55)
    print("   1 → Cargar folleto específico   (modo prueba)")
    print("   2 → Cargar todo data/processed/ (batch)")
    print("   3 → Cargar batch forzando       (reprocesa todo)")
    print("   4 → Ver estado de la BD")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_folleto() -> Path | None:
    """
    Lista carpetas con nlp_resultado.json disponible y deja elegir una.
    Indica cuáles ya están cargadas en BD (requiere loader para consulta).
    """
    carpetas = sorted([
        p.parent for p in DATA_PROCESSED.rglob("nlp_resultado.json")
    ])

    if not carpetas:
        logger.error("No se encontraron nlp_resultado.json en data/processed/")
        logger.error("Ejecuta primero: python probar_nlp.py")
        return None

    print("\n" + "─" * 65)
    print(f"   Folletos con NLP disponible:")
    print(f"   {'#':>3}  {'RUTA':<50}")
    print("─" * 65)

    for i, carpeta in enumerate(carpetas, 1):
        ruta_rel = carpeta.relative_to(DATA_PROCESSED)
        print(f"   {i:>3}. {str(ruta_rel):<50}")

    print("─" * 65)
    try:
        idx = int(input("\n   Número de folleto: ").strip())
        if 1 <= idx <= len(carpetas):
            return carpetas[idx - 1] / "nlp_resultado.json"
    except ValueError:
        pass
    logger.warning("Selección inválida.")
    return None


# ------------------------- Modos -------------------------

def modo_prueba(loader: Loader):
    """Carga un único folleto seleccionado por el usuario."""
    ruta = menu_folleto()
    if not ruta:
        return

    print(f"\n   Cargando: {ruta.relative_to(DATA_PROCESSED)}")
    try:
        r = loader.cargar_folleto(ruta)
        _imprimir_resumen_folleto(r)
    except Exception as e:
        logger.error(f"Error al cargar folleto: {e}")


def modo_batch(loader: Loader, forzar: bool = False):
    """Carga todos los nlp_resultado.json bajo data/processed/."""
    rutas = list(DATA_PROCESSED.rglob("nlp_resultado.json"))

    if not rutas:
        logger.error("Sin nlp_resultado.json disponibles.")
        return

    pendientes = rutas if forzar else [
        r for r in rutas if not loader._ya_cargado(r)
    ]
    ya_cargados = len(rutas) - len(pendientes)

    print(f"\n   {len(rutas)} folletos con NLP")
    print(f"   {ya_cargados} ya cargados en BD")
    print(f"   {len(pendientes)} pendientes")

    if not pendientes:
        print("\n   ✅ Todo está al día.")
        return

    accion = "Recargar todo" if forzar else "Cargar pendientes"
    if input(f"\n   ¿{accion} ({len(pendientes)} folletos)? (s/n): ").strip().lower() != "s":
        print("   Cancelado.")
        return

    totales = loader.cargar_batch(DATA_PROCESSED, forzar=forzar)
    _imprimir_resumen_batch(totales)


def modo_ver_bd(loader: Loader):
    """Muestra el estado actual de la BD."""
    estado = loader.resumen_bd()
    print(f"\n{'─'*45}")
    print(f"  {'TABLA':<22} {'REGISTROS':>10}")
    print(f"{'─'*45}")
    for tabla, count in estado.items():
        if count is None:
            print(f"  {tabla:<22} {'NO EXISTE':>10}")
        else:
            print(f"  {tabla:<22} {count:>10,}")
    print(f"{'─'*45}")


# ------------------------- Helpers de impresión -------------------------

def _imprimir_resumen_folleto(r: dict):
    print(f"\n{'─'*50}")
    print(f"  Tienda:      {r['tienda']} ({r['fuente']})")
    print(f"  Folleto:     {r['folleto_id']}")
    print(f"  Páginas:     {r['paginas_procesadas']}")
    print(f"{'─'*50}")
    print(f"  Extracciones insertadas:  {r['extracciones_insertadas']}")
    print(f"  Precios sin producto:     {r['precios_sin_producto']}")
    print(f"  Eventos promo:            {r['eventos_insertados']}")
    if r["errores"] > 0:
        print(f"  WARNING:  Errores de página:      {r['errores']}")
    print(f"{'─'*50}")

    if r["precios_sin_producto"] > 0:
        pct = r["precios_sin_producto"] / max(r["extracciones_insertadas"], 1) * 100
        if pct > 30:
            print(f"\n  WARNING:  {pct:.0f}% de precios sin producto asociado.")
            print("     Revisar: calidad OCR, tolerancia bbox en load.py")


def _imprimir_resumen_batch(totales: dict):
    print(f"\n{'═'*50}")
    print(f"  ✅ Batch completado")
    print(f"{'─'*50}")
    print(f"  Procesados:        {totales.get('procesados', 0)}")
    print(f"  Omitidos (ya BD):  {totales.get('omitidos', 0)}")
    print(f"  Errores:           {totales.get('errores', 0)}")
    print(f"{'─'*50}")
    print(f"  Extracciones total: {totales.get('extracciones_total', 0):,}")
    print(f"  Eventos promo:      {totales.get('eventos_total', 0):,}")
    print(f"{'═'*50}")


# ------------------------- Main -------------------------

def main():
    logger.info("═" * 55)
    logger.info("PriceScraper MX — Módulo Load")
    logger.info("═" * 55)

    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH_DEFAULT
    loader  = Loader(db_path)

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  ------ Saliendo...\n")
            break
        elif opcion == 1:
            modo_prueba(loader)
        elif opcion == 2:
            modo_batch(loader, forzar=False)
        elif opcion == 3:
            modo_batch(loader, forzar=True)
        elif opcion == 4:
            modo_ver_bd(loader)
        else:
            print("  WARNING:  Opción no válida.")

        try:
            if input("\n  ¿Otra operación? (s/n): ").strip().lower() != "s":
                print("\n  ------ Saliendo...\n")
                break
        except EOFError:
            break


if __name__ == "__main__":
    main()
