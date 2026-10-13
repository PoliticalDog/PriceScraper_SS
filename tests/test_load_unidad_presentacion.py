"""Unidad de presentacion suelta ("Carton", "Pieza", "GRAMOS"...) como ultima linea del nombre:
load.es_unidad_suelta / nombre_con_unidad / construir_registros_pagina."""
import pytest

from load.load import construir_registros_pagina, es_unidad_suelta, nombre_con_unidad
from nlp.normalizador import Normalizador

NORM = Normalizador()


def _b(texto, x, y, ancho=50, alto=14, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


# Textos reales del OCR de produccion/dev (casa_ley, alsuper, s-mart, merco, soriana)
UNIDADES = [
    "Carton", "carton", "Cartón", "Carron", "Crton", "Cron", "Garton", "Canton", "Caron", "canón",
    "Pieza", "Piezas", "PIEZA", "piezas.", "25 Piezas", "Pza", "3 Pzas", "Pzas.",
    "Paquete", "Paquetes", "Paq.", "Gramos", "GRAMOS", "GraMOS", "00 GRAMOS", "Gramo",
    "Producto", "Productos", "productos", "Rollos", "ROlLOS", "rollos", "Rollo",
    "Variedad de", "VARIEDAD De", "Variedad Df", "Variedades",
]

# Nombres reales que contienen la palabra (o se le parecen) y NO son solo la unidad
NO_UNIDADES = [
    "Paquete escolar", "Producto Bimbo", "Canon", "Con", "Cartera", "Pizza", "Piezas de pollo",
    "Carton de huevo", "Rollo de canela", "Variedad de bebidas Tampico", "Gramolina", "Contenido",
    "Galletas Gamesa", "Papel Higienico 4 Rollos", "Elote Dorado Del Monte Carton", "Caronte",
    "Productos de limpieza", "Rollos Primavera",
]


@pytest.mark.parametrize("texto", UNIDADES)
def test_unidad_suelta_se_reconoce(texto):
    assert es_unidad_suelta(texto)


@pytest.mark.parametrize("texto", NO_UNIDADES)
def test_nombres_reales_no_son_unidad_suelta(texto):
    assert not es_unidad_suelta(texto)


def _casilla_jabon():
    # casa_ley 422328 pag 1: burbuja "en Barra / Lirio / Sin Envoltura / Carton" (bboxes reales)
    return [_b("en Barra", 1727, 651, 48), _b("Urio", 1721, 677, 34),
            _b("Envoltura", 1723, 689, 56), _b("carton", 1729, 703, 42, 12)]


def test_unidad_toma_las_lineas_contiguas_de_encima():
    lineas = _casilla_jabon()
    nuevo = nombre_con_unidad(lineas[-1], lineas, NORM)
    assert nuevo["texto"] == "en Barra Urio Envoltura carton"
    assert "Envoltura" in nuevo["_nombre_norm"] and nuevo["_nombre_norm"].lower().endswith("carton")
    assert nuevo["bbox"] == {"x": 1721, "y": 651, "ancho": 1779 - 1721, "alto": 715 - 651}
    assert lineas[-1]["texto"] == "carton"  # el bloque original no se modifica


def test_unidad_sin_linea_encima_no_cambia():
    # el "1 Pieza" del cintillo GRATIS: la descripcion esta a 58 px (mas de una linea)
    pieza = _b("Pieza", 1441, 487, 40, 16)
    otros = [_b("Limon Axion", 1407, 413, 88, 16), pieza]
    assert nombre_con_unidad(pieza, otros, NORM) is pieza


def test_linea_de_otra_columna_no_se_une():
    carton = _b("Carton", 1225, 437, 44)
    otros = [_b("oXion", 1284, 428, 50, 26), carton]  # pegado en y, pero sin traslape en x
    assert nombre_con_unidad(carton, otros, NORM) is carton


def test_nombre_que_no_es_unidad_no_cambia():
    lineas = [_b("Grano DE", 534, 562, 106, 24), _b("DORADO", 536, 586, 86, 24)]
    assert nombre_con_unidad(lineas[1], lineas, NORM) is lineas[1]


def test_maximo_de_lineas():
    lineas = [_b(f"Linea{i}", 100, 100 + 16 * i, 60, 14) for i in range(10)] + [_b("Carton", 100, 260, 60, 14)]
    nuevo = nombre_con_unidad(lineas[-1], lineas, NORM)
    assert nuevo["texto"].split() == [f"Linea{i}" for i in range(4, 10)] + ["Carton"]


def _pagina_banda(con_otra_columna=True):
    # casa_ley 426471 pag 3 (bboxes reales): la banda de seccion va sobre los encabezados "Detergente" y "Jabon"
    lineas = [_b("VeRANOde AHoRROS", 475, 4, 913, 128), _b("GUIDADODELAROPALIMPIEZADELHOGAR", 1282, 138, 362, 24),
              _b("Jabón", 1464, 166, 58, 24), _b("en Barra", 1467, 185, 76, 20), _b("Amarlllo", 1481, 209, 48),
              _b("Lirio", 1485, 221, 34, 12), _b("Sin Envoltura", 1469, 231, 72), _b("Grton", 1484, 242, 39)]
    return lineas + ([_b("Detergente", 1281, 165, 99, 28)] if con_otra_columna else [])


def test_banda_de_seccion_sobre_dos_casillas_corta_la_pila():
    lineas = _pagina_banda()
    grton = next(l for l in lineas if l["texto"] == "Grton")
    assert nombre_con_unidad(grton, lineas, NORM)["texto"] == "Jabón en Barra Amarlllo Lirio Sin Envoltura Grton"


def test_linea_ancha_que_solo_cubre_su_casilla_si_entra():
    # sin otra casilla debajo de la linea ancha no hay senal de banda (soriana "Recogedor con baston" / "pieza")
    lineas = [_b("Recogedor con bastón", 400, 100, 300, 24), _b("pieza", 520, 126, 50, 16)]
    assert nombre_con_unidad(lineas[1], lineas, NORM)["texto"] == "Recogedor con bastón pieza"


def test_encabezado_de_casilla_alineado_si_entra():
    # casa_ley 422328 pag 1: "Detergente" (123 px, 2.7x la pila) sobre "Liquido / Axion / Limon / Carton"
    lineas = [_b("Detergente", 1205, 343, 123, 32), _b("Liquido", 1225, 383, 46), _b("Axion", 1225, 411, 40),
              _b("Limon", 1226, 422, 43, 18), _b("Carton", 1225, 437, 44)]
    assert nombre_con_unidad(lineas[-1], lineas, NORM)["texto"] == "Detergente Liquido Axion Limon Carton"


def test_nombre_ancho_encima_de_rollos_si_entra():
    # s-mart 423050 pag 2 (bboxes reales)
    lineas = [_b("Papel higlénico", 1556, 1281, 179, 31), _b("Klecnex", 1596, 1308, 99, 29),
              _b("Mega Jumnbo", 1592, 1335, 108, 26), _b("rollos", 1630, 1357, 49, 19)]
    assert nombre_con_unidad(lineas[-1], lineas, NORM)["texto"] == "Papel higlénico Klecnex Mega Jumnbo rollos"


def _precio(valor, x, y, ancho, alto=40):
    return {"texto": f"${valor}", "valor": valor, "confianza": 0.9,
            "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _registros(productos, precios):
    pag = {"pagina": "p.webp", "productos": productos, "precios": precios, "precios_anteriores": []}
    return construir_registros_pagina(pag, None, NORM)["precios"]


def test_guarda_columna_unidad_de_la_casilla_vecina_no_se_une():
    # casa_ley 422938 pag 1 (bboxes reales): el precio de Huggies ($39, x=155) toma por cercania el
    # "Paquete" de la casilla vecina (x=445, 242 px a la derecha); sin guarda mostraba "Suavelastic Paquete"
    productos = [_b("Toallitas", 334, 828, 82, 26), _b("húmedas", 336, 850, 82, 24),
                 _b("Suavelastic", 433, 843, 72, 14), _b("Paquete", 445, 869, 50, 14),
                 _b("con 100 Piezas", 427, 881, 84, 14)]
    reg = _registros(productos, [_precio(39.0, 155, 869, 48)])[0]
    assert reg["producto"]["texto"] == "Paquete"
    assert reg["producto"]["_nombre_norm"] == "Paquete"


def test_guarda_columna_hueco_de_22px_si_se_une():
    # casa_ley 422328 pag 1 (bboxes reales): precio $506.34 en x 1619-1707, burbuja "carton" desde x=1729
    reg = _registros(_casilla_jabon(), [_precio(506.34, 1619, 699, 88)])[0]
    assert reg["producto"]["texto"] == "en Barra Urio Envoltura carton"


def test_guarda_columna_misma_unidad_otro_precio_lejano_no_se_une():
    # mismo bloque "carton": el precio $193.72 (x 1423-1509, 220 px a la izquierda) es de otra casilla
    reg = _registros(_casilla_jabon(), [_precio(193.72, 1423, 701, 86)])[0]
    assert reg["producto"]["texto"] == "carton"


@pytest.mark.parametrize("x_precio,ancho,esperado", [
    (1619, 88, True),    # hueco de 22 px (Jabon Lirio)
    (1640, 40, True),    # hueco de 49 px: dentro del margen
    (1600, 70, False),   # hueco de 59 px: fuera del margen
    (1423, 86, False),   # 220 px: casilla vecina
    (1700, 80, True),    # traslape directo
    (1780, 60, True),    # unidad a la izquierda del precio, hueco de 9 px
])
def test_unidad_en_columna_del_precio(x_precio, ancho, esperado):
    from load.load import MARGEN_COLUMNA_UNIDAD_PX, unidad_en_columna_del_precio
    assert MARGEN_COLUMNA_UNIDAD_PX == 50
    carton = _b("carton", 1729, 703, 42, 12)  # x 1729-1771
    assert unidad_en_columna_del_precio(carton, _precio(1.0, x_precio, 699, ancho)) is esperado


def test_registro_del_dashboard_muestra_la_descripcion():
    # alsuper 423212 pag 3 (bboxes reales): el precio $36.90 tomaba "GRAMOS"
    productos = [_b("MARGARINA", 802, 1106, 118, 24), _b("IBERIA CON SAL", 800, 1124, 146, 24),
                 _b("GRAMOS", 850, 1142, 90, 24)]
    pag = {"pagina": "pagina_003.webp", "productos": productos, "precios_anteriores": [],
           "precios": [{"texto": "$36.90", "valor": 36.9, "confianza": 0.9,
                        "bbox": {"x": 807, "y": 1163, "ancho": 120, "alto": 50}}]}
    regs = construir_registros_pagina(pag, None, NORM)
    prod = regs["precios"][0]["producto"]
    assert prod["texto"] == "MARGARINA IBERIA CON SAL GRAMOS"
    assert prod["_nombre_norm"].lower() == "margarina iberia con sal gramos"
    # la fila PRODUCTO enlazada sigue siendo la de la unidad (load inserta los productos tal cual)
    assert [p["texto"] for p in regs["productos"]] == ["MARGARINA", "IBERIA CON SAL", "GRAMOS"]
    assert prod["_idx"] == 2
