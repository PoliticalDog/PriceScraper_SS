# Benchmark hibrido: ROI vs distancia bbox para asociacion producto-precio.
# Fase 2 del plan de mejora de OCR -- responde la pregunta pendiente de
# sources/vision/05_benchmark_roi_deteccion_regiones.md: ya sabemos que ROI
# detecta regiones confiables sobre todo en tiendas con layout de grid; esto
# mide si USARLO cambia (mejora) la asociacion producto-precio en esas
# tiendas, comparado contra el metodo actual de load/load.py (distancia bbox).
#
# NO vuelve a correr OCR/EasyOCR: reutiliza los nlp_resultado.json que ya
# existen en data/processed/tiendeo (productos y precios con bbox, generados
# por el pipeline de produccion). Solo corre deteccion de regiones (OpenCV,
# sin GPU) sobre la imagen original de cada pagina.
#
# Metodo HIBRIDO: para cada precio, si cae dentro de una region que tambien
# contiene un producto, se asocia por ROI. Si no, fallback al metodo de
# distancia (replica exacta de Loader._asociar_producto en load/load.py).
#
# No modifica load/load.py ni la base de datos -- es solo para decidir si
# vale la pena integrar el hibrido al pipeline real.

import argparse
import csv
import json
import logging
from pathlib import Path

from vision.preprocessor import obtener_preprocesador
from vision.region_detector import detectar_regiones, calificar_regiones, asociar_producto_por_region

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("probar_hibrido_roi")

DATA_RAW = Path("data/raw/tiendeo")
DATA_PROCESSED = Path("data/processed/tiendeo")
SALIDA = Path("data/processed/_v7_hibrido_roi_asociacion")

# Tiendas grid-friendly identificadas en el benchmark de corpus completo
# (sources/vision/05_benchmark_roi_deteccion_regiones.md): >=45% de paginas
# con al menos 1 region confiable. "merco" se excluye de este benchmark --
# no tiene carpeta procesada en data/processed/tiendeo (nunca se corrio el
# pipeline completo para esa tienda). "soriana_híper" (con acento, 44
# folletos en data/processed) se excluye tambien -- no tiene imagenes
# correspondientes en data/raw/tiendeo (carpeta legacy/duplicada, fuera de
# alcance de este benchmark).
TIENDAS_GRID_FRIENDLY = ["walmart", "chedraui", "soriana_hiper", "soriana_mercado"]


def _asociar_por_distancia(precio: dict, productos: list) -> dict | None:
    """Replica exacta de Loader._asociar_producto (load/load.py) para poder comparar."""
    if not productos:
        return None
    precio_x = precio.get("bbox", {}).get("x", 0)
    precio_y = precio.get("bbox", {}).get("y", 0)
    mejor, menor_dist = None, float("inf")
    for prod in productos:
        prod_bbox = prod.get("bbox", {})
        prod_x = prod_bbox.get("x", 0)
        prod_y = prod_bbox.get("y", 0)
        if abs(prod_x - precio_x) > 400:
            continue
        diff_y = precio_y - prod_y
        if 0 < diff_y < menor_dist:
            menor_dist = diff_y
            mejor = prod
    return mejor


def _id_producto(producto: dict | None) -> str | None:
    """Identificador estable para comparar 'es el mismo producto' entre metodos (bbox no cambia)."""
    if not producto:
        return None
    b = producto.get("bbox", {})
    return f"{b.get('x')}_{b.get('y')}_{b.get('ancho')}_{b.get('alto')}"


def enumerar_folletos(tienda: str):
    carpeta_tienda = DATA_PROCESSED / tienda
    if not carpeta_tienda.is_dir():
        logger.warning(f"No existe {carpeta_tienda} -- se omite tienda '{tienda}'")
        return
    for carpeta_folleto in sorted(carpeta_tienda.iterdir()):
        ruta_nlp = carpeta_folleto / "nlp_resultado.json"
        if ruta_nlp.exists():
            yield carpeta_folleto.name, ruta_nlp


def parse_args():
    parser = argparse.ArgumentParser(description="Benchmark hibrido ROI vs distancia para asociacion producto-precio")
    parser.add_argument("--tiendas", nargs="*", default=TIENDAS_GRID_FRIENDLY,
                         help="Tiendas a evaluar (default: las grid-friendly ya identificadas)")
    return parser.parse_args()


def main():
    args = parse_args()
    SALIDA.mkdir(parents=True, exist_ok=True)
    preprocesador = obtener_preprocesador("color_normal")  # mismo perfil de produccion

    filas = []
    for tienda in args.tiendas:
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
                    logger.warning(f"Sin imagen raw: {ruta_imagen} -- se omite pagina")
                    continue

                imagen_proc = preprocesador.procesar(ruta_imagen)
                candidatas = detectar_regiones(imagen_proc)
                # Los "bloques_ocr" para calificar regiones son los precios ya
                # clasificados por el pipeline -- mismo texto que hubiera visto
                # el OCR, sin necesidad de re-correrlo.
                bloques_precio = [{"texto": p.get("texto", ""), "bbox": p.get("bbox", {})} for p in precios]
                regiones = calificar_regiones(candidatas, bloques_precio)
                regiones_confiables = [r for r in regiones if r["tiene_precio"]]

                for precio in precios:
                    prod_distancia = _asociar_por_distancia(precio, productos)
                    prod_roi = asociar_producto_por_region(precio, productos, regiones_confiables)

                    if prod_roi is not None:
                        metodo_usado = "roi"
                        prod_hibrido = prod_roi
                    else:
                        metodo_usado = "fallback_distancia"
                        prod_hibrido = prod_distancia

                    id_dist = _id_producto(prod_distancia)
                    id_hib = _id_producto(prod_hibrido)

                    filas.append({
                        "tienda": tienda, "folleto_id": folleto_id, "pagina": nombre_pag,
                        "precio_texto": precio.get("texto", ""),
                        "metodo_usado_hibrido": metodo_usado,
                        "sin_producto_distancia": id_dist is None,
                        "sin_producto_hibrido": id_hib is None,
                        "coinciden": id_dist == id_hib,
                        "mejora_hibrido": id_dist is None and id_hib is not None,
                        "regresion_hibrido": id_dist is not None and id_hib is None,
                    })

                logger.info(f"{tienda}/{folleto_id}/{nombre_pag}: {len(precios)} precios, {len(regiones_confiables)} regiones confiables")

    if not filas:
        logger.warning("Sin datos -- revisa que las tiendas tengan nlp_resultado.json e imagenes raw correspondientes")
        return

    ruta_csv = SALIDA / "resumen.csv"
    with open(ruta_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        writer.writeheader()
        writer.writerows(filas)

    print("\n" + "=" * 90)
    print("RESUMEN GLOBAL")
    print("=" * 90)
    total = len(filas)
    via_roi = sum(1 for r in filas if r["metodo_usado_hibrido"] == "roi")
    sin_prod_dist = sum(1 for r in filas if r["sin_producto_distancia"])
    sin_prod_hib = sum(1 for r in filas if r["sin_producto_hibrido"])
    desacuerdos = sum(1 for r in filas if not r["coinciden"])
    mejoras = sum(1 for r in filas if r["mejora_hibrido"])
    regresiones = sum(1 for r in filas if r["regresion_hibrido"])

    print(f"Precios evaluados:                    {total}")
    print(f"Resueltos via ROI directo:             {via_roi} ({via_roi/total:.1%})")
    print(f"Sin producto -- metodo distancia:      {sin_prod_dist} ({sin_prod_dist/total:.1%})")
    print(f"Sin producto -- metodo hibrido:        {sin_prod_hib} ({sin_prod_hib/total:.1%})")
    print(f"Desacuerdos (distinto producto):       {desacuerdos} ({desacuerdos/total:.1%})")
    print(f"Mejora (hibrido encontro, distancia no): {mejoras} ({mejoras/total:.1%})")
    print(f"Regresion (distancia encontro, hibrido no): {regresiones} ({regresiones/total:.1%})")

    print("\n" + "=" * 90)
    print("POR TIENDA")
    print("=" * 90)
    print(f"{'Tienda':<16} {'Precios':>8} {'ViaROI':>8} {'SinProd_dist':>13} {'SinProd_hib':>12} {'Mejora':>8} {'Regresion':>10}")
    print("-" * 90)
    for tienda in args.tiendas:
        filas_t = [r for r in filas if r["tienda"] == tienda]
        if not filas_t:
            continue
        n = len(filas_t)
        print(
            f"{tienda:<16} {n:>8} "
            f"{sum(1 for r in filas_t if r['metodo_usado_hibrido']=='roi'):>8} "
            f"{sum(1 for r in filas_t if r['sin_producto_distancia']):>13} "
            f"{sum(1 for r in filas_t if r['sin_producto_hibrido']):>12} "
            f"{sum(1 for r in filas_t if r['mejora_hibrido']):>8} "
            f"{sum(1 for r in filas_t if r['regresion_hibrido']):>10}"
        )

    print(f"\nCSV de resumen guardado en: {ruta_csv}")


if __name__ == "__main__":
    main()
