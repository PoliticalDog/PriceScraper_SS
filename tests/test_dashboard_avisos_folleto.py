"""Avisos del filtro "Folleto" y de Errores de carga (aprobados 14-oct-2026, docs/bi/metricas.md seccion 6).

Sin BD: la conexion queda bloqueada y los modelos se sustituyen por dobles. Se verifica la clasificacion del folleto
(no_existe / sin_precios / con_precios), el conteo de errores ocultos por el filtro de Estado, el endpoint, el aviso
del Explorador (renderizado en el servidor, con el id escapado) y que las paginas tengan los contenedores ocultos.
Los conteos reales se validan con docs/bi/consultas/avisos_folleto.sql.
"""

import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.test import RequestFactory  # noqa: E402

from dashboard import queries, views  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
rf = RequestFactory()


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)


# -- Dobles de los modelos ---------------------------------------------------------------------------------

class _QS:
    def __init__(self, filas=None, n=0, registro=None):
        self._filas, self._n, self._registro = filas or [], n, registro

    def filter(self, *a, **k):
        if self._registro is not None:
            self._registro.append(k)
        return self

    def order_by(self, *a):
        return self

    def values(self, *a):
        return self._filas

    def count(self):
        return self._n


class _Modelo:
    def __init__(self, qs):
        self.objects = qs


def _dobles(monkeypatch, folletos, registros, errores, registro=None):
    monkeypatch.setattr(queries, "Folleto", _Modelo(_QS(filas=folletos, registro=registro)))
    monkeypatch.setattr(queries, "VPreciosActuales", _Modelo(_QS(n=registros, registro=registro)))
    monkeypatch.setattr(queries, "ErrorCarga", _Modelo(_QS(n=errores, registro=registro)))


# -- estado_folleto ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor", [None, "", "   "])
def test_estado_folleto_sin_filtro_es_none_y_no_consulta(valor):
    assert queries.estado_folleto(valor) is None  # _sin_bd fallaria si consultara


def test_estado_folleto_no_existe(monkeypatch):
    _dobles(monkeypatch, folletos=[], registros=99, errores=2)
    e = queries.estado_folleto(" 999999 ")
    assert e["estado"] == queries.FOLLETO_NO_EXISTE
    assert e["folleto"] == "999999"
    assert e["registros"] == 0  # no se cuentan registros de un folleto que no existe
    assert e["errores_carga"] == 2  # un folleto que fallo entero no esta en folletos pero si en errores


def test_estado_folleto_sin_precios(monkeypatch):
    _dobles(monkeypatch, folletos=[{"fuente": "tiendeo", "tienda__nombre": "Soriana"}], registros=0, errores=0)
    e = queries.estado_folleto("413679")
    assert e["estado"] == queries.FOLLETO_SIN_PRECIOS
    assert e["tiendas"] == ["Soriana"] and e["fuentes"] == ["tiendeo"] and e["folletos"] == 1


def test_estado_folleto_con_precios(monkeypatch):
    registro = []
    _dobles(monkeypatch, folletos=[{"fuente": "tiendeo", "tienda__nombre": "La Comer"}], registros=213, errores=0,
            registro=registro)
    e = queries.estado_folleto("430658")
    assert e["estado"] == queries.FOLLETO_CON_PRECIOS and e["registros"] == 213
    assert all(k == {"folleto_id_fuente": "430658"} for k in registro)  # igualdad exacta en las 3 consultas


# -- errores ocultos por el filtro de Estado ---------------------------------------------------------------

@pytest.mark.parametrize("estado, opuesto", [("abiertos", "resueltos"), ("resueltos", "abiertos")])
def test_errores_ocultos_cuenta_el_estado_opuesto_con_los_demas_filtros(monkeypatch, estado, opuesto):
    llamadas = []

    def falso(categorias, tiendas, fuente, est, folleto=None):
        llamadas.append((categorias, tiendas, fuente, est, folleto))
        return _QS(n=3)

    monkeypatch.setattr(queries, "_filtrar_errores", falso)
    r = queries.errores_ocultos_por_estado(["otro"], ["walmart"], "tiendeo", estado, "413647")
    assert r == {"n": 3, "estado_oculto": opuesto, "estado_filtro": estado}
    assert llamadas == [(["otro"], ["walmart"], "tiendeo", opuesto, "413647")]


@pytest.mark.parametrize("estado", [None, "", "todos"])
def test_errores_ocultos_sin_filtro_de_estado_es_none(estado):
    assert queries.errores_ocultos_por_estado(None, None, None, estado, "413647") is None


@pytest.mark.parametrize("folleto", [None, "", "   "])
def test_errores_ocultos_sin_folleto_es_none(monkeypatch, folleto):
    # decision 15-oct-2026: el aviso solo sale con un folleto escrito; sin folleto ni se consulta
    monkeypatch.setattr(queries, "_filtrar_errores", lambda *a, **k: pytest.fail("no debe consultar"))
    assert queries.errores_ocultos_por_estado(None, None, None, "abiertos", folleto) is None


def test_filtro_resueltos_mas_folleto_genera_el_sql_esperado():
    from dashboard.models import ErrorCarga  # el real (no hay dobles en esta prueba)
    monkey_qs = queries.filtrar_folleto(ErrorCarga.objects.all(), "413647").filter(resuelto=True)
    sql = str(monkey_qs.query)
    assert '"errores_carga"."folleto_id_fuente" = 413647' in sql
    assert '"errores_carga"."resuelto"' in sql and " JOIN " not in sql


def test_api_errores_devuelve_ocultos(monkeypatch):
    monkeypatch.setattr(queries, "errores_carga", lambda **k: {"ocultos_por_estado": {"n": 1, **k}})
    datos = views.api_errores(rf.get("/api/errores?estado=abiertos&folleto=413647"))
    assert b'"ocultos_por_estado"' in datos.content


# -- Endpoint ----------------------------------------------------------------------------------------------

def test_api_filtros_folleto_vacio_no_consulta():
    r = views.api_filtros_folleto(rf.get("/api/filtros/folleto?folleto=%20%20"))
    assert r.status_code == 200 and r.content == b'{"estado": null}'


def test_api_filtros_folleto_pasa_el_id_normalizado(monkeypatch):
    recibido = []
    monkeypatch.setattr(queries, "estado_folleto", lambda f: recibido.append(f) or {"folleto": f, "estado": "no_existe"})
    r = views.api_filtros_folleto(rf.get("/api/filtros/folleto?folleto=%20999999%20"))
    assert recibido == ["999999"] and b'"no_existe"' in r.content


# -- Explorador (aviso del lado del servidor) --------------------------------------------------------------

def _explorador(monkeypatch, estado, url="/datos?folleto=999999"):
    monkeypatch.setattr(queries, "listar_tiendas_detalle", lambda: [])
    monkeypatch.setattr(queries, "listar_folletos", lambda **k: [])
    monkeypatch.setattr(queries, "listar_tipos_extraccion", lambda: [])
    monkeypatch.setattr(queries, "listar_extracciones", lambda **k: [])
    monkeypatch.setattr(queries, "estado_folleto", lambda f: estado)
    return views.pagina_explorador(rf.get(url)).content.decode("utf-8")


def test_explorador_sin_filtro_no_pinta_aviso(monkeypatch):
    html = _explorador(monkeypatch, None, "/datos")
    assert "Folleto no encontrado" not in html and "no tiene precios" not in html


def test_explorador_aviso_no_existe(monkeypatch):
    html = _explorador(monkeypatch, {"folleto": "999999", "estado": "no_existe", "errores_carga": 0})
    assert "Folleto no encontrado" in html and '"999999"' in html
    assert "error(es) de carga" not in html


def test_explorador_aviso_no_existe_con_errores(monkeypatch):
    html = _explorador(monkeypatch, {"folleto": "123456", "estado": "no_existe", "errores_carga": 2})
    assert "Tiene 2 error(es) de carga" in html


def test_explorador_aviso_sin_precios(monkeypatch):
    html = _explorador(monkeypatch, {"folleto": "413679", "estado": "sin_precios", "errores_carga": 0,
                                     "tiendas": ["Soriana"], "fuentes": ["tiendeo"]})
    assert 'el folleto "413679" existe' in html and "no tiene precios" in html
    assert "Folleto no encontrado" not in html


def test_explorador_con_precios_no_pinta_aviso(monkeypatch):
    html = _explorador(monkeypatch, {"folleto": "430658", "estado": "con_precios", "errores_carga": 0})
    assert "Folleto no encontrado" not in html and "no tiene precios" not in html


def test_explorador_escapa_el_id_en_el_aviso(monkeypatch):
    html = _explorador(monkeypatch, {"folleto": "<b>x</b>", "estado": "no_existe", "errores_carga": 0})
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html


# -- Paginas y JS ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista, contenedores", [
    ("pagina_resumen", ["avisoFolleto"]), ("pagina_precios", ["avisoFolleto"]),
    ("pagina_comparativa", ["avisoFolleto"]), ("pagina_historico", ["avisoFolleto"]),
    ("pagina_calidad", ["avisoConfFolleto", "avisoFolleto"]), ("pagina_errores", ["avisoFolleto", "avisoEstado"]),
])
def test_paginas_tienen_contenedores_ocultos(vista, contenedores):
    html = getattr(views, vista)(rf.get("/")).content.decode("utf-8")
    for c in contenedores:
        assert f'<div id="{c}" hidden></div>' in html, c


def test_js_del_aviso_no_usa_innerhtml():
    js = (RAIZ / "dashboard" / "static" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    bloque = js[js.index("function textoAvisoFolleto"):js.index("// Texto corto del filtro activo")]
    assert "innerHTML" not in bloque
    assert "createTextNode(aviso.texto)" in bloque
    assert "if (!folleto) return null;" in bloque  # filtro vacio: ni consulta ni aviso


def test_js_aviso_estado_no_usa_innerhtml():
    html = (RAIZ / "dashboard" / "templates" / "dashboard" / "errores.html").read_text(encoding="utf-8")
    bloque = html[html.index("function pintarAvisoEstado"):html.index('document.getElementById("btnAplicar")')]
    assert "innerHTML" not in bloque and "textContent" in bloque
    assert re.search(r"if \(!ocultos \|\| !ocultos\.n\) return;", bloque)  # sin ocultos no hay aviso
