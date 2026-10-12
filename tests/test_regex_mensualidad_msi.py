"""Chedraui: la mensualidad "9 MSI | $777.22" de la etiqueta de la casilla no es el precio del producto."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques, ancho=1200):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho})


def _casilla_pegada(linea_9, linea_12):
    """Geometria real de chedraui 428352 p8 (ancho 1200): precio grande + mensualidades + nombre."""
    return [
        _b("$11,995", 849, 291, 206, 66),
        _b(linea_9, 858, 388, 130, 24),
        _b(linea_12, 854, 422, 140, 24),
        _b("Lavadora 21 kg", 858, 455, 160, 26),
    ]


@pytest.mark.parametrize("linea_9,linea_12", [
    ("9MSI | $1,3327", "(12MSI | $99958"),
    ("9 MSI | $77722", "12 MSI | $58292"),
    ("9MSI|$1,44433)", "(12MsI/$70750"),
    ("9MSI [$1,666\"", "I2MSI | 51,58292"),
    ("(9MSI |$355", "[12 MsI| $49958"),
    ("9MSI /$1,888*3", "(i2MSI $4741)"),
    ("9 MSI /81,221\"", "l2MsI | $79125"),
    ("MSI | $34944", "15MSI |$1,19993"),
    ("9MsI| $3883}", "'12MsI| $541?5"),
    ("9 MSI de $777.22", "12 MSI de $582.92"),
])
def test_mensualidad_pegada_al_rotulo_no_es_precio(linea_9, linea_12):
    res = _pagina(_casilla_pegada(linea_9, linea_12))
    assert [e.valor for e in res.precios] == [11995.0]
    assert {linea_9, linea_12} <= {e.texto_raw for e in res.descartes}


def test_mensualidad_en_bloque_aparte_no_es_precio():
    # chedraui 425917 p7: "9MSI" + "877722" y "(i2MsI" + "858292" en bloques separados
    res = _pagina([
        _b("86,995", 928, 274, 199, 68),
        _b("9MSI", 943, 339, 46, 20),
        _b("877722", 999, 339, 62, 20),
        _b("(i2MsI", 936, 370, 64, 26),
        _b("858292", 1008, 370, 72, 26),
        _b("Motobici eléctrica", 932, 402, 192, 26),
    ])
    assert [e.valor for e in res.precios] == [6995.0]
    assert {"877722", "858292"} <= {e.texto_raw for e in res.descartes}


@pytest.mark.parametrize("monto", ["$77722", "$1,44433", "51,22167", "841583", "$611"])
def test_monto_aparte_variantes(monto):
    res = _pagina([
        _b("$6,995", 928, 274, 199, 68),
        _b("9 MSI", 943, 339, 46, 20),
        _b(monto, 943 + 46 + 8, 337, 62, 24),
        _b("Motobici eléctrica", 932, 402, 192, 26),
    ])
    assert [e.valor for e in res.precios] == [6995.0]


@pytest.mark.parametrize("rotulo", ["9 MSI", "(12 MSI", "12 MSII", "{12 MSI"])
def test_rotulo_solo_no_es_producto(rotulo):
    # Antes "9 MSI" pasaba como PRODUCTO y podia asociarse como nombre
    res = _pagina([_b(rotulo, 61, 339, 46, 20)])
    assert res.productos == []


# ---------------- Casos que NO deben cambiar ----------------

def test_precio_real_antes_de_msi_se_conserva():
    # Un precio real en el mismo bloque, antes de la mensualidad, sigue siendo el precio
    res = _pagina([_b("$5,999 o 12 MSI de $499.92", 100, 300, 300, 30)])
    assert [e.valor for e in res.precios] == [5999.0]


def test_precio_grande_a_la_derecha_lejos_del_rotulo_se_conserva():
    # Un precio grande (alto > 2.5x el rotulo) en la misma linea no es la mensualidad
    res = _pagina([
        _b("9 MSI", 300, 300, 46, 20),
        _b("$5,699", 300 + 46 + 5, 280, 180, 60),
    ])
    assert [e.valor for e in res.precios] == [5699.0]


def test_precio_debajo_del_rotulo_no_cambia():
    res = _pagina([
        _b("12 MSI", 37, 249, 60, 20),
        _b("$399", 37, 290, 80, 30),
        _b("Pista Ferrari", 28, 330, 130, 26),
    ])
    assert [e.valor for e in res.precios] == [399.0]


@pytest.mark.parametrize("texto", [
    "MSI aplican pagando con Paypal:",
    "+6 MSI con",
    "MSI GF63 Thin",
    "mslo",
    "@PTIMSI",
    "PARACETAMSL",
])
def test_textos_con_msi_que_no_son_mensualidad(texto):
    assert not RegexExtractor.PATRONES_DESCARTE[-1].search(texto)


@pytest.mark.parametrize("texto,valor", [
    ("M51 $4,999", 4999.0),      # Samsung Galaxy M51
    ("M5i $2,499", 2499.0),
    ("m5l $12.90", 12.90),
    ("MS11 $25", 25.0),
    ("M S 1 $45", 45.0),
    ("M5 I $99", 99.0),
])
def test_sin_numero_de_meses_un_modelo_no_se_descarta(texto, valor):
    # QA 12-oct-2026: sin N delante solo cuenta "MSI" literal (con la I deformada)
    assert not RegexExtractor.PATRONES_DESCARTE[-1].search(texto)
    res = _pagina([_b(texto, 100, 300, 200, 30)])
    assert texto not in [e.texto_raw for e in res.descartes]
    assert [e.valor for e in res.precios] == [valor]


@pytest.mark.parametrize("texto", ["M5I 3x2", "MSl 2x$50"])
def test_sin_numero_de_meses_una_promo_no_se_descarta(texto):
    assert not RegexExtractor.PATRONES_DESCARTE[-1].search(texto)
    res = _pagina([_b("$5,999", 100, 200, 200, 66), _b(texto, 100, 300, 200, 30)])
    assert texto not in [e.texto_raw for e in res.descartes]


@pytest.mark.parametrize("texto", ["MSI | $34944", "MSI|$1,499", "MSl / $1,499", "MS1 [$1,499", "MSI",
                                   "9MSI|$1,44433)", "(12MsI/$70750", "I2MSI | 51,58292", "(gMsI |$1,299*4"])
def test_mensualidad_con_y_sin_numero_se_descarta(texto):
    assert RegexExtractor.PATRONES_DESCARTE[-1].search(texto)


def test_precio_sin_msi_no_cambia():
    res = _pagina([
        _b("Refresco Cola 2 L", 37, 249, 140, 20),
        _b("$50", 37 + 140 + 9, 246, 56, 30),
    ])
    assert [e.valor for e in res.precios] == [50.0]


def test_anticipo_de_apartado_sigue_igual():
    res = _pagina([
        _b("$2,099", 21, 179, 205, 72),
        _b("Apártalo con", 37, 249, 98, 20),
        _b("$50", 144, 246, 56, 30),
        _b("Pista Ferrari", 28, 278, 130, 26),
    ])
    assert [e.valor for e in res.precios] == [2099.0]
