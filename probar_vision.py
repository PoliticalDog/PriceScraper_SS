# Orquestador de procesamiento de visión
# Preprocesamiento (OpenCV) --> OCR (EasyOCR o Tesseract) --> JSON
# El motor y el perfil se eligen en cada corrida

import sys
import logging
import json
import cv2
import numpy as np
from logging.handlers import RotatingFileHandler
from pathlib import Path

from vision.preprocessor import obtener_preprocesador, Preprocessor, resolucion_para_tienda, perfil_para_tienda
from vision.ocr_engine import OCREngine, MOTORES_DISPONIBLES

# configuración de logging
Path("logs").mkdir(exist_ok=True)

# logging a consola
console_handler = logging.StreamHandler()
# Formato log: hora-fecha, nivel, nombre logger, mensaje, HH:MM:SS
console_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"
))

# logging a archivo
file_handler = RotatingFileHandler(
    "logs/vision.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
# Formato log: año-mes-día, hora, nivel, nombre logger, mensaje
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("vision")

sys.path.insert(0, str(Path(__file__).parent))

# Rutas
DATA_RAW       = Path("data/raw")
DATA_PROCESSED = Path("data/processed")

# Mapeo opción --> nombre interno de perfil
_OPCIONES_PERFIL = [
    "color_suave",
    "color_normal",
    "color_fuerte",
    "bn_suave",
    "bn_normal",
    "bn_fuerte",
]

# ---------------- Menús de consola ----------------
def menu_principal() -> int:
    print("\n" + "-" * 55)
    print("   PriceScraper — Módulo de Visión")
    print("-" * 55)
    print("   1 --> Procesar carpeta específica  (modo prueba)")
    print("   2 --> Procesar todo data/raw/       (modo batch)")
    print("   0 --> Salir")
    print("-" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1

# Menú motor OCR 
def menu_motor() -> str:
    print("\n" + "-" * 55)
    print("   Motor OCR:")
    print("   1. EasyOCR")
    print("   2. Tesseract")
    print("-" * 55)
    try:
        opc = int(input("   Motor (Enter = EasyOCR): ") or "1")
        return MOTORES_DISPONIBLES[opc - 1]
    except (ValueError, IndexError):
        return "easyocr"

# Menú perfil
def menu_perfil(tienda: str = "") -> str | None:
    print("\n" + "-" * 55)
    print("   Perfil de preprocesamiento:")
    print("   1. Color         - suave")
    print("   2. Color         - normal  (default global)")
    print("   3. Color         - fuerte")
    print("   4. Blanco y Negro - suave")
    print("   5. Blanco y Negro - normal")
    print("   6. Blanco y Negro - fuerte")
    print("   Enter --> el de cada tienda (PERFIL_POR_TIENDA, Color normal si no aparece)")
    print("-" * 55)
    try:
        raw = input("   Perfil (Enter = por tienda): ").strip()
        if not raw:
            return None  # None --> perfil por tienda
        opc = int(raw) - 1
        return _OPCIONES_PERFIL[opc]
    except (ValueError, IndexError):
        return None

# Menú resolución px
def menu_resolucion() -> int | None:
    print("\n" + "-" * 55)
    print("   Resolución objetivo (escalado adaptativo):")
    print("   1. 1200px  --> (mejor para imagenes grandes)")
    print("   2. 1350px   ")
    print("   3. 1500px  --> (mejor para imágenes pequeñas)")
    print("   4. 1800px --> mejor resultado promedio (default global)")
    print("   Enter --> la mejor de cada tienda (RESOLUCION_POR_TIENDA)")
    print("-" * 55)
    opciones = [1200, 1350, 1500, 1800]
    try:
        raw = input("   Resolución (Enter = por tienda): ").strip()
        if not raw:
            return None  # None --> resolución por tienda
        return opciones[int(raw) - 1]
    except (ValueError, IndexError):
        return None

# Recopilación de carpetas
def menu_carpeta() -> Path | None:
    carpetas = sorted([ 
        p for p in DATA_RAW.rglob("*") # rglob busca recursivamente en subcarpetas
        if p.is_dir() and list(p.glob("pagina_*.webp")) # solo carpetas que contengan al menos una imagen
    ])

    # No se hallo nada
    if not carpetas:
        logger.error("No se encontraron carpetas con imágenes en data/raw/")
        return None

    # Regresa un menú de todas las carpetas | Procesas y pendientes
    print("\n" + "-" * 55)
    print("   Folletos disponibles:")
    print(f"   {'#':>3}  {'RUTA':<45}  {'PÁG':>4}  {'ESTADO'}") # estilo en forma de tabla
    print("-" * 55)

    # Enumerar carpetas y mostrar estado de procesamiento
    for i, carpeta in enumerate(carpetas, 1):
        # paginas por carpeta
        n = len(list(carpeta.glob("pagina_*.webp")))
        ruta_rel = carpeta.relative_to(DATA_RAW)
        # impresión de estado - si existe el archivo ocr_resultado.json
        if (DATA_PROCESSED / ruta_rel / "ocr_resultado.json").exists():
            estado = "✅ procesado"
        else:
            estado = "pendiente"
        print(f"   {i:>3}. {str(ruta_rel):<45}  {n:>4}  {estado}")

    print("-" * 55)
    try:
        opc = int(input("\n   Número de carpeta: ").strip())
        if 1 <= opc <= len(carpetas):
            return carpetas[opc - 1]
    except ValueError:
        pass
    return None


#  ------------------- Procesamiento -------------------

# Procesamiento de una carpeta (folleto) completa
def procesar_carpeta(
    carpeta_raw:         Path,          # imagenes originales
    preprocessor:        Preprocessor,  # recibe la clase prinicpal preprocesador del modulo preprocessor.py
    ocr:                 OCREngine,     # recibe la clase principal del modulo ocr_engine.py
    motor:               str,
    nombre_perfil:       str,
    forzar:              bool = False,
    guardar_comparacion: bool = False,
) -> dict | None:

    # ----- Preparar rutas de salida -----
    ruta_rel     = carpeta_raw.relative_to(DATA_RAW)
    carpeta_proc = DATA_PROCESSED / ruta_rel
    ruta_json    = carpeta_proc / "ocr_resultado.json"

    # Si ya existe el JSON y no se fuerza, se salta el procesamiento
    if ruta_json.exists() and not forzar:
        logger.info(f"[Vision] ⏭️  Ya procesado: {ruta_rel}")
        return None

    # Buscar todas las páginas (imagenes) en la carpeta
    paginas = sorted(carpeta_raw.glob("pagina_*.webp"))
    if not paginas:
        logger.warning(f"[Vision] Sin páginas en {carpeta_raw}")
        return None

    # Crear carpeta de salida si no existe
    carpeta_proc.mkdir(parents=True, exist_ok=True) # parents=True crea subcarpetas si no existen
    logger.info(f"\n[Vision] Procesando: {ruta_rel} ({len(paginas)} páginas)")

    #  ----- Guardar imagen de comparación (ya solo aplica para una sola capreta manual) -----
    if guardar_comparacion:
        ruta_comp = carpeta_proc / "comparacion.jpg"
        preprocessor.guardar_comparacion(paginas[0], ruta_comp)
        logger.info(f"[Vision] IMAGEN  Comparación: {ruta_comp}")

    # ----- Inicializar motor OCR -----
    # Inicializar resultado final
    resultado_folleto = {
        "fuente":        ruta_rel.parts[0] if len(ruta_rel.parts) > 0 else "",
        "tienda":        ruta_rel.parts[1] if len(ruta_rel.parts) > 1 else "",
        "folleto_id":    ruta_rel.parts[2] if len(ruta_rel.parts) > 2 else "",
        "motor_ocr":     motor,
        "perfil_imagen": nombre_perfil,
        "total_paginas": len(paginas),
        "paginas":       [],
    }

    #  ----- Metrcias globales -----
    total_bloques   = 0
    confianzas_prom = []

    # Procesa cada pagina de una carpeta (folleto) y guarda resultados en JSON
    # pagina tiene 
    for ruta_pagina in paginas:
        ruta_pagina_proc = carpeta_proc / ruta_pagina.name

        # Preprocesar y guardar
        preprocessor.procesar_y_guardar(ruta_pagina, ruta_pagina_proc)

        # Leer  para el motor OCR
        imagen_np = cv2.imread(str(ruta_pagina_proc))
        if imagen_np is None:
            logger.error(f"[Vision] XX No se pudo leer: {ruta_pagina_proc}")
            continue

        # OCR con el motor elegido
        # resultados_ocr regresa una lista con [texto, confianza, bbox, y motor]
        resultados_ocr = ocr.extraer_texto(imagen_np, motor=motor)

        # Calcular confianza promedio y total de bloques
        conf_prom = (
            sum(r.confianza for r in resultados_ocr) / len(resultados_ocr)
            if resultados_ocr else 0.0
        )
        # apilca los resultados para el global
        confianzas_prom.append(conf_prom)
        total_bloques += len(resultados_ocr)

        logger.info(
            f"[Vision] {ruta_pagina.name}: "
            f"{len(resultados_ocr)} bloques, confianza: {conf_prom:.0%}"
        )

        # Guardar resultados de la página en el JSON
        resultado_folleto["paginas"].append({
            "pagina":         ruta_pagina.name,
            "ancho_pagina":   imagen_np.shape[1],  # px reales tras preprocesar
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
        f"[Vision] ✅ {ruta_rel} --> "
        f"{total_bloques} bloques, confianza: {conf_global:.0%}"
    )
    return resultado_folleto


# ----------------------- Unitario o batch -----------------------

# Procesamieno batch (todas las carpetas en data/raw)
def modo_batch(ocr: OCREngine):

    # Recopilar carpetas con imágenes y las ordena por nombre
    carpetas = sorted([
        p for p in DATA_RAW.rglob("*")
        if p.is_dir() and list(p.glob("pagina_*.webp"))
    ])

    if not carpetas:
        logger.error("No se encontraron imágenes en data/raw/")
        return

    # Filtra carpetas que ya tienen el JSON de resultado
    pendientes    = [
        c for c in carpetas
        if not (DATA_PROCESSED / c.relative_to(DATA_RAW) / "ocr_resultado.json").exists()
    ]
    ya_procesadas = len(carpetas) - len(pendientes)

    logger.info(f"\n[Vision] {len(carpetas)} folletos totales")
    logger.info(f"[Vision] ⏭️  {ya_procesadas} ya procesados")
    logger.info(f"[Vision] 🆕 {len(pendientes)} pendientes")

    # Si no hay pendientes, termina
    if not pendientes:
        logger.info("[Vision] ✅ Todo procesado.")
        return

    # Menú de motor, perfil y resolución
    motor         = menu_motor()
    nombre_perfil = menu_perfil()
    resolucion    = menu_resolucion()

    # Enter (default) --> cada tienda usa su perfil y su resolución (PERFIL_POR_TIENDA y RESOLUCION_POR_TIENDA;
    # color_normal y 1800px si no aparece). Elegir uno explícito lo fuerza para todo el batch
    def config_para(carpeta: Path) -> tuple[str, Preprocessor]:
        ruta_rel = carpeta.relative_to(DATA_RAW).parts
        tienda   = ruta_rel[1] if len(ruta_rel) > 1 else ""
        perfil   = nombre_perfil or perfil_para_tienda(tienda)
        ancho    = resolucion or resolucion_para_tienda(tienda)
        return perfil, obtener_preprocesador(perfil, ancho_objetivo=ancho)

    perfil_str = nombre_perfil or "por tienda (color_normal default)"
    res_str = f"{resolucion}px" if resolucion else "por tienda (1800px default)"
    print(f"\n  Motor: {motor}  |  Perfil: {perfil_str}  |  Resolución: {res_str}")
    print(f"  Se procesarán {len(pendientes)} folletos.")
    if input("  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    # contadores de métricas globales
    procesados    = 0
    total_bloques = 0
    errores       = 0

    # Procesamiento de cada carpeta pendiente
    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"\n[Vision] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_RAW)}")
        try:
            perfil, preprocessor = config_para(carpeta)
            r = procesar_carpeta(
                carpeta_raw=carpeta,
                preprocessor=preprocessor,
                ocr=ocr,
                motor=motor,
                nombre_perfil=perfil,
                forzar=False,
                guardar_comparacion=True,   # ← esto es todo
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

# procesameinto unitario (carpeta)
def modo_prueba(ocr: OCREngine):
    carpeta = menu_carpeta()
    if not carpeta:
        return

    motor         = menu_motor()
    nombre_perfil = menu_perfil()
    resolucion    = menu_resolucion()

    # Enter --> perfil y resolución de la tienda del folleto (color_normal y 1800px si la tienda no aparece)
    ruta_rel = carpeta.relative_to(DATA_RAW).parts
    tienda   = ruta_rel[1] if len(ruta_rel) > 1 else ""
    perfil   = nombre_perfil or perfil_para_tienda(tienda)
    ancho    = resolucion or resolucion_para_tienda(tienda)
    preprocessor  = obtener_preprocesador(perfil, ancho_objetivo=ancho)

    # perfil/resolucion_str para mostrar en consola
    perfil_str = perfil + ("" if nombre_perfil else f" (por tienda: {tienda})")
    res_str = f"{preprocessor.ancho_objetivo}px" + ("" if resolucion else f" (por tienda: {tienda})")
    logger.info(f"[Vision] Motor: {motor}  |  Perfil: {perfil_str}  |  Resolución: {res_str}")

    resultado = procesar_carpeta(
        carpeta_raw=carpeta,
        preprocessor=preprocessor,
        ocr=ocr,
        motor=motor,
        nombre_perfil=perfil,
        forzar=True,
        guardar_comparacion=True,
    )

    if resultado:
        print(f"\n{'-'*55}")
        print(f"  Folleto:         {resultado['tienda']} / {resultado['folleto_id']}")
        print(f"  Motor OCR:       {resultado['motor_ocr']}")
        print(f"  Perfil imagen:   {resultado['perfil_imagen']}")
        print(f"  Resolución obj:  {res_str}")
        print(f"  Páginas:         {resultado['total_paginas']}")
        print(f"  Bloques totales: {resultado['total_bloques']}")
        print(f"  Confianza OCR:   {resultado['confianza_global']:.0%}")
        print(f"{'-'*55}")
        print(f"\n  {'PÁGINA':<20} {'BLOQUES':>8} {'CONFIANZA':>10}")
        print(f"  {'-'*20} {'-'*8} {'-'*10}")
        for pag in resultado["paginas"]:
            print(
                f"  {pag['pagina']:<20} "
                f"{len(pag['bloques']):>8} "
                f"{pag['confianza_prom']:>9.0%}"
            )

        if resultado["confianza_global"] < 0.5:
            print(f"\n  X  Confianza baja ({resultado['confianza_global']:.0%})")
            if motor == "easyocr":
                print("     Prueba con 'color_normal' o 'color_fuerte'")
            else:
                print("     Prueba con 'bn_normal' o 'bn_fuerte'")

# ----------------------- Main -----------------------
def main():
    logger.info("=" * 55)
    logger.info("PriceScraper — Módulo de Visión")
    logger.info("=" * 55)

    # OCREngine se instancia una sola vez — carga EasyOCR en memoria la primera vez
    ocr = OCREngine(idiomas=["es", "en"], usar_gpu=False)

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  ------------ Saliendo...\n")
            break
        elif opcion == 1:
            modo_prueba(ocr)
        elif opcion == 2:
            modo_batch(ocr)
        else:
            print("  X  Opción no válida.")

        try:
            if input("\n  ¿Hacer otra operación? (s/n): ").strip().lower() != "s":
                print("\n  ------------ Saliendo...\n")
                break
        except EOFError:
            break


if __name__ == "__main__":
    main()