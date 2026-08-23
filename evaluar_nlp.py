# Evalua la tasa de captura real del pipeline OCR+NLP contra el dataset
# de etiquetado manual (data/raw/_revision_manual/tiendeo/), folleto por
# folleto, tienda por tienda y a nivel global.
#
# Compara SOLO los folletos del dataset manual que ya tienen ocr_resultado.json
# y nlp_resultado.json en data/processed/tiendeo/ -- los que aun no tienen OCR
# (pendientes de correr en la PC con GPU) se reportan aparte, sin afectar las
# metricas.

import json
import logging
from pathlib import Path

import pandas as pd

from nlp.evaluador_calidad import comparar_folleto

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("evaluar_nlp")

MANUAL     = Path("data/raw/_revision_manual/tiendeo")
PROCESSED  = Path("data/processed/tiendeo")
SALIDA_DIR = Path("data/processed/_evaluacion_nlp")


def cargar_json(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def pct(a: int, b: int) -> str:
    return f"{(a / b * 100):.1f}%" if b else "  n/a"


def main():
    SALIDA_DIR.mkdir(parents=True, exist_ok=True)

    archivos_manual = sorted(MANUAL.rglob("*_contenido.json"))
    sin_datos = []
    resultados_por_folleto = []  # [(tienda, folleto_id, [ResultadoPaginaEval,...])]

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

    # ---------------- Agregacion (pandas) ----------------
    # Antes: defaultdict anidado sumando campo por campo en un loop manual.
    # Ahora: una fila por pagina evaluada -> DataFrame -> groupby("tienda").sum()
    # + .sum() global. Mismo resultado, agregacion tabular real en vez de
    # acumular a mano -- es exactamente el caso de uso para el que pandas
    # existe (ver decision de integracion, 23-ago-2026: no se toco load.py
    # por riesgo sobre codigo de escritura ya validado, pero este script de
    # evaluacion es de solo lectura/reporte).
    CAMPOS = [
        "productos_total", "productos_ocr_ok", "productos_nlp_ok",
        "precios_total", "precios_ok", "precios_mal_clasificados",
        "promos_total", "promos_ok",
    ]

    filas_paginas = []
    fallos_producto_muestra = []   # para el reporte JSON de detalle
    fallos_precio_muestra   = []
    fallos_promo_muestra    = []

    for tienda, folleto_id, paginas_eval in resultados_por_folleto:
        for p in paginas_eval:
            filas_paginas.append({"tienda": tienda, **{c: getattr(p, c) for c in CAMPOS}})

            for nombre, ocr_ok, nlp_ok, ratio in p.productos_fallidos:
                fallos_producto_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina,
                    "producto": nombre, "ocr_encontrado": ocr_ok, "cobertura_tokens": ratio,
                })
            for nombre, precio, mal_clasificado in p.precios_fallidos:
                fallos_precio_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina,
                    "producto": nombre, "precio_esperado": precio, "mal_clasificado": mal_clasificado,
                })
            for texto in p.promos_fallidas:
                fallos_promo_muestra.append({
                    "tienda": tienda, "folleto_id": folleto_id, "pagina": p.pagina, "promo": texto,
                })

    df_paginas = pd.DataFrame(filas_paginas, columns=["tienda", *CAMPOS])

    # .astype(int): pandas suma a int64 (numpy) -- se castea a int nativo de
    # Python para que json.dump() no truene mas abajo (no sabe serializar
    # numpy.int64).
    agregados_tienda = {
        tienda: fila.astype(int).to_dict()
        for tienda, fila in df_paginas.groupby("tienda")[CAMPOS].sum().iterrows()
    }
    agregados_global = df_paginas[CAMPOS].sum().astype(int).to_dict()

    # ---------------- Reporte en consola ----------------
    print("\n" + "=" * 88)
    print("EVALUACION DE CALIDAD OCR+NLP vs DATASET MANUAL (tiendeo)")
    print("=" * 88)
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

    g = agregados_global
    print("-" * 88)
    print(
        f"{'GLOBAL':<18} "
        f"{pct(g['productos_ocr_ok'], g['productos_total']):>12} "
        f"{pct(g['productos_nlp_ok'], g['productos_total']):>12} "
        f"{pct(g['precios_ok'], g['precios_total']):>10} "
        f"{pct(g['promos_ok'], g['promos_total']):>10}"
    )
    print("=" * 88)
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
    print("=" * 88)

    # ---------------- Guardar reporte detallado ----------------
    reporte = {
        "folletos_en_dataset_manual": len(archivos_manual),
        "folletos_evaluados": len(resultados_por_folleto),
        "folletos_sin_datos": sin_datos,
        "por_tienda": {t: dict(a) for t, a in agregados_tienda.items()},
        "global": dict(g),
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
