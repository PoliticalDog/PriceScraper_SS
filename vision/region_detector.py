# Deteccion de regiones (ROI) --> recuadros por producto
# Despues de procesar la iamgen --> solo se aplica a (walmart, chedraui, soriana_hiper, soriana_mercado) 

import logging
import cv2
import numpy as np

from nlp.regex_extractor import RegexExtractor

logger = logging.getLogger(__name__)

# Parametros con los que se filtran los contornos candidatos a "recuadro de producto"
AREA_MIN_FRACCION = 0.001   # descarta ruido muy pequeno (iconos, letras sueltas)
AREA_MAX_FRACCION = 0.5     # descarta contenedores casi del tamano de la pagina completa
RECTANGULARIDAD_MIN = 0.6   # area_contorno / area_bbox -- que tan "rectangular" es la forma

# Proporcion maxima (lado largo / lado corto) para aceptar una candidata. 
PROPORCION_MAX = 3.0

# Cualquiera de estos patrones dentro de la region cuenta como "hay precio aqui"
_PATRONES_PRECIO = (
    RegexExtractor.PATRON_PRECIO,
    RegexExtractor.PATRON_PRECIO_ANTERIOR,
    RegexExtractor.PATRON_AHORRO,
    RegexExtractor.PATRON_PRECIO_OCR_CORRUPTO,
)

# Fraccion minima del area del bbox de OCR que debe caer dentro de la region
# para considerar que ese bloque de texto "pertenece" a la region
SOLAPE_MIN_FRACCION = 0.5
DISPERSION_MAX_FRACCION = 0.5

# Detecta recuadros rectangulares candidatos en una imagen de folleto ya
# preprocesada, filtrando solo por geometria (area/rectangularidad/forma).
def detectar_regiones(imagen: np.ndarray) -> list[dict]:
    if imagen is None or imagen.size == 0:
        return []

    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if len(imagen.shape) == 3 else imagen
    alto, ancho = gris.shape[:2]
    area_total = alto * ancho
    if area_total == 0:
        return []

    bordes = cv2.Canny(gris, 50, 150)
    # cierra pequenos huecos en las lineas del recuadro antes de buscar contornos
    bordes = cv2.dilate(bordes, np.ones((3, 3), np.uint8), iterations=1)

    contornos, _ = cv2.findContours(bordes, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    area_min = area_total * AREA_MIN_FRACCION
    area_max = area_total * AREA_MAX_FRACCION

    candidatas = []
    for c in contornos:
        area = cv2.contourArea(c)
        if area < area_min or area > area_max:
            continue

        x, y, w, h = cv2.boundingRect(c)
        area_bbox = w * h
        if area_bbox == 0:
            continue

        # rectangularidad: que tanto del bounding box realmente ocupa el contorno
        rectangularidad = area / area_bbox
        if rectangularidad < RECTANGULARIDAD_MIN:
            continue

        # preferir formas con ~4 vertices (rectangulos), tolerando ligera distorsion
        perimetro = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * perimetro, True)
        if not (4 <= len(approx) <= 8):
            continue

        # descarta cajas desproporcionadamente anchas o altas -- tipicamente
        # dos o mas celdas de producto fusionadas por falta de borde entre ellas
        proporcion = max(w, h) / min(w, h) if min(w, h) > 0 else float("inf")
        if proporcion > PROPORCION_MAX:
            continue

        candidatas.append({"x": x, "y": y, "ancho": w, "alto": h})

    regiones = _quitar_anidadas(candidatas)
    logger.info(f"[RegionDetector] {len(regiones)} regiones candidatas (geometria)")
    return regiones # Retorna una lista de regiones {"x","y","ancho","alto"}

# True si al menos `umbral` del area del bbox de OCR cae dentro de la region.
def _bbox_dentro_de_region(bbox: dict, region: dict, umbral: float = SOLAPE_MIN_FRACCION) -> bool:
    x1, y1 = max(bbox["x"], region["x"]), max(bbox["y"], region["y"])
    x2 = min(bbox["x"] + bbox["ancho"], region["x"] + region["ancho"])
    y2 = min(bbox["y"] + bbox["alto"], region["y"] + region["alto"])
    inter = max(0, x2 - x1) * max(0, y2 - y1)

    area_bbox = bbox["ancho"] * bbox["alto"]
    if area_bbox == 0:
        return False
    return (inter / area_bbox) >= umbral


# True si algun bloque de OCR de la pagina (ya extraido, sin OCR adicional)
# cae dentro de la region y su texto coincide con un patron de precio.
def region_contiene_precio(region: dict, bloques_ocr: list[dict]) -> bool:
    for bloque in bloques_ocr:
        bbox = bloque.get("bbox")
        if not bbox or not _bbox_dentro_de_region(bbox, region):
            continue
        texto = bloque.get("texto", "")
        if any(patron.search(texto) for patron in _PATRONES_PRECIO):
            return True
    return False


def calificar_regiones(regiones: list[dict], bloques_ocr: list[dict]) -> list[dict]:
    calificadas = [
        {**region, "tiene_precio": region_contiene_precio(region, bloques_ocr)}
        for region in regiones
    ]
    con_precio = sum(1 for r in calificadas if r["tiene_precio"])
    logger.info(f"[RegionDetector] {con_precio}/{len(calificadas)} regiones con precio confirmado")
    return calificadas

# Solo las regiones que demuestran contener un precio -- utiles para asociar producto-precio
def filtrar_regiones_confiables(regiones_calificadas: list[dict]) -> list[dict]:
    return [r for r in regiones_calificadas if r.get("tiene_precio")]

# Elimina regiones que estan contenidas dentro de otras regiones
def _quitar_anidadas(regiones: list[dict]) -> list[dict]:
    def area(r):
        return r["ancho"] * r["alto"]

    def solapan(a, b, umbral=0.85):
        x1, y1 = max(a["x"], b["x"]), max(a["y"], b["y"])
        x2 = min(a["x"] + a["ancho"], b["x"] + b["ancho"])
        y2 = min(a["y"] + a["alto"], b["y"] + b["alto"])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        if inter == 0:
            return False
        return inter / min(area(a), area(b)) >= umbral

    ordenadas = sorted(regiones, key=area, reverse=True)
    resultado = []
    for r in ordenadas:
        if not any(solapan(r, otra) for otra in resultado):
            resultado.append(r)
    return resultado

# Devuelve True si el centro del bbox cae dentro de la region.
def _centro_dentro_de_region(bbox: dict, region: dict) -> bool:
    if not bbox:
        return False
    cx = bbox.get("x", 0) + bbox.get("ancho", 0) / 2
    cy = bbox.get("y", 0) + bbox.get("alto", 0) / 2
    return (
        region["x"] <= cx <= region["x"] + region["ancho"]
        and region["y"] <= cy <= region["y"] + region["alto"]
    )


def asociar_producto_por_region(precio: dict, productos: list[dict], regiones: list[dict]) -> dict | None:
    precio_bbox = precio.get("bbox", {})
    region_del_precio = next(
        (r for r in regiones if _centro_dentro_de_region(precio_bbox, r)), None
    )
    if region_del_precio is None:
        return None

    candidatos = [p for p in productos if _centro_dentro_de_region(p.get("bbox", {}), region_del_precio)]
    if not candidatos:
        return None
    if len(candidatos) == 1:
        return candidatos[0]

    centros_x = [p.get("bbox", {}).get("x", 0) + p.get("bbox", {}).get("ancho", 0) / 2 for p in candidatos]
    dispersion = (max(centros_x) - min(centros_x)) / region_del_precio["ancho"] if region_del_precio["ancho"] else 0
    if dispersion > DISPERSION_MAX_FRACCION:
        logger.debug("[RegionDetector] Candidatos dispersos en la region (posible fusion) -- se descarta ROI para este precio")
        return None

    precio_y = precio_bbox.get("y", 0)
    mejor, menor_dist = None, float("inf")
    for prod in candidatos:
        prod_y = prod.get("bbox", {}).get("y", 0)
        diff_y = precio_y - prod_y
        if 0 < diff_y < menor_dist:
            menor_dist = diff_y
            mejor = prod
    return mejor or candidatos[0]


def dibujar_regiones(imagen: np.ndarray, regiones: list[dict]) -> np.ndarray:
    copia = imagen.copy()
    if len(copia.shape) == 2:
        copia = cv2.cvtColor(copia, cv2.COLOR_GRAY2BGR)
    for r in regiones:
        x, y, w, h = r["x"], r["y"], r["ancho"], r["alto"]
        if "tiene_precio" in r:
            color = (0, 255, 0) if r["tiene_precio"] else (0, 0, 255)
        else:
            color = (0, 255, 0)
        cv2.rectangle(copia, (x, y), (x + w, y + h), color, 3)
    return copia
