"""Digitos puros sin "$" con letra del tamano del texto no son precio (ALTO_MIN_PRECIO_SIN_SIMBOLO)."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=30, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1500})
    return sorted(e.valor for e in res.precios)


def _texto_de_pagina():
    # Nombres y descripciones de otras casillas: fijan la mediana del alto del texto (30 px)
    return [_bloque("Leche entera 1 L", 700, 100), _bloque("Detergente en polvo", 700, 300),
            _bloque("Varios sabores", 700, 500)]


# --- numeros del nombre o de un atributo ---

def test_numero_bajo_el_nombre_con_la_misma_letra_no_es_precio():
    # Bodega Aurrera: "Iphone" en una linea y "14" en la siguiente -> no es Iphone a $14
    bloques = _texto_de_pagina() + [_bloque("Iphone", 100, 100), _bloque("14", 100, 135, ancho=30)]
    assert _precios(bloques) == []


def test_iphone_14_con_letra_grande_bajo_el_nombre_no_es_precio():
    # bodega_aurrera 412322 p2 (geometria real): "iPhone" 67 px y "14" 72 px en la pantalla del
    # telefono; el texto de la pagina mide ~40 px, asi que el alto relativo no basta: el "14"
    # continua el nombre (misma columna, justo debajo, letra parecida)
    texto = [_bloque("Colores disponibles", 1420, 860, ancho=250, alto=40),
             _bloque("12Mpx", 1499, 654, ancho=119, alto=44), _bloque("6 GBRAM", 1472, 739, ancho=171, alto=41),
             _bloque("1B GBROM", 1459, 784, ancho=196, alto=39), _bloque("1Mpxfrental", 1462, 697, ancho=193, alto=41)]
    bloques = texto + [_bloque("iPhone", 1145, 560, ancho=197, alto=67), _bloque("14", 1194, 664, ancho=102, alto=72)]
    assert 14.0 not in _precios(bloques)


def test_b2_grande_a_la_derecha_del_nombre_chico_sigue_siendo_precio():
    # El nombre a la izquierda en la misma linea pero con letra mucho menor: es la casilla, no el nombre
    bloques = _texto_de_pagina() + [_bloque("Queso Oaxaca", 100, 120), _bloque("69", 230, 105, ancho=60, alto=60)]
    assert _precios(bloques) == [69.0]


def test_peso_de_caja_leido_como_cuatro_digitos_no_es_precio():
    # bodega_aurrera 417118 p1: etiquetas "560 g" / "580 g" de las cajas de cereal -> "5609", "5809"
    bloques = _texto_de_pagina() + [_bloque("QUAKER", 100, 100), _bloque("5609", 100, 140, ancho=60),
                                    _bloque("5809", 300, 140, ancho=60)]
    assert _precios(bloques) == []


def test_porcentaje_o_modelo_pequeno_no_es_precio():
    bloques = _texto_de_pagina() + [_bloque("Smart TV", 100, 100), _bloque("32", 230, 100, ancho=30),
                                    _bloque("Pantalla Led", 100, 300), _bloque("55", 230, 300, ancho=30)]
    assert _precios(bloques) == []


# --- precios bare reales de grid: el numero grande sigue siendo precio ---

def test_b2_entero_grande_junto_al_nombre_sigue_siendo_precio():
    # tiendas_3b / bodega_aurrera: "Salsa BBQ" + "30" (precio entero, ~1.8x el texto)
    bloques = _texto_de_pagina() + [_bloque("Salsa BBQ", 100, 100), _bloque("30", 100, 140, ancho=60, alto=55)]
    assert _precios(bloques) == [30.0]


def test_b4_con_centavos_grande_sigue_siendo_precio():
    # alsuper / s-mart: "3999" -> $39.99 junto a "Aguacate"
    bloques = _texto_de_pagina() + [_bloque("Aguacate", 100, 100), _bloque("3999", 100, 140, alto=70)]
    assert _precios(bloques) == [39.99]


def test_b5_carton_grande_sigue_siendo_precio():
    # casa_ley: "39788" -> $397.88 bajo el nombre del carton
    bloques = _texto_de_pagina() + [_bloque("Detergente En Polvo Ariel Carton", 100, 100, ancho=300),
                                    _bloque("39788", 100, 140, alto=80)]
    assert _precios(bloques) == [397.88]


def test_umbral_relativo_a_la_mediana_de_la_pagina():
    # Justo por encima de 1.3x la mediana (30 px) se acepta; justo por debajo no. El numero va
    # separado del nombre (no lo continua) para medir solo el umbral de alto.
    base = _texto_de_pagina() + [_bloque("Salsa BBQ", 100, 100)]
    assert _precios(base + [_bloque("30", 300, 100, ancho=40, alto=40)]) == [30.0]
    assert _precios(base + [_bloque("30", 300, 100, ancho=40, alto=38)]) == []


def test_precio_con_simbolo_no_depende_del_alto():
    bloques = _texto_de_pagina() + [_bloque("Iphone", 100, 100), _bloque("$14", 100, 135, ancho=40)]
    assert _precios(bloques) == [14.0]


# --- rotulos de precio de casilla (QA 24-oct-2026, OCR de produccion) ---

def _pagina_1800(bloques):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1800})
    return sorted(e.valor for e in res.precios)


def test_rotulo_precio_bodega_encima_no_es_nombre():
    # bodega_aurrera 417943 p2 (geometria real): "PREçIQ" 115 px y "DEGA" encima del "62" (165 px)
    bloques = [_bloque("Arizona", 1250, 1100, ancho=300, alto=60), _bloque("Te verde 680 ml", 1250, 1170, ancho=300, alto=45),
               _bloque("PREçIQ", 1175, 585, ancho=333, alto=115), _bloque("DEGA", 1306, 650, ancho=223, alto=91),
               _bloque("62", 1216, 765, ancho=230, alto=165)]
    assert _pagina_1800(bloques) == [62.0]


def test_rotulo_deformado_prefio_y_texto_de_empaque_desplazado():
    # 417943 p3: "PREFIO" encima del "52" y "ATE" (empaque, 190 px) arriba a la izquierda
    bloques = [_bloque("Paketaxo", 1240, 1280, ancho=300, alto=60), _bloque("Variedad de botanas", 1200, 1350, ancho=400, alto=45),
               _bloque("ATE", 1015, 475, ancho=273, alto=190), _bloque("PREFIO", 1175, 585, ancho=335, alto=115),
               _bloque("52", 1219, 765, ancho=227, alto=165)]
    assert _pagina_1800(bloques) == [52.0]


def test_portada_con_titulares_precio_bajo_rotulo_se_conserva():
    # bodega_aurrera 417679 p4: titulares de 100-200 px suben la mediana a ~64 px; el "12" mide 68
    titulares = [_bloque("Lo que necesita", 947, 182, ancho=731, alto=102), _bloque("tu despensa", 1009, 268, ancho=572, alto=108),
                 _bloque("al precio más bajo,", 893, 346, ancho=845, alto=116), _bloque("siempre", 984, 419, ancho=659, alto=198),
                 _bloque("Más Bajos", 76, 220, ancho=357, alto=104), _bloque("Aurrera", 755, 1429, ancho=189, alto=87),
                 _bloque("Precios", 134, 140, ancho=242, alto=78), _bloque("siempre", 157, 323, ancho=183, alto=65),
                 _bloque("AGUACATE HASS", 618, 774, ancho=129, alto=57), _bloque("MALLA", 661, 793, ancho=76, alto=41)]
    casilla = [_bloque("PREçQ", 534, 415, ancho=173, alto=65), _bloque("DE@A", 589, 452, ancho=116, alto=53),
               _bloque("12", 573, 503, ancho=96, alto=68), _bloque("kilo", 604, 566, ancho=48, alto=26)]
    assert 12.0 in _pagina_1800(titulares + casilla)


def test_titular_ancho_encima_no_es_continuacion_del_nombre():
    # soriana_hiper 415920 p1: "¡ELIGE!" (84 px, empieza 213 px a la izquierda) sobre el "75" de 78 px
    bloques = _texto_de_pagina() + [_bloque("¡ELIGE!", 755, 795, ancho=298, alto=84), _bloque("75", 968, 890, ancho=126, alto=78),
                                    _bloque("Pantalla Led", 968, 990, ancho=200, alto=30)]
    assert 75.0 in _pagina_1800(bloques)


def test_centavos_bajo_rotulo_mas_alto_siguen_fuera():
    # merco 423338 p6: "99" (centavos, chico frente al texto) bajo "[PRECIAZO" mas alto no se rescata
    bloques = _texto_de_pagina() + [_bloque("[PRECIAZO", 383, 1130, alto=60), _bloque("99", 383, 1183, ancho=56, alto=36),
                                    _bloque("LAVATRASTES", 383, 1250, alto=30)]
    assert 99.0 not in _precios(bloques)


def test_centavos_bajo_rotulo_con_letra_grande_siguen_fuera():
    # merco 432380 p5 (geometria real, 1350 px): "f14" + "99" (52 px) bajo "PRECIAZO" (74 px) = $14.99;
    # el "99" no pasa a ser un precio de $99 aunque mida mas que el texto de la pagina
    texto = [_bloque("Leche entera 1 L", 300, 300, alto=30), _bloque("Detergente", 300, 500, alto=30),
             _bloque("Varios sabores", 300, 700, alto=30), _bloque("caca", 1085, 1265, ancho=64, alto=16)]
    bloques = texto + [_bloque("PRECIAZO", 1069, 1311, ancho=247, alto=74), _bloque("99", 1078, 1448, ancho=74, alto=52),
                       _bloque("clu", 1090, 1526, ancho=52, alto=32), _bloque("Chocolate en polvo", 1060, 1580, ancho=250)]
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1350})
    assert 99.0 not in [e.valor for e in res.precios]


def test_patron_rotulo_precio():
    for t in ("PREçIQ", "PREçQ", "PREçO", "PREFIO", "DEGA", "DE@A", "BODEGA", "PRECIAZO", "[PRECIAZO]",
              "PPRECIAZO", "PRECIAZQ]", "PRECIAZ0", "PRECINZO", "PEECIAZa", "PREGIAZ0", "PPECIZo", "SÚPER",
              "Precíssimo", "Precio Bodega"):
        assert EX.PATRON_ROTULO_PRECIO.match(t), t
    for t in ("iPhone", "Super Value", "Precios", "Presentación", "Precocida", "Bodega Aurrera", "Pepino"):
        assert not EX.PATRON_ROTULO_PRECIO.match(t), t


def test_sin_bloques_con_letras_no_se_aplica():
    # Sin texto en la pagina no hay referencia de alto: siguen las reglas de siempre
    assert EX._alto_como_texto({"alto": 10}, [_bloque("1234", 0, 0)]) is False
