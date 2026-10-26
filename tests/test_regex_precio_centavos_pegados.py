"""Centavos pegados (PATRON_CENTAVOS_PEGADOS): "$" literal + 4-5 digitos sin separador es entero + centavos en
superindice que el OCR junto en un bloque ("$2189" = $21⁸⁹, no $2,189). Contrapruebas: precios grandes reales con
coma (A2-miles, "$1,299"), "$" + 3 digitos, 6 digitos y las fusiones/enteros de 3 digitos de otras reglas."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=160, alto=70, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques, ancho_pagina=1500):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho_pagina})
    return sorted(e.valor for e in res.precios)


def _solo(texto):
    return _precios([_bloque(texto, 100, 100), _bloque("Pepino verde", 100, 30, alto=24)])


@pytest.mark.parametrize("texto, valor", [
    ("$2189", 21.89),     # soriana_hiper 418060 p3: $21⁸⁰ (el "80" subrayado leido "89")
    ("$1990", 19.90),     # arteli 135664 p1: $19⁹⁰
    ("$7899", 78.99),     # merco 428257 p15: $78⁹⁹
    ("$1000", 10.00),     # soriana_hiper 418863 p6: "A SOLO: $10⁰⁰"
    ("$3450", 34.50),     # soriana_mercado 417964 p2
    ("$10399", 103.99),   # soriana_mercado 417965 p2: $103⁹⁰
    ("$64990", 649.90),   # soriana_mercado 428317 p5
    ("$31304", 313.04),   # sam's_club 431992 p3: "$313.04" sin el punto
    ("$1990 c/u", 19.90),
    ("$ 2290", 22.90),
])
def test_signo_mas_cuatro_o_cinco_digitos_lleva_centavos(texto, valor):
    assert _solo(texto) == [valor]


@pytest.mark.parametrize("texto, valor", [
    ("$1,299", 1299.0),       # coma de miles: precio grande real
    ("$10,999", 10999.0),
    ("$1,299.00", 1299.0),
    ("$4,395.80", 4395.8),
    ("$18.50", 18.5),
    ("$379", 379.0),          # soriana_hiper 422326 p13: "$" + 3 digitos es real
    ("$849", 849.0),          # walmart 413251 p2
    ("$129900", 129900.0),    # 6 digitos: fuera a proposito
    ("$12990.00", 12990.0),   # con punto decimal detras: fuera a proposito
])
def test_formas_sin_cambio(texto, valor):
    assert _solo(texto) == [valor]


def test_a2_miles_soriana_no_cambia():
    # soriana_hiper (A2-miles, 94cc22a): "511,99000" = $11,990⁰⁰ y "52,49000" = $2,490⁰⁰, precios reales
    assert _solo("511,99000") == [11990.0]
    assert _solo("52,49000") == [2490.0]


def test_fusion_entero_y_centavos_no_cambia():
    # merco 423338 p6: "839"+"99" = $39.99 (Regla A-escala) y alsuper 416306 p2: "99"+"90" = $99.90 (fusion)
    texto = [_bloque("Leche entera 1 L", 100, 2500, alto=30), _bloque("Detergente en polvo", 100, 2600, alto=30),
             _bloque("Varios sabores", 100, 2700, alto=30)]
    bloques = texto + [
        _bloque("839", 200, 400, ancho=170, alto=80), _bloque("99", 380, 405, ancho=50, alto=40),
        _bloque("824", 800, 400, ancho=170, alto=80), _bloque("99", 980, 405, ancho=50, alto=40),
    ]
    precios = _precios(bloques, 1800)
    assert 39.99 in precios and 24.99 in precios
    assert 99.9 in _precios([_bloque("99", 1169, 1237, 86, 64), _bloque("90", 1247, 1235, 50, 42)])


def test_casa_ley_544_90_no_cambia():
    # casa_ley 427141 p1: "544"+"90" = $544.90, entero real de 3 digitos sin "$"
    texto = [_bloque("Leche entera 1 L", 100, 2500, alto=30), _bloque("Detergente en polvo", 100, 2600, alto=30),
             _bloque("Varios sabores", 100, 2700, alto=30)]
    bloques = texto + [
        _bloque("544", 200, 400, ancho=110, alto=70), _bloque("90", 315, 402, ancho=30, alto=30),
        _bloque("174", 800, 400, ancho=110, alto=70), _bloque("50", 915, 402, ancho=30, alto=30),
    ]
    precios = _precios(bloques, 1800)
    assert 44.0 not in precios and 44.9 not in precios and 5.44 not in precios
