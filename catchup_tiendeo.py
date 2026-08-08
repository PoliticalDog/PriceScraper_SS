# Catch-up dirigido de OCR+NLP SOLO para la fuente "tiendeo".
# Reusa la logica de probar_vision.py / probar_nlp.py (mismos parametros de
# produccion: easyocr + color_normal + resolucion default 1500px) pero
# filtra data/raw/ y data/processed/ a fuente == "tiendeo" y corre sin
# prompts interactivos, para poder lanzarse en background.
#
# Decision del usuario (06-ago-2026): "ofertomat" queda pausado a proposito,
# no tocar hasta que se pida explicitamente.

import logging
from pathlib import Path

from vision.preprocessor import obtener_preprocesador
from vision.ocr_engine import OCREngine
from nlp.regex_extractor import RegexExtractor

import probar_vision
import probar_nlp

logger = logging.getLogger("catchup_tiendeo")

DATA_RAW       = Path("data/raw")
DATA_PROCESSED = Path("data/processed")
FUENTE         = "tiendeo"


def catchup_vision():
    carpetas = sorted([
        p for p in (DATA_RAW / FUENTE).rglob("*")
        if p.is_dir() and list(p.glob("pagina_*.webp"))
    ])
    pendientes = [
        c for c in carpetas
        if not (DATA_PROCESSED / c.relative_to(DATA_RAW) / "ocr_resultado.json").exists()
    ]

    logger.info(f"[Vision/{FUENTE}] {len(carpetas)} folletos totales, {len(pendientes)} pendientes")
    if not pendientes:
        logger.info(f"[Vision/{FUENTE}] Nada pendiente.")
        return

    ocr           = OCREngine(idiomas=["es", "en"], usar_gpu=False)
    nombre_perfil = "color_normal"
    preprocessor  = obtener_preprocesador(nombre_perfil, ancho_objetivo=None)

    procesados, total_bloques, errores = 0, 0, 0
    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"[Vision/{FUENTE}] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_RAW)}")
        try:
            r = probar_vision.procesar_carpeta(
                carpeta_raw=carpeta,
                preprocessor=preprocessor,
                ocr=ocr,
                motor="easyocr",
                nombre_perfil=nombre_perfil,
                forzar=False,
                guardar_comparacion=True,
            )
            if r:
                procesados    += 1
                total_bloques += r["total_bloques"]
        except Exception as e:
            logger.error(f"[Vision/{FUENTE}] Error en {carpeta}: {e}")
            errores += 1

    logger.info(
        f"[Vision/{FUENTE}] Completado — {procesados} folletos, "
        f"{total_bloques} bloques, {errores} errores"
    )


def catchup_nlp():
    carpetas = sorted([
        p.parent for p in (DATA_PROCESSED / FUENTE).rglob("ocr_resultado.json")
    ])
    pendientes = [c for c in carpetas if not (c / "nlp_resultado.json").exists()]

    logger.info(f"[NLP/{FUENTE}] {len(carpetas)} folletos con OCR, {len(pendientes)} pendientes de NLP")
    if not pendientes:
        logger.info(f"[NLP/{FUENTE}] Nada pendiente.")
        return

    extractor = RegexExtractor(confianza_minima=0.15)

    procesados, errores = 0, 0
    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"[NLP/{FUENTE}] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_PROCESSED)}")
        try:
            r = probar_nlp.procesar_carpeta(carpeta, extractor, forzar=False)
            if r:
                procesados += 1
        except Exception as e:
            logger.error(f"[NLP/{FUENTE}] Error en {carpeta}: {e}")
            errores += 1

    logger.info(f"[NLP/{FUENTE}] Completado — {procesados} folletos, {errores} errores")


def main():
    logger.info("=" * 55)
    logger.info(f"Catch-up OCR+NLP — fuente restringida: {FUENTE}")
    logger.info("=" * 55)
    catchup_vision()
    catchup_nlp()
    logger.info("=" * 55)
    logger.info("Catch-up tiendeo terminado.")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
