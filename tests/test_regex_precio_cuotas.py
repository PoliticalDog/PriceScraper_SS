"""Chedraui: el precio grande con el "$" leido 8/5/S se elige con la mensualidad o el anticipo de su casilla."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques, ancho=1200):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho})


def _precios(res):
    return sorted(e.valor for e in res.precios)


def test_tablet_428354_p4_anticipo_y_mensualidad():
    # "82995c/u" no lo lee ninguna regla (4 digitos + c/u); anticipo $299.50 y 9 x $332.78
    res = _pagina([
        _b("82995c/u", 935, 1259, 244, 66),
        _b("Apártalo con", 947, 1327, 94, 16),
        _b("829950", 1053, 1319, 87, 30),
        _b("9MSI | $33278", 946, 1354, 116, 24),
        _b("Tablet", 938, 1388, 68, 26),
    ])
    assert _precios(res) == [2995.0]


def test_s_por_signo_con_anticipo_428354_p8():
    # Hoy PATRON_PRECIO_OCR_CORRUPTO lo lee $79.95
    res = _pagina([
        _b("S7995", 935, 300, 200, 68),
        _b("Apártalo con", 947, 375, 94, 16),
        _b("$79950", 1053, 368, 87, 30),
        _b("9 MSI | $88833", 946, 400, 116, 24),
        _b("12 MSI | $66625", 946, 430, 130, 24),
        _b("Lavadora 20 kg", 938, 460, 160, 26),
    ])
    assert _precios(res) == [7995.0]


def test_mensualidad_en_bloque_aparte_425917_p7():
    # "86495" -> hoy $64.95; "9 MSI" + "872167" ($721.67 con el "$" leido 8)
    res = _pagina([
        _b("Antes: $8,395", 52, 256, 138, 26),
        _b("86495", 47, 274, 197, 66),
        _b("9 MSI", 61, 339, 46, 20),
        _b("872167", 119, 339, 56, 20),
        _b("(12MsI|", 54, 370, 64, 24),
        _b("854125", 128, 370, 68, 24),
        _b("Scooter eléctrico", 50, 400, 160, 26),
    ])
    assert 6495.0 in _precios(res)
    assert 64.95 not in _precios(res)


def test_miles_con_cu_416057_p5():
    res = _pagina([
        _b("85,990c/u", 370, 300, 200, 76),
        _b("9 MSI |$66556", 385, 380, 112, 20),
        _b("12 MSI |$49917", 385, 410, 120, 20),
        _b("Refrigerador", 377, 440, 120, 26),
    ])
    assert _precios(res) == [5990.0]


def test_anticipo_de_50_no_confirma():
    # 428354 p15: "8929" es $929 pero el anticipo es el minimo fijo de $50: no cambia
    res = _pagina([
        _b("8929", 958, 552, 149, 67),
        _b("Apártalo con| $50", 970, 618, 164, 30),
        _b("Vehículo SONIC", 961, 644, 169, 30),
    ])
    assert _precios(res) == [89.29]


def test_sin_cuotas_no_cambia():
    res = _pagina([
        _b("86495", 47, 274, 197, 66),
        _b("Scooter eléctrico", 50, 345, 160, 26),
    ])
    assert _precios(res) == [64.95]


def test_mensualidad_que_no_cuadra_no_cambia():
    res = _pagina([
        _b("S7995", 935, 300, 200, 68),
        _b("9 MSI | $12345", 946, 400, 116, 24),
        _b("Lavadora 20 kg", 938, 460, 160, 26),
    ])
    assert _precios(res) == [79.95]


def test_precio_con_signo_bien_leido_no_cambia():
    # "$6,490" con una mensualidad ilegible ("727"") se queda en 6490
    res = _pagina([
        _b("$6,490", 370, 300, 200, 72),
        _b('9 MSI |727"', 385, 380, 112, 20),
        _b("Colchón", 377, 440, 120, 26),
    ])
    assert _precios(res) == [6490.0]


def test_precio_correcto_confirmado_se_conserva():
    # "85,495" ya se lee $5,495 (Regla A-miles); el anticipo "854950" admite 5495 y 85495:
    # la mensualidad desempata y el valor no cambia
    res = _pagina([
        _b("85,495", 935, 300, 200, 64),
        _b("Apártalo con", 947, 375, 94, 16),
        _b("854950", 1053, 368, 87, 30),
        _b("9 MSI | $61056", 946, 400, 116, 24),
        _b("Multifuncional", 938, 460, 160, 26),
    ])
    assert _precios(res) == [5495.0]


def test_empate_no_elige():
    # Solo el anticipo "829950": 82995 y 2995 cuadran igual -> no se elige ninguno
    res = _pagina([
        _b("82995c/u", 935, 1259, 244, 66),
        _b("Apártalo con", 947, 1327, 94, 16),
        _b("829950", 1053, 1319, 87, 30),
        _b("Tablet", 938, 1388, 68, 26),
    ])
    assert 2995.0 not in _precios(res) and 82995.0 not in _precios(res)


def test_rotulo_encima_del_precio_no_cuenta():
    # La etiqueta de la casilla de arriba (por encima del precio) no confirma este precio
    res = _pagina([
        _b("9 MSI | $88833", 946, 230, 116, 24),
        _b("S7995", 935, 300, 200, 68),
        _b("Lavadora 20 kg", 938, 380, 160, 26),
    ])
    assert _precios(res) == [79.95]


def test_rotulo_de_la_casilla_de_al_lado_no_cuenta():
    # La mensualidad de la casilla vecina (sin traslape horizontal con el precio) no confirma
    res = _pagina([
        _b("S7995", 935, 300, 200, 68),
        _b("9 MSI | $88833", 812, 360, 120, 24),
        _b("Lavadora 20 kg", 938, 380, 160, 26),
    ])
    assert _precios(res) == [79.95]


@pytest.mark.parametrize("texto,esperado", [
    ("$1,48950", {1489.5}), ("|$355", {3.55, 355.0}), ("858292", {8582.92, 582.92}),
    ("s99083", {990.83}), ("1,655", {16.55, 1655.0}), ("abc", set()),
])
def test_lecturas_monto_cuota(texto, esperado):
    lecturas = EX._lecturas_monto_cuota(texto)
    assert all(any(abs(l - e) < 1e-6 for l in lecturas) for e in esperado)
