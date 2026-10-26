"""Un "$" que el OCR leyo como bloque aparte, pegado a la izquierda del numero, es senal de precio
(PATRON_SIGNO_SUELTO / _tiene_signo_suelto): bodega_aurrera 417119 p1 y 429796 p1, calimax 136384 p2."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=30, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques, ancho_pagina=1800):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho_pagina})
    return sorted(e.valor for e in res.precios)


def _texto_de_pagina(alto=32):
    # Nombres de otras casillas, lejos: fijan la mediana del alto del texto
    return [_bloque("Leche entera 1 L", 100, 2500, alto=alto), _bloque("Detergente en polvo", 100, 2600, alto=alto),
            _bloque("Varios sabores", 100, 2700, alto=alto)]


def test_signo_suelto_entero_sin_producto_cerca_es_precio():
    # 417119 p1 (geometria real): "$" de 31 px pegado al "35" de 60 px, sin nombre al lado (B-2 lo descartaba)
    bloques = _texto_de_pagina() + [_bloque("35", 1250, 995, ancho=85, alto=60), _bloque("$", 1228, 1003, ancho=24, alto=31)]
    assert _precios(bloques) == [35.0]


def test_sin_signo_el_mismo_numero_sigue_fuera():
    bloques = _texto_de_pagina() + [_bloque("35", 1250, 995, ancho=85, alto=60)]
    assert _precios(bloques) == []


def test_signo_suelto_que_se_mete_en_el_numero():
    # 429796 p1: "$" de 60 px que termina 30 px dentro del "10" de 161 px
    bloques = _texto_de_pagina(48) + [_bloque("10", 252, 398, ancho=209, alto=161), _bloque("$", 234, 462, ancho=48, alto=60)]
    assert _precios(bloques) == [10.0]


def test_signo_suelto_gana_a_continua_nombre():
    # 429796 p1: el "50" de 152 px queda en la linea de un texto de 161 px a su izquierda
    # (_continua_nombre lo quitaba), pero el "$" esta entre los dos
    bloques = _texto_de_pagina(48) + [_bloque("ANOLRNolRNo)", 1000, 2770, ancho=400, alto=161),
                                      _bloque("$", 1435, 2836, ancho=44, alto=54), _bloque("50", 1461, 2774, ancho=212, alto=152)]
    assert _precios(bloques) == [50.0]


def test_signo_suelto_gana_al_alto_como_texto():
    # Numero chico frente al texto de la pagina (0.9x la mediana) con su "$" aparte: es precio
    bloques = _texto_de_pagina(40) + [_bloque("$", 480, 1012, ancho=14, alto=16), _bloque("20", 490, 1000, ancho=40, alto=36)]
    assert _precios(bloques) == [20.0]


def test_signo_suelto_con_centavos_b4():
    bloques = _texto_de_pagina() + [_bloque("$", 1000, 1020, ancho=30, alto=40), _bloque("1890", 1025, 1000, ancho=200, alto=90)]
    assert _precios(bloques) == [18.9]


def test_signo_no_pegado_no_cuenta():
    base = _texto_de_pagina() + [_bloque("35", 1250, 995, ancho=85, alto=60)]
    # a la derecha del numero
    assert _precios(base + [_bloque("$", 1340, 1003, ancho=24, alto=31)]) == []
    # lejos a la izquierda (hueco > 0.3x el alto del numero)
    assert _precios(base + [_bloque("$", 1200, 1003, ancho=24, alto=31)]) == []
    # encima del numero (centro fuera de su altura)
    assert _precios(base + [_bloque("$", 1228, 940, ancho=24, alto=31)]) == []
    # mas alto que el numero: es otro precio, no el signo de este
    assert _precios(base + [_bloque("$", 1180, 980, ancho=60, alto=80)]) == []


def test_signo_suelto_no_cambia_b3():
    # "$" + "129": $129 o $1.29 es ambiguo; B-3 sigue exigiendo contexto fuerte
    bloques = _texto_de_pagina() + [_bloque("$", 1000, 1015, ancho=30, alto=40), _bloque("129", 1025, 1000, ancho=150, alto=90)]
    assert 1.29 not in _precios(bloques)


def test_patron_signo_suelto():
    for t in ("$", " $ ", "$.", "'$", "($"):
        assert EX.PATRON_SIGNO_SUELTO.match(t.strip()), t
    for t in ("$35", "S", "5", "$$5", "s"):
        assert not EX.PATRON_SIGNO_SUELTO.match(t), t
