"""
Guarda de cobertura del normalizador: un match fuzzy solo se acepta si el nombre canonico
(o el alias que hizo match) explica todas las palabras significativas del texto del folleto.
Si no, se conserva el texto como heuristico. Casos tomados de la corrida dev 20261011_214819.
"""
import pytest

from nlp.normalizador import Normalizador


@pytest.fixture(scope="module")
def norm():
    return Normalizador()


@pytest.mark.parametrize("texto, esperado", [
    # Fuzzy por caracteres sin palabras en comun (antes fuzzy_bajo)
    ("MORENA", "Morena"),                       # antes Mayonesa
    ("res para asar", "Res Para Asar"),         # antes Pasta para sopa
    ("Hass", "Hass"),                           # antes Salsa
    ("Uva roja", "Uva Roja"),                   # antes Manzana
    ("Gelatina en Polvo", "Gelatina en Polvo"),  # antes Detergente
    ("gises", "Gises"),                         # antes Acondicionador
    # Un token en el catalogo y el resto no (antes fuzzy al 100%)
    ("Salsa Chamoy", "Salsa Chamoy"),           # antes Salsa
    ("Audífonos Vibe Beam 2 negro", "Audífonos Vibe Beam 2 Negro"),  # antes Audifonos
    ("Playera estampada", "Playera Estampada"),  # antes Playera
])
def test_texto_no_cubierto_se_conserva(norm, texto, esperado):
    r = norm.normalizar(texto)
    assert not r.descartado
    assert r.metodo == "heuristico"
    assert r.nombre_canonico == esperado


@pytest.mark.parametrize("texto, canonico", [
    ("Entera", "Leche entera"),                  # el canonico agrega palabras: se acepta
    ("PECHUGA DE", "Pechuga de pollo"),
    ("PECHUCA DE", "Pechuga de pollo"),          # error OCR leve en la palabra
    ("PLTANO", "Plátano"),
    ("cebolca", "Cebolla"),
    ("Leche 1 lt", "Leche entera"),              # numeros y unidades no cuentan
])
def test_texto_cubierto_conserva_canonico(norm, texto, canonico):
    r = norm.normalizar(texto)
    assert r.metodo in ("exacto", "fuzzy", "fuzzy_bajo")
    assert r.nombre_canonico == canonico


def test_heuristico_descartable_mantiene_fuzzy():
    # Si el heuristico se descartaria por largo, se mantiene el fuzzy: la guarda no cambia
    # que bloques se aceptan como producto (no deja precios sin producto)
    n = Normalizador()
    n.LARGO_MAXIMO_HEURISTICO = 10
    r = n.normalizar("Salsa Chamoy")
    assert not r.descartado
    assert r.nombre_canonico == "Salsa"


@pytest.mark.parametrize("texto, canonico", [
    # Error OCR de sustitucion de letras en palabra de 6+ letras (Levenshtein normalizado >= 0.78)
    ("Acondklonador", "Acondicionador"),
    ("Oexaca", "Queso Oaxaca"),
])
def test_error_ocr_leve_recupera_canonico(norm, texto, canonico):
    r = norm.normalizar(texto)
    assert r.metodo in ("fuzzy", "fuzzy_bajo")
    assert r.nombre_canonico == canonico


@pytest.mark.parametrize("texto", [
    # Falsos amigos que la guarda debe seguir rechazando
    "MORENA", "res para asar", "Salsa Chamoy", "Figura", "Milanesa", "Smartdecó",
    "Lavasecadora", "NINJA", "Bocina Partybox", "Tablet", "espinaca", "JICAMA",
    # Una letra distinta en palabra corta ya es otro producto; 0.75 en 6+ letras reabriria Refresco
    "Jabón", "Popa", "Acoe", "Refritos",
    # Fuera de alcance de la tolerancia OCR (demasiado distintos de la palabra del catalogo):
    # se documenta que siguen como texto del folleto
    "Papcl Hlgiénko", "Papcl Higlénico", "Gaxesas", "Jazatun", "en 0gug( acelte", "Coayonsn", "Savzante y Jamnin",
])
def test_sigue_rechazado(norm, texto):
    r = norm.normalizar(texto)
    assert not r.descartado
    assert r.metodo == "heuristico"
