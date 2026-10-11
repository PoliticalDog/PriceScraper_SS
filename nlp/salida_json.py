# Arma el contenido de nlp_resultado.json a partir de ocr_resultado.json, sin escribir nada.
# probar_nlp.procesar_carpeta lo guarda en disco; el evaluador (evaluador/) lo usa en memoria
# para medir un cambio del NLP sin tocar los JSON de produccion.

from .regex_extractor import RegexExtractor, ResultadoPagina


def clasificar_paginas_ocr(ocr_data: dict, extractor: RegexExtractor) -> list[ResultadoPagina]:
    datos_para_extractor = [
        {"imagen": p["pagina"], "bloques": p["bloques"], "ancho_pagina": p.get("ancho_pagina")}
        for p in ocr_data.get("paginas", [])
    ]
    return extractor.procesar_json_ocr(datos_para_extractor)


def resultado_nlp(ocr_data: dict, resultados_paginas: list[ResultadoPagina]) -> dict:
    # Totales por categoría y tasa útil
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

    # Cada página con sus bloques clasificados
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
                {"texto": e.texto_norm, "valor": e.valor, "candidatos": e.candidatos,
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
    return resultado
