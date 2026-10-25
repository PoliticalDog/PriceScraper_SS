"""Nombre partido en varias lineas: el registro muestra la pila de lineas contiguas del bloque elegido
(load.nombre_en_pila / construir_registros_pagina). Cajas reales de dev salvo donde se indica."""
from types import SimpleNamespace

import pytest

from load.load import (_inicia_renglon_lista, _tipo_corte_pila, construir_registros_pagina, metodo_nombre,
                       nombre_en_pila)
from nlp.normalizador import Normalizador

NORM = Normalizador()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precio(texto, valor, x, y, ancho, alto):
    return {"texto": texto, "valor": valor, "confianza": 0.9, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _registros(productos, precios):
    pag = {"pagina": "p.webp", "productos": productos, "precios": precios, "precios_anteriores": []}
    return construir_registros_pagina(pag, None, NORM)["precios"]


def test_atributo_al_pie_del_nombre_toma_las_lineas_de_encima():
    # sam's_club 421762 p4: se mostraba "Baja en Calorias 4 Kg" (atributo como nombre, sin la marca Metco)
    productos = [_b("Metco BC", 289, 606, 319, 78), _b("Edulcorantede Mesa", 218, 686, 462, 56),
                 _b("Baja en Calorías 4 kg", 219, 747, 456, 68)]
    reg = _registros(productos, [_precio("$199", 199.0, 299, 795, 293, 132)])[0]
    assert reg["producto"]["texto"] == "Metco BC Edulcorantede Mesa Baja en Calorías 4 kg"
    assert reg["producto"]["_resultado_unido"] is not None
    assert reg["producto"]["bbox"] == {"x": 218, "y": 606, "ancho": 680 - 218, "alto": 815 - 606}


def test_nombre_debajo_del_precio_toma_la_linea_siguiente():
    # chedraui 416057 p7: "Bocina" / "Mod. Charge Essential 2" bajo $2,290 (se mostraba "Bocina Bluetooth")
    productos = [_b("Bocina", 738, 670, 58, 26), _b("Mod. Charge Essential 2", 738, 692, 188, 31)]
    reg = _registros(productos, [_precio("52,290", 2290.0, 728, 558, 160, 72)])[0]
    assert reg["producto"]["texto"] == "Bocina Mod. Charge Essential 2"


def test_vineta_de_caracteristicas_corta_la_pila():
    # chedraui 416057 p15: la vineta "•" se lee "'"; la columna vecina (Lavasecadora) no entra
    productos = [_b("Lavadora", 650, 934, 76, 24), _b("Lavasecadora", 882, 936, 116, 26),
                 _b("Mod. WDABO", 650, 956, 104, 24), _b("Diamond gray", 650, 978, 114, 28),
                 _b("'Pantalla LED", 885, 989, 122, 20), _b("'Tecnologia", 649, 1006, 104, 26),
                 _b("Aqua Saver Green", 654, 1024, 158, 24)]
    nuevo = nombre_en_pila(productos[0], productos, NORM)
    assert nuevo["texto"] == "Lavadora Mod. WDABO Diamond gray"
    assert productos[0]["texto"] == "Lavadora"  # el bloque original no se modifica


def test_renglon_de_lista_numerada_no_se_une():
    # bodega_aurrera 422604 p1: lista numerada de productos distintos, uno por renglon
    productos = [_b("Descripción", 1272, 1198, 185, 41), _b("1-Galletas Marias 4328", 1262, 1242, 229, 36),
                 _b("3-Salchichas con pavo 640g", 1262, 1330, 274, 36),
                 _b("4- Acelte Nutrloll 780 ml", 1261, 1376, 229, 26)]
    for prod in productos[1:]:
        assert nombre_en_pila(prod, productos, NORM) is prod


def test_linea_elegida_por_otro_precio_corta_la_pila():
    # Sintetico (renglones de una lista con el precio a la derecha, como merco): cada precio toma su
    # renglon y las dos lineas son contiguas; sin el corte, los dos registros mostrarian ambos nombres
    productos = [_b("Pierna de cerdo", 100, 100, 150, 24), _b("Pechuga de pollo", 100, 126, 150, 24)]
    regs = _registros(productos, [_precio("$1", 1.0, 300, 98, 80, 30), _precio("$2", 2.0, 300, 128, 80, 30)])
    assert [r["producto"]["texto"] for r in regs] == ["Pierna de cerdo", "Pechuga de pollo"]
    assert nombre_en_pila(productos[0], productos, NORM)["texto"] == "Pierna de cerdo Pechuga de pollo"


def test_linea_compartida_por_dos_pilas_sigue_en_ambas():
    # chedraui 416057 p17 (dev, cajas reales): $6,490 esta mal asociado (toma "Mod Gravita blanco", el nombre
    # de arriba, en vez del suyo debajo) y su pila comparte "queen size" con la de $8,990. Las pilas solo se
    # cortan en el bloque elegido por otro precio, no se reparten las lineas (variante descartada el 25-oct:
    # empeoraba nombres de productos con varios precios); $8,990 conserva "Colchon en caja queen size" (acierto)
    productos = [_b("Colchón en caja", 664, 794, 122, 28), _b("queen size", 664, 818, 84, 26),
                 _b("Mod Gravita blanco", 664, 838, 150, 26)]
    precios = [_precio("$8,990", 8990.0, 658, 656, 162, 72), _precio("$6,490", 6490.0, 658, 926, 158, 72)]
    regs = _registros(productos, precios)
    assert [r["producto"]["texto"] for r in regs] == ["Colchón en caja queen size", "queen size Mod Gravita blanco"]


def test_sin_lineas_contiguas_no_cambia():
    prod = _b("Tomatillo", 748, 1626, 98, 26)
    otros = [prod, _b("Lejano", 748, 1700, 98, 26), _b("Otra columna", 900, 1652, 98, 26)]
    assert nombre_en_pila(prod, otros, NORM) is prod


def test_pila_que_el_normalizador_descarta_no_se_une():
    # Letra chica partida en renglones: unida pasa de 150 caracteres (VARCHAR de productos_canonicos y
    # texto_norm de 300): se queda el bloque elegido
    renglones = [_b("Promocion valida del 19 de agosto al 3 de septiembre de 2026 en tiendas participantes", 100, 100 + 20 * i, 600, 18)
                 for i in range(3)]
    assert nombre_en_pila(renglones[0], renglones, NORM) is renglones[0]


def test_de_oferta_bajo_el_nombre_corta_la_pila():
    # s-mart 430291 p2 (produccion, cajas reales): se mostraba "Detsrgente de Oferta: 81392"
    productos = [_b("Detsrgente", 1292, 1022, 169, 68), _b("De oferta: 81392", 1268, 1108, 197, 29)]
    reg = _registros(productos, [_precio("10999", 109.99, 1476, 1030, 280, 108)])[0]
    assert reg["producto"]["texto"] == "Detsrgente"


def test_vigencia_bajo_el_nombre_corta_la_pila():
    # calimax 135706 p1 (produccion, cajas reales): se mostraba "...Fud / 500 G. del Viernes 24 al Jueves 30 de Julio"
    productos = [_b("Salchichas de Pavo", 992, 2413, 182, 31), _b("Fud / 500 gr.", 991, 2432, 117, 36),
                 _b("Del viernes 24 al jueves 30 de julio de 2026", 615, 2498, 715, 49)]
    reg = _registros(productos, [_precio("90", 90.0, 1305, 2374, 65, 52)])[0]
    assert reg["producto"]["texto"] == "Salchichas de Pavo Fud / 500 gr."


def test_la_linea_elegida_no_se_corta_aunque_sea_promocion():
    # el corte es solo para las lineas que se agregan: si el precio eligio el renglon "De oferta", ese renglon
    # se conserva y la pila sube a su nombre (mejor que mostrar "De oferta" solo)
    prod = _b("De oferta: 81392", 1268, 1108, 197, 29)
    nuevo = nombre_en_pila(prod, [prod, _b("Detsrgente", 1292, 1022, 169, 68)], NORM)
    assert nuevo["texto"] == "Detsrgente De oferta: 81392"


@pytest.mark.parametrize("texto,tipo", [
    ("Todos los Helados Mi marca y Yummy 3.9 L", "promocion"),
    ("TODA LA MARCA TEMPO, ARMO ALL", "promocion"),
    ("Todas las Cerraduras Marca Dexter y Todas las Sandalias de Temporada", "promocion"),
    ("En toda la Farmacia", "promocion"),
    ("30% de descuento", "promocion"),
    ("Hasta 12 MSI", "promocion"),
    ("12 meses sin intereses", "promocion"),
    ("Precio especial", "promocion"),
    ("Llévate 2 y recibe", "promocion"),
    ("3x2 en toda la línea", "promocion"),
    ("2 x 1", "promocion"),
    ("del Viernes 24 al Jueves 30 de Julio de 2026", "vigencia"),
    ("03 al 16 de Agosto", "vigencia"),
    ("Solo Hoy 13 de Octubre", "vigencia"),
    ("03 - 16 ago 2026", "vigencia"),
    ("Vigencia al 30 de septiembre", "vigencia"),
    ("Válido en tiendas participantes", "vigencia"),
    ("Hasta agotar existencias", "vigencia"),
    ("De oferta", "oferta"),
    ("¡En oferta! Ejemplo:", "oferta"),
])
def test_texto_que_corta_la_pila(texto, tipo):
    assert _tipo_corte_pila({"texto": texto}) == tipo


@pytest.mark.parametrize("texto", [
    "Todas las variedades", "Todos los sabores", "Variedad de sabores", "Leche 1 L 2x", "Crema dental 2x75ml",
    "Chocolate amargo 70% cacao", "Yoghurt 0% grasa", "Tallas del 2 al 8", "Ejemplo: Queso Chihuahua Menonita",
    "Baja en Calorías 4 kg", "Mod. Charge Essential 2", "Tazón Contempo 760ml", "Papel Higiénico 4 Rollos",
    "Cerveza 6 x 355 ml", "Pantalla 55\"", "Filete de pechuga de pollo", "Ofertas", "Mesa 4x4",
])
def test_nombres_que_no_cortan_la_pila(texto):
    assert _tipo_corte_pila({"texto": texto}) is None


def test_inicio_de_renglon_de_lista():
    for texto in ("'tecnología Inverter", "~wireless Subwoofer", "•Portátil", "- Karaoke", "2- Limpiador",
                  "8- Shampoo Savilé", "1-Galletas", "3) Arroz", "\"adaptación Sónica"):
        assert _inicia_renglon_lista({"texto": texto}), texto
    for texto in ("Bocina", "Mod. Charge Essential 2", "2 Leche entera", "3.78 lt", "12 rollos", "Baja en Calorías 4 kg",
                  "6 menús automáticos", "Edulcorante de Mesa"):
        assert not _inicia_renglon_lista({"texto": texto}), texto


# -- metodo_norm del PRECIO (KPI "% catalogo", 25-oct-2026) -----------------------------------------------------

def _res(metodo):
    return SimpleNamespace(metodo=metodo)


def test_metodo_nombre_sin_union_es_el_de_la_fila_producto():
    assert metodo_nombre({"_resultado": _res("exacto")}) == "exacto"


def test_metodo_nombre_con_union_es_el_del_nombre_unido():
    # "Pechuga de pollo" (exacto) unida a su pila queda texto del folleto: el PRECIO ya no es de catalogo
    prod = {"_resultado": _res("exacto"), "_resultado_unido": _res("heuristico")}
    assert metodo_nombre(prod) == "heuristico"


def test_metodo_nombre_union_descartada_es_heuristico():
    # nombre_con_unidad devuelve la union aunque el normalizador la descarte: el PRECIO lleva el texto tal cual
    assert metodo_nombre({"_resultado": _res("exacto"), "_resultado_unido": None}) == "heuristico"


def test_metodo_nombre_sin_producto_es_none():
    assert metodo_nombre(None) is None


def test_metodo_nombre_de_registro_real_con_pila():
    productos = [_b("Metco BC", 289, 606, 319, 78), _b("Edulcorantede Mesa", 218, 686, 462, 56),
                 _b("Baja en Calorías 4 kg", 219, 747, 456, 68)]
    prod = _registros(productos, [_precio("$199", 199.0, 299, 795, 293, 132)])[0]["producto"]
    assert metodo_nombre(prod) == prod["_resultado_unido"].metodo
