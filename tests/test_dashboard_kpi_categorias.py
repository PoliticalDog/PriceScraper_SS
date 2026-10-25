"""KPI "Categorias" del Resumen (aprobado 17-oct-2026, docs/bi/metricas.md seccion 3).

Sin BD: la conexion queda bloqueada (fixture _sin_bd). Se verifica el SQL que genera el ORM (categorias distintas con
TRIM, sin vacia/NULL, sin joins, con el filtro de folleto), el armado del KPI (% y "no aplica" con "sin categoria"),
que resumen_kpis use el denominador sin el filtro con/sin categoria y que la pagina pinte la tarjeta. Los conteos
contra PostgreSQL se validan con consulta.py (18 / 12,495 / 32,073 el 17-oct-2026).
"""

import os
import re

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.db.models import QuerySet  # noqa: E402
from django.test import RequestFactory  # noqa: E402

from dashboard import queries, views  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    """Cualquier intento de abrir conexion a la BD falla la prueba."""
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)


rf = RequestFactory()


def _espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto)


# -- ORM ---------------------------------------------------------------------------------------------------

def test_categorias_distintas_con_trim_sin_vacias_y_sin_joins():
    sql = _espacios(str(queries.qs_categorias_distintas().query))
    assert sql.startswith('SELECT DISTINCT TRIM("v_precios_actuales"."categoria") AS "_categoria"')
    assert "JOIN" not in sql
    # misma regla que filtrar_con_categoria: excluye NULL y '' despues de TRIM
    assert 'TRIM("v_precios_actuales"."categoria") IS NULL OR TRIM("v_precios_actuales"."categoria") = ' in sql
    assert "folleto_id_fuente" not in sql
    assert "ORDER BY" not in sql  # sin ordenamiento que agregue columnas al DISTINCT


def test_categorias_distintas_respeta_folleto():
    sql = _espacios(str(queries.qs_categorias_distintas(" 416117 ").query))
    assert '"v_precios_actuales"."folleto_id_fuente" = 416117' in sql


# -- Armado del KPI ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("args, esperado", [
    ((18, 12495, 32073, None), {"categorias": 18, "registros_con_categoria": 12495, "registros_base": 32073,
                                "pct_con_categoria": 39.0}),
    ((18, 12495, 32073, "si"), {"categorias": 18, "registros_con_categoria": 12495, "registros_base": 32073,
                                "pct_con_categoria": 39.0}),
    ((12, 104, 409, None), {"categorias": 12, "registros_con_categoria": 104, "registros_base": 409,
                            "pct_con_categoria": 25.4}),
    # con "sin categoria" no aplica aunque lleguen cifras
    ((18, 12495, 32073, "no"), {"categorias": None, "registros_con_categoria": None, "registros_base": 32073,
                                "pct_con_categoria": None}),
    # folleto sin registros: 0 categorias, % indefinido
    ((0, 0, 0, None), {"categorias": 0, "registros_con_categoria": 0, "registros_base": 0,
                       "pct_con_categoria": None}),
])
def test_kpi_categorias(args, esperado):
    assert queries.kpi_categorias(*args) == esperado


# -- resumen_kpis (conteos simulados: se registra el SQL de cada COUNT) ----------------------------------------

@pytest.fixture
def conteos(monkeypatch):
    registrados = []

    def _count(self):
        registrados.append(_espacios(str(self.query)))
        return 10

    monkeypatch.setattr(QuerySet, "count", _count)
    monkeypatch.setattr(QuerySet, "aggregate", lambda self, **k: {"vigentes": 0, "dudosos": 0})
    return registrados


def test_resumen_kpis_incluye_categorias(conteos):
    k = queries.resumen_kpis()
    assert (k["categorias"], k["registros_con_categoria"], k["registros_base"], k["pct_con_categoria"]) == (
        10, 10, 10, 100.0)
    assert any("SELECT DISTINCT TRIM" in s for s in conteos)


def test_resumen_kpis_denominador_sin_filtro_de_categoria(conteos):
    queries.resumen_kpis(con_categoria="si", folleto="416117")
    base = [s for s in conteos if "v_precios_actuales" in s and "folleto_id_fuente" in s and "TRIM" not in s]
    assert base, "falta el conteo base del folleto sin filtro de categoria"


def test_resumen_kpis_sin_categoria_no_aplica(conteos):
    k = queries.resumen_kpis(con_categoria="no")
    assert k["categorias"] is None and k["pct_con_categoria"] is None
    assert not any("SELECT DISTINCT TRIM" in s for s in conteos)  # no consulta categorias si no aplica


# -- Pagina ------------------------------------------------------------------------------------------------

def test_resumen_pinta_la_tarjeta_categorias():
    html = views.pagina_resumen(rf.get("/")).content.decode("utf-8")
    assert 'tarjetaKpi("ti-tags", k.categorias ?? "—", "Categorías", notaCategorias,' in html
    assert 'no aplica con filtro "sin categoría"' in html
    assert "% de los precios con categoría" in html
    assert '"Frutas y Verduras" se cuenta dentro de alimentos.' in html
    assert 'Aplica a "Precios detectados", "Categorías" y a la gráfica de categorías' in html
