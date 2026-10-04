# Orquestador que valua la tasa de captura real del pipeline OCR+NLP contra el dataset
# Evalua solo los folletos que tienen ocr y nlp real vs un dataset manual

import json
import logging
from pathlib import Path

import pandas as pd

from nlp.evaluador_calidad import comparar_folleto

"""
- Recall de OCR: ¿el texto llegó a leerse siquiera? (productos_ocr_ok)
- Recall de NLP: de lo que el OCR sí leyó, ¿el regex lo clasificó bien como PRODUCTO/PRECIO/PROMO? (productos_nlp_ok, precios_ok, promos_ok)
- Precision de NLP: de todo lo que el regex clasificó en una categoría, ¿cuánto es correcto? (línea 61-63, comparado contra *_nlp_clasificados/*_nlp_correctos)
- F1-score por categoría y promedio, contra un criterio de éxito explícito del proyecto: "F1 ≥ 70%" (línea 197-203)
"""

# arranque de login
logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("evaluar_nlp")

# Paths carpetas
MANUAL     = Path("data/raw/_revision_manual/tiendeo")
PROCESSED  = Path("data/processed/tiendeo")
SALIDA_DIR = Path("data/processed/_evaluacion_nlp")


def cargar_json(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)

# porcentaje
def pct(a: int, b: int) -> str:
    return f"{(a / b * 100):.1f}%" if b else "  n/a"

# tasa de acierto (0.0 si b==0)
def tasa(a: int, b: int) -> float:
    return a / b if b else 0.0

# F1-score (0.0 si precision+recall==0)
def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)

# Calcula precision, recall y F1 para una categoria
def precision_recall_f1(agregado: dict, prefijo: str) -> dict:
   
    campo_ok = "productos_nlp_ok" if prefijo == "productos" else f"{prefijo}_ok"
    recall = tasa(agregado[campo_ok], agregado[f"{prefijo}_total"])
    precision = tasa(agregado[f"{prefijo}_nlp_correctos"], agregado[f"{prefijo}_nlp_clasificados"])
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1_score(precision, recall), 4),
    }

# Funcion principal
def main():
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)

    # Cargar los archivos de datos manual
    archivos_manual = sorted(MANUAL.rglob("*_contenido.json"))
    sin_datos = []
    resultados_por_folleto = [] 

    # Procesar cada archivo de datos
    for archivo in archivos_manual:
        tienda = archivo.parent.name
        folleto_id = archivo.name.replace("_contenido.json", "")
        carpeta_proc = PROCESSED / tienda / folleto_id

        datos_gt = cargar_json(archivo)
        datos_ocr = cargar_json(carpeta_proc / "ocr_resultado.json")
        datos_nlp = cargar_json(carpeta_proc / "nlp_resultado.json")

        if datos_ocr is None or datos_nlp is None:
            sin_datos.append(f"{tienda}/{folleto_id}")
            continue

        paginas_eval = comparar_folleto(datos_gt, datos_ocr, datos_nlp)
        resultados_por_folleto.append((tienda, folleto_id, paginas_eval))

    # cataloga los resultados por pagina y por tienda, para luego calcular agregados y F1-score
    CAMPOS = [
        "productos_total", "productos_ocr_ok", "productos_nlp_ok",
        "precios_total", "precios_ok", "precios_mal_clasificados",
        "promos_total", "promos_ok",
        "productos_nlp_clasificados", "productos_nlp_correctos",
        "precios_nlp_clasificados", "precios_nlp_correctos",
        "promos_nlp_clasificados", "promos_nlp_correctos",
    ]

    filas_paginas = []
    fallos_producto_muestra = []   # para el reporte JSON de detalle
    fallos_precio_muestra   = []
    fallos_promo_muestra    = []

    # Reasignar los resultados de cada folleto a cada pagina, y luego a cada tienda
    for tienda, folleto_id, paginas_eval in resultados_por_folleto:
        for p in paginas_eval:
            # Agrega una fila por pagina, con los campos de interes
            filas_paginas.append({"tienda": tienda, **{c: getattr(p, c) for c in CAMPOS}})

            # Agrega a la muestra de fallos para el reporte JSON, solo los primeros 5 de cada tipo por pagina
            for nombre, ocr_ok, nlp_ok, ratio in p.productos_fallidos:
                fallos_producto_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina,
                    "producto": nombre, "ocr_encontrado": ocr_ok, "cobertura_tokens": ratio,
                })
            # Agrega a la muestra de fallos de precios
            for nombre, precio, mal_clasificado in p.precios_fallidos:
                fallos_precio_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina,
                    "producto": nombre, "precio_esperado": precio, "mal_clasificado": mal_clasificado,
                })
            # Agrega a la muestra de fallos de promos
            for texto in p.promos_fallidas:
                fallos_promo_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina, "promo": texto,
                })

    # Crear un DataFrame con las filas de paginas evaluadas
    df_paginas = pd.DataFrame(filas_paginas, columns=["tienda", *CAMPOS])

    # Agregados por tienda y globales
    agregados_tienda = {
        tienda: fila.astype(int).to_dict()
        for tienda, fila in df_paginas.groupby("tienda")[CAMPOS].sum().iterrows()
    }
    agregados_global = df_paginas[CAMPOS].sum().astype(int).to_dict()

    # ---------------- Reporte en consola ----------------
    print("\n" + "-" * 88)
    print("EVALUACION DE CALIDAD OCR+NLP vs DATASET MANUAL (tiendeo)")
    print("-" * 88)
    print(f"Folletos en dataset manual:        {len(archivos_manual)}")
    print(f"Folletos evaluados (con OCR+NLP):   {len(resultados_por_folleto)}")
    print(f"Folletos SIN datos (pendiente GPU): {len(sin_datos)}  -> {', '.join(sin_datos)}")

    print("\n" + "-" * 88)
    print(f"{'TIENDA':<18} {'PROD (OCR)':>12} {'PROD (NLP)':>12} {'PRECIOS':>10} {'PROMOS':>10}")
    print("-" * 88)
    for tienda in sorted(agregados_tienda):
        a = agregados_tienda[tienda]
        print(
            f"{tienda:<18} "
            f"{pct(a['productos_ocr_ok'], a['productos_total']):>12} "
            f"{pct(a['productos_nlp_ok'], a['productos_total']):>12} "
            f"{pct(a['precios_ok'], a['precios_total']):>10} "
            f"{pct(a['promos_ok'], a['promos_total']):>10}"
        )

    # Agregar los agregados globales
    g = agregados_global
    print("-" * 88)
    print(
        f"{'GLOBAL':<18} "
        f"{pct(g['productos_ocr_ok'], g['productos_total']):>12} "
        f"{pct(g['productos_nlp_ok'], g['productos_total']):>12} "
        f"{pct(g['precios_ok'], g['precios_total']):>10} "
        f"{pct(g['promos_ok'], g['promos_total']):>10}"
    )
    print("-" * 88)
    print(f"Total articulos evaluados:  {g['productos_total']}")
    print(f"  Detectados por OCR:       {g['productos_ocr_ok']}  ({pct(g['productos_ocr_ok'], g['productos_total'])})")
    print(f"  Clasificados como PROD:   {g['productos_nlp_ok']}  ({pct(g['productos_nlp_ok'], g['productos_total'])})")
    fallo_clasificacion = g['productos_ocr_ok'] - g['productos_nlp_ok']
    print(f"  -> de esos, {fallo_clasificacion} fueron leidos por OCR pero NO clasificados como producto (posible fallo de NLP/regex)")
    print(f"  -> {g['productos_total'] - g['productos_ocr_ok']} nunca fueron leidos por OCR (posible fallo de imagen/EasyOCR)")
    print(f"\nTotal precios evaluados:    {g['precios_total']}")
    print(f"  Encontrados correctamente: {g['precios_ok']}  ({pct(g['precios_ok'], g['precios_total'])})")
    print(f"  Mal clasificados (como precio_anterior/ahorro): {g['precios_mal_clasificados']}")
    print(f"\nTotal promos evaluadas:     {g['promos_total']}")
    print(f"  Detectadas:               {g['promos_ok']}  ({pct(g['promos_ok'], g['promos_total'])})")
    print("-" * 88)

    # ---------------- F1-score (criterio "NLP: F1-score >= 70%" de la propuesta) ----------------
    f1_producto = precision_recall_f1(g, "productos")
    f1_precio   = precision_recall_f1(g, "precios")
    f1_promo    = precision_recall_f1(g, "promos")
    f1_promedio = round((f1_producto["f1"] + f1_precio["f1"] + f1_promo["f1"]) / 3, 4)

    print("\nF1-SCORE (criterio de exito de la propuesta: >= 70%)")
    print(f"{'CATEGORIA':<12} {'PRECISION':>10} {'RECALL':>10} {'F1':>10}")
    for nombre, r in [("Producto", f1_producto), ("Precio", f1_precio), ("Promo", f1_promo)]:
        print(f"{nombre:<12} {r['precision']*100:>9.1f}% {r['recall']*100:>9.1f}% {r['f1']*100:>9.1f}%")
    print(f"{'PROMEDIO':<12} {'':>10} {'':>10} {f1_promedio*100:>9.1f}%")
    print(f"\n{'CUMPLE >= 70%' if f1_promedio >= 0.70 else 'NO CUMPLE 70%'} "
          f"(F1 promedio = {f1_promedio*100:.1f}%)")
    print("-" * 88)

    # ---------------- Guardar reporte detallado ----------------
    reporte = {
        "folletos_en_dataset_manual": len(archivos_manual),
        "folletos_evaluados": len(resultados_por_folleto),
        "folletos_sin_datos": sin_datos,
        "por_tienda": {t: dict(a) for t, a in agregados_tienda.items()},
        "global": dict(g),
        "f1_score": {
            "producto": f1_producto,
            "precio": f1_precio,
            "promo": f1_promo,
            "promedio": f1_promedio,
            "cumple_criterio_70pct": f1_promedio >= 0.70,
        },
        "fallos_producto": fallos_producto_muestra,
        "fallos_precio": fallos_precio_muestra,
        "fallos_promo": fallos_promo_muestra,
    }
    ruta_reporte = SALIDA_DIR / "reporte.json"
    with open(ruta_reporte, "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
    print(f"\nReporte detallado guardado en: {ruta_reporte}")


if __name__ == "__main__":
    main()
