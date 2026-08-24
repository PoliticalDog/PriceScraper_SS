# Revision manual de una muestra de "desacuerdos reales" del benchmark
# hibrido (probar_hibrido_roi.py): casos donde AMBOS metodos (distancia y
# ROI) encontraron un producto, pero uno DISTINTO. No incluye los casos de
# "mejora" (donde distancia no encontraba nada) -- esos no son ambiguos.
#
# Para cada caso de la muestra, dibuja sobre la pagina completa:
#   - precio: amarillo
#   - producto elegido por distancia bbox: azul
#   - producto elegido por ROI: verde
# y guarda un recorte alrededor de la zona relevante para inspeccion visual,
# junto con un log de texto con el contenido de cada bloque.
#
# No modifica load/load.py ni el benchmark principal -- es una herramienta
# de apoyo para decidir si el metodo hibrido es confiable en los casos donde
# discrepa del metodo actual.

import json
import logging
import random
from pathlib import Path

import cv2

from vision.preprocessor import obtener_preprocesador
from vision.region_detector import detectar_regiones, calificar_regiones, asociar_producto_por_region
from probar_hibrido_roi import (
    TIENDAS_GRID_FRIENDLY, DATA_RAW, DATA_PROCESSED, enumerar_folletos, _asociar_por_distancia,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("revisar_desacuerdos")

SALIDA = Path("data/processed/_v7_hibrido_roi_asociacion/muestra_desacuerdos")
MUESTRAS_POR_TIENDA = 4
SEED = 42
MARGEN_RECORTE = 150  # px alrededor de la zona relevante, para dar contexto visual


def _bbox_a_rect(bbox: dict) -> tuple[int, int, int, int]:
    x, y, w, h = bbox.get("x", 0), bbox.get("y", 0), bbox.get("ancho", 0), bbox.get("alto", 0)
    return x, y, x + w, y + h


def main():
    preprocesador = obtener_preprocesador("color_normal")
    SALIDA.mkdir(parents=True, exist_ok=True)

    casos_por_tienda: dict[str, list] = {t: [] for t in TIENDAS_GRID_FRIENDLY}

    for tienda in TIENDAS_GRID_FRIENDLY:
        for folleto_id, ruta_nlp in enumerar_folletos(tienda):
            with open(ruta_nlp, encoding="utf-8") as f:
                nlp = json.load(f)

            for pag in nlp.get("paginas", []):
                nombre_pag = pag.get("pagina", "")
                productos = pag.get("productos", [])
                precios = pag.get("precios", [])
                if not precios:
                    continue

                ruta_imagen = DATA_RAW / tienda / folleto_id / nombre_pag
                if not ruta_imagen.exists():
                    continue

                imagen_proc = preprocesador.procesar(ruta_imagen)
                candidatas = detectar_regiones(imagen_proc)
                bloques_precio = [{"texto": p.get("texto", ""), "bbox": p.get("bbox", {})} for p in precios]
                regiones = calificar_regiones(candidatas, bloques_precio)
                regiones_confiables = [r for r in regiones if r["tiene_precio"]]

                for precio in precios:
                    prod_distancia = _asociar_por_distancia(precio, productos)
                    prod_roi = asociar_producto_por_region(precio, productos, regiones_confiables)

                    if prod_roi is None or prod_distancia is None:
                        continue  # solo nos interesan desacuerdos reales (ambos encontraron algo)
                    if prod_roi.get("bbox") == prod_distancia.get("bbox"):
                        continue  # coinciden, no es desacuerdo

                    casos_por_tienda[tienda].append({
                        "tienda": tienda, "folleto_id": folleto_id, "pagina": nombre_pag,
                        "imagen_proc": imagen_proc, "precio": precio,
                        "prod_distancia": prod_distancia, "prod_roi": prod_roi,
                    })

    random.seed(SEED)
    resumen_txt = []
    total_guardados = 0

    for tienda, casos in casos_por_tienda.items():
        if not casos:
            logger.warning(f"Sin desacuerdos reales para {tienda}")
            continue
        muestra = random.sample(casos, min(MUESTRAS_POR_TIENDA, len(casos)))

        for i, caso in enumerate(muestra, start=1):
            img = caso["imagen_proc"].copy()
            precio, pd, pr = caso["precio"], caso["prod_distancia"], caso["prod_roi"]

            for bbox, color, etiqueta in [
                (precio.get("bbox", {}), (0, 255, 255), "PRECIO"),
                (pd.get("bbox", {}), (255, 0, 0), "DIST"),
                (pr.get("bbox", {}), (0, 200, 0), "ROI"),
            ]:
                x1, y1, x2, y2 = _bbox_a_rect(bbox)
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 4)
                cv2.putText(img, etiqueta, (x1, max(0, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 1.1, color, 3)

            todas_x = [b.get("bbox", {}).get("x", 0) for b in (precio, pd, pr)]
            todas_x2 = [b.get("bbox", {}).get("x", 0) + b.get("bbox", {}).get("ancho", 0) for b in (precio, pd, pr)]
            todas_y = [b.get("bbox", {}).get("y", 0) for b in (precio, pd, pr)]
            todas_y2 = [b.get("bbox", {}).get("y", 0) + b.get("bbox", {}).get("alto", 0) for b in (precio, pd, pr)]
            alto, ancho = img.shape[:2]
            x1 = max(0, min(todas_x) - MARGEN_RECORTE)
            y1 = max(0, min(todas_y) - MARGEN_RECORTE)
            x2 = min(ancho, max(todas_x2) + MARGEN_RECORTE)
            y2 = min(alto, max(todas_y2) + MARGEN_RECORTE)
            recorte = img[y1:y2, x1:x2]

            nombre = f"{tienda}_{caso['folleto_id']}_{caso['pagina'].replace('.webp','')}_{i}.jpg"
            cv2.imwrite(str(SALIDA / nombre), recorte)
            total_guardados += 1

            resumen_txt.append(
                f"{nombre}\n"
                f"  precio texto:          '{precio.get('texto','')}'\n"
                f"  producto (DISTANCIA):  '{pd.get('texto','')}' (categoria={pd.get('categoria','')})\n"
                f"  producto (ROI):        '{pr.get('texto','')}' (categoria={pr.get('categoria','')})\n"
            )

    ruta_resumen = SALIDA / "muestra_resumen.txt"
    with open(ruta_resumen, "w", encoding="utf-8") as f:
        f.write("\n".join(resumen_txt))

    print(f"{total_guardados} imagenes de muestra guardadas en {SALIDA}")
    print(f"Resumen de texto en {ruta_resumen}")


if __name__ == "__main__":
    main()
