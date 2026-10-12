"""Asociacion precio -> producto por cercania (load.asociar_por_cercania)."""
from load.load import MARGEN_DEBAJO_PRECIO, asociar_por_cercania


def _bloque(texto, x, y, ancho=100, alto=30):
    return {"texto": texto, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


PRECIO = _bloque("$199", 500, 1000, alto=60)


def test_sin_admitir_debajo_conserva_solo_arriba():
    lejos_arriba = _bloque("ruido", 500, 700)
    debajo = _bloque("Audifonos Vibe Beam 2", 505, 1068)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, debajo]) is lejos_arriba


def test_nombre_justo_debajo_gana_a_bloque_lejano_arriba():
    # Chedraui/Walmart: el nombre va debajo del precio y lo mas cercano arriba es otro articulo
    lejos_arriba = _bloque("Ioow", 500, 700)
    debajo = _bloque("Audifonos Vibe Beam 2", 505, 1068)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, debajo], admitir_debajo=True) is debajo


def test_nombre_a_la_misma_altura():
    # Alsuper: el nombre a la izquierda del precio, misma fila
    lejos_arriba = _bloque("RGYADA", 500, 740)
    lado = _bloque("DURAZNO", 382, 994)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, lado], admitir_debajo=True) is lado


def test_debajo_fuera_del_margen_no_cuenta():
    debajo_lejos = _bloque("siguiente articulo", 500, 1000 + 60 + MARGEN_DEBAJO_PRECIO + 1)
    assert asociar_por_cercania(PRECIO, [debajo_lejos], admitir_debajo=True) is None


def test_arriba_mas_cercano_que_debajo_sigue_ganando():
    arriba = _bloque("Crema acida", 500, 950)
    debajo = _bloque("200 g", 500, 1080)
    assert asociar_por_cercania(PRECIO, [debajo, arriba], admitir_debajo=True) is arriba


def test_empate_prefiere_arriba():
    arriba = _bloque("arriba", 500, 950)
    debajo = _bloque("debajo", 500, 1050)
    assert asociar_por_cercania(PRECIO, [debajo, arriba], admitir_debajo=True) is arriba


def test_atributos_conservan_distancia_solo_vertical():
    # Sin admitir_debajo el criterio no cambia: el mas cercano arriba por dy, sin mirar dx
    lado = _bloque("lejos al lado", 850, 980)
    encima = _bloque("encima", 500, 900)
    assert asociar_por_cercania(PRECIO, [encima, lado]) is lado


def test_tolerancia_horizontal_se_mantiene():
    debajo_otra_columna = _bloque("otro", 950, 1020)
    assert asociar_por_cercania(PRECIO, [debajo_otra_columna], admitir_debajo=True) is None
