"""Campañas del folleto (nivel A de promociones, 15-oct-2026): slug canonico (nlp.regex_extractor.
slug_evento), lemas y letra chica a DESCARTE, y load inserta solo campañas con la vigencia del folleto.
Textos reales del OCR de produccion (sin holdout)."""
import pytest

from load.load import Loader
from nlp.normalizador import Normalizador
from nlp.regex_extractor import RegexExtractor, slug_evento

EX = RegexExtractor()
BBOX = {"x": 100, "y": 100, "ancho": 200, "alto": 30}

CAMPANAS = [
    ("JULIO REGALADO", "julio_regalado"), ("JULIOREGALADOE", "julio_regalado"),
    ("Julioregaladods", "julio_regalado"), ("JULIO REGALADL", "julio_regalado"),
    ("Este Hot Sale obtén con", "hot_sale"), ("hotsale com mx", "hot_sale"), ("hotsale-commx", "hot_sale"),
    ("El Buen Fin", "buen_fin"),
    ("El regreso a clases empieza con el", "regreso_a_clases"), ("para el regreso a clases", "regreso_a_clases"),
    ("Back to School", "regreso_a_clases"), ("enBack To School", "regreso_a_clases"),
    ("72ANIVERSARIO]", "aniversario"), ("EESTADE/72ANIVERSARIO", "aniversario"), ("TANIVERSARIO]", "aniversario"),
    ("ofertones", "ofertones"), ("Portiofertones", "ofertones"), ("oFERTONONON]", "ofertones"),
    ("LIQUIDACION DERoPA", "liquidacion"), ("Liquidación", "liquidacion"),
    ("en Navidad", "navidad"), ("Halloween", "halloween_dia_de_muertos"),
    ("en Día de muertos", "halloween_dia_de_muertos"),
    ("fiestas patrias", "fiestas_patrias"), ("PARA LAS FIESTAS PATRIAS", "fiestas_patrias"),
]

NO_CAMPANAS = [
    # letra chica y bancos
    "(excepto códigos de liquidación)", "Corsulta términos y condiciones en wwwbanamex comhotsale",
    "en https /wwwsantancercom mx hot-salelindex html", "Julio Regalado $29.90",
    # lemas de tienda
    "nuestros Precios Bajos Todos los Días, nos reservamos el derecho de limitar la compra",
    "La supercampeona de los precios bajos", "de los Precios Bajos", "PRECIO ESPECIAL",
    # nombres de producto con la campaña como adjetivo
    "BAÑO NAVIDAD", "Vela aromática Navidad Santa", "Figura Navidad c/ml", "CORONA NAVIDEÑA",
    "Plato desechable Halloween;", "Halloween; Varios Modelos", "Día de Muertos 500 mI.",
    "Back to School 100 hojas", "Halloween; 12 cm",
    "patrias 3 pzas", "Mod. patrio", "Bufanda Viva México", "Fiestas patrias banderín 3 pzas",
]


@pytest.mark.parametrize("texto,slug", CAMPANAS)
def test_campania_da_su_slug_canonico(texto, slug):
    assert slug_evento(texto) == slug


@pytest.mark.parametrize("texto", NO_CAMPANAS)
def test_no_campania_no_da_slug(texto):
    assert slug_evento(texto) is None


@pytest.mark.parametrize("texto", ["72ANIVERSARIO]", "hotsale-commx", "ofertones", "JULIOREGALADOE"])
def test_campania_se_clasifica_como_evento_antes_del_descarte(texto):
    assert EX._clasificar(texto, texto, 0.9, BBOX).tipo == "EVENTO_PROMO"


@pytest.mark.parametrize("texto", [
    "nuestros Precios Bajos Todos los Días; nos reservamos el derecho de limitar la compra de grandes cantidades.",
    "Lnsupercampeona delos precios bujos", "(excepto códigos de liquidación)", "{excepto cádigos de liquidación)",
    "SuPeR OFERTA", "precio especial de",
])
def test_lemas_y_letra_chica_son_descarte(texto):
    assert EX._clasificar(texto, texto, 0.9, BBOX).tipo == "DESCARTE"


def test_nombre_de_producto_con_navidad_no_es_evento():
    assert EX._clasificar("Vela aromática Navidad Santa", "Vela aromática Navidad Santa", 0.9, BBOX).tipo == "PRODUCTO"


class _CursorFalso:
    def __init__(self):
        self.sentencias, self._n = [], 1

    def execute(self, sql, params=None):
        self.sentencias.append((" ".join(sql.split()), params))

    def fetchone(self):
        self._n += 1
        return {"id": self._n}

    def eventos(self):
        return [(s, p) for s, p in self.sentencias if s.startswith("INSERT INTO eventos_promo")]

    def filas_evento(self):
        return [p for s, p in self.sentencias if s.startswith("INSERT INTO extracciones") and p[3] == "EVENTO_PROMO"]


def _procesar(eventos):
    loader = Loader.__new__(Loader)  # sin conexion
    loader._normalizador = Normalizador()
    cur = _CursorFalso()
    pag = {"pagina": "pagina_001.webp", "productos": [], "precios": [], "precios_anteriores": [], "promos": [],
           "atributos": [], "eventos_promo": [{"texto": t, "confianza": 0.9, "bbox": BBOX} for t in eventos]}
    loader._procesar_pagina(cur, tienda_id=7, folleto_id=42, pag_data=pag)
    return cur


def test_load_inserta_solo_campanias_con_slug_y_vigencia_del_folleto():
    # JSON de disco anterior al cambio: el lema de HEB venia como evento
    cur = _procesar(["JULIOREGALADOE", "nuestros Precios Bajos Todos los Días, nos reservamos el derecho"])
    [(sql, params)] = cur.eventos()
    assert params[:3] == (42, 7, "julio_regalado")
    assert "SELECT" in sql and "f.fecha_inicio, f.fecha_fin" in sql and params[4] == 42
    assert [p[5] for p in cur.filas_evento()] == ["julio_regalado"]
