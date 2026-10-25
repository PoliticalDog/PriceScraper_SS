"""Pestana "Precios" del visor de procedencia (aprobada 17-oct-2026, docs/bi/metricas.md seccion 4).

Sin BD: la conexion queda bloqueada (fixture _sin_bd) y las consultas se reemplazan con monkeypatch. Se verifica el SQL
del ORM (filtro de los registros del dashboard + fila PRODUCTO, una fila por precio, orden de lectura), el armado de
cada renglon, las cajas en % de la API y que la plantilla pinte la pestana solo con textContent. Los conteos por pagina
contra PostgreSQL se validan con consulta.py (64943 -> 17, 64928 -> 17, 66216 -> 7, 69371 -> 0 con 6 sin producto).
"""

import json
import os
import re

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.db.models import QuerySet  # noqa: E402
from django.test import RequestFactory, override_settings  # noqa: E402

from dashboard import origen, queries, views  # noqa: E402


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


def _fila(eid=100, texto="Leche entera 1L", valor=39.9, anterior=None, prod=200, metodo="heuristico",
          prod_texto=None, prod_pagina=7, x=180, y=100, w=360, h=50):
    """Fila plana como la devuelve qs_precios_de_pagina().values()."""
    return {
        "id": eid, "valor": valor, "valor_anterior": anterior, "texto_norm": texto, "texto_raw": "$39.90",
        "categoria_nlp": "alimentos", "confianza_ocr": 0.9, "producto_canonico__nombre_canonico": texto,
        "bbox_x": x, "bbox_y": y, "bbox_ancho": w, "bbox_alto": h, "producto_extraccion_id": prod,
        "producto_extraccion__pagina_id": prod_pagina, "producto_extraccion__texto_raw": prod_texto or texto,
        "producto_extraccion__texto_norm": prod_texto or texto, "producto_extraccion__metodo_norm": metodo,
        "producto_extraccion__confianza_norm": 0.8, "producto_extraccion__bbox_x": 0,
        "producto_extraccion__bbox_y": 0, "producto_extraccion__bbox_ancho": 900, "producto_extraccion__bbox_alto": 500,
    }


# -- ORM ---------------------------------------------------------------------------------------------------

def test_sql_filtra_pares_de_la_pagina_en_orden_de_lectura():
    sql = _espacios(str(queries.qs_precios_de_pagina(64943).query))
    where = sql.split(" WHERE ", 1)[1]
    for cond in ('"extracciones"."pagina_id" = 64943', '"extracciones"."tipo" = PRECIO',
                 '"extracciones"."valor" IS NOT NULL', '"extracciones"."texto_norm" IS NOT NULL',
                 '"extracciones"."producto_extraccion_id" IS NOT NULL'):
        assert cond in where
    # joins N:1 por PK (fila PRODUCTO y catalogo): no duplican filas
    assert 'INNER JOIN "extracciones" T3 ON ("extracciones"."producto_extraccion_id" = T3."id")' in sql
    assert 'LEFT OUTER JOIN "productos_canonicos" ON ("extracciones"."producto_canonico_id" = "productos_canonicos"."id")' in sql
    assert sql.count(" JOIN ") == 2
    assert "GROUP BY" not in sql
    assert sql.endswith("ORDER BY 10 ASC, 9 ASC, 1 ASC")  # bbox_y, bbox_x, id


def test_precios_sin_producto_es_el_resto_de_los_precio(monkeypatch):
    conteos = []
    monkeypatch.setattr(queries, "qs_precios_de_pagina", lambda pid: [_fila()])
    monkeypatch.setattr(QuerySet, "count", lambda self: conteos.append(_espacios(str(self.query))) or 6)
    datos = queries.precios_de_pagina(69371)
    assert len(datos["precios"]) == 1 and datos["precios_sin_producto"] == 5
    # el total cuenta todos los PRECIO de la pagina, sin los filtros de la lista
    assert len(conteos) == 1 and "IS NOT NULL" not in conteos[0] and '"pagina_id" = 69371' in conteos[0]


# -- Armado de renglones -----------------------------------------------------------------------------------

def test_armar_precios_anida_producto_y_no_cambia_el_numero_de_filas():
    filas = [
        _fila(1, "Euccrin", 50.0, prod=11), _fila(2, "Euccrin", 50.0, prod=12),
        _fila(3, "Papel de cocina", 24.5, anterior=30.0, prod=13, metodo="fuzzy", prod_texto="Rollos"),
    ]
    salida = queries.armar_precios_pagina(filas)
    assert [p["id"] for p in salida] == [1, 2, 3]
    assert [p["repetido"] for p in salida] == [True, True, False]
    p = salida[2]
    assert p["descuento_pct"] == 18.3
    assert p["producto"]["id"] == 13 and p["producto"]["texto_norm"] == "Rollos"
    assert p["producto"]["es_catalogo"] is True and salida[0]["producto"]["es_catalogo"] is False
    assert not any(k.startswith("producto_extraccion__") for k in p)


@pytest.mark.parametrize("valor, anterior, esperado", [
    (39.9, 49.9, 20.0), (50.0, None, None), (50.0, 50.0, None), (50.0, 40.0, None), (None, 40.0, None),
])
def test_descuento_igual_que_la_vista(valor, anterior, esperado):
    assert queries._descuento_pct(valor, anterior) == esperado


# -- API ---------------------------------------------------------------------------------------------------

def _ctx(precios, sin_producto=0):
    return {
        "pagina": {
            "id": 7, "numero_pagina": 2, "archivo_imagen": "pagina_002.webp", "folleto_id": 3,
            "folleto__fuente": "tiendeo", "folleto__folleto_id_fuente": "425961", "folleto__tienda__slug": "la_comer",
            "folleto__tienda__nombre": "La Comer", "folleto__titulo": "Ofertas", "folleto__url_origen": None,
            "folleto__fecha_inicio": None, "folleto__fecha_fin": None, "folleto__total_paginas": 45,
        },
        "vecinas": {"anterior": None, "siguiente": None}, "bloques": [], "promos": None,
        "precios": queries.armar_precios_pagina(precios), "precios_sin_producto": sin_producto,
    }


def test_api_pagina_devuelve_precios_con_cajas_en_porcentaje(tmp_path, monkeypatch):
    monkeypatch.setattr(queries, "contexto_pagina", lambda pid: _ctx([_fila(), _fila(101, prod_pagina=8)], 6))
    monkeypatch.setattr(origen, "dimensiones_imagen", lambda ruta: (1800, 1000))
    with override_settings(ORIGEN_PROCESSED_DIR=tmp_path):
        datos = json.loads(views.api_origen_pagina(rf.get("/x"), pagina_id=7).content)
    assert datos["precios_sin_producto"] == 6
    p, otra = datos["precios"]
    assert p["caja_pct"] == {"left": 10.0, "top": 10.0, "width": 20.0, "height": 5.0}
    assert p["producto"]["caja_pct"] == {"left": 0.0, "top": 0.0, "width": 50.0, "height": 50.0}
    assert p["producto"]["otra_pagina"] is False
    # producto en otra pagina: sin caja (no se dibuja sobre esta imagen)
    assert otra["producto"]["otra_pagina"] is True and otra["producto"]["caja_pct"] is None


def test_api_pagina_sin_imagen_procesada_deja_cajas_en_none(tmp_path, monkeypatch):
    monkeypatch.setattr(queries, "contexto_pagina", lambda pid: _ctx([_fila()]))
    monkeypatch.setattr(origen, "dimensiones_imagen", lambda ruta: None)
    with override_settings(ORIGEN_PROCESSED_DIR=tmp_path):
        datos = json.loads(views.api_origen_pagina(rf.get("/x"), pagina_id=7).content)
    assert datos["precios"][0]["caja_pct"] is None and datos["precios"][0]["producto"]["caja_pct"] is None


# -- Plantilla ---------------------------------------------------------------------------------------------

def _html(monkeypatch):
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: _ctx([])["pagina"])
    return views.pagina_origen_pagina(rf.get("/origen/pagina/7"), pagina_id=7).content.decode()


def test_visor_pinta_la_pestana_precios(monkeypatch):
    html = _html(monkeypatch)
    assert 'data-bs-target="#tabPrecios"' in html and 'id="tabPrecios"' in html
    for id_ in ("cuentaPrecios", "btnPrecioAnterior", "btnPrecioSiguiente", "posicionPrecio", "avisoPrecios",
                "tablaPrecios"):
        assert f'id="{id_}"' in html
    assert "precios de esta página no tienen producto asociado y no se listan." in html
    assert 'history.replaceState(null, "", `/origen/extraccion/${encodeURIComponent(id)}`)' in html
    assert "new AbortController()" in html


def test_renglones_solo_con_textcontent(monkeypatch):
    html = _html(monkeypatch)
    inicio = html.index("function celda(")
    fin = html.index("function indicePrecioActual(")
    assert "innerHTML" not in html[inicio:fin]
    assert "textContent" in html[inicio:fin]
