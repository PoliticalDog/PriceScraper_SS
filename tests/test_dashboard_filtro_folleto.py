"""Filtro "Folleto" del dashboard (aprobado 14-oct-2026, docs/bi/metricas.md seccion 6).

Sin BD: la conexion queda bloqueada (fixture _sin_bd). Se verifica la normalizacion del parametro (id de la fuente,
exacto), el SQL que genera el ORM y el de la consulta cruda, que las vistas pasen el parametro y que las paginas
pinten el campo. Los conteos contra PostgreSQL se validan con docs/bi/consultas/filtro_folleto*.sql.
"""

import os
import re

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.test import RequestFactory  # noqa: E402

from dashboard import queries, views  # noqa: E402
from dashboard.models import (  # noqa: E402
    ErrorCarga, Extraccion, Folleto, VCalidadPipeline, VComparativaPrecios, VHistoricoPrecios, VPreciosActuales,
)


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    """Cualquier intento de abrir conexion a la BD falla la prueba."""
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)


rf = RequestFactory()


def _sql(qs) -> str:
    return str(qs.query)


def _espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto)


# -- Parametro ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor, esperado", [
    ("430658", "430658"), ("  430658 ", "430658"), ("abc-1", "abc-1"),
    (None, None), ("", None), ("   ", None),
])
def test_normalizar_folleto(valor, esperado):
    assert queries.normalizar_folleto(valor) == esperado


# -- ORM ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor", [None, "", "  "])
def test_sin_folleto_no_toca_el_queryset(valor):
    qs = VPreciosActuales.objects.all()
    assert queries.filtrar_folleto(qs, valor) is qs


@pytest.mark.parametrize("modelo, tabla", [
    (VPreciosActuales, "v_precios_actuales"), (VHistoricoPrecios, "v_historico_precios"),
    (VCalidadPipeline, "v_calidad_pipeline"), (Folleto, "folletos"), (ErrorCarga, "errores_carga"),
])
def test_igualdad_exacta_sin_joins(modelo, tabla):
    sql = _sql(queries.filtrar_folleto(modelo.objects.all(), " 430658 "))
    assert f'"{tabla}"."folleto_id_fuente" = 430658' in sql  # exacto (sin LIKE/ILIKE) y sin espacios
    assert "LIKE" not in sql.upper()
    assert " JOIN " not in sql


def test_extracciones_une_folletos_por_fk():
    sql = _sql(queries.filtrar_folleto(Extraccion.objects.all(), "430658", "folleto__folleto_id_fuente"))
    assert 'INNER JOIN "folletos" ON ("extracciones"."folleto_id" = "folletos"."id")' in sql  # N:1, no duplica
    assert '"folletos"."folleto_id_fuente" = 430658' in sql


def test_comparativa_usa_exists_sin_join():
    qs = VComparativaPrecios.objects.filter(num_tiendas__gte=2).filter(queries._en_folleto("430658"))
    sql = _espacios(_sql(qs))
    principal = sql.split("EXISTS", 1)[0]
    assert " JOIN " not in principal  # la consulta externa no une nada: no puede duplicar grupos
    assert "EXISTS(SELECT" in sql.replace(" (", "(")
    subconsulta = sql.split("EXISTS", 1)[1]
    assert re.search(r'U\d\."texto_norm" = \("v_comparativa_precios"\."producto"\)', subconsulta)
    assert re.search(r'U\d\."folleto_id_fuente" = 430658', subconsulta)
    assert re.search(r'U\d\."tipo" = PRECIO', subconsulta) and re.search(r'U\d\."valor" IS NOT NULL', subconsulta)
    assert 'COALESCE("v_comparativa_precios"."categoria"' in subconsulta


class _QSFalso:
    """Registra los filtros que recibe comparativa_precios sin ejecutar nada."""

    def __init__(self):
        self.filtros = []

    def filter(self, *a, **k):
        self.filtros.append((a, k))
        return self

    def order_by(self, *a):
        return self

    def __getitem__(self, _):
        return self

    def values(self, *a):
        return []


@pytest.mark.parametrize("folleto, con_exists", [("430658", True), (" ", False), (None, False)])
def test_comparativa_agrega_exists_solo_con_folleto(monkeypatch, folleto, con_exists):
    falso = _QSFalso()
    monkeypatch.setattr(queries, "filtrar_con_categoria", lambda qs, valor: falso)
    queries.comparativa_precios(min_tiendas=2, folleto=folleto)
    exists = [a for a, _ in falso.filtros if a and type(a[0]).__name__ == "Exists"]
    assert bool(exists) is con_exists


# -- SQL crudo (confiabilidad) -----------------------------------------------------------------------------

def test_sql_confiabilidad_incluye_la_regla():
    sql = _espacios(queries._SQL_CONFIABILIDAD)
    assert _espacios(queries._SQL_FOLLETO) in sql
    assert "f.folleto_id_fuente = %(folleto)s::text" in sql
    assert "EXISTS (SELECT 1 FROM folletos fx WHERE fx.tienda_id = t.id AND fx.folleto_id_fuente = %(folleto)s::text)" in sql


def test_confiabilidad_pasa_el_parametro(monkeypatch):
    capturas = []
    monkeypatch.setattr(queries, "_filas_sql", lambda sql, params: capturas.append(params) or [])
    monkeypatch.setattr(queries.confiabilidad, "corrida_vigente", lambda *a, **k: None)
    queries.confiabilidad_por_tienda(folleto=" 430658 ")
    queries.confiabilidad_por_tienda()
    assert [p["folleto"] for p in capturas] == ["430658", None]


# -- Vistas (API) ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista, funcion, url", [
    ("api_precios", "precios_actuales", "/api/precios"),
    ("api_comparativa", "comparativa_precios", "/api/comparativa"),
    ("api_historico", "historico_precios", "/api/historico?producto=leche"),
    ("api_calidad", "calidad_pipeline", "/api/calidad"),
    ("api_confiabilidad", "confiabilidad_por_tienda", "/api/confiabilidad"),
    ("api_errores", "errores_carga", "/api/errores"),
])
@pytest.mark.parametrize("valor, esperado", [("430658", "430658"), ("%20430658%20", "430658"), ("", None), (None, None)])
def test_api_pasa_folleto(monkeypatch, vista, funcion, url, valor, esperado):
    recibido = {}

    def falsa(*a, **k):
        recibido.update(k)
        return {} if funcion in ("confiabilidad_por_tienda", "errores_carga") else []

    monkeypatch.setattr(queries, funcion, falsa)
    sep = "&" if "?" in url else "?"
    getattr(views, vista)(rf.get(url + (f"{sep}folleto={valor}" if valor is not None else "")))
    assert recibido["folleto"] == esperado


def test_api_resumen_pasa_folleto(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "resumen_kpis", lambda **k: recibido.setdefault("kpis", k) and {})
    monkeypatch.setattr(queries, "resumen_top_categorias", lambda **k: recibido.setdefault("top", k) and [])
    monkeypatch.setattr(queries, "resumen_folletos_por_tienda", lambda: [])
    views.api_resumen(rf.get("/api/resumen?folleto=430658"))
    assert recibido["kpis"] == {"con_categoria": None, "folleto": "430658"}
    assert recibido["top"] == {"con_categoria": None, "folleto": "430658"}


def test_cobertura_y_detalle_comparativa_no_usan_folleto(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "cobertura_por_tienda", lambda **k: recibido.setdefault("cob", k) and {})
    monkeypatch.setattr(queries, "comparativa_por_tienda", lambda p, **k: recibido.setdefault("det", k) and [])
    views.api_cobertura(rf.get("/api/cobertura?folleto=430658"))
    views.api_comparativa_por_tienda(rf.get("/api/comparativa/x/por-tienda?folleto=430658"), "x")
    assert "folleto" not in recibido["cob"]
    assert "folleto" not in recibido["det"]


# -- Paginas -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista, fid", [
    ("pagina_resumen", "fFolleto"), ("pagina_precios", "fFolleto"), ("pagina_comparativa", "fFolleto"),
    ("pagina_historico", "fFolleto"), ("pagina_calidad", "fConfFolleto"), ("pagina_calidad", "fFolleto"),
    ("pagina_errores", "fFolleto"),
])
def test_paginas_pintan_el_campo_vacio(vista, fid):
    html = getattr(views, vista)(rf.get("/")).content.decode("utf-8")
    m = re.search(rf'<input type="text" id="{fid}"[^>]*>', html, re.S)
    assert m, fid
    assert "value=" not in m.group(0)  # vacio por defecto = todos


def test_explorador_filtra_y_propaga_folleto(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "listar_tiendas_detalle", lambda: [])
    monkeypatch.setattr(queries, "listar_folletos", lambda **k: recibido.setdefault("fol", k) and [{"id": 5}])
    monkeypatch.setattr(queries, "listar_tipos_extraccion", lambda: ["PRECIO"])
    monkeypatch.setattr(queries, "listar_extracciones", lambda **k: recibido.setdefault("ext", k) and [])
    monkeypatch.setattr(queries, "estado_folleto", lambda f: None)
    html = views.pagina_explorador(rf.get("/datos?folleto=%20430658%20")).content.decode("utf-8")
    assert recibido["fol"]["folleto"] == "430658"
    assert recibido["ext"]["folleto"] == "430658"
    assert 'name="folleto" value="430658"' in html
    assert "folleto=430658" in html  # el enlace "ver" conserva el filtro


def test_explorador_escapa_el_id(monkeypatch):
    monkeypatch.setattr(queries, "listar_tiendas_detalle", lambda: [])
    monkeypatch.setattr(queries, "listar_folletos", lambda **k: [])
    monkeypatch.setattr(queries, "listar_tipos_extraccion", lambda: [])
    monkeypatch.setattr(queries, "listar_extracciones", lambda **k: [])
    monkeypatch.setattr(queries, "estado_folleto", lambda f: {"folleto": f, "estado": "no_existe", "errores_carga": 0})
    html = views.pagina_explorador(rf.get('/datos?folleto="><script>x</script>')).content.decode("utf-8")
    assert "<script>x</script>" not in html
