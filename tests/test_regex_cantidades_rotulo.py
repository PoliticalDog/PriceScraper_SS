"""Puntos de lealtad, plazos de meses sin intereses, mensualidades y bonificaciones "por cada $N"
no son precios de producto (12-oct-2026). Geometrias tomadas del OCR real (ancho 1800 salvo nota)."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques, ancho=1800):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho})


def _valores(res):
    return sorted(e.valor for e in res.precios)


# -- Soriana Hiper 416269 p3: "$8.80 KILO / CON 50 PUNTOS" ---------------------------------
def _casilla_kilo(rotulo="PUNTOS", cantidad="50"):
    return [
        _b("ZANAHORIA", 1060, 1030, 190, 40),
        _b("8880", 1366, 926, 263, 136),            # precio por kilo (B-4 -> 88.80)
        _b("KILO", 1521, 1010, 102, 48),
        _b("CON", 1316, 1084, 62, 30),
        _b(cantidad, 1379, 1063, 88, 66),
        _b(rotulo, 1468, 1084, 106, 30),
    ]


@pytest.mark.parametrize("rotulo", ["PUNTOS", "PUnTOs", "Puhtos", "Puntos", "[punTOS", "punlos"])
def test_puntos_a_la_izquierda_del_rotulo_no_son_precio(rotulo):
    res = _pagina(_casilla_kilo(rotulo))
    assert 50.0 not in _valores(res)
    assert "50" in [e.texto_raw for e in res.descartes]


def test_precio_por_kilo_encima_de_con_50_puntos_se_conserva():
    # El precio queda arriba de "PUNTOS" a 22 px pero mide 4.5x el rotulo
    res = _pagina(_casilla_kilo())
    assert _valores(res) == [88.8]


# -- Soriana Hiper 422326 p8/p14: insignia "Te regala N puntos / 18 Meses sin intereses / $X" --
def _insignia(puntos="436", plazo="18", mensualidad="819389", meses="Mcscs sin", intereses="intcrcscs"):
    return [
        _b("Teregol", 667, 588, 67, 20),
        _b(puntos, 665, 605, 72, 36),
        _b("punlos", 675, 637, 50, 16),
        _b(plazo, 664, 674, 70, 52),
        _b(meses, 650, 716, 100, 24),
        _b(intereses, 653, 737, 92, 20),
        _b(mensualidad, 647, 765, 106, 36),
        _b("Laptop VIOS VNB1 N4000", 90, 640, 400, 40),
        _b("$3,490", 90, 820, 330, 90),
    ]


def test_insignia_soriana_solo_queda_el_precio():
    res = _pagina(_insignia())
    assert _valores(res) == [3490.0]


@pytest.mark.parametrize("puntos", ["1623", "1,873", "50", "86"])
def test_puntos_encima_del_rotulo_no_son_precio(puntos):
    res = _pagina(_insignia(puntos=puntos))
    assert _valores(res) == [3490.0]


@pytest.mark.parametrize("mensualidad", ["833317", "$49944", "s55500", "*1,05500", "822167"])
def test_mensualidad_debajo_de_intereses_no_es_precio(mensualidad):
    res = _pagina(_insignia(mensualidad=mensualidad))
    assert _valores(res) == [3490.0]


@pytest.mark.parametrize("meses,intereses", [("Meses sin", "intereses"), ("HESES SIH", "Interescs"),
                                             ("Mcscssin", "intcrcsc>"), ("Meses sln", "INTERESES")])
def test_variantes_ocr_de_meses_sin_intereses(meses, intereses):
    res = _pagina(_insignia(meses=meses, intereses=intereses))
    assert _valores(res) == [3490.0]


# -- Chedraui 416057 p7 (ancho 1200): "12" grande a la izquierda de "meses sin / intereses" ----
@pytest.mark.parametrize("plazo", ["12", "18", "24"])
def test_plazo_grande_a_la_izquierda_no_es_precio(plazo):
    res = _pagina([
        _b(plazo, 61, 923, 114, 90),
        _b("meses sin", 172, 929, 191, 44),
        _b("intereses", 166, 962, 198, 55),
        _b("En Electrónica, Línea Blanca y Muebles", 61, 1030, 400, 30),
    ], ancho=1200)
    assert _valores(res) == []


def test_costco_plazo_junto_a_meses():
    res = _pagina([
        _b("12", 579, 167, 106, 86),
        _b("Meses", 688, 170, 81, 33),
        _b("compra mínima", 688, 222, 140, 28),
    ], ancho=1350)
    assert _valores(res) == []


# -- Precios reales que NO cambian ---------------------------------------------------------
def test_precio_real_encima_de_meses_sin_intereses_se_conserva():
    # Walmart/Chedraui: el precio de la casilla y abajo la leyenda; no es un plazo
    res = _pagina([
        _b("Pantalla Smart TV 50", 61, 800, 300, 30),
        _b("$5,999", 61, 840, 200, 70),
        _b("Meses sin intereses", 61, 915, 200, 28),
    ], ancho=1200)
    assert _valores(res) == [5999.0]


def test_precio_bare_que_no_es_plazo_encima_de_meses_se_conserva():
    res = _pagina([
        _b("Licuadora Oster", 61, 800, 300, 30),
        _b("6990", 61, 840, 120, 60),          # B-4 -> 69.90, no es un plazo
        _b("Meses sin", 61, 902, 150, 28),
    ], ancho=1200)
    assert _valores(res) == [69.9]


def test_precio_debajo_de_meses_sin_intereses_sin_plazo_se_conserva():
    # Sin un plazo suelto cerca no hay mensualidad que confirmar: "$949" bajo la leyenda sigue
    res = _pagina([
        _b("Meses sin intereses", 100, 100, 200, 30),
        _b("$949", 100, 140, 120, 40),
        _b("Horno de microondas", 240, 140, 200, 30),
    ])
    assert _valores(res) == [949.0]


def test_insignia_sin_plazo_legible_conserva_el_monto():
    # Mismo caso con la insignia de Soriana si el OCR no leyo el "18": la mensualidad no se toca
    bloques = [b for b in _insignia() if b["texto"] != "18"]
    assert 193.89 in _valores(_pagina(bloques))


def test_precio_con_simbolo_encima_de_puntos_se_conserva():
    # Los puntos nunca traen "$": "$199" encima de "puntos" no se toca
    res = _pagina([
        _b("Sartén 20 cm", 40, 780, 120, 24),
        _b("$199", 200, 770, 100, 40),
        _b("puntos", 210, 812, 70, 18),
    ])
    assert _valores(res) == [199.0]


def test_solo_el_bloque_mas_pegado_al_rotulo():
    # Soriana 412336 p38 "A SOLO $549 / con 50 / puntos": el precio queda arriba de "puntos" a
    # 22 px, pero el "50" esta en medio (-3 px); solo el 50 es la cantidad de puntos
    res = _pagina([
        _b("Cacerola 2.8L", 300, 1060, 150, 24),
        _b("6549", 481, 1043, 82, 38),
        _b("Coh", 470, 1080, 36, 18),
        _b("50", 508, 1076, 44, 30),
        _b("PuLos", 495, 1103, 54, 18),
    ])
    assert _valores(res) == [65.49]


def test_50_que_si_es_precio_sin_rotulo_no_cambia():
    res = _pagina([
        _b("Refresco Cola 2 L", 37, 249, 140, 20),
        _b("$50", 37 + 140 + 9, 246, 56, 30),
    ])
    assert _valores(res) == [50.0]


def test_18_lejos_del_rotulo_no_cambia():
    # "18" con producto cerca pero el rotulo a 200 px: no estan pegados
    res = _pagina([
        _b("Galletas Marias", 600, 600, 200, 30),
        _b("18", 600, 640, 60, 50),
        _b("Meses sin", 600, 890, 100, 24),
    ])
    assert _valores(res) == [18.0]


# -- Bonificacion "por cada $N" (la_comer, HEB) --------------------------------------------
@pytest.mark.parametrize("texto", [
    "s25 por cada $100", "510 porcada $50", "s10 por cada $50", "525por cada $100",
    "5250por cada $1,000", "$40 Por cAda", "8250 Por CADA", "Por cada $1OO de compra",
    "Por cada S1OO de compra", "s30 por cada $i00", "530 poR cADA $100",
])
def test_bonificacion_por_cada_es_promo(texto):
    res = _pagina([_b("$29.90", 100, 100, 150, 60), _b(texto, 100, 600, 250, 40)])
    assert _valores(res) == [29.9]
    assert texto in [e.texto_raw for e in res.promos]


@pytest.mark.parametrize("texto,valor", [("$15 cada uno", 15.0), ("$15 por cada uno", 15.0),
                                         ("$99.90 c/u", 99.9)])
def test_precio_cada_uno_sigue_siendo_precio(texto, valor):
    res = _pagina([_b(texto, 100, 100, 200, 50)])
    assert _valores(res) == [valor]


# -- Casos limite fijados por QA (12-oct-2026) ---------------------------------------------
def test_precio_sin_signo_justo_encima_del_umbral_de_alto_se_conserva():
    # Sin bloque de cantidad: el mas pegado arriba de "PUNTOS" es el precio por kilo, que mide 2.67x el
    # rotulo (> ALTO_MAX_ANTICIPO_VS_ROTULO = 2.5): no se toma como cantidad de puntos.
    res = _pagina([
        _b("ZANAHORIA", 1060, 1030, 190, 40),
        _b("8880", 1366, 1000, 263, 80),
        _b("KILO", 1521, 1010, 102, 48),
        _b("CON", 1316, 1084, 62, 30),
        _b("PUNTOS", 1468, 1084, 106, 30),
    ])
    assert _valores(res) == [88.8]


def test_monto_por_cada_pieza_queda_como_promo():
    # Comportamiento conocido del patron "N por cada": "$25 por cada pieza" se clasifica como PROMO, no como
    # precio (solo "cada uno/a" queda fuera). No aparece en el corpus actual; si aparece y es un precio, revisar.
    res = _pagina([_b("Manzana Gala", 100, 100, 200, 40), _b("$25 por cada pieza", 100, 150, 260, 40)])
    assert _valores(res) == []
    assert [p.texto_raw for p in res.promos] == ["$25 por cada pieza"]
