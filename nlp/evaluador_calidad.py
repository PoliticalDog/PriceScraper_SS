# Comparador de calidad OCR+NLP contra el dataset de etiquetado manual
# (data/raw/_revision_manual/tiendeo/{tienda}/{folleto_id}_contenido.json).
#
# La comparacion es a nivel de texto, no de bbox: el ground truth tiene
# nombres de producto curados a mano (ej. "Panal adulto Predoblado
# Affective 10pz"), mientras que el pipeline real produce bloques de OCR
# independientes que pueden fragmentar ese mismo texto en varios bloques.
# Por eso "encontrado" se mide como cobertura de tokens significativos del
# nombre dentro del corpus de texto de la pagina, no como igualdad exacta.
#
# Se miden dos cosas por separado para poder distinguir la causa raiz:
#   - ocr_encontrado:  el texto aparece en ALGUN bloque de OCR de la pagina
#                       (sin importar como lo clasifico el NLP)
#   - nlp_clasificado:  el texto aparece especificamente en bloques que el
#                       NLP clasifico como producto/atributo
# Si ocr_encontrado=True y nlp_clasificado=False -> fallo de clasificacion
# (probablemente cayo en descartes). Si ocr_encontrado=False -> fallo de
# OCR (la imagen/EasyOCR no lo leyo con suficiente calidad).

import re
import unicodedata
from dataclasses import dataclass, field

STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "a", "o", "y", "en", "con",
    "sin", "para", "por", "un", "una", "al", "su", "tu", "mi", "que",
    "es", "se", "le", "lo",
}

UMBRAL_RECALL_TEXTO = 0.5  # fraccion minima de tokens significativos que deben aparecer
TOLERANCIA_PRECIO = 0.01


def normalizar(texto: str) -> str:
    """minusculas, sin acentos, solo alfanumerico + espacios, espacios colapsados."""
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def tokens_significativos(texto: str) -> list[str]:
    norm = normalizar(texto)
    return [t for t in norm.split() if len(t) >= 3 and t not in STOPWORDS]


def corpus_de_bloques(bloques: list[dict], campo: str = "texto") -> str:
    return " ".join(normalizar(b.get(campo, "")) for b in bloques)


def recall_texto(texto_gt: str, corpus_norm: str, umbral: float = UMBRAL_RECALL_TEXTO) -> tuple[bool, float]:
    """Retorna (encontrado, ratio_cobertura) para texto_gt contra un corpus ya normalizado."""
    tokens = tokens_significativos(texto_gt)
    if not tokens:
        return False, 0.0
    encontrados = sum(1 for t in tokens if t in corpus_norm)
    ratio = encontrados / len(tokens)
    return ratio >= umbral, ratio


@dataclass
class ResultadoPaginaEval:
    pagina: str
    productos_total: int = 0
    productos_ocr_ok: int = 0
    productos_nlp_ok: int = 0
    precios_total: int = 0
    precios_ok: int = 0
    precios_mal_clasificados: int = 0
    promos_total: int = 0
    promos_ok: int = 0
    productos_fallidos: list = field(default_factory=list)  # [(nombre, ocr_ok, nlp_ok, ratio)]
    precios_fallidos: list = field(default_factory=list)    # [(producto, precio)]
    promos_fallidas: list = field(default_factory=list)     # [texto]

    # ---- Precision (24-ago-2026, para F1-score real vs criterio de la propuesta) ----
    # Los campos de arriba miden RECALL (de cada item del ground truth, se
    # encontro?). Estos miden PRECISION en la direccion inversa (de cada
    # bloque que el NLP clasifico, es correcto?) -- necesarios para F1, que
    # castiga tanto lo que no se encuentra como el ruido que se clasifica de
    # mas (ej. slogans marcados como PRODUCTO). Mismo umbral/metodologia de
    # recall_texto que el resto del evaluador, solo invertido: se busca el
    # texto del bloque NLP dentro del corpus del ground truth.
    productos_nlp_clasificados: int = 0
    productos_nlp_correctos: int = 0
    precios_nlp_clasificados: int = 0
    precios_nlp_correctos: int = 0
    promos_nlp_clasificados: int = 0
    promos_nlp_correctos: int = 0


def comparar_pagina(pagina_gt: dict, ocr_pagina: dict | None, nlp_pagina: dict | None) -> ResultadoPaginaEval:
    res = ResultadoPaginaEval(pagina=pagina_gt["pagina"])

    ocr_bloques = ocr_pagina.get("bloques", []) if ocr_pagina else []
    corpus_ocr = corpus_de_bloques(ocr_bloques, "texto")

    nlp_productos = (nlp_pagina.get("productos", []) + nlp_pagina.get("atributos", [])) if nlp_pagina else []
    corpus_nlp_producto = corpus_de_bloques(nlp_productos, "texto")

    nlp_precios = nlp_pagina.get("precios", []) if nlp_pagina else []
    nlp_precios_ant = nlp_pagina.get("precios_anteriores", []) if nlp_pagina else []
    nlp_ahorros = nlp_pagina.get("ahorros", []) if nlp_pagina else []

    nlp_promos = (nlp_pagina.get("promos", []) + nlp_pagina.get("eventos_promo", [])) if nlp_pagina else []
    corpus_nlp_promo = corpus_de_bloques(nlp_promos, "texto")

    # ---- Productos ----
    for art in pagina_gt.get("articulos", []):
        nombre = art.get("producto", "")
        if not nombre:
            continue
        res.productos_total += 1

        ocr_ok, _ = recall_texto(nombre, corpus_ocr)
        nlp_ok, ratio = recall_texto(nombre, corpus_nlp_producto)

        if ocr_ok:
            res.productos_ocr_ok += 1
        if nlp_ok:
            res.productos_nlp_ok += 1
        if not nlp_ok:
            res.productos_fallidos.append((nombre, ocr_ok, nlp_ok, round(ratio, 2)))

        # ---- Precio de ese articulo ----
        precio = art.get("precio")
        if precio is not None:
            res.precios_total += 1
            encontrado = any(abs(p.get("valor", -1e9) - precio) < TOLERANCIA_PRECIO for p in nlp_precios)
            if encontrado:
                res.precios_ok += 1
            else:
                mal_clasificado = any(
                    abs(p.get("valor", -1e9) - precio) < TOLERANCIA_PRECIO
                    for p in nlp_precios_ant + nlp_ahorros
                )
                if mal_clasificado:
                    res.precios_mal_clasificados += 1
                res.precios_fallidos.append((nombre, precio, mal_clasificado))

    # ---- Promociones de pagina ----
    # El ground truth guarda la mecanica real de la promo (ej. "3X2",
    # "25% de descuento") en "notas" -- "texto" es la descripcion del
    # producto/categoria al que aplica, casi nunca coincide con lo que el
    # OCR lee junto al bloque de mecanica de precio.
    for promo in pagina_gt.get("promociones_pagina", []):
        mecanica = promo.get("notas", "") or promo.get("texto", "")
        if not mecanica:
            continue
        res.promos_total += 1
        ok, _ = recall_texto(mecanica, corpus_nlp_promo)
        if ok:
            res.promos_ok += 1
        else:
            res.promos_fallidas.append(promo.get("texto", "") or mecanica)

    # ---- Precision: de cada bloque que el NLP clasifico, es correcto? ----
    # Productos: se busca el texto de CADA bloque NLP dentro del corpus del
    # ground truth (inverso al bloque de arriba, misma funcion recall_texto).
    corpus_gt_productos = corpus_de_bloques(pagina_gt.get("articulos", []), "producto")
    res.productos_nlp_clasificados = len(nlp_productos)
    for bloque in nlp_productos:
        ok, _ = recall_texto(bloque.get("texto", ""), corpus_gt_productos)
        if ok:
            res.productos_nlp_correctos += 1

    # Precios: un bloque PRECIO es correcto si su valor numerico coincide
    # (tolerancia) con ALGUN precio del ground truth de la pagina -- no se
    # exige que sea el precio de "su" producto asociado, mismo criterio
    # laxo que ya usa el bloque de recall de arriba.
    precios_gt_valores = [
        art["precio"] for art in pagina_gt.get("articulos", []) if art.get("precio") is not None
    ]
    res.precios_nlp_clasificados = len(nlp_precios)
    for p in nlp_precios:
        valor = p.get("valor")
        if valor is not None and any(abs(valor - pv) < TOLERANCIA_PRECIO for pv in precios_gt_valores):
            res.precios_nlp_correctos += 1

    # Promos: mismo criterio de texto que productos, contra la mecanica real
    # del ground truth (notas/texto, igual que el bloque de recall de arriba).
    textos_gt_promo = [
        (promo.get("notas", "") or promo.get("texto", ""))
        for promo in pagina_gt.get("promociones_pagina", [])
    ]
    corpus_gt_promos = " ".join(normalizar(t) for t in textos_gt_promo if t)
    res.promos_nlp_clasificados = len(nlp_promos)
    for bloque in nlp_promos:
        ok, _ = recall_texto(bloque.get("texto", ""), corpus_gt_promos)
        if ok:
            res.promos_nlp_correctos += 1

    return res


def comparar_folleto(datos_gt: dict, datos_ocr: dict | None, datos_nlp: dict | None) -> list[ResultadoPaginaEval]:
    ocr_por_pagina = {p["pagina"]: p for p in (datos_ocr.get("paginas", []) if datos_ocr else [])}
    nlp_por_pagina = {p["pagina"]: p for p in (datos_nlp.get("paginas", []) if datos_nlp else [])}

    resultados = []
    for pagina_gt in datos_gt.get("paginas", []):
        nombre_pag = pagina_gt["pagina"]
        resultados.append(comparar_pagina(
            pagina_gt,
            ocr_por_pagina.get(nombre_pag),
            nlp_por_pagina.get(nombre_pag),
        ))
    return resultados
