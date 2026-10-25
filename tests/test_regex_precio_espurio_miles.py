"""Regla A2-miles: "$" leido 5/8/s + miles con coma + superindice pegado ("52,49000" = $2,490⁰⁰, no $2.49)."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=160, alto=70, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1500})
    return sorted(e.valor for e in res.precios)


def _solo(texto):
    return _precios([_bloque(texto, 100, 100), _bloque("Pantalla Smart TV 50 pulgadas", 100, 30, alto=24)])


@pytest.mark.parametrize("texto, valor", [
    ("52,49000", 2490.0),     # el caso del hallazgo (soriana_hiper / chedraui)
    ("51,42900", 1429.0),     # casa_ley 430499 p3
    ("s4,79900", 4799.0),     # la_comer 411547 p22
    ("s12,49800", 12498.0),   # la_comer 411547 p23
    ("88,49989", 8499.0),     # la_comer 425961 p14: $8,499⁰⁰ c/u, el "c/u" leido como digitos
    ("82,99929", 2999.0),     # la_comer 425961 p14: $2,999⁰⁰ c/u
    ("85,9990", 5999.0),      # la_comer 425961 p14: un solo digito del superindice
    ("529,990005", 29990.0),  # soriana_hiper 416117 p15: superindice + basura
    ("59,490o0", 9490.0),     # soriana_hiper 416117 p8: "00" leido "o0"
])
def test_miles_con_superindice_pegado(texto, valor):
    assert _solo(texto) == [valor]


@pytest.mark.parametrize("texto, valor", [
    ("824.95k6", 24.95),      # A2 original: decimal con punto + "kg" ilegible
    ("826,99", 26.99),        # s-mart: coma decimal con 2 digitos
    ("88,90", 8.90),          # merco
    ("5565.00", 565.0),
])
def test_a2_con_decimal_de_dos_digitos_no_cambia(texto, valor):
    assert _solo(texto) == [valor]


@pytest.mark.parametrize("texto, valor", [
    ("58,999", 8999.0),       # A-miles sin sufijo
    ("S9,499clu", 9499.0),    # A-miles con c/u ilegible
    ("s6,490oo", 6490.0),     # A-miles con superindice leido como letras
])
def test_a_miles_no_cambia(texto, valor):
    assert _solo(texto) == [valor]


def test_coma_de_miles_legitima_sin_espurio_no_cambia():
    # Regla C: "12,499" sin "$" se lee completo, no con el 1 como espurio
    assert _solo("12,499") == [12499.0]


def test_con_simbolo_de_pesos_no_pasa_por_la_regla():
    assert _solo("$2,49000") == [2490.0]
    assert _solo("$12,499") == [12499.0]


def test_punto_seguido_de_cinco_digitos_queda_fuera():
    # "51.06350" (casa_ley 426465) es ambiguo: el punto es decimal en MX. Esta regla no lo toca.
    assert EX.PATRON_DIGITO_ESPURIO_MILES_SUPERINDICE.match("51.06350") is None
    assert EX.PATRON_DIGITO_ESPURIO_MILES_SUPERINDICE.match("52.69900") is None
