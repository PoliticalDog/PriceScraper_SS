# Benchmark de deteccion de regiones (ROI) -- Fase 1 del plan de mejora de OCR.
# Corre vision/region_detector.py sobre imagenes reales ya preprocesadas de
# distintas tiendas y guarda una imagen de comparacion (recuadros detectados)
# para revisar visualmente la calidad de la deteccion.
#
# Cada region candidata se califica con calificar_regiones(): usa el OCR de la
# pagina completa (que de todos modos ya corre en produccion, sin costo extra)
# para verificar si algun bloque de texto que cae dentro de la region coincide
# con un patron de precio. Verde = precio confirmado (region confiable para
# asociacion producto-precio). Rojo = sin precio confirmado (no confiable).
#
# No toca probar_vision.py, probar_nlp.py ni load/load.py -- es solo para
# validar la calidad de la deteccion antes de decidir si se integra al pipeline.

import logging
import cv2
from pathlib import Path

from vision.preprocessor import obtener_preprocesador
from vision.ocr_engine import OCREngine
from vision.region_detector import detectar_regiones, calificar_regiones, dibujar_regiones

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("probar_regiones")

# Casos de prueba: (tienda, folleto_id, archivo de pagina) -- mezcla de layouts
# con grid limpio esperado y layouts sin recuadros claros (para confirmar el fallback).
CASOS = [
    ("casa_ley",  "422327", "pagina_002.webp"),  # grid limpio: producto+precio en el mismo recuadro
    ("casa_ley",  "422328", "pagina_001.webp"),
    ("costco",    "414713", "pagina_002.webp"),  # producto aislado a pagina completa (sin grid)
    ("costco",    "418210", "pagina_003.webp"),
    ("chedraui",  "413467", "pagina_003.webp"),  # precio aislado, buen contraste, sin grid denso
    ("la_comer",  "415686", "pagina_005.webp"),  # precio flota AFUERA del recuadro de producto
    ("la_comer",  "415686", "pagina_010.webp"),
    # Ronda 2 -- tiendas aun no probadas, para ver si el patron generaliza
    ("alsuper",         "416303", "pagina_003.webp"),
    ("alsuper",         "416303", "pagina_005.webp"),
    ("bodega_aurrera",  "412322", "pagina_002.webp"),
    ("bodega_aurrera",  "412322", "pagina_003.webp"),
    ("heb",             "415691", "pagina_001.webp"),
    ("heb",             "415691", "pagina_002.webp"),
    ("merco",           "422679", "pagina_005.webp"),
    ("merco",           "422679", "pagina_010.webp"),
    ("s-mart",          "416155", "pagina_001.webp"),
    ("s-mart",          "416155", "pagina_002.webp"),
    ("sam's_club",      "417748", "pagina_002.webp"),
    ("sam's_club",      "417748", "pagina_003.webp"),
    ("soriana_hiper",   "412336", "pagina_005.webp"),
    ("soriana_hiper",   "412336", "pagina_015.webp"),
    ("soriana_mercado", "412225", "pagina_003.webp"),
    ("soriana_mercado", "412225", "pagina_008.webp"),
    ("tiendas_3b",      "413843", "pagina_001.webp"),
    ("waldos",          "413247", "pagina_002.webp"),
    ("waldos",          "413247", "pagina_004.webp"),
    ("walmart",         "412757", "pagina_003.webp"),
    ("walmart",         "412757", "pagina_007.webp"),
    ("oxxo",            "415666", "pagina_003.webp"),
    ("oxxo",            "415666", "pagina_008.webp"),
]

DATA_RAW = Path("data/raw/tiendeo")
SALIDA = Path("data/processed/_benchmark_regiones")


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    preprocesador = obtener_preprocesador("color_normal")  # mismo perfil de produccion
    ocr = OCREngine(idiomas=["es", "en"], usar_gpu=False)  # se inicializa una sola vez

    resumen = []
    for tienda, folleto_id, archivo in CASOS:
        ruta_original = DATA_RAW / tienda / folleto_id / archivo
        if not ruta_original.exists():
            logger.warning(f"No existe: {ruta_original} -- se omite")
            continue

        logger.info(f"--- {tienda}/{folleto_id}/{archivo} ---")
        imagen_proc = preprocesador.procesar(ruta_original)

        # OCR de pagina completa -- el mismo que ya corre en produccion (probar_vision.py)
        resultados_ocr = ocr.extraer_texto(imagen_proc, motor="easyocr")
        bloques_ocr = [{"texto": r.texto, "bbox": r.bbox_simple} for r in resultados_ocr]

        candidatas = detectar_regiones(imagen_proc)
        calificadas = calificar_regiones(candidatas, bloques_ocr)
        confiables = [r for r in calificadas if r["tiene_precio"]]

        alto, ancho = imagen_proc.shape[:2]
        area_total = ancho * alto
        cobertura_confiable = (
            sum(r["ancho"] * r["alto"] for r in confiables) / area_total if confiables else 0.0
        )

        comparacion = dibujar_regiones(imagen_proc, calificadas)
        nombre_salida = f"{tienda}_{folleto_id}_{archivo.replace('.webp', '')}_regiones.jpg"
        ruta_salida = SALIDA / nombre_salida
        cv2.imwrite(str(ruta_salida), comparacion)

        resumen.append((
            tienda, folleto_id, archivo,
            len(calificadas), len(confiables), cobertura_confiable, ruta_salida
        ))
        logger.info(
            f"    {len(confiables)}/{len(calificadas)} regiones con precio confirmado, "
            f"{cobertura_confiable:.1%} cobertura confiable -> {ruta_salida}"
        )

    print("\n" + "=" * 80)
    print("RESUMEN")
    print("=" * 80)
    print(f"{'Tienda':<16} {'Folleto':<9} {'Pagina':<18} {'Candidatas':>10} {'ConPrecio':>10} {'Cobertura':>10}")
    print("-" * 80)
    for tienda, folleto_id, archivo, n_cand, n_conf, cob, _ in resumen:
        estado = "confiable" if n_conf > 0 else "sin senal de precio"
        print(f"{tienda:<16} {folleto_id:<9} {archivo:<18} {n_cand:>10} {n_conf:>10} {cob:>9.1%}  [{estado}]")
    print(f"\nImagenes de comparacion guardadas en: {SALIDA}")
    print("Verde = region con precio confirmado | Rojo = region sin precio confirmado")


if __name__ == "__main__":
    main()
