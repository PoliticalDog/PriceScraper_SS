# Experimento: viabilidad de integrar spaCy (es_core_news_sm) al pipeline NLP,
# tal como proponia Propuesta_PriceScraper_SS.docx ("modelo spaCy entrenado
# para reconocimiento de entidades PRODUCTO/PRECIO/PROMO").
#
# No modifica nlp/regex_extractor.py ni la base de datos -- es solo para
# decidir si vale la pena integrarlo al pipeline real (mismo patron que
# probar_hibrido_roi.py).
#
# Mide DOS enfoques de "usar spaCy" sin entrenar un modelo custom (eso se
# analiza aparte, ver reporte final):
#   1. NER pre-entrenado (LOC/MISC/ORG/PER) como señal de "esto es un producto"
#   2. PhraseMatcher cargado con el vocabulario que YA existe en el proyecto
#      (nlp/normalizador.CATALOGO_CANONICO + nlp/catalogo_productos.CATALOGO)
#
# Ambos se comparan contra el mismo dataset manual y la misma metodologia de
# recall que usa evaluar_nlp.py (recall_texto/corpus_de_bloques de
# nlp/evaluador_calidad.py) para que el numero sea directamente comparable
# al 75.2% de PROD (NLP) ya medido con el regex actual.

import json
import logging
import time
from pathlib import Path

import spacy
from spacy.matcher import PhraseMatcher

from nlp.evaluador_calidad import corpus_de_bloques, recall_texto
from nlp.normalizador import CATALOGO_CANONICO
from nlp.catalogo_productos import CATALOGO as CATALOGO_DEPARTAMENTOS

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger("probar_spacy_ner")

MANUAL    = Path("data/raw/_revision_manual/tiendeo")
PROCESSED = Path("data/processed/tiendeo")
SALIDA    = Path("data/processed/_evaluacion_nlp/reporte_spacy.json")


def cargar_json(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def pct(a: int, b: int) -> str:
    return f"{(a / b * 100):.1f}%" if b else "  n/a"


def construir_matcher(nlp) -> PhraseMatcher:
    """Vocabulario reusado tal cual del proyecto -- no se agrega nada nuevo,
    para que la comparacion sea sobre el MOTOR de matching (spaCy vs regex),
    no sobre tener mejor o peor catalogo."""
    matcher = PhraseMatcher(nlp.vocab, attr="LOWER")

    frases = set()
    for nombre, datos in CATALOGO_CANONICO.items():
        frases.add(nombre)
        frases.update(datos.get("aliases", []))
    for datos in CATALOGO_DEPARTAMENTOS.values():
        frases.update(datos["keywords"])

    patrones = list(nlp.tokenizer.pipe(frases))
    matcher.add("CATALOGO", patrones)
    logger.info(f"PhraseMatcher cargado con {len(patrones)} frases")
    return matcher


def main():
    print("\n" + "=" * 88)
    print("EXPERIMENTO: spaCy (es_core_news_sm) vs regex actual -- recall de PRODUCTO")
    print("=" * 88)

    t0 = time.time()
    nlp = spacy.load("es_core_news_sm")
    matcher = construir_matcher(nlp)
    print(f"Modelo cargado en {time.time()-t0:.1f}s")

    archivos_manual = sorted(MANUAL.rglob("*_contenido.json"))

    # ---- Recolectar todos los bloques OCR + los productos GT a evaluar ----
    tareas = []  # [(tienda, folleto_id, pagina_gt, bloques_ocr)]
    for archivo in archivos_manual:
        tienda = archivo.parent.name
        folleto_id = archivo.name.replace("_contenido.json", "")
        carpeta_proc = PROCESSED / tienda / folleto_id

        datos_gt = cargar_json(archivo)
        datos_ocr = cargar_json(carpeta_proc / "ocr_resultado.json")
        if datos_gt is None or datos_ocr is None:
            continue

        ocr_por_pagina = {p["pagina"]: p for p in datos_ocr.get("paginas", [])}
        for pagina_gt in datos_gt.get("paginas", []):
            ocr_pagina = ocr_por_pagina.get(pagina_gt["pagina"])
            bloques = ocr_pagina.get("bloques", []) if ocr_pagina else []
            tareas.append((tienda, folleto_id, pagina_gt, bloques))

    print(f"Paginas a evaluar: {len(tareas)} (mismo dataset manual que evaluar_nlp.py)")

    # ---- Procesar todos los bloques con spaCy en batch (nlp.pipe) ----
    todos_los_textos = [b.get("texto", "") for _, _, _, bloques in tareas for b in bloques]
    print(f"Bloques OCR totales a procesar con spaCy: {len(todos_los_textos)}")

    t_spacy = time.time()
    docs = list(nlp.pipe(todos_los_textos, batch_size=256))
    dt_spacy = time.time() - t_spacy
    print(f"spaCy proceso {len(todos_los_textos)} bloques en {dt_spacy:.1f}s "
          f"({len(todos_los_textos)/dt_spacy:.0f} bloques/seg)")

    # ---- Reasignar los docs procesados de vuelta a cada pagina/bloque ----
    idx = 0
    resultados_por_tienda = {}  # tienda -> [ratios de recall NER, recall Matcher]
    conteo_entidades = {"LOC": 0, "MISC": 0, "ORG": 0, "PER": 0, "sin_entidad": 0}
    total_bloques_con_match = 0

    for tienda, folleto_id, pagina_gt, bloques in tareas:
        docs_pagina = docs[idx: idx + len(bloques)]
        idx += len(bloques)

        bloques_ner = []      # bloques con alguna entidad NER (MISC/ORG como proxy de "nombre propio")
        bloques_matcher = []  # bloques con match del PhraseMatcher (catalogo)

        for bloque, doc in zip(bloques, docs_pagina):
            tiene_entidad_relevante = any(ent.label_ in ("MISC", "ORG") for ent in doc.ents)
            if doc.ents:
                conteo_entidades[doc.ents[0].label_] = conteo_entidades.get(doc.ents[0].label_, 0) + 1
            else:
                conteo_entidades["sin_entidad"] += 1

            if tiene_entidad_relevante:
                bloques_ner.append(bloque)

            if matcher(doc):
                bloques_matcher.append(bloque)
                total_bloques_con_match += 1

        corpus_ner = corpus_de_bloques(bloques_ner, "texto")
        corpus_matcher = corpus_de_bloques(bloques_matcher, "texto")

        resultados_por_tienda.setdefault(tienda, {
            "total": 0, "ner_ok": 0, "matcher_ok": 0,
        })

        for art in pagina_gt.get("articulos", []):
            nombre = art.get("producto", "")
            if not nombre:
                continue
            resultados_por_tienda[tienda]["total"] += 1
            ok_ner, _ = recall_texto(nombre, corpus_ner)
            ok_matcher, _ = recall_texto(nombre, corpus_matcher)
            if ok_ner:
                resultados_por_tienda[tienda]["ner_ok"] += 1
            if ok_matcher:
                resultados_por_tienda[tienda]["matcher_ok"] += 1

    # ---- Reporte ----
    print("\n" + "-" * 88)
    print(f"{'TIENDA':<18} {'PROD (NER)':>14} {'PROD (Matcher)':>16}")
    print("-" * 88)
    g_total = g_ner = g_matcher = 0
    for tienda in sorted(resultados_por_tienda):
        r = resultados_por_tienda[tienda]
        g_total += r["total"]; g_ner += r["ner_ok"]; g_matcher += r["matcher_ok"]
        print(f"{tienda:<18} {pct(r['ner_ok'], r['total']):>14} {pct(r['matcher_ok'], r['total']):>16}")

    print("-" * 88)
    print(f"{'GLOBAL':<18} {pct(g_ner, g_total):>14} {pct(g_matcher, g_total):>16}")
    print("=" * 88)
    print(f"Total articulos evaluados: {g_total}")
    print(f"Distribucion de entidades NER en bloques OCR: {conteo_entidades}")
    print(f"Bloques con match de PhraseMatcher: {total_bloques_con_match} de {len(todos_los_textos)} "
          f"({pct(total_bloques_con_match, len(todos_los_textos))})")
    print(f"\nTiempo spaCy (pipeline completo, {len(todos_los_textos)} bloques): {dt_spacy:.1f}s")
    print("=" * 88)

    reporte = {
        "por_tienda": resultados_por_tienda,
        "global": {"total": g_total, "ner_ok": g_ner, "matcher_ok": g_matcher},
        "distribucion_entidades": conteo_entidades,
        "bloques_con_match_matcher": total_bloques_con_match,
        "total_bloques": len(todos_los_textos),
        "tiempo_spacy_seg": round(dt_spacy, 2),
        "bloques_por_seg": round(len(todos_los_textos) / dt_spacy, 1),
    }
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(reporte, f, ensure_ascii=False, indent=2)
    print(f"\nReporte guardado en: {SALIDA}")


if __name__ == "__main__":
    main()
