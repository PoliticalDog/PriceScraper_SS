#  clasifica cada bloque en PRODUCTO / PRECIO / PROMO / DESCARTE 
# y guarda nlp_resultado.json junto al folleto procesado


import sys
import json
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
    "logs/nlp.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
))
logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
logger = logging.getLogger("nlp")

sys.path.insert(0, str(Path(__file__).parent))

from nlp.regex_extractor import RegexExtractor

DATA_PROCESSED = Path("data/processed")


# ------------------------- Menús -------------------------

def menu_principal() -> int:
    print("\n" + "═" * 55)
    print("   PriceScraper — Módulo NLP (Regex)")
    print("═" * 55)
    print("   1 → Procesar carpeta específica  (modo prueba)")
    print("   2 → Procesar todo data/processed/ (modo batch)")
    print("   0 → Salir")
    print("─" * 55)
    try:
        return int(input("   Selecciona una opción: ").strip())
    except ValueError:
        return -1


def menu_carpeta() -> Path | None:
    """
    Lista todas las carpetas que tienen ocr_resultado.json disponible
    y permite elegir una para procesar.
    """
    carpetas = sorted([
        p.parent for p in DATA_PROCESSED.rglob("ocr_resultado.json")
    ])

    if not carpetas:
        logger.error("No se encontraron ocr_resultado.json en data/processed/")
        logger.error("Ejecuta primero: python probar_vision.py")
        return None

    print("\n" + "─" * 60)
    print("   Folletos con OCR disponible:")
    print(f"   {'#':>3}  {'RUTA':<45}  {'ESTADO NLP'}")
    print("─" * 60)

    for i, carpeta in enumerate(carpetas, 1):
        ruta_rel = carpeta.relative_to(DATA_PROCESSED)
        ya_procesado = (carpeta / "nlp_resultado.json").exists()
        estado = "✅ procesado" if ya_procesado else "pendiente"
        print(f"   {i:>3}. {str(ruta_rel):<45}  {estado}")

    print("─" * 60)
    try:
        idx = int(input("\n   Número de carpeta: ").strip())
        if 1 <= idx <= len(carpetas):
            return carpetas[idx - 1]
    except ValueError:
        pass
    logger.warning("Selección inválida.")
    return None


# ------------------------- Procesamiento de una carpeta -------------------------

def procesar_carpeta(
    carpeta: Path,
    extractor: RegexExtractor,
    forzar: bool = False,
    imprimir_detalle: bool = False,
) -> dict | None:
    """
    Procesa el ocr_resultado.json de un folleto y genera nlp_resultado.json.

    Args:
        carpeta:          Ruta a data/processed/{fuente}/{tienda}/{folleto_id}/
        extractor:        Instancia de RegexExtractor.
        forzar:           Si True, reprocesa aunque ya exista nlp_resultado.json.
        imprimir_detalle: Si True, imprime clasificación por página en consola.

    Returns:
        Dict con resumen del resultado, o None si se saltó.
    """
    ruta_ocr = carpeta / "ocr_resultado.json"
    ruta_nlp = carpeta / "nlp_resultado.json"

    if not ruta_ocr.exists():
        logger.warning(f"[NLP] Sin ocr_resultado.json en {carpeta}")
        return None

    if ruta_nlp.exists() and not forzar:
        logger.info(f"[NLP] ⏭️  Ya procesado: {carpeta.relative_to(DATA_PROCESSED)}")
        return None

    # ------------------------- Cargar OCR -------------------------
    with open(ruta_ocr, encoding="utf-8") as f:
        ocr_data = json.load(f)

    ruta_rel = carpeta.relative_to(DATA_PROCESSED)
    logger.info(f"\n[NLP] Procesando: {ruta_rel}")

    # El ocr_resultado.json tiene estructura:
    # { "fuente": ..., "tienda": ..., "folleto_id": ..., "paginas": [...] }
    # Cada página tiene { "pagina": ..., "bloques": [...] }
    paginas_ocr = ocr_data.get("paginas", [])

    if not paginas_ocr:
        logger.warning(f"[NLP] Sin páginas en {ruta_ocr}")
        return None

    # Adaptar formato para RegexExtractor
    # procesar_json_ocr espera: [{"imagen": ..., "bloques": [...], "ancho_pagina": ...}]
    # "ancho_pagina" es opcional (paginas de antes de este campo no lo traen; el
    # extractor asume el ancho de referencia y no cambia su comportamiento).
    datos_para_extractor = [
        {"imagen": p["pagina"], "bloques": p["bloques"], "ancho_pagina": p.get("ancho_pagina")}
        for p in paginas_ocr
    ]

    # ------------------------- Clasificar con Regex -------------------------
    resultados_paginas = extractor.procesar_json_ocr(datos_para_extractor)

    # ------------------------- Imprimir detalle si modo prueba -------------------------
    if imprimir_detalle:
        for r in resultados_paginas:
            extractor.imprimir_resultado(r)

    # ------------------------- Calcular métricas globales -------------------------
    total_prod       = sum(len(r.productos)          for r in resultados_paginas)
    total_prec       = sum(len(r.precios)            for r in resultados_paginas)
    total_prec_ant   = sum(len(r.precios_anteriores) for r in resultados_paginas)
    total_ahorros    = sum(len(r.ahorros)            for r in resultados_paginas)
    total_promo      = sum(len(r.promos)             for r in resultados_paginas)
    total_eventos    = sum(len(r.eventos_promo)      for r in resultados_paginas)
    total_attr       = sum(len(r.atributos)          for r in resultados_paginas)
    total_financiero = 0  # reservado
    total_desc       = sum(len(r.descartes)          for r in resultados_paginas)
    # Tasa útil: todo lo que no es descarte (incluye ahorros y eventos como info valiosa)
    total_util  = total_prod + total_prec + total_prec_ant + total_ahorros + total_promo + total_eventos + total_attr
    total       = total_util + total_desc
    tasa_util   = total_util / total if total > 0 else 0

    # ------------------------- Construir JSON de salida -------------------------
    resultado = {
        "fuente":        ocr_data.get("fuente", ""),
        "tienda":        ocr_data.get("tienda", ""),
        "folleto_id":    ocr_data.get("folleto_id", ""),
        "total_paginas": len(resultados_paginas),
        "resumen": {
            "total_productos":        total_prod,
            "total_precios":          total_prec,
            "total_precios_anterior": total_prec_ant,
            "total_ahorros":          total_ahorros,
            "total_financiero":       total_financiero,
            "total_promos":           total_promo,
            "total_eventos_promo":    total_eventos,
            "total_atributos":        total_attr,
            "total_descartes":        total_desc,
            "tasa_util":              round(tasa_util, 3),
        },
        "paginas": []
    }

    for r in resultados_paginas:
        resultado["paginas"].append({
            "pagina":    r.imagen,
            "productos": [
                {"texto": e.texto_norm, "confianza": e.confianza,
                 "bbox": e.bbox, "categoria": e.categoria}
                for e in r.productos
            ],
            "precios": [
                {"texto": e.texto_norm, "valor": e.valor,
                 "confianza": e.confianza, "bbox": e.bbox}
                for e in r.precios
            ],
            "precios_anteriores": [
                {"texto": e.texto_norm, "valor": e.valor,
                 "confianza": e.confianza, "bbox": e.bbox}
                for e in r.precios_anteriores
            ],
            "ahorros": [
                {"texto": e.texto_norm, "valor": e.valor,
                 "confianza": e.confianza, "bbox": e.bbox}
                for e in r.ahorros
            ],
            "financiero": [],  # reservado
            "promos": [
                {"texto": e.texto_norm, "confianza": e.confianza, "bbox": e.bbox}
                for e in r.promos
            ],
            "eventos_promo": [
                {"texto": e.texto_norm, "confianza": e.confianza, "bbox": e.bbox}
                for e in r.eventos_promo
            ],
            "atributos": [
                {"texto": e.texto_norm, "confianza": e.confianza,
                 "bbox": e.bbox, "categoria": e.categoria}
                for e in r.atributos
            ],
        })

    #  ------------------------- Guardar junto al folleto -------------------------
    with open(ruta_nlp, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    logger.info(
        f"[NLP] ✅ {ruta_rel} → "
        f"prod:{total_prod} prec:{total_prec} promo:{total_promo} "
        f"attr:{total_attr} desc:{total_desc} | tasa útil: {tasa_util:.0%}"
    )
    logger.info(f"[NLP] 💾 Guardado: {ruta_nlp}")

    return resultado


# ------------------------- Modos -------------------------

def modo_prueba(extractor: RegexExtractor):
    carpeta = menu_carpeta()
    if not carpeta:
        return

    resultado = procesar_carpeta(
        carpeta=carpeta,
        extractor=extractor,
        forzar=True,           # siempre reprocesar en modo prueba
        imprimir_detalle=True, # mostrar clasificación por página
    )

    if resultado:
        r = resultado["resumen"]
        print(f"\n{'─'*55}")
        print(f"  Folleto:     {resultado['tienda']} / {resultado['folleto_id']}")
        print(f"  Páginas:     {resultado['total_paginas']}")
        print(f"{'─'*55}")
        print(f"  ** Productos:          {r['total_productos']}")
        print(f"  ** Precios actuales:   {r['total_precios']}")
        print(f"  ** Precios anteriores: {r['total_precios_anterior']}")
        print(f"  ** Ahorros:            {r['total_ahorros']}")
        print(f"  ** Financiero:         {r['total_financiero']}")
        print(f"  ** Promociones:        {r['total_promos']}")
        print(f"  ** Eventos promo:      {r['total_eventos_promo']}")
        print(f"  ** Atributos:          {r['total_atributos']}")
        print(f"  **  Descartes:          {r['total_descartes']}")
        print(f"  ** Tasa útil:          {r['tasa_util']:.0%}")
        print(f"{'─'*55}")

        if r["tasa_util"] < 0.30:
            print(f"\n  WARNING:  Tasa útil baja ({r['tasa_util']:.0%})")
            print("     Revisar: calidad del OCR, keywords de producto,")
            print("     o umbrales de confianza en regex_extractor.py")


def modo_batch(extractor: RegexExtractor):
    carpetas = sorted([
        p.parent for p in DATA_PROCESSED.rglob("ocr_resultado.json")
    ])

    if not carpetas:
        logger.error("No se encontraron ocr_resultado.json en data/processed/")
        return

    pendientes    = [c for c in carpetas if not (c / "nlp_resultado.json").exists()]
    ya_procesadas = len(carpetas) - len(pendientes)

    logger.info(f"\n[NLP] {len(carpetas)} folletos con OCR disponible")
    logger.info(f"[NLP] ⏭️  {ya_procesadas} ya procesados con NLP")
    logger.info(f"[NLP] 🆕 {len(pendientes)} pendientes")

    if not pendientes:
        logger.info("[NLP] ✅ Todo está al día.")
        return

    print(f"\n  Se procesarán {len(pendientes)} folletos.")
    if input("  ¿Continuar? (s/n): ").strip().lower() != "s":
        return

    procesados       = 0
    total_prod       = 0
    total_prec       = 0
    total_prec_ant   = 0
    total_financiero = 0
    total_promo      = 0
    errores          = 0

    for i, carpeta in enumerate(pendientes, 1):
        logger.info(f"\n[NLP] [{i}/{len(pendientes)}] {carpeta.relative_to(DATA_PROCESSED)}")
        try:
            r = procesar_carpeta(carpeta, extractor, forzar=False)
            if r:
                procesados       += 1
                total_prod       += r["resumen"]["total_productos"]
                total_prec       += r["resumen"]["total_precios"]
                total_prec_ant   += r["resumen"]["total_precios_anterior"]
                total_financiero += r["resumen"]["total_financiero"]
                total_promo      += r["resumen"]["total_promos"]
        except Exception as e:
            logger.error(f"[NLP] Error en {carpeta}: {e}")
            errores += 1

    logger.info("\n" + "=" * 55)
    logger.info(f"✅ Batch NLP completado")
    logger.info(f"   Folletos procesados: {procesados}")
    logger.info(f"   Errores:             {errores}")
    logger.info(f"   Total productos:          {total_prod}")
    logger.info(f"   Total precios actuales:   {total_prec}")
    logger.info(f"   Total precios anteriores: {total_prec_ant}")
    logger.info(f"   Total financiero:         {total_financiero}")
    logger.info(f"   Total promociones:        {total_promo}")
    logger.info(f"   Próximo paso: ETL → asociar producto+precio por bbox → PostgreSQL")
    logger.info("=" * 55)


#  ------------------------- Main -------------------------

def main():
    logger.info("=" * 55)
    logger.info("PriceScraper MX — Módulo NLP (Regex)")
    logger.info("=" * 55)

    # Extractor se inicializa una vez para toda la sesión
    extractor = RegexExtractor(confianza_minima=0.15)

    while True:
        opcion = menu_principal()

        if opcion == 0:
            print("\n  ------ Saliendo...\n")
            break
        elif opcion == 1:
            modo_prueba(extractor)
        elif opcion == 2:
            modo_batch(extractor)
        else:
            print("  WARNING:  Opción no válida.")

        try:
            if input("\n  ¿Hacer otra operación? (s/n): ").strip().lower() != "s":
                print("\n  ------ Saliendo...\n")
                break
        except EOFError:
            break


if __name__ == "__main__":
    main()