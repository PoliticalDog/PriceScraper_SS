# Orquestador para probar los scrapers de Tiendeo y Ofertomat, con menú 

import asyncio
import json
import logging
import random
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

# Modulos del scraper
from scraper.sources.tiendeo   import TiendeoScraper, CATEGORIAS, TIENDAS
from scraper.sources.ofertomat import OfertomatScraper, TIENDAS as TIENDAS_OFERTOMAT
from scraper.downloader        import Downloader
from scraper.registro          import Registro

# Crear carpeta de logs
Path("logs").mkdir(exist_ok=True)

# login personlaizado 
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
))

# Handler para archivo - acumula entre ejecuciones
file_handler = RotatingFileHandler(
    "logs/scraper.log",
    maxBytes=5 * 1024 * 1024,  # 5 MB por archivo
    backupCount=5,              # máximo 5 archivos de respaldo
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"  # fecha completa en el archivo
))

# Aplicar ambos handlers
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])

logger = logging.getLogger("scraper")
sys.path.insert(0, str(Path(__file__).parent))


# -------------------- Menús --------------------

def menu_principal() -> int:
    print("\n" + "-" * 55)
    print("   PriceScraper -- Prueba de Scrapers")
    print("-" * 55)
    print("   1 --> Tiendeo.com.mx  (supermercados)")
    print("   2 --> Ofertomat.mx    (supermercados)")
    print("   3 --> Ambas fuentes   (Tiendeo + Ofertomat)")
    print("   4 --> Tiendeo -- Rastreo completo (tienda por tienda)")
    print("   0 --> Salir")
    print("-" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1

# Menús para elegir tienda específica o todas en tiendeo
def menu_tiendas_tiendeo() -> str:
    print("\n" + "-" * 55)
    print("   Tiendas disponibles en Tiendeo:")
    tiendas = list(TIENDAS.keys())
    for i, t in enumerate(tiendas, 1):
        nombre = t.replace("-", " ").title()
        print(f"   {i:>2}. {nombre}")
    print(f"    0. Todas las tiendas (categoría supermercados)")
    print("-" * 55)
    try:
        idx = int(input("   Tienda específica (0 = todas): ").strip())
        if idx == 0:
            return "todas"
        return tiendas[idx - 1] if 1 <= idx <= len(tiendas) else "todas" # Si el número no es válido, se asume "todas"
    except (ValueError, IndexError):
        return "todas"

# Menú para elegir tienda específica o todas en ofertomat
def menu_tiendas_ofertomat() -> str:
    print("\n" + "-" * 55)
    print("   Tiendas disponibles en Ofertomat:")
    tiendas = list(TIENDAS_OFERTOMAT.keys())
    for i, t in enumerate(tiendas, 1):
        print(f"   {i:>2}. {t}")
    print(f"    0. Todas las tiendas")
    print("-" * 55)
    try:
        idx = int(input("   Tienda específica (0 = todas): ").strip())
        if idx == 0:
            return "todas"
        return tiendas[idx - 1] if 1 <= idx <= len(tiendas) else "todas"  # Si el número no es válido, se asume "todas"
    except (ValueError, IndexError):
        return "todas"

# Función para mostrar un resumen de los folletos encontrados
def mostrar_resumen_folletos(folletos: list[dict]):
    print(f"\n  {'TIENDA':<25} {'TÍTULO':<35} {'VIGENCIA'}")
    print(f"  {'-'*25} {'-'*35} {'-'*20}")
    for f in folletos:
        vigencia = f"{f['fecha_inicio'] or '?'} --> {f['fecha_fin'] or '?'}" # Si no hay fecha, se muestra "?" para indicar desconocida
        print(f"  {f['tienda']:<25} {f['titulo'][:35]:<35} {vigencia}")


# ---------------------- Tiendeo ----------------------

# Funcion principal tiendeo
async def scrapear_tiendeo(registro: Registro, slug_tienda: str = "todas"):
    logger.info(f"\n[TIENDEO] Iniciando scraping "
                f"({'todas las tiendas' if slug_tienda == 'todas' else slug_tienda.replace('-',' ').title()})...")

    # ------------- Paso 1: Obtener folletos -------------
    async with TiendeoScraper(headless=True) as scraper:
        if slug_tienda == "todas":
            folletos = await scraper.scrapear_categoria("supermercados")
        else:
            folletos = await scraper.scrapear_tienda(slug_tienda)

    logger.info(f"[TIENDEO] {len(folletos)} folletos encontrados")
    mostrar_resumen_folletos(folletos)

    # Guardar JSON
    Path("data").mkdir(exist_ok=True)
    nombre_json = f"folletos_tiendeo_{slug_tienda}.json"
    with open(f"data/{nombre_json}", "w", encoding="utf-8") as f:
        json.dump(folletos, f, ensure_ascii=False, indent=2)
    logger.info(f"[TIENDEO] Lista guardada en data/{nombre_json}")

    # Filtrar ya procesados
    nuevos = [f for f in folletos
              if not registro.ya_procesado("tiendeo", f["folleto_id"], f["tienda"])]
    ya_procesados = len(folletos) - len(nuevos)

    if ya_procesados:
        logger.info(f"[TIENDEO] ⏭️  {ya_procesados} folletos ya procesados --> omitidos")
    if not nuevos:
        logger.info("[TIENDEO] ✅ No hay folletos nuevos.")
        return

    logger.info(f"[TIENDEO] 🆕 {len(nuevos)} folletos nuevos a descargar")

    # ------------- Paso 2 y 3: Descargar páginas -------------
    
    downloader = Downloader(max_concurrentes=2) # solo 2 descargas simultáneas para no saturar ni parecer bot
    
    # Descargar cada folleto nuevo
    for folleto in nuevos:
        tienda_display = folleto['tienda'] or "X  Sin tienda (--> desconocidos)"
        logger.info(f"\n[TIENDEO] --> {tienda_display} -- {folleto['titulo']}")

        async with TiendeoScraper(headless=True) as scraper:
            paginas = await scraper.obtener_paginas_folleto(folleto["url_folleto"])

        logger.info(f"[TIENDEO] {len(paginas)} páginas encontradas")

        if paginas:
            rutas = await downloader.descargar_paginas(
                urls_paginas=paginas,  # todas las páginas disponibles
                fuente=folleto["fuente"],
                tienda=folleto["tienda"],
                folleto_id=folleto["folleto_id"],
            )
            logger.info(f"[TIENDEO] ✅ {len(rutas)}/{len(paginas)} páginas descargadas")
            for r in rutas:
                print(f"    💾 {r}")

        registro.marcar_procesado("tiendeo", folleto["folleto_id"], {
            "tienda":       folleto["tienda"],
            "titulo":       folleto["titulo"],
            "fecha_inicio": folleto["fecha_inicio"],
            "fecha_fin":    folleto["fecha_fin"],
        })

    logger.info(f"\n[TIENDEO] ✅ Completado -- "
                f"Acumulados: {registro.total_procesados('tiendeo')} folletos")


# ------------- Tiendeo -- Rastreo completo tienda por tienda -------------

# Esta función recorre todas las tiendas de la categoría "supermercados" en Tiendeo, obtiene sus folletos y descarga los nuevos.
async def scrapear_tiendeo_todas_tiendas(registro: Registro):
    
    tiendas = list(TIENDAS.keys())
    logger.info(f"\n[TIENDEO] Rastreo completo: {len(tiendas)} tiendas a revisar")

    downloader = Downloader(max_concurrentes=2)
    total_nuevos = 0

    for i, slug in enumerate(tiendas, 1):
        nombre = slug.replace("-", " ").title()

        # Pausa aleatoria entre tiendas para no parecer bot
        if i > 1:
            pausa = random.uniform(3.0, 8.0)
            logger.info(f"[TIENDEO] Esperando {pausa:.1f}s antes de siguiente tienda...")
            await asyncio.sleep(pausa)

        logger.info(f"\n[TIENDEO] [{i}/{len(tiendas)}] Revisando: {nombre}...")

        # ------------- Obtener folletos de esta tienda -------------
        try:
            async with TiendeoScraper(headless=True) as scraper:
                folletos = await scraper.scrapear_tienda(slug)
        except Exception as e:
            logger.error(f"[TIENDEO] Error scrapeando {nombre}: {e}")
            continue

        if not folletos:
            logger.info(f"[TIENDEO] Sin folletos en {nombre}")
            continue

        nuevos = [f for f in folletos
                  if not registro.ya_procesado("tiendeo", f["folleto_id"], f["tienda"])]

        logger.info(f"[TIENDEO] {nombre}: {len(folletos)} folletos, {len(nuevos)} nuevos")

        if not nuevos:
            continue

        # ------------- Descargar los folletos nuevos de esta tienda -------------
        for folleto in nuevos:
            tienda_display = folleto['tienda'] or "X  Sin tienda (--> desconocidos)"
            logger.info(f"[TIENDEO] --> {tienda_display} -- {folleto['titulo']}")
            total_nuevos += 1

            try:
                async with TiendeoScraper(headless=True) as scraper:
                    paginas = await scraper.obtener_paginas_folleto(folleto["url_folleto"])

                logger.info(f"[TIENDEO] {len(paginas)} páginas encontradas")

                if paginas:
                    rutas = await downloader.descargar_paginas(
                        urls_paginas=paginas,
                        fuente=folleto["fuente"],
                        tienda=folleto["tienda"],
                        folleto_id=folleto["folleto_id"],
                    )
                    logger.info(f"[TIENDEO] ✅ {len(rutas)}/{len(paginas)} páginas descargadas")
                    for r in rutas:
                        print(f"    💾 {r}")

                registro.marcar_procesado("tiendeo", folleto["folleto_id"], {
                    "tienda":       folleto["tienda"],
                    "titulo":       folleto["titulo"],
                    "fecha_inicio": folleto["fecha_inicio"],
                    "fecha_fin":    folleto["fecha_fin"],
                })

            except Exception as e:
                logger.error(f"[TIENDEO] Error procesando folleto {folleto['folleto_id']}: {e}")
                continue

    logger.info(f"\n[TIENDEO] ✅ Rastreo completo terminado -- "
                f"{total_nuevos} folletos nuevos descargados -- "
                f"Acumulados: {registro.total_procesados('tiendeo')}")


# ------------- Ofertomat -------------

# Función principal para Ofertomat, similar a la de Tiendeo pero adaptada a su estructura y opciones de tienda.
async def scrapear_ofertomat(registro: Registro, slug_tienda: str = "todas",
                              paginas_prueba: int = 3):
    logger.info(f"\n[OFERTOMAT] Iniciando scraping "
                f"({'todas' if slug_tienda == 'todas' else slug_tienda})...")

    async with OfertomatScraper(headless=True) as scraper:
        if slug_tienda == "todas":
            folletos = await scraper.scrapear_supermercados()
        else:
            folletos = await scraper.scrapear_tienda(slug_tienda)

    logger.info(f"[OFERTOMAT] {len(folletos)} folletos encontrados")
    mostrar_resumen_folletos(folletos)

    nombre_json = f"folletos_ofertomat_{slug_tienda}.json"
    with open(f"data/{nombre_json}", "w", encoding="utf-8") as f:
        json.dump(folletos, f, ensure_ascii=False, indent=2)

    nuevos = [f for f in folletos
              if not registro.ya_procesado("ofertomat", f["folleto_id"], f["tienda"])]
    ya_procesados = len(folletos) - len(nuevos)

    if ya_procesados:
        logger.info(f"[OFERTOMAT] ⏭️  {ya_procesados} ya procesados --> omitidos")
    if not nuevos:
        logger.info("[OFERTOMAT] ✅ No hay folletos nuevos.")
        return

    logger.info(f"[OFERTOMAT] 🆕 {len(nuevos)} folletos nuevos")

    downloader = Downloader(max_concurrentes=2)

    for folleto in nuevos:
        logger.info(f"\n[OFERTOMAT] --> {folleto['tienda']} -- {folleto['titulo']}")

        async with OfertomatScraper(headless=True) as scraper:
            paginas = await scraper.obtener_paginas_folleto(folleto["url_folleto"])

        logger.info(f"[OFERTOMAT] {len(paginas)} páginas encontradas")

        if paginas:
            rutas = await downloader.descargar_paginas(
                urls_paginas=paginas[:paginas_prueba],
                fuente=folleto["fuente"],
                tienda=folleto["tienda"],
                folleto_id=folleto["folleto_id"],
            )
            logger.info(f"[OFERTOMAT] ✅ {len(rutas)} páginas descargadas")
            for r in rutas:
                print(f"    💾 {r}")

        registro.marcar_procesado("ofertomat", folleto["folleto_id"], {
            "tienda":       folleto["tienda"],
            "titulo":       folleto["titulo"],
            "fecha_inicio": folleto["fecha_inicio"],
            "fecha_fin":    folleto["fecha_fin"],
        })

    logger.info(f"\n[OFERTOMAT] ✅ Completado -- "
                f"Acumulados: {registro.total_procesados('ofertomat')} folletos")


# ------------------------------------ Main ------------------------------------

#dispara el menu principal
async def main():
    # Cargar registro de folletos procesados para evitar duplicados en pruebas sucesivas
    registro = Registro()
    logger.info(f"Registro cargado: {registro.total_procesados()} folletos previos")

    # Menú principal para elegir qué scraper probar
    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  ------ Saliendo...\n")
            break

        elif opcion == 1:
            slug = menu_tiendas_tiendeo()
            await scrapear_tiendeo(registro, slug_tienda=slug)

        elif opcion == 2:
            slug = menu_tiendas_ofertomat()
            await scrapear_ofertomat(registro, slug_tienda=slug, paginas_prueba=3)

        elif opcion == 3:
            slug_t = menu_tiendas_tiendeo()
            await scrapear_tiendeo(registro, slug_tienda=slug_t)
            slug_o = menu_tiendas_ofertomat()
            await scrapear_ofertomat(registro, slug_tienda=slug_o, paginas_prueba=3)

        elif opcion == 4:
            await scrapear_tiendeo_todas_tiendas(registro)

        else:
            print("  ERROR: Opción no válida.")

        try:
            continuar = input("\n  ¿Hacer otra prueba? (s/n): ").strip().lower()
        except EOFError:
            break
        if continuar != "s":
            print("\n  ------ Saliendo...\n")
            break


if __name__ == "__main__":
    asyncio.run(main())