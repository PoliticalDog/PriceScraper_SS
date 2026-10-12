"""Filtro de legibilidad del nombre en load.productos_aceptados / construir_registros_pagina."""
import pytest

from load.load import CONFIANZA_MINIMA_HEURISTICO, construir_registros_pagina, productos_aceptados
from nlp.normalizador import Normalizador

NORM = Normalizador()


def _bloque(texto, confianza, x=500, y=900, ancho=200, alto=30):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _textos(aceptados):
    return [p["texto"] for p in aceptados]


# Marcas y nombres legitimos fuera del catalogo (con su confianza OCR real en dev o una tipica)
LEGITIMOS = [
    ("Salsa Chamoy", 1.0), ("Bocina Partybox", 0.9), ("MORENA", 0.875), ("Hass", 0.978),
    ("Saladette", 0.97), ("SABRITAS", 0.616), ("Freidora Ninja", 0.9), ("Toallas Minecraft", 0.96),
    ("Smartdecó", 0.773), ("Botana $-Mart", 0.938), ("Bebida sabor Manzana;", 0.735),
]


@pytest.mark.parametrize("texto,confianza", LEGITIMOS)
def test_marcas_legitimas_fuera_del_catalogo_no_se_filtran(texto, confianza):
    assert _textos(productos_aceptados([_bloque(texto, confianza)], NORM)) == [texto]


@pytest.mark.parametrize("texto,confianza", [("Cansbca", 0.154), ("BRcRE", 0.169), ("Sskrvih", 0.212)])
def test_texto_crudo_de_baja_confianza_se_filtra(texto, confianza):
    assert productos_aceptados([_bloque(texto, confianza)], NORM) == []


def test_baja_confianza_con_categoria_del_catalogo_se_conserva():
    # Correctos en dev con confianza < 0.30: el texto cae en una categoria del catalogo
    texto = "8- Shampoo Savilé 7C0 ml"
    assert _textos(productos_aceptados([_bloque(texto, 0.234)], NORM)) == [texto]


def test_baja_confianza_con_canonico_se_conserva():
    aceptados = productos_aceptados([_bloque("Leche", 0.2)], NORM)
    assert len(aceptados) == 1 and aceptados[0]["_resultado"].metodo != "heuristico"


def test_sin_confianza_no_se_filtra():
    bloque = {"texto": "Cansbca", "bbox": {"x": 0, "y": 0, "ancho": 10, "alto": 10}}
    assert _textos(productos_aceptados([bloque], NORM)) == ["Cansbca"]


def test_umbral_es_estricto():
    assert _textos(productos_aceptados([_bloque("Cansbca", CONFIANZA_MINIMA_HEURISTICO)], NORM)) == ["Cansbca"]


def test_idx_cuenta_solo_legibles():
    bloques = [_bloque("Salsa Chamoy", 1.0), _bloque("Cansbca", 0.15), _bloque("Saladette", 0.97)]
    legibles = productos_aceptados(bloques, NORM)
    assert [(p["texto"], p["_idx"]) for p in legibles] == [("Salsa Chamoy", 0), ("Saladette", 1)]
    todos = productos_aceptados(bloques, NORM, incluir_ilegibles=True)
    assert [(p["texto"], p["_idx"], p["_ilegible"]) for p in todos] == [
        ("Salsa Chamoy", 0, False), ("Cansbca", None, True), ("Saladette", 1, False)]


def _pagina(productos, precio):
    return {"productos": productos, "precios": [precio], "precios_anteriores": [], "atributos": []}


PRECIO = {"texto": "$10995", "valor": 10995.0, "confianza": 0.99,
          "bbox": {"x": 500, "y": 1000, "ancho": 150, "alto": 60}}


def test_cercania_salta_el_bloque_ilegible():
    # Chedraui 428354 p013: "Sskrvih" (0.21) quedaba entre el precio y "Moto Electrica"
    nombre = _bloque("Moto Eléctrica", 0.95, y=850)
    basura = _bloque("Sskrvih", 0.212, y=950)
    regs = construir_registros_pagina(_pagina([nombre, basura], PRECIO), None, NORM)
    assert regs["precios"][0]["producto"]["texto"] == "Moto Eléctrica"
    assert _textos(regs["productos"]) == ["Moto Eléctrica"]


def test_roi_que_elige_un_ilegible_pasa_a_cercania():
    nombre = _bloque("Moto Eléctrica", 0.95, y=700)          # fuera de la region
    basura = _bloque("Sskrvih", 0.212, y=950)                # unico candidato dentro de la region
    region = {"x": 400, "y": 900, "ancho": 400, "alto": 300}
    regs = construir_registros_pagina(_pagina([nombre, basura], PRECIO), [region], NORM)
    assert regs["precios"][0]["producto"]["texto"] == "Moto Eléctrica"


@pytest.mark.parametrize("texto,esperado", [
    ("[Chocolate Oscuro", "Chocolate Oscuro"),
    ("Fabuloso)", "Fabuloso"),
    ("Bebida sabor Manzana;", "Bebida Sabor Manzana"),
    ("'Libre de BPA", "Libre de Bpa"),
    ("Figura Naruto=", "Figura Naruto"),
    ("Botana $-Mart", "Botana $-mart"),
    ('Derpy 18"', 'Derpy 18"'),
    ("Sopa instantanea (pollo)", "Sopa Instantanea (pollo)"),
])
def test_nombre_heuristico_sin_puntuacion_en_los_bordes(texto, esperado):
    resultado = NORM.normalizar(texto)
    assert resultado.metodo == "heuristico"
    assert resultado.nombre_canonico == esperado


@pytest.mark.parametrize("texto,esperado", [
    ("Regio Rinde+", "Regio Rinde+"),
    ("Complete +", "Complete +"),
    ("Oialiet 38+", "Oialiet 38+"),
    ("Figura Naruto+;", "Figura Naruto+"),
    ("+ ;", ""),
])
def test_recorte_conserva_el_mas_que_es_parte_del_nombre(texto, esperado):
    assert NORM._recortar_puntuacion(texto) == esperado


def test_precio_sin_legible_cerca_queda_sin_producto():
    basura = _bloque("Sskrvih", 0.212, y=950)
    regs = construir_registros_pagina(_pagina([basura], PRECIO), None, NORM)
    assert regs["precios"][0]["producto"] is None
