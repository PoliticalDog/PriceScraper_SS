"""Filtro "Con / sin categoria" del dashboard (aprobado 14-oct-2026, docs/bi/metricas.md seccion 5).

Sin BD: la conexion queda bloqueada (fixture _sin_bd). Se verifica la regla (normalizacion del parametro), el SQL que
genera el ORM y el de las consultas crudas, y que las vistas pasen el parametro. Los conteos contra PostgreSQL se
validan aparte con docs/bi/consultas/filtro_con_categoria*.sql.
"""

import os
import re

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.test import RequestFactory  # noqa: E402

from dashboard import queries, views  # noqa: E402
from dashboard.models import Extraccion, VComparativaPrecios, VHistoricoPrecios, VPreciosActuales  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    """Cualquier intento de abrir conexion a la BD falla la prueba."""
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)


rf = RequestFactory()


def _where(qs) -> str:
    sql = str(qs.query)
    return sql.split(" WHERE ", 1)[1] if " WHERE " in sql else ""


def _espacios(texto: str) -> str:
    return re.sub(r"\s+", " ", texto)


# -- Parametro ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor, esperado", [
    ("si", "si"), ("no", "no"), (" SI ", "si"), ("No", "no"),
    (None, None), ("", None), ("todos", None), ("true", None), ("1", None),
])
def test_normalizar_con_categoria(valor, esperado):
    assert queries.normalizar_con_categoria(valor) == esperado


# -- ORM ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor", [None, "", "x"])
def test_todos_no_toca_el_queryset(valor):
    qs = VPreciosActuales.objects.all()
    assert queries.filtrar_con_categoria(qs, valor) is qs


def test_sin_categoria_es_null_o_vacia_tras_trim():
    where = _where(queries.filtrar_con_categoria(VPreciosActuales.objects.all(), "no"))
    assert 'TRIM("v_precios_actuales"."categoria") IS NULL' in where
    assert 'TRIM("v_precios_actuales"."categoria") =' in where
    assert not where.startswith("NOT")


def test_con_categoria_es_el_complemento_exacto():
    sin = _where(queries.filtrar_con_categoria(VPreciosActuales.objects.all(), "no"))
    con = _where(queries.filtrar_con_categoria(VPreciosActuales.objects.all(), "si"))
    assert con.startswith("NOT (")
    assert sin in con  # NOT (<misma condicion>): con + sin = todos, sin solapes


def test_filtro_no_agrega_joins():
    for modelo, campo in ((VPreciosActuales, "categoria"), (VComparativaPrecios, "categoria"),
                          (VHistoricoPrecios, "categoria"), (Extraccion, "categoria_nlp")):
        for valor in ("si", "no"):
            sql = str(queries.filtrar_con_categoria(modelo.objects.all(), valor, campo).query)
            assert " JOIN " not in sql, (modelo, valor)


def test_extracciones_usa_categoria_nlp():
    where = _where(queries.filtrar_con_categoria(Extraccion.objects.filter(tipo="PRECIO"), "no", "categoria_nlp"))
    assert 'TRIM("extracciones"."categoria_nlp")' in where


# -- SQL crudo (confiabilidad y cobertura) -----------------------------------------------------------------

def test_sql_crudo_incluye_la_regla():
    regla = _espacios(queries._SQL_CON_CATEGORIA)
    assert "COALESCE(BTRIM(e.categoria_nlp), '') <> ''" in regla
    assert regla in _espacios(queries._SQL_CONFIABILIDAD)
    assert regla in _espacios(queries._SQL_COBERTURA)
    # el conteo "sin categoria" del panel usa la misma regla
    assert "COALESCE(BTRIM(categoria_nlp), '') = ''" in queries._SQL_CONFIABILIDAD


def test_confiabilidad_y_cobertura_pasan_el_parametro(monkeypatch):
    capturas = []
    monkeypatch.setattr(queries, "_filas_sql", lambda sql, params: capturas.append(params) or [])
    monkeypatch.setattr(queries.confiabilidad, "corrida_vigente", lambda *a, **k: None)
    monkeypatch.setattr(queries, "_dudosos", lambda tiendas: [])

    queries.confiabilidad_por_tienda(con_categoria="NO")
    queries.cobertura_por_tienda(con_categoria="si")
    queries.confiabilidad_por_tienda()
    queries.cobertura_por_tienda(con_categoria="otro")
    assert [p["con_categoria"] for p in capturas] == ["no", "si", None, None]


# -- Vistas (API) ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista, funcion, url", [
    ("api_precios", "precios_actuales", "/api/precios"),
    ("api_comparativa", "comparativa_precios", "/api/comparativa"),
    ("api_historico", "historico_precios", "/api/historico?producto=leche"),
    ("api_confiabilidad", "confiabilidad_por_tienda", "/api/confiabilidad"),
    ("api_cobertura", "cobertura_por_tienda", "/api/cobertura"),
])
@pytest.mark.parametrize("valor, esperado", [("si", "si"), ("no", "no"), ("", None), (None, None)])
def test_api_pasa_con_categoria(monkeypatch, vista, funcion, url, valor, esperado):
    recibido = {}

    def falsa(*a, **k):
        recibido.update(k)
        return {} if funcion in ("confiabilidad_por_tienda", "cobertura_por_tienda") else []

    monkeypatch.setattr(queries, funcion, falsa)
    sep = "&" if "?" in url else "?"
    peticion = rf.get(url + (f"{sep}con_categoria={valor}" if valor is not None else ""))
    getattr(views, vista)(peticion)
    assert recibido["con_categoria"] == esperado


@pytest.mark.parametrize("vista, fid", [
    ("pagina_resumen", "fConCategoria"), ("pagina_precios", "fConCategoria"),
    ("pagina_comparativa", "fConCategoria"), ("pagina_historico", "fConCategoria"),
    ("pagina_calidad", "fConfConCategoria"), ("pagina_cobertura", "fConCategoria"),
])
def test_paginas_pintan_el_control_con_todos_por_defecto(vista, fid):
    html = getattr(views, vista)(rf.get("/")).content.decode("utf-8")
    assert f'<select id="{fid}" class="form-select"' in html
    assert '<option value="" selected>Todos</option>' in html
    assert '<option value="si">Con categoría</option>' in html
    assert '<option value="no">Sin categoría</option>' in html


def test_explorador_propaga_con_categoria(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "listar_tiendas_detalle", lambda: [])
    monkeypatch.setattr(queries, "listar_folletos", lambda **k: [{"id": 5}])
    monkeypatch.setattr(queries, "listar_tipos_extraccion", lambda: ["PRECIO"])
    monkeypatch.setattr(queries, "listar_extracciones", lambda **k: recibido.update(k) or [])
    html = views.pagina_explorador(rf.get("/datos?con_categoria=no")).content.decode("utf-8")
    assert recibido["con_categoria"] == "no"
    assert '<option value="no" selected>sin categoria</option>' in html
    assert "con_categoria=no" in html  # enlaces "ver" del folleto conservan el filtro


def test_api_resumen_y_detalle_comparativa(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "resumen_kpis", lambda **k: recibido.setdefault("kpis", k) and {})
    monkeypatch.setattr(queries, "resumen_top_categorias", lambda **k: recibido.setdefault("top", k) and [])
    monkeypatch.setattr(queries, "resumen_folletos_por_tienda", lambda: [])
    monkeypatch.setattr(queries, "comparativa_por_tienda",
                        lambda producto, **k: recibido.setdefault("detalle", (producto, k)) and [])

    views.api_resumen(rf.get("/api/resumen?con_categoria=no"))
    views.api_comparativa_por_tienda(rf.get("/api/comparativa/leche/por-tienda?con_categoria=si"), "leche")
    assert recibido["kpis"] == {"con_categoria": "no", "folleto": None}
    assert recibido["top"] == {"con_categoria": "no", "folleto": None}
    assert recibido["detalle"] == ("leche", {"con_categoria": "si", "categoria": None})


# -- Detalle por tienda: categoria del grupo y nombres con "/" (26-oct-2026) ----------------------------------------

def test_detalle_comparativa_filtra_por_la_categoria_del_grupo():
    def where(**k):
        return _espacios(str(queries.qs_precios_del_grupo("Leche", **k).query)).split(" WHERE ", 1)[1]
    sin, con, vacia = where(), where(categoria="alimentos"), where(categoria="")
    assert '"texto_norm" = Leche' in sin and "categoria_nlp" not in sin
    assert '"categoria_nlp" = alimentos' in con
    assert '"categoria_nlp" IS NULL' in vacia and "OR" in vacia


def test_api_detalle_pasa_la_categoria_y_acepta_barra_en_el_nombre(monkeypatch):
    from django.urls import resolve
    recibido = {}
    monkeypatch.setattr(queries, "comparativa_por_tienda",
                        lambda producto, **k: recibido.setdefault("detalle", (producto, k)) and [])
    coincidencia = resolve("/api/comparativa/Leche 1/2 L/por-tienda")
    assert coincidencia.kwargs == {"producto": "Leche 1/2 L"}
    views.api_comparativa_por_tienda(rf.get("/x?categoria="), "Leche 1/2 L")
    assert recibido["detalle"] == ("Leche 1/2 L", {"con_categoria": None, "categoria": ""})
