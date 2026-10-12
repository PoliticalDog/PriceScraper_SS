"""Chedraui: el anticipo de apartado leido en un bloque aparte, a la derecha de "Apartalo con", no es precio."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques, ancho=1200):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho})


def _casilla(rotulo, monto, gap=9):
    """Geometria real de chedraui 428354 p15/p16 (ancho 1200): precio grande, rotulo + monto, nombre."""
    return [
        _b("$2,099", 21, 179, 205, 72),
        _b(rotulo, 37, 249, 98, 20),
        _b(monto, 37 + 98 + gap, 246, 56, 30),
        _b("Pista Ferrari", 28, 278, 130, 26),
    ]


@pytest.mark.parametrize("monto", ["$50", "850", "$59990", "838650", "889950", "$1,48950", "81,39959"])
def test_monto_junto_al_rotulo_no_es_precio(monto):
    res = _pagina(_casilla("Apártalo con", monto))
    assert [e.valor for e in res.precios] == [2099.0]
    assert monto in [e.texto_raw for e in res.descartes]


@pytest.mark.parametrize("rotulo", ["Apártalo con |", "Apartalo cou", "Apartalorcon", "Aprtallo coh", "Apärtalo con"])
def test_variantes_ocr_del_rotulo(rotulo):
    res = _pagina(_casilla(rotulo, "$50"))
    assert [e.valor for e in res.precios] == [2099.0]


def test_gap_negativo_y_superpuesto():
    # "Apártalo con" + "1$1,09950" (428354 p4): el OCR solapa 5 px los bloques
    res = _pagina(_casilla("Apártalo con", "1$1,09950", gap=-5))
    assert [e.valor for e in res.precios] == [2099.0]


def test_precio_grande_a_la_derecha_del_rotulo_se_conserva():
    # 428354 p14: rotulo con monto pegado y el precio grande "$5,699" (alto 66) a 110 px
    res = _pagina([
        _b("Apártalo con", 300, 300, 98, 20),
        _b("$5,699", 300 + 98 + 12, 255, 180, 66),
        _b("Bicicleta R26", 300, 330, 150, 26),
    ])
    assert [e.valor for e in res.precios] == [5699.0]


def test_precio_alto_pegado_al_rotulo_no_se_toma_como_anticipo():
    # Un bloque de precio grande (alto > 2.5x el rotulo) nunca es la linea del anticipo
    res = _pagina([
        _b("Apártalo con", 300, 300, 98, 20),
        _b("$5,699", 300 + 98 + 5, 280, 180, 60),
        _b("Bicicleta R26", 300, 350, 150, 26),
    ])
    assert [e.valor for e in res.precios] == [5699.0]


def test_solo_el_bloque_mas_cercano_por_rotulo():
    res = _pagina([
        _b("Apártalo con", 37, 249, 98, 20),
        _b("$50", 144, 246, 56, 30),
        _b("$79", 144 + 56 + 2, 246, 50, 30),
        _b("Pista Ferrari", 28, 278, 130, 26),
    ])
    assert [e.valor for e in res.precios] == [79.0]


def test_50_que_si_es_precio_sin_rotulo_no_cambia():
    # Otra tienda: "$50" junto a un nombre, sin "Apartalo con" en la pagina
    res = _pagina([
        _b("Refresco Cola 2 L", 37, 249, 140, 20),
        _b("$50", 37 + 140 + 9, 246, 56, 30),
    ])
    assert [e.valor for e in res.precios] == [50.0]


def test_precio_debajo_del_rotulo_no_cambia():
    # El monto que NO esta en la misma linea del rotulo (debajo) sigue siendo precio
    res = _pagina([
        _b("Apártalo con", 37, 249, 98, 20),
        _b("$399", 37, 290, 80, 30),
        _b("Pista Ferrari", 28, 330, 130, 26),
    ])
    assert [e.valor for e in res.precios] == [399.0]


def test_otro_rotulo_con_precio_a_la_derecha_no_cambia():
    # "a sólo:" + "$149" en la misma linea: el precio real se conserva
    res = _pagina([
        _b("a sólo:", 37, 249, 70, 20),
        _b("$149", 37 + 70 + 9, 246, 60, 30),
        _b("Jabon Zote 400 g", 28, 278, 160, 26),
    ])
    assert [e.valor for e in res.precios] == [149.0]


def test_nombre_a_la_derecha_del_rotulo_no_se_descarta():
    # Solo se toman bloques con digitos: un nombre a la derecha sigue siendo producto
    res = _pagina([
        _b("Apártalo con", 37, 249, 98, 20),
        _b("Bicicleta", 37 + 98 + 9, 246, 90, 30),
        _b("$1,299", 37, 180, 180, 66),
    ])
    assert "Bicicleta" in [e.texto_raw for e in res.productos]
