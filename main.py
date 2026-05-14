# Prueba de scrapeo
import asyncio
import json
import logging
from pathlib import Path
import sys
from scraper.sources.tiendeo import TiendeoScraper, CATEGORIAS
from scraper.downloader import Downloader

"""
Prueba el pipeline completo:
  1. Obtener lista de folletos de supermercados
  2. Tomar el primer folleto como prueba
  3. Obtener sus páginas
  4. Descargar las imágenes a data/raw/
"""

# Configuracion mensajes login durante el proceso
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")

# Configuracion del path para scraper y vision
sys.path.insert(0, str(Path(__file__).parent))

# Proceso asincrono de scraper
async def main():
    logger.info("=" * 60)
    logger.info("PriceScraper — Tiendeo Scraper")
    logger.info("=" * 60)

    # ── Paso 1: Obtener lista de folletos ────────────────────────
    logger.info("[PASO 1] Obteniendo folletos de supermercados...")

    async with TiendeoScraper(headless=True) as scraper:
        folletos = await scraper.scrapear_categoria("supermercados")

    logger.info(f"\n✅ {len(folletos)} folletos encontrados\n")

    # Mostrar resumen de los primeros 5
    for f in folletos[:5]:
        print(f"  📋 {f['tienda']:25} | {f['titulo'][:35]:35} | {f['fecha_inicio']} → {f['fecha_fin']}")

    if not folletos:
        logger.error("No se encontraron folletos. Revisar selectores.")
        return

    # Guardar lista completa en JSON para inspección
    Path("data").mkdir(exist_ok=True)
    with open("data/folletos_tiendeo.json", "w", encoding="utf-8") as f:
        json.dump(folletos, f, ensure_ascii=False, indent=2)
    logger.info("Lista completa guardada en data/folletos_tiendeo.json")

    # ── Paso 2: Descargar páginas del primer folleto ─────────────
    folleto_prueba = folletos[0]
    logger.info(f"\n[PASO 2] Obteniendo páginas de: {folleto_prueba['tienda']} — {folleto_prueba['titulo']}")

    async with TiendeoScraper(headless=True) as scraper:
        paginas = await scraper.obtener_paginas_folleto(folleto_prueba["url_folleto"])

    logger.info(f"✅ {len(paginas)} páginas encontradas")
    for i, url in enumerate(paginas[:3], 1):
        print(f"  Página {i}: {url[:80]}...")

    if not paginas:
        logger.warning("No se encontraron páginas. El visor puede requerir interacción adicional.")
        logger.info("Intentando descargar solo el preview del folleto...")

    # ── Paso 3: Descargar imágenes ───────────────────────────────
    logger.info(f"\n[PASO 3] Descargando imágenes...")
    downloader = Downloader(max_concurrentes=2)

    # Descargar preview siempre
    preview = await downloader.descargar_preview(
        url_preview=folleto_prueba["url_preview"],
        fuente=folleto_prueba["fuente"],
        tienda=folleto_prueba["tienda"],
        folleto_id=folleto_prueba["folleto_id"],
    )
    if preview:
        logger.info(f"✅ Preview guardada: {preview}")

    # Descargar páginas si las encontramos
    if paginas:
        # Limitar a 3 páginas en modo prueba para no sobrecargar
        paginas_prueba = paginas[:3]
        rutas = await downloader.descargar_paginas(
            urls_paginas=paginas_prueba,
            fuente=folleto_prueba["fuente"],
            tienda=folleto_prueba["tienda"],
            folleto_id=folleto_prueba["folleto_id"],
        )
        logger.info(f"✅ {len(rutas)} páginas descargadas")
        for ruta in rutas:
            print(f"  💾 {ruta}")

    logger.info("\n" + "=" * 60)
    logger.info("✅ Pipeline de scraping completado exitosamente")
    logger.info("Próximo paso: ejecutar pipeline de visión (OpenCV + EasyOCR)")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())