"""Detalle por caso y comparacion caso por caso entre corridas (evaluador/casos.py)."""
from evaluador.casos import OK, comparar_casos, detalle
from evaluador.comparar import comparar_pagina
from evaluador.gt import ArticuloGT, PaginaGT
from evaluador.pipeline import PaginaPipeline, Registro


def reg(producto, precio, x):
    return Registro("t/f/p", x, precio, f"${precio}", {"x": x, "y": 100}, producto, producto, None, None, None)


def art(producto, precio, id_):
    return ArticuloGT("t", "f", "p", id_, producto, None, precio, None, None)


def pagina(registros, articulos):
    gt = PaginaGT("t", "f", "p", list(articulos), [])
    return PaginaPipeline(gt, {"precios": []}, {"bloques": []}, list(registros), [], [])


ARTS = [art("Leche Lala entera 1L", 25.0, 1), art("Jugo Jumex mango 1L", 30.0, 2), art("Cebolla blanca", 15.9, 3)]


def _detalle(registros):
    return detalle([comparar_pagina(pagina(registros, ARTS))])


def test_detalle_da_estado_a_cada_articulo_y_registro():
    d = _detalle([reg("Leche Lala 1L", 25.0, 10), reg("Cerveza", 30.0, 20)])
    assert d["articulos"]["t/f/p#1"]["estado"] == OK
    assert d["articulos"]["t/f/p#2"]["estado"] == "asociacion_producto"
    assert d["articulos"]["t/f/p#3"]["estado"] not in (OK, None)  # perdido, con su codigo de diagnostico
    assert d["registros"]["t/f/p|25.0|10,100"]["estado"] == OK
    assert d["registros"]["t/f/p|30.0|20,100"]["articulo"] == "t/f/p#2"


def test_comparar_casos_separa_ganados_de_perdidos():
    # El neto es 0 (un acierto ganado, uno perdido), pero los dos cambios quedan a la vista
    base = _detalle([reg("Leche Lala 1L", 25.0, 10), reg("Cerveza", 30.0, 20)])
    nueva = _detalle([reg("Vino tinto", 25.0, 10), reg("Jugo Jumex", 30.0, 20)])
    comp = comparar_casos(base, nueva)
    t = comp["por_tienda"]["t"]
    assert t["articulos_ganados"] == 1 and t["articulos_perdidos"] == 1
    assert t["registros_ganados"] == 1 and t["registros_perdidos"] == 1
    perdido = next(c for c in comp["articulos"] if c["antes"] == OK)
    assert perdido["clave"] == "t/f/p#1" and perdido["despues"] == "asociacion_producto"
    assert ("ok -> asociacion_producto", 1) in comp["transiciones_articulo"]


def test_registro_nuevo_con_error_se_cuenta_aparte():
    base = _detalle([reg("Leche Lala 1L", 25.0, 10)])
    nueva = _detalle([reg("Leche Lala 1L", 25.0, 10), reg("Pijama", 15.9, 30)])
    t = comparar_casos(base, nueva)["por_tienda"]["t"]
    assert t.get("registros_nuevos_mal") == 1 and "registros_perdidos" not in t


def test_corridas_iguales_sin_cambios():
    d = _detalle([reg("Leche Lala 1L", 25.0, 10)])
    comp = comparar_casos(d, d)
    assert comp["por_tienda"] == {} and comp["articulos"] == [] and comp["registros"] == []
