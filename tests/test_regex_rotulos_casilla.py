"""Rotulos de casilla de precio ("Precio bajo todos los dias", "Apartalo con", "a solo:") no son PRODUCTO."""
import pytest

from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=40, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1500})


@pytest.mark.parametrize("texto", [
    "todos los días", "todoslos días", "todoslosdías", "Precio bajo todos los días",
    "Apártalo con", "Apártalo con |", "Apartalo cou",
    "a sólo:", "asólo:", "asolo:", "ASOLO:", "SOLO:", "sólo:", "0 sólo:", "Sólo",
    "De oferta:", "De oferta?", "De ofertar", "Da oferter", "De ofcrta:", "Preciobajo", "AHORRA", "AHORRA MÁS", "Ahorras", "Ahara",
    "COMPRA", "cada una", "Llevate", "DEMo", "Aurrera", "Aurrerao", "Aurrera_", "Aurrera@",
])
def test_rotulo_solo_no_es_producto(texto):
    res = _pagina([_bloque(texto, 100, 100), _bloque("$949", 100, 160)])
    assert [p.texto_raw for p in res.productos] == []


def test_rotulo_no_toca_precio_del_mismo_bloque():
    # Con monto en el bloque, la regla de precio sigue mandando (anclado, sin digitos)
    res = _pagina([_bloque("A sólo $149.00", 100, 100), _bloque("Detergente líquido", 100, 40)])
    assert [e.valor for e in res.precios] == [149.0]
    res = _pagina([_bloque("Ahorra $245", 100, 100)])
    assert [e.valor for e in res.ahorros] == [245.0]


def test_nombre_con_palabra_del_rotulo_sigue_siendo_producto():
    res = _pagina([_bloque("Leche Aurrera entera 1 L", 100, 100), _bloque("Pan para todos", 100, 300),
                   _bloque("$24.90", 100, 160)])
    assert sorted(p.texto_raw for p in res.productos) == ["Leche Aurrera entera 1 L", "Pan para todos"]


def test_rotulo_no_bloquea_precio_sin_simbolo_con_producto_cerca():
    # Regla B-4 usa los bloques crudos: "a solo:" sigue contando como contexto fuerte
    res = _pagina([_bloque("a sólo:", 100, 60), _bloque("4990", 100, 100), _bloque("Jabón de tocador", 100, 160)])
    assert [e.valor for e in res.precios] == [49.9]
    assert [p.texto_raw for p in res.productos] == ["Jabón de tocador"]
