"""Catalogo de disenos por tienda (evaluador/catalogo.py)."""
from evaluador.catalogo import alcanzable_cercania, caja, medir_pagina, posicion, resumen
from evaluador.gt import ArticuloGT, PaginaGT
from evaluador.pipeline import PaginaPipeline

PRECIO = caja({"bbox": {"x": 500, "y": 1000, "ancho": 150, "alto": 60}})


def _n(x, y, ancho=200, alto=30):
    return caja({"bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}})


def test_posiciones():
    assert posicion(PRECIO, _n(480, 900)) == "arriba"
    assert posicion(PRECIO, _n(480, 1120)) == "debajo"
    assert posicion(PRECIO, _n(250, 1010)) == "fila_izq"   # Merco: nombre a la izquierda, misma fila
    assert posicion(PRECIO, _n(700, 1010)) == "fila_der"


def test_alcanzable_por_cercania():
    assert alcanzable_cercania(PRECIO, _n(480, 700))          # arriba, cualquier distancia
    assert alcanzable_cercania(PRECIO, _n(480, 1150))         # debajo, dentro de alto + margen
    assert not alcanzable_cercania(PRECIO, _n(480, 1400))     # debajo, fuera del margen
    assert not alcanzable_cercania(PRECIO, _n(1000, 900))     # a mas de 400px en horizontal


def _pagina(precios_nlp, bloques_ocr, articulos):
    gt = PaginaGT("t", "f", "p", list(articulos), [])
    return gt, PaginaPipeline(gt, {"precios": precios_nlp}, {"ancho_pagina": 1000, "bloques": bloques_ocr}, [], [], [])


def _bloque(texto, x, y, valor=None):
    b = {"texto": texto, "bbox": {"x": x, "y": y, "ancho": 150, "alto": 50}}
    if valor is not None:
        b["valor"] = valor
    return b


def test_medir_pagina_estados_y_par_mas_cercano():
    arts = [ArticuloGT("t", "f", "p", 1, "Lechuga romana", None, 18.9, None, None),
            ArticuloGT("t", "f", "p", 2, "Papaya maradol", None, 39.9, None, None),
            ArticuloGT("t", "f", "p", 3, "Sandia", None, 9.9, None, None)]
    precios = [_bloque("$18.90", 500, 500, 18.9), _bloque("$39.90", 500, 900, 39.9)]
    ocr = [_bloque("LECHUGA romana", 500, 400), _bloque("Lechuga Romana", 500, 1500), _bloque("$18.90", 500, 500),
           _bloque("$39.90", 500, 900)]
    gt, pp = _pagina(precios, ocr, arts)
    filas = {f["id"]: f for f in medir_pagina(gt, pp, None)}
    assert filas[1]["estado"] == "completo" and filas[1]["posicion"] == "arriba"   # el mas cercano, no el de y=1500
    assert filas[2]["estado"] == "sin_nombre_ocr"
    assert filas[3]["estado"] == "sin_precio_nlp"

    tiendas = resumen({"articulos": list(filas.values()),
                       "paginas": [{"tienda": "t", "folleto": "f", "pagina": "p", "articulos": 3, "roi": False}]})
    assert tiendas["t"]["localizados"] == 1 and tiendas["t"]["posiciones"]["arriba"] == 1
    assert tiendas["t"]["por_folleto"]["f"] == {"posicion": "arriba", "fraccion": 1.0, "n": 1}
