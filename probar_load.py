"""
probar_load.py
PriceScraper MX — Orquestador del módulo Load (NLP → PostgreSQL)

Menú:
  1 → Cargar folleto específico   (modo prueba)
  2 → Cargar todo data/processed/ (batch, salta ya cargados)
  3 → Cargar batch forzando       (reprocesa todo)
  4 → Ver estado de la BD
  0 → Salir

Uso:
    python probar_load.py
"""

import sys
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ── Logging ───────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "logs/load.log", maxBytes=5 * 1024 * 1024,
            backupCount=3, encoding="utf-8"
        ),
    ],
)
logger = logging.getLogger("probar_load")

sys.path.insert(0, str(Path(__file__).parent))

from load.load import Loader
from load.db_builder import verificar_conexion, resumen_bd

DATA_PROCESSED = Path("data/processed")


# ── Menú ──────────────────────────────────────────────────────────────────────

def menu_principal() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper MX — Módulo Load (NLP → PostgreSQL)")
    print("═" * 55)
    print("   1 → Cargar folleto específico")
    print("   2 → Cargar batch (salta ya cargados)")
    print("   3 → Cargar batch forzando (reprocesa todo)")
    print("   4 → Ver estado de la BD")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Opción: ").strip())
    except ValueError:
        return -1


def menu_folleto() -> Path | None:
    rutas = sorted(DATA_PROCESSED.rglob("nlp_resultado.json"))
    if not rutas:
        print("\n  ⚠️  Sin nlp_resultado.json en data/processed/")
        print("     Ejecuta primero: python probar_nlp.py")
        return None

    print(f"\n{'─' * 65}")
    print(f"   {'#':>3}  {'RUTA'}")
    print(f"{'─' * 65}")
    for i, ruta in enumerate(rutas, 1):
        ruta_rel = ruta.parent.relative_to(DATA_PROCESSED)
        print(f"   {i:>3}. {ruta_rel}")
    print(f"{'─' * 65}")

    try:
        idx = int(input("\n   Número de folleto: ").strip())
        if 1 <= idx <= len(rutas):
            return rutas[idx - 1]
    except ValueError:
        pass

    print("  ⚠️  Selección inválida.")
    return None


# ── Modos ─────────────────────────────────────────────────────────────────────

def modo_prueba(loader: Loader):
    ruta = menu_folleto()
    if not ruta:
        return
    print(f"\n   Cargando: {ruta.parent.relative_to(DATA_PROCESSED)}")
    try:
        r = loader.cargar_folleto(ruta)
        _imprimir_resumen_folleto(r)
    except Exception as e:
        logger.error(f"Error al cargar folleto: {e}")


def modo_batch(loader: Loader, forzar: bool = False):
    rutas = list(DATA_PROCESSED.rglob("nlp_resultado.json"))
    if not rutas:
        print("\n  ⚠️  Sin nlp_resultado.json disponibles.")
        return

    pendientes  = rutas if forzar else [r for r in rutas if not loader._ya_cargado(r)]
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


def modo_ver_bd():
    estado = resumen_bd()
    print(f"\n{'─' * 40}")
    print(f"  {'TABLA':<22} {'REGISTROS':>10}")
    print(f"{'─' * 40}")
    for tabla, count in estado.items():
        valor = f"{count:>10,}" if count is not None else "  NO EXISTE"
        print(f"  {tabla:<22} {valor}")
    print(f"{'─' * 40}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _imprimir_resumen_folleto(r: dict):
    print(f"\n{'─' * 50}")
    print(f"  Tienda:      {r['tienda']} ({r['fuente']})")
    print(f"  Folleto:     {r['folleto_id']}")
    print(f"  Páginas:     {r['paginas_procesadas']}")
    print(f"{'─' * 50}")
    print(f"  Extracciones:       {r['extracciones_insertadas']}")
    print(f"  Sin producto:       {r['precios_sin_producto']}")
    print(f"  Eventos promo:      {r['eventos_insertados']}")
    if r["errores"]:
        print(f"  ⚠️  Errores:         {r['errores']}")
    print(f"{'─' * 50}")

    if r["extracciones_insertadas"] > 0 and r["precios_sin_producto"] > 0:
        pct = r["precios_sin_producto"] / r["extracciones_insertadas"] * 100
        if pct > 30:
            print(f"\n  ⚠️  {pct:.0f}% de precios sin producto asociado.")
            print("     Revisar calidad OCR o tolerancia bbox.")


def _imprimir_resumen_batch(totales: dict):
    print(f"\n{'═' * 50}")
    print(f"  ✅ Batch completado")
    print(f"{'─' * 50}")
    print(f"  Procesados:         {totales.get('procesados', 0)}")
    print(f"  Omitidos (ya BD):   {totales.get('omitidos', 0)}")
    print(f"  Errores:            {totales.get('errores', 0)}")
    print(f"{'─' * 50}")
    print(f"  Extracciones total: {totales.get('extracciones_total', 0):,}")
    print(f"  Eventos promo:      {totales.get('eventos_total', 0):,}")
    print(f"{'═' * 50}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 55)
    print("   PriceScraper MX — Módulo Load")
    print("═" * 55)

    # Health-check antes de inicializar el Loader
    if not verificar_conexion():
        print("\n  ✗ No se pudo conectar a PostgreSQL.")
        print("  Verifica que el servidor esté activo y que .env sea correcto.")
        sys.exit(1)

    with Loader() as loader:
        while True:
            opcion = menu_principal()

            if opcion == 0:
                print("\n  👋 Saliendo...\n")
                break
            elif opcion == 1:
                modo_prueba(loader)
            elif opcion == 2:
                modo_batch(loader, forzar=False)
            elif opcion == 3:
                modo_batch(loader, forzar=True)
            elif opcion == 4:
                modo_ver_bd()
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