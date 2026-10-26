"""Centavos consumidos: el bloque de centavos que ya se sumo a un precio (fusion de _detectar_precios_fusionados o
Regla A-escala) no sale ademas como precio propio ("99"+"90" = $99.90, sin un $90 suelto). Contrapruebas: un "$99"
real sin entero a la izquierda, casa_ley "544"+"90", fusiones validas y A-escala sin centavos."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=30, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques, ancho_pagina=1500):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho_pagina})


def _precios(bloques, ancho_pagina=1500):
    return sorted(e.valor for e in _pagina(bloques, ancho_pagina).precios)


def _texto_de_pagina(alto=30):
    return [_bloque("Leche entera 1 L", 100, 2500, alto=alto), _bloque("Detergente en polvo", 100, 2600, alto=alto),
            _bloque("Varios sabores", 100, 2700, alto=alto)]


def test_fusion_consume_los_centavos():
    # alsuper 416306 p2 (geometria real): "99"+"90" = $99.90; antes ademas salia $90 (B-2 con producto cerca)
    bloques = [_bloque("99", 1169, 1237, 86, 64), _bloque("90", 1247, 1235, 50, 42),
               _bloque("PECHUGA DE POLLO KG", 1000, 1240, 160, 24)]
    assert _precios(bloques) == [99.9]


def test_fusion_con_signo_consume_los_centavos():
    # arteli 135652 p1: "$19"+"90" = $19.90 y nada mas
    bloques = [_bloque("$19", 125, 1850, 121, 84), _bloque("90", 236, 1859, 56, 38),
               _bloque("Leche condensada Pronto", 100, 1950, 260, 30)]
    assert _precios(bloques, 1800) == [19.9]


def test_a_escala_consume_los_centavos():
    # merco 423338 p6: "839"+"99" = $39.99 y "824"+"99" = $24.99, sin $99 sueltos
    bloques = _texto_de_pagina() + [
        _bloque("839", 200, 400, ancho=170, alto=80), _bloque("99", 380, 405, ancho=50, alto=40),
        _bloque("HARINA DE TRIGO", 450, 410, ancho=160, alto=26),
        _bloque("824", 800, 400, ancho=170, alto=80), _bloque("99", 980, 405, ancho=50, alto=40),
        _bloque("ATUN EN AGUA", 1050, 410, ancho=160, alto=26),
    ]
    assert _precios(bloques, 1800) == [24.99, 39.99]


def test_a_escala_centavos_antes_que_el_entero():
    # El bloque de centavos va primero en la lista del OCR: igual queda consumido
    bloques = _texto_de_pagina() + [
        _bloque("99", 380, 405, ancho=50, alto=40), _bloque("839", 200, 400, ancho=170, alto=80),
        _bloque("HARINA DE TRIGO", 450, 410, ancho=160, alto=26),
        _bloque("824", 800, 400, ancho=170, alto=80),
    ]
    assert 99.0 not in _precios(bloques, 1800)


def test_precio_99_real_sin_entero_no_cambia():
    # bodega_aurrera 417943 p1: "$99" grande bajo "PRECIO BODEGA", sin entero a la izquierda
    bloques = _texto_de_pagina() + [_bloque("PRECIO BODEGA", 1250, 650, ancho=220, alto=60),
                                    _bloque("99", 1271, 731, ancho=196, alto=122),
                                    _bloque("Cerveza Tecate 6 pack", 1200, 900, ancho=240, alto=30)]
    assert _precios(bloques, 1800) == [99.0]


def test_casa_ley_544_90_no_cambia():
    # casa_ley 427141 p1: "544"+"90" = $544.90 (entero de 3 digitos, no se fusiona): no se crea ningun 44/44.90
    bloques = _texto_de_pagina() + [
        _bloque("544", 200, 400, ancho=110, alto=70), _bloque("90", 315, 402, ancho=30, alto=30),
        _bloque("174", 800, 400, ancho=110, alto=70), _bloque("50", 915, 402, ancho=30, alto=30),
    ]
    precios = _precios(bloques, 1800)
    assert 44.0 not in precios and 44.9 not in precios and 54.49 not in precios


def test_fusion_valida_y_entero_aparte():
    # Dos casillas: una con superindice y otra sin; el "45" de la segunda sigue siendo precio
    bloques = [_bloque("99", 1169, 1237, 86, 64), _bloque("90", 1247, 1235, 50, 42),
               _bloque("PECHUGA DE POLLO KG", 1000, 1320, 160, 24),
               _bloque("45", 300, 600, 86, 64), _bloque("PAPA BLANCA KG", 300, 680, 160, 24)]
    assert _precios(bloques) == [45.0, 99.9]


def test_centavos_consumidos_van_a_descartes():
    res = _pagina([_bloque("99", 1169, 1237, 86, 64), _bloque("90", 1247, 1235, 50, 42),
                   _bloque("PECHUGA DE POLLO KG", 1000, 1240, 160, 24)])
    assert [e.texto_raw for e in res.precios] == ["99+90"]
