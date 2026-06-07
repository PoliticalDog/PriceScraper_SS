# Orquestador de procesamiento de visión
# Preprocesamiento (OpenCV) + OCR (EasyOCR | Tesseract)
# El motor y el perfil de imagen se eligen explícitamente en cada sesión.

import sys
import logging
import json
import cv2
import numpy as np
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vision.preprocessor import obtener_preprocesador, Preprocessor
from vision.ocr_engine import OCREngine, MOTORES_DISPONIBLES

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))
file_handler = RotatingFileHandler(
    "logs/vision.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("vision")

sys.path.insert(0, str(Path(__file__).parent))

# ─────────────────────────────────────────────────────────────────────────────
# Rutas
# ─────────────────────────────────────────────────────────────────────────────
DATA_RAW       = Path("data/raw")
DATA_PROCESSED = Path("data/processed")

# ─────────────────────────────────────────────────────────────────────────────
# Menús
# ─────────────────────────────────────────────────────────────────────────────
def menu_principal() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper — Módulo de Visión")
    print("═" * 55)
    print("   1 → Procesar carpeta específica  (modo prueba)")
    print("   2 → Procesar todo data/raw/       (modo batch)")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_motor() -> str:
    """Selección del motor OCR."""
    print("\n" + "─" * 55)
    print("   Motor OCR:")
    print("   1. EasyOCR")
    print("   2. Tesseract")
    print("─" * 55)
    try:
        idx = int(input("   Motor (Enter = EasyOCR): ").strip() or "1")
        return MOTORES_DISPONIBLES[idx - 1]
    except (ValueError, IndexError):
        return "easyocr"


# Mapeo opción → nombre interno de perfil
_OPCIONES_PERFIL = [
    "color_suave",
    "color_normal",
    "color_fuerte",
    "bn_suave",
    "bn_normal",
    "bn_fuerte",
    "badge_normal",   # experimental — no aparece destacado en el menú
]

def menu_perfil(tienda: str = "") -> str:
    """Selección del perfil de preprocesamiento.

    Producción: opciones 1-6 (color y B/N).
    Experimental: opción 7 (badge_normal) — disponible pero no destacado.
    """
    print("\n" + "─" * 55)
    print("   Perfil de preprocesamiento:")
    print("   1. Color         - suave")
    print("   2. Color         - normal  ★ producción")
    print("   3. Color         - fuerte")
    print("   4. Blanco y Negro - suave")
    print("   5. Blanco y Negro - normal")
    print("   6. Blanco y Negro - fuerte")
    print("   7. Badge normal              [experimental]")
    print("─" * 55)
    try:
        raw = input("   Perfil (Enter = Color normal): ").strip()
        if not raw:
            return "color_normal"
        idx = int(raw) - 1
        return _OPCIONES_PERFIL[idx]
    except (ValueError, IndexError):
        return "color_normal"


def menu_resolucion() -> int | None:
    """Selección de resolución objetivo para escalado adaptativo.
    Solo aplica a perfiles v2 (color_* y bn_*).
    Retorna None si se elige el default.
    """
    print("\n" + "─" * 55)
    print("   Resolución objetivo (escalado adaptativo):")
    print("   1. 1200px  → más rápido, bueno para imágenes ya grandes")
    print("   2. 1350px  → default (benchmark base Bodega Aurrerá)")
    print("   3. 1500px  → recomendado para imágenes pequeñas")
    print("   4. 1800px  → máxima calidad, más lento")
    print("─" * 55)
    opciones = [1200, 1350, 1500, 1800]
    try:
        raw = input("   Resolución (Enter = 1350px): ").strip() or "2"
        idx = int(raw) - 1
        resolucion = opciones[idx]
        if resolucion == 1350:
            return None  # default, no necesita cambio
        return resolucion
    except (ValueError, IndexError):
        return None


def menu_carpeta() -> Path | None:
    carpetas = sorted([
        p for p in DATA_RAW.rglob("*")
        if p.is_dir() and list(p.glob("pagina_*.webp"))
    ])

    if not carpetas:
        logger.error("No se encontraron carpetas con imágenes en data/raw/")
        return None

    print("\n" + "─" * 55)
    print("   Folletos disponibles:")
    print(f"   {'#':>3}  {'RUTA':<45}  {'PÁG':>4}  {'ESTADO'}")
    print("─" * 55)

    for i, carpeta in enumerate(carpetas, 1):
        n        = len(list(carpeta.glob("pagina_*.webp")))
        ruta_rel = carpeta.relative_to(DATA_RAW)
        estado   = (
            "✅ procesado"
            if (DATA_PROCESSED / ruta_rel / "ocr_resultado.json").exists()
            else "pendiente"
        )
        print(f"   {i:>3}. {str(ruta_rel):<45}  {n:>4}  {estado}")

    print("─" * 55)
    try:
        idx = int(input("\n   Número de carpeta: ").strip())
        if 1 <= idx <= len(carpetas):
            return carpetas[idx - 1]
    except ValueError:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Procesamiento
# ─────────────────────────────────────────────────────────────────────────────
def procesar_carpeta(
    carpeta_raw:         Path,
    preprocessor:        Preprocessor,
    ocr:                 OCREngine,
    motor:               str,
    nombre_perfil:       str,
    forzar:              bool = False,
    guardar_comparacion: bool = False,
) -> dict | None:

    ruta_rel     = carpeta_raw.relative_to(DATA_RAW)
    carpeta_proc = DATA_PROCESSED / ruta_rel
    ruta_json    = carpeta_proc / "ocr_resultado.json"

    if ruta_json.exists() and not forzar:
        logger.info(f"[Vision] ⏭️  Ya procesado: {ruta_rel}")
        return None

    paginas = sorted(carpeta_raw.glob("pagina_*.webp"))
    if not paginas:
        logger.warning(f"[Vision] Sin páginas en {carpeta_raw}")
        return None

    carpeta_proc.mkdir(parents=True, exist_ok=True)
    logger.info(f"\n[Vision] Procesando: {ruta_rel} ({len(paginas)} páginas)")

    if guardar_comparacion:
        ruta_comp = carpeta_proc / "comparacion.jpg"
        preprocessor.guardar_comparacion(paginas[0], ruta_comp)
        logger.info(f"[Vision] 🖼️  Comparación: {ruta_comp}")

    resultado_folleto = {
        "fuente":        ruta_rel.parts[0] if len(ruta_rel.parts) > 0 else "",
        "tienda":        ruta_rel.parts[1] if len(ruta_rel.parts) > 1 else "",
        "folleto_id":    ruta_rel.parts[2] if len(ruta_rel.parts) > 2 else "",
        "motor_ocr":     motor,
        "perfil_imagen": nombre_perfil,
        "total_paginas": len(paginas),
        "paginas":       [],
    }

    total_bloques   = 0
    confianzas_prom = []

    for ruta_pagina in paginas:
        ruta_pagina_proc = carpeta_proc / ruta_pagina.name

        # Preprocesar y guardar
        preprocessor.procesar_y_guardar(ruta_pagina, ruta_pagina_proc)

        # Leer como ndarray para el motor OCR
        imagen_np = cv2.imread(str(ruta_pagina_proc))
        if imagen_np is None:
            logger.error(f"[Vision] 🛑 No se pudo leer: {ruta_pagina_proc}")
            continue

        # OCR con el motor elegido
        resultados_ocr = ocr.extraer_texto(imagen_np, motor=motor)

        conf_prom = (
            sum(r.confianza for r in resultados_ocr) / len(resultados_ocr)
            if resultados_ocr else 0.0
        )
        confianzas_prom.append(conf_prom)
        total_bloques += len(resultados_ocr)

        logger.info(
            f"[Vision] {ruta_pagina.name}: "
            f"{len(resultados_ocr)} bloques, confianza: {conf_prom:.0%}"
        )

        resultado_folleto["paginas"].append({
            "pagina":         ruta_pagina.name,
            "confianza_prom": round(conf_prom, 3),
            "bloques": [
                {
                    "texto":     r.texto,
                    "confianza": round(r.confianza, 3),
                    "bbox":      r.bbox_simple,
                    "motor":     r.motor,
                }
                for r in resultados_ocr
            ],
        })

    conf_global = (
        sum(confianzas_prom) / len(confianzas_prom) if confianzas_prom else 0
    )
    resultado_folleto["confianza_global"] = round(conf_global, 3)
    resultado_folleto["total_bloques"]    = total_bloques

    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(resultado_folleto, f, ensure_ascii=False, indent=2)

    logger.info(
        f"[Vision] ✅ {ruta_rel} → "
        f"{total_bloques} bloques, confianza: {conf_global:.0%}"
    )
    return resultado_folleto


# ─────────────────────────────────────────────────────────────────────────────
# Modos
# ─────────────────────────────────────────────────────────────────────────────
def modo_prueba(ocr: OCREngine):
    carpeta = menu_carpeta()
    if not carpeta:
        return

    motor         = menu_motor()
    nombre_perfil = menu_perfil()
    resolucion    = menu_resolucion()
    preprocessor  = obtener_preprocesador(nombre_perfil, ancho_objetivo=resolucion)

    res_str = f"{resolucion}px" if resolucion else "1350px (default)"
    logger.info(f"[Vision] Motor: {motor}  |  Perfil: {nombre_perfil}  |  Resolución: {res_str}")

    resultado = procesar_carpeta(
        carpeta_raw=carpeta,
        preprocessor=preprocessor,
        ocr=ocr,
        motor=motor,
        nombre_perfil=nombre_perfil,
        forzar=True,
        guardar_comparacion=True,
    )

    if resultado:
        print(f"\n{'─'*55}")
        print(f"  Folleto:         {resultado['tienda']} / {resultado['folleto_id']}")
        print(f"  Motor OCR:       {resultado['motor_ocr']}")
        print(f"  Perfil imagen:   {resultado['perfil_imagen']}")
        print(f"  Resolución obj:  {res_str}")
        print(f"  Páginas:         {resultado['total_paginas']}")
        print(f"  Bloques totales: {resultado['total_bloques']}")
        print(f"  Confianza OCR:   {resultado['confianza_global']:.0%}")
        print(f"{'─'*55}")
        print(f"\n  {'PÁGINA':<20} {'BLOQUES':>8} {'CONFIANZA':>10}")
        print(f"  {'─'*20} {'─'*8} {'─'*10}")
        for pag in resultado["paginas"]:
            print(
                f"  {pag['pagina']:<20} "
                f"{len(pag['bloques']):>8} "
                f"{pag['confianza_prom']:>9.0%}"
            )

        if resultado["confianza_global"] < 0.5:
            print(f"\n  ⚠️  Confianza baja ({resultado['confianza_global']:.0%})")
            if motor == "easyocr":
                print("     Prueba con 'color_normal' o 'color_fuerte'")
            else:
                print("     Prueba con 'bn_normal' o 'bn_fuerte'")


def modo_batch(ocr: OCREngine):
    carpetas = sorted([
        p for p in DATA_RAW.rglob("*")
        if p.is_dir() and list(p.glob("pagina_*.webp"))
    ])

    if not carpetas:
        logger.error("No se encontraron imágenes en data/raw/")
        return

    pendientes    = [
        c for c in carpetas
        if not (DATA_PROCESSED / c.relative_to(DATA_RAW) / "ocr_resultado.json").exists()
    ]
    ya_procesadas = len(carpetas) - len(pendientes)

    logger.info(f"\n[Vision] {len(carpetas)} folletos totales")
    logger.info(f"[Vision] ⏭️  {ya_procesadas} ya procesados")
    logger.info(f"[Vision] 🆕 {len(pendientes)} pendientes")

    if not pendientes:
        logger.info("[Vision] ✅ Todo procesado.")
        return

    motor         = menu_motor()
    nombre_perfil = menu_perfil()
    resolucion    = menu_resolucion()
    preprocessor  = obtener_preprocesador(nombre_perfil, ancho_objetivo=resolucion)

    res_str = f"{resolucion}px" if resolucion else "1500px (default)"
    print(f"\n  Motor: {motor}  |  Perfil: {nombre_perfil}  |  Resolución: {res_str}")
    print(f"  Se procesarán {len(pendientes)} folletos.")
    if input("  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    procesados    = 0
    total_bloques = 0
    errores       = 0

    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"\n[Vision] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_RAW)}")
        try:
            r = procesar_carpeta(
                carpeta_raw=carpeta,
                preprocessor=preprocessor,
                ocr=ocr,
                motor=motor,
                nombre_perfil=nombre_perfil,
                forzar=False,
            )
            if r:
                procesados    += 1
                total_bloques += r["total_bloques"]
        except Exception as e:
            logger.error(f"[Vision] Error: {e}")
            errores += 1

    logger.info("\n" + "=" * 55)
    logger.info(
        f"✅ Batch completado — {procesados} folletos, "
        f"{total_bloques} bloques, {errores} errores"
    )
    logger.info("=" * 55)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    logger.info("=" * 55)
    logger.info("PriceScraper — Módulo de Visión")
    logger.info("=" * 55)

    # OCREngine se instancia una sola vez — carga EasyOCR en memoria la primera vez
    ocr = OCREngine(idiomas=["es", "en"], usar_gpu=False)

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  👋 Saliendo...\n")
            break
        elif opcion == 1:
            modo_prueba(ocr)
        elif opcion == 2:
            modo_batch(ocr)
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