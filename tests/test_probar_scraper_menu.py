"""Menu de tiendas del scraper: una opcion invalida ya no lanza el rastreo de todas las tiendas (26-oct-2026)."""
import pytest

from probar_scraper import elegir_tienda

TIENDAS = ["bodega-aurrera", "chedraui", "heb"]


@pytest.mark.parametrize("respuesta, esperado", [
    ("0", "todas"), ("2", "chedraui"), (" 3 ", "heb"),
    ("4", None), ("-1", None), ("chedraui", None), ("", None),
])
def test_elegir_tienda(respuesta, esperado):
    assert elegir_tienda(TIENDAS, respuesta) == esperado
