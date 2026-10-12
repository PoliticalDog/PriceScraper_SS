"""Precio entero con el "$" leido como 5/8/s (Regla A) confirmado por la casilla: c/u ilegible y antes - ahorro."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=40, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1500})
    return sorted(e.valor for e in res.precios)


# --- c/u ilegible (Walmart 413251 / 413647) ---

def test_cu_ilegible_pegado_es_entero():
    assert _precios([_bloque("5949clu", 100, 100)]) == [949.0]
    assert _precios([_bloque("5479cIu", 100, 100)]) == [479.0]


def test_cu_ilegible_con_espacio_y_dos_digitos():
    assert _precios([_bloque("555 clu", 100, 100)]) == [55.0]
    assert _precios([_bloque("519clu", 100, 100)]) == [19.0]


def test_cu_no_acepta_cuatro_digitos_tras_el_espurio():
    # "52995clu" podria ser $29.95 c/u con el "$" mal leido: no se lee como $2,995
    assert 2995.0 not in _precios([_bloque("52995clu", 100, 100)])


def test_cu_no_lee_centavos_en_superindice_como_entero():
    # Soriana Mercado 425730: "$69⁰⁰ c/u" llega como "6900 clu"; no es $900
    assert 900.0 not in _precios([_bloque("6900 clu", 100, 100)])
    assert 900.0 not in _precios([_bloque("6900clu", 100, 100)])


def test_cu_walmart_sigue_funcionando_con_la_excepcion_00():
    for texto, valor in [("5949clu", 949.0), ("5409clu", 409.0), ("5599clu", 599.0),
                         ("5249clu", 249.0), ("5669clu", 669.0), ("5125 clu", 125.0)]:
        assert _precios([_bloque(texto, 100, 100)]) == [valor], texto


# --- desempate por antes - ahorro (Walmart 413647 pagina_008) ---

def _casilla(precio_txt, antes_txt="Antes $699", ahorro_txt="Ahorra $245"):
    return [
        _bloque("Ahora", 100, 60),
        _bloque(precio_txt, 100, 100, alto=60),
        _bloque(antes_txt, 240, 100),
        _bloque(ahorro_txt, 240, 140),
        _bloque("Mezcal artesanal", 100, 180),
    ]


def test_resta_antes_ahorro_desempata_a_favor_del_entero():
    # Sin el desempate, B-4 lo leia como 54.54 (hay producto cerca)
    assert 454.0 in _precios(_casilla("5454"))
    assert 54.54 not in _precios(_casilla("5454"))


def test_resta_con_tres_digitos():
    assert 23.0 in _precios(_casilla("523", "Antes $36", "Ahorra$13"))


def test_resta_acepta_entero_terminado_en_00_si_cuadra_exacto():
    assert 600.0 in _precios(_casilla("5600", "Antes $900", "Ahorra $300"))


def test_sin_cuadrar_la_resta_sigue_b4():
    # La resta da 454 y el bloque dice 6990: se queda la lectura con centavos (Alsuper/S-Mart)
    assert 69.9 in _precios(_casilla("6990"))


def test_sin_par_antes_ahorro_no_cambia_b4():
    bloques = [_bloque("5699", 100, 100, alto=60), _bloque("Suavizante Downy", 100, 150)]
    assert _precios(bloques) == [56.99]
