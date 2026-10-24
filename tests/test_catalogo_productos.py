"""
Pruebas de nlp/catalogo_productos.buscar_categoria: keywords de la revisión manual del
23-oct-2026 y la prioridad tipo de producto > marca.
"""
import pytest

from nlp.catalogo_productos import CATALOGO, buscar_categoria


@pytest.mark.parametrize("texto, categoria", [
    ("Queso manchego Carranco", "Alimentos y Bebidas"),     # tipo ("queso")
    ("Carranco 400 g", "Alimentos y Bebidas"),              # solo marca
    ("Detergente Foca", "Limpieza del Hogar"),
    ("Pinol", "Limpieza del Hogar"),                        # sin cambio
    ("Abrigo largo con peluche", "Juguetes y Bebés"),       # "peluche" > "abrigo" por longitud (aceptado)
])
def test_categoria(texto, categoria):
    assert buscar_categoria(texto) == (True, categoria, False)


def test_tipo_de_otra_categoria_gana_a_la_marca():
    # "vaso" (Muebles y Hogar) es tipo; "colgate" (Cuidado Personal) es marca y es más larga
    assert buscar_categoria("Vaso Colgate") == (True, "Muebles y Hogar", False)
    assert buscar_categoria("Colgate vaso 350 ml") == (True, "Muebles y Hogar", False)


def test_solo_marca_de_cuidado_personal():
    assert buscar_categoria("Colgate 100 ml") == (True, "Cuidado Personal", False)


def test_una_marca_nunca_es_atributo():
    for datos in CATALOGO.values():
        for marca in datos.get("marcas", []):
            encontrado, _, es_atributo = buscar_categoria(f"{marca} 500 g")
            assert encontrado and not es_atributo, marca


def test_marca_no_empieza_a_mitad_de_palabra():
    # mismas reglas de borde que las keywords: "nido" no se busca dentro de "contenido"
    assert buscar_categoria("contenido neto") == (False, "", False)


def test_regio_exige_palabra_completa():
    assert buscar_categoria("Regio 32 rollos") == (True, "Limpieza del Hogar", False)
    assert buscar_categoria("REGIONAL") == (False, "", False)
    assert buscar_categoria("En dulces regional") == (True, "Alimentos y Bebidas", False)


def test_sharpie_es_papeleria_no_electronica():
    assert buscar_categoria("Sharpie") == (True, "Papelería y Útiles Escolares", False)
    assert buscar_categoria("Sharp") == (True, "Electrónica", False)


def test_sin_coincidencia():
    assert buscar_categoria("Precio especial") == (False, "", False)
