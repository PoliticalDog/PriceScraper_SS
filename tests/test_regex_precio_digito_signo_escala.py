"""Regla A-escala (PATRON_DIGITO_SIGNO / _escala_digito_signo): el "$" leido 5/6/8/s + entero de 2 digitos se
lee $dd solo cuando todos los bloques de 3 caracteres de alto parecido de la pagina empiezan con 5/6/8/s
(merco "839"+"99", bodega_aurrera "835", tiendas_3b "s19"); los enteros reales de 3 digitos de casa_ley
("544"+"90") o alsuper ("239"+"90") no cambian."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=30, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques, ancho_pagina=1800):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho_pagina})
    return sorted(e.valor for e in res.precios)


def _texto_de_pagina(alto=30):
    # Nombres de otras casillas, lejos: fijan la mediana del alto del texto
    return [_bloque("Leche entera 1 L", 100, 2500, alto=alto), _bloque("Detergente en polvo", 100, 2600, alto=alto),
            _bloque("Varios sabores", 100, 2700, alto=alto)]


def test_merco_signo_leido_8_con_centavos_en_superindice():
    # merco 423338 p6 / 423341 p3: "$39⁹⁹" y "$24⁹⁹"
    bloques = _texto_de_pagina() + [
        _bloque("839", 200, 400, ancho=170, alto=80), _bloque("99", 380, 405, ancho=50, alto=40),
        _bloque("824", 800, 400, ancho=170, alto=80), _bloque("99", 980, 405, ancho=50, alto=40),
    ]
    assert _precios(bloques) == [24.99, 39.99]


def test_merco_enteros_con_un_solo_superindice_en_la_pagina():
    # merco 423338 p16: "$59", "$54", "$24" sin centavos y un solo "$29⁹⁹"
    bloques = _texto_de_pagina() + [
        _bloque("859", 200, 400, ancho=170, alto=80), _bloque("854", 800, 400, ancho=170, alto=80),
        _bloque("824", 200, 1200, ancho=170, alto=80),
        _bloque("829", 800, 1200, ancho=170, alto=80), _bloque("99", 980, 1205, ancho=50, alto=40),
    ]
    assert _precios(bloques) == [24.0, 29.99, 54.0, 59.0]


def test_heb_centavos_perdidos_no_crea_precio():
    # heb 424850 p1: "s27" es $27⁹⁰ (el OCR perdio el "90") junto a "s39"+"90" y "s59"+"90"
    bloques = _texto_de_pagina() + [
        _bloque("s39", 280, 440, ancho=130, alto=80), _bloque("90", 410, 450, ancho=45, alto=36),
        _bloque("s59", 1580, 740, ancho=140, alto=86), _bloque("90", 1710, 755, ancho=45, alto=36),
        _bloque("s27", 288, 594, ancho=132, alto=80),
    ]
    precios = _precios(bloques)
    assert 27.0 not in precios and precios == [39.9, 59.9]


def test_bodega_signo_leido_8_sin_centavos():
    # bodega_aurrera 417118 p2: "$22", "$45", "$35"
    bloques = _texto_de_pagina() + [_bloque("822", 200, 400, ancho=150, alto=100), _bloque("845", 800, 400, ancho=150, alto=100),
                                    _bloque("835", 200, 1200, ancho=150, alto=110)]
    assert _precios(bloques) == [22.0, 35.0, 45.0]


def test_tiendas_3b_signo_leido_s():
    # tiendas_3b 419897 p7: recuadro rojo "$29.00", "$59.00"
    bloques = _texto_de_pagina() + [_bloque("s29", 200, 400, ancho=150, alto=70), _bloque("s59", 800, 400, ancho=150, alto=70)]
    assert _precios(bloques) == [29.0, 59.0]


def test_casa_ley_enteros_de_tres_digitos_no_cambian():
    # casa_ley 427141 p1: "544"+"90" = $544.90 junto a otros enteros de 3 digitos que no empiezan con 5/6/8
    bloques = _texto_de_pagina() + [
        _bloque("544", 200, 400, ancho=110, alto=70), _bloque("90", 315, 402, ancho=30, alto=30),
        _bloque("174", 800, 400, ancho=110, alto=70), _bloque("50", 915, 402, ancho=30, alto=30),
        _bloque("299", 200, 1200, ancho=110, alto=70), _bloque("90", 315, 1202, ancho=30, alto=30),
    ]
    precios = _precios(bloques)
    assert 44.0 not in precios and 44.9 not in precios


def test_alsuper_239_90_no_cambia():
    # alsuper: "239"+"90" = $239.90 y "549"+"90" = $549.90 en la misma pagina
    bloques = _texto_de_pagina() + [
        _bloque("239", 200, 400, ancho=110, alto=70), _bloque("90", 315, 402, ancho=30, alto=30),
        _bloque("549", 800, 400, ancho=110, alto=70), _bloque("90", 915, 402, ancho=30, alto=30),
    ]
    precios = _precios(bloques)
    assert 49.0 not in precios and 49.9 not in precios and 39.9 not in precios


def test_un_solo_bloque_no_da_escala():
    # la_comer "844" en un empaque, waldos "509" = 50%: sin otro bloque de 3 caracteres no hay escala
    assert _precios(_texto_de_pagina() + [_bloque("835", 200, 400, ancho=150, alto=100)]) == []


def test_galaxy_s23_solo_no_es_precio():
    assert _precios(_texto_de_pagina() + [_bloque("S23", 200, 400, ancho=150, alto=100)]) == []


def test_iphone_14_sigue_fuera():
    # bodega_aurrera 412322 p2: "iPhone" / "14" del nombre, aunque la pagina tenga precios con el "$" leido 8
    bloques = _texto_de_pagina(30) + [
        _bloque("iPhone", 300, 600, ancho=200, alto=67), _bloque("14", 510, 598, ancho=70, alto=72),
        _bloque("835", 200, 1200, ancho=150, alto=100), _bloque("845", 800, 1200, ancho=150, alto=100),
    ]
    precios = _precios(bloques)
    assert 14.0 not in precios and precios == [35.0, 45.0]


def test_porcentaje_con_leyenda_debajo_no_es_precio():
    # merco 432383 p7: "25%" leido "559" sobre "DE DESCUENTO", en una pagina con "$39⁹⁹" leido "839"
    bloques = _texto_de_pagina() + [
        _bloque("559", 200, 400, ancho=200, alto=100), _bloque("DE DESCUENTO", 180, 505, ancho=260, alto=40),
        _bloque("839", 800, 400, ancho=170, alto=90), _bloque("99", 980, 405, ancho=50, alto=40),
    ]
    precios = _precios(bloques)
    assert 59.0 not in precios and 39.99 in precios


def test_letra_de_texto_no_cuenta():
    # Menos de ALTO_MIN_DIGITO_SIGNO x la mediana del texto: parte de un nombre o atributo
    bloques = _texto_de_pagina(40) + [_bloque("835", 200, 400, ancho=90, alto=60), _bloque("845", 800, 400, ancho=90, alto=60)]
    assert _precios(bloques) == []


def test_primer_digito_cero_no_cuenta():
    # soriana_mercado 425730 p15: "50%" leido "S08"
    bloques = _texto_de_pagina() + [_bloque("S08", 200, 400, ancho=150, alto=100), _bloque("S09", 800, 400, ancho=150, alto=100)]
    assert _precios(bloques) == []


def test_escala_gana_a_b3_con_contexto_fuerte():
    # Antes B-3 leia "835" junto a "Antes" como $8.35
    bloques = _texto_de_pagina() + [_bloque("835", 200, 400, ancho=150, alto=100), _bloque("Antes", 200, 510, ancho=80, alto=25),
                                    _bloque("845", 800, 400, ancho=150, alto=100)]
    precios = _precios(bloques)
    assert 35.0 in precios and 8.35 not in precios


def test_patron_digito_signo():
    for t, v in (("835", "35"), ("s19", "19"), ("S42", "42"), ("629", "29"), ("599", "99")):
        assert EX.PATRON_DIGITO_SIGNO.match(t).group(1) == v, t
    for t in ("S08", "800", "135", "8355", "$35", "83", "s1"):
        assert not EX.PATRON_DIGITO_SIGNO.match(t), t
