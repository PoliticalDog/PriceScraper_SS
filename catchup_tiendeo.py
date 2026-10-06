# script que automatiza OCR+NLP de los folletos pendientes de una fuente (por defecto "tiendeo")
#
# Uso:
#   python catchup_tiendeo.py                        # tiendeo, CPU
#   python catchup_tiendeo.py --gpu                  # tiendeo, GPU
#   python catchup_tiendeo.py --gpu --fuente todas   # tiendeo + ofertomat, GPU

import argparse
import logging
from pathlib import Path

from vision.preprocessor import obtener_preprocesador, resolucion_para_tienda, perfil_para_tienda
from vision.ocr_engine import OCREngine
from nlp.regex_extractor import RegexExtractor

import probar_vision
import probar_nlp

logger = logging.getLogger("catchup_tiendeo")

DATA_RAW       = Path("data/raw")
DATA_PROCESSED = Path("data/processed")
FUENTES        = ["tiendeo", "ofertomat"]

# El perfil y la resolucion por tienda viven en vision/preprocessor.py (PERFIL_POR_TIENDA, RESOLUCION_POR_TIENDA)

def catchup_vision(fuente: str, usar_gpu: bool = False):
    carpetas = sorted([
        p for p in (DATA_RAW / fuente).rglob("*")
        if p.is_dir() and list(p.glob("pagina_*.webp"))
    ])
    pendientes = [
        c for c in carpetas
        if not (DATA_PROCESSED / c.relative_to(DATA_RAW) / "ocr_resultado.json").exists()
    ]

    logger.info(f"[Vision/{fuente}] {len(carpetas)} folletos totales, {len(pendientes)} pendientes")
    if not pendientes:
        logger.info(f"[Vision/{fuente}] Nada pendiente.")
        return

    ocr           = OCREngine(idiomas=["es", "en"], usar_gpu=usar_gpu)
    # Un preprocesador por (perfil, ancho_objetivo) distinto (cache), en vez de uno solo
    # para todo el batch, porque cada tienda puede usar un perfil y una resolucion distintos.
    preprocesadores = {}

    def preprocesador_para(tienda: str):
        clave = (perfil_para_tienda(tienda), resolucion_para_tienda(tienda))
        if clave not in preprocesadores:
            preprocesadores[clave] = obtener_preprocesador(clave[0], ancho_objetivo=clave[1])
        return preprocesadores[clave]

    procesados, total_bloques, errores = 0, 0, 0
    for i, carpeta in enumerate(pendientes, 1):
        tienda = carpeta.relative_to(DATA_RAW / fuente).parts[0]
        nombre_perfil = perfil_para_tienda(tienda)
        preprocessor = preprocesador_para(tienda)
        logger.info(f"[Vision/{fuente}] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_RAW)}")
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
            logger.error(f"[Vision/{fuente}] Error en {carpeta}: {e}")
            errores += 1

    logger.info(
        f"[Vision/{fuente}] Completado — {procesados} folletos, "
        f"{total_bloques} bloques, {errores} errores"
    )


def catchup_nlp(fuente: str):
    carpetas = sorted([
        p.parent for p in (DATA_PROCESSED / fuente).rglob("ocr_resultado.json")
    ])
    pendientes = [c for c in carpetas if not (c / "nlp_resultado.json").exists()]

    logger.info(f"[NLP/{fuente}] {len(carpetas)} folletos con OCR, {len(pendientes)} pendientes de NLP")
    if not pendientes:
        logger.info(f"[NLP/{fuente}] Nada pendiente.")
        return

    extractor = RegexExtractor(confianza_minima=0.15)

    procesados, errores = 0, 0
    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"[NLP/{fuente}] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_PROCESSED)}")
        try:
            r = probar_nlp.procesar_carpeta(carpeta, extractor, forzar=False)
            if r:
                procesados += 1
        except Exception as e:
            logger.error(f"[NLP/{fuente}] Error en {carpeta}: {e}")
            errores += 1

    logger.info(f"[NLP/{fuente}] Completado — {procesados} folletos, {errores} errores")


def main():
    ap = argparse.ArgumentParser(description="Catch-up OCR+NLP de folletos pendientes")
    ap.add_argument("--fuente", choices=FUENTES + ["todas"], default="tiendeo")
    ap.add_argument("--gpu", action="store_true", help="EasyOCR en GPU (requiere torch con CUDA)")
    a = ap.parse_args()
    fuentes = FUENTES if a.fuente == "todas" else [a.fuente]

    if a.gpu:
        import torch
        if not torch.cuda.is_available():
            raise SystemExit("ERROR: --gpu pedido pero torch.cuda.is_available() es False.")

    logger.info("=" * 55)
    logger.info(f"Catch-up OCR+NLP — fuentes: {', '.join(fuentes)}  |  GPU: {a.gpu}")
    logger.info("=" * 55)
    for fuente in fuentes:
        catchup_vision(fuente, usar_gpu=a.gpu)
        catchup_nlp(fuente)
    logger.info("=" * 55)
    logger.info("Catch-up terminado.")
    logger.info("=" * 55)


if __name__ == "__main__":
    main()
