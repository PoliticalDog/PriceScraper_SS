# funciones del comparador de calidad OCR+NLP contra el dataset de etiquetado manual

import re
import unicodedata
from dataclasses import dataclass, field

"""
FLUJO:
    normalizar(texto) -> acentis
    tokens_significativos(texto) -> conectores 
    corpus_de_bloques(bloques) -> conecta palabras de todos los bloques de una pagina
    recall_texto(texto_gt, corpus_norm) --> compara un texto del ground truth contra un corpus normalizado de OCR/NLP
    comparar_pagina(pagina_gt, ocr_pagina, nlp_pagina) -> compara una pagina del ground truth con las salidas de OCR y NLP
    comparar_folleto(datos_gt, datos_ocr, datos_nlp) -> compara un folleto completo (ground truth) 
"""

# palabras que no se consideran significativas en la comparacion de texto
STOPWORDS = {
    "de", "del", "la", "el", "los", "las", "a", "o", "y", "en", "con",
    "sin", "para", "por", "un", "una", "al", "su", "tu", "mi", "que",
    "es", "se", "le", "lo",
}

# umbral de cobertura de tokens significativos para considerar que un texto del ground truth fue encontrado en el OCR/NLP
UMBRAL_RECALL_TEXTO = 0.5  # fraccion minima de tokens significativos que deben aparecer
TOLERANCIA_PRECIO = 0.01

# minusculas, sin acentos, solo alfanumerico + espacios, espacios colapsados
def normalizar(texto: str) -> str:

    if not texto:
        return ""
    
    # quita acentos, deja solo los caracteres base
    texto = unicodedata.normalize("NFKD", texto)    # descompone acentos y base
    caracteres_limpios = []

    for caracter in texto:
        if not unicodedata.combining(caracter):
            caracteres_limpios.append(caracter)
    texto = "".join(caracteres_limpios) 
    texto = texto.lower()
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto

# devuelve los tokens significativos de un texto
def tokens_significativos(texto: str) -> list[str]:
    norm = normalizar(texto)

    tokens = []

    for t in norm.split():
        if len(t) >= 3 and t not in STOPWORDS:
            tokens.append(t)

    return tokens

# devuelve un corpus normalizado de todos los bloques de una pagina, para comparacion de recall
def corpus_de_bloques(bloques: list[dict], campo: str = "texto") -> str:
    textos_normalizados = []

    for bloque in bloques:
        texto = bloque.get(campo, "")
        texto_normalizado = normalizar(texto)
        textos_normalizados.append(texto_normalizado)

    corpus = " ".join(textos_normalizados)

    return corpus

# Retorna (encontrado, ratio_cobertura) para texto_gt contra un corpus ya normalizado
def recall_texto(texto_gt: str, corpus_norm: str, umbral: float = UMBRAL_RECALL_TEXTO) -> tuple[bool, float]:
    tokens = tokens_significativos(texto_gt)
    if not tokens:
        return False, 0.0
    encontrados = 0
    for token in tokens:
        if token in corpus_norm:
            encontrados += 1
    ratio = encontrados / len(tokens)
    return ratio >= umbral, ratio

# -------------------------- Comparador de calidad por pagina --------------------------
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

   # Agregados de precision: de cada bloque que el NLP clasifico, cuantos son correctos
    productos_nlp_clasificados: int = 0
    productos_nlp_correctos: int = 0
    precios_nlp_clasificados: int = 0
    precios_nlp_correctos: int = 0
    promos_nlp_clasificados: int = 0
    promos_nlp_correctos: int = 0

# Compara una pagina del ground truth con las salidas de OCR y NLP
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
    precios_gt_valores = [
        art["precio"] for art in pagina_gt.get("articulos", []) if art.get("precio") is not None
    ]
    res.precios_nlp_clasificados = len(nlp_precios)
    for p in nlp_precios:
        valor = p.get("valor")
        if valor is not None and any(abs(valor - pv) < TOLERANCIA_PRECIO for pv in precios_gt_valores):
            res.precios_nlp_correctos += 1

    # Promos: mismo criterio de texto que productos, contra la mecanica real
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

# Compara un folleto completo (ground truth) con las salidas de OCR y NLP, pagina por pagina
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
