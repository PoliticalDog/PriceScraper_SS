"""Procedencia por registro (visor de pagina, imagen y fragmentos OCR/NLP). Sin BD: la BD queda bloqueada en todo el
modulo (fixture _sin_bd) y las consultas se reemplazan con monkeypatch."""

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.http import Http404  # noqa: E402
from django.test import RequestFactory, override_settings  # noqa: E402
from django.urls import Resolver404, resolve  # noqa: E402

from dashboard import origen, queries, views  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    """Cualquier intento de abrir conexion a la BD falla la prueba."""
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)
    origen._cache.clear()
    yield
    origen._cache.clear()


rf = RequestFactory()


def _pagina(archivo="pagina_002.webp", fuente="tiendeo", tienda="la_comer", folleto="425961", pid=7):
    return {
        "id": pid, "numero_pagina": 2, "archivo_imagen": archivo, "folleto_id": 3, "folleto__fuente": fuente,
        "folleto__folleto_id_fuente": folleto, "folleto__tienda__slug": tienda, "folleto__tienda__nombre": "La Comer",
        "folleto__titulo": "Ofertas", "folleto__url_origen": "https://www.tiendeo.mx/Catalogos/425961",
        "folleto__fecha_inicio": None, "folleto__fecha_fin": None, "folleto__total_paginas": 45,
    }


def _ext(eid=100, pid=7, x=10, y=20, w=30, h=40, tipo="PRECIO", prod=None):
    return {
        "id": eid, "tipo": tipo, "texto_raw": "$27.90", "texto_norm": "leche", "valor": 27.9, "valor_anterior": None,
        "confianza_ocr": 0.9, "bbox_x": x, "bbox_y": y, "bbox_ancho": w, "bbox_alto": h, "pagina_id": pid,
        "producto_extraccion_id": prod, "metodo_norm": None, "producto_canonico__nombre_canonico": None,
    }


# -- Rutas seguras -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("archivo", [
    "../pagina_001.webp", "..\\pagina_001.webp", "a/pagina_001.webp", "a\\pagina_001.webp", "pagina_001.webp/..",
    "pagina_001.exe", "pagina_001.svg", "pagina_001.webp.exe", "pagina_1.webp", "", None, "/etc/passwd",
    "C:\\Windows\\win.ini",
])
def test_rechaza_archivo_imagen_invalido(tmp_path, archivo):
    with pytest.raises(origen.RutaInvalida):
        origen.ruta_imagen(tmp_path, "tiendeo", "la_comer", "425961", archivo)


@pytest.mark.parametrize("fuente,tienda,folleto", [
    ("otra", "la_comer", "425961"),
    ("tiendeo", "..", "425961"),
    ("tiendeo", "a/b", "425961"),
    ("tiendeo", "a\\b", "425961"),
    ("tiendeo", "la_comer", ".."),
    ("tiendeo", "la_comer", "42/61"),
    ("tiendeo", "la_comer", "42\\61"),
    ("tiendeo", "la_comer", "4259.61"),
    ("../tiendeo", "la_comer", "425961"),
])
def test_rechaza_componentes_invalidos(tmp_path, fuente, tienda, folleto):
    with pytest.raises(origen.RutaInvalida):
        origen.ruta_imagen(tmp_path, fuente, tienda, folleto, "pagina_001.webp")
    with pytest.raises(origen.RutaInvalida):
        origen.ruta_json(tmp_path, fuente, tienda, folleto, "ocr")


def test_ruta_valida_queda_dentro_de_la_base(tmp_path):
    r = origen.ruta_imagen(tmp_path, "tiendeo", "sam's_club", "425961", "pagina_001.webp")
    assert r.is_relative_to(tmp_path.resolve())
    assert r.parts[-4:] == ("tiendeo", "sam's_club", "425961", "pagina_001.webp")
    j = origen.ruta_json(tmp_path, "ofertomat", "7_eleven", "136018", "nlp")
    assert j.name == "nlp_resultado.json" and j.is_relative_to(tmp_path.resolve())


def test_dentro_de_rechaza_ruta_fuera_de_la_base(tmp_path):
    with pytest.raises(origen.RutaInvalida):
        origen._dentro_de(tmp_path / "base", tmp_path / "base" / ".." / "otro" / "x.webp")


def test_json_solo_nombres_fijos(tmp_path):
    with pytest.raises(origen.RutaInvalida):
        origen.ruta_json(tmp_path, "tiendeo", "la_comer", "425961", "../../settings")


# -- Fragmento de pagina del JSON ------------------------------------------------------------------------------

def _escribir_json(ruta: Path, datos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


def test_fragmento_encuentra_la_pagina_correcta(tmp_path):
    ruta = _escribir_json(tmp_path / "ocr_resultado.json", {"paginas": [
        {"pagina": "pagina_001.webp", "bloques": [1]},
        {"pagina": "pagina_002.webp", "bloques": [2]},
        {"pagina": "pagina_003.webp", "bloques": [3]},
    ]})
    frag = origen.fragmento_pagina(ruta, "pagina_002.webp")
    assert frag == {"estado": "ok", "pagina": {"pagina": "pagina_002.webp", "bloques": [2]}}


def test_fragmento_archivo_ausente_corrupto_o_sin_pagina(tmp_path):
    assert origen.fragmento_pagina(tmp_path / "no_existe.json", "pagina_001.webp")["estado"] == "ausente"
    corrupto = tmp_path / "corrupto.json"
    corrupto.write_text("{no es json", encoding="utf-8")
    assert origen.fragmento_pagina(corrupto, "pagina_001.webp")["estado"] == "corrupto"
    lista = _escribir_json(tmp_path / "lista.json", [1, 2])
    assert origen.fragmento_pagina(lista, "pagina_001.webp")["estado"] == "corrupto"
    sin_paginas = _escribir_json(tmp_path / "sin.json", {"paginas": "x"})
    assert origen.fragmento_pagina(sin_paginas, "pagina_001.webp")["estado"] == "corrupto"
    otra = _escribir_json(tmp_path / "otra.json", {"paginas": [{"pagina": "pagina_009.webp"}]})
    assert origen.fragmento_pagina(otra, "pagina_001.webp")["estado"] == "sin_pagina"


def test_fragmento_respeta_limite_de_tamano(tmp_path, monkeypatch):
    ruta = _escribir_json(tmp_path / "grande.json", {"paginas": [{"pagina": "pagina_001.webp", "x": "a" * 500}]})
    monkeypatch.setattr(origen, "MAX_BYTES_JSON", 100)
    assert origen.fragmento_pagina(ruta, "pagina_001.webp")["estado"] == "muy_grande"


def test_cache_se_invalida_si_cambia_el_archivo(tmp_path):
    ruta = _escribir_json(tmp_path / "ocr_resultado.json", {"paginas": [{"pagina": "pagina_001.webp", "v": 1}]})
    assert origen.fragmento_pagina(ruta, "pagina_001.webp")["pagina"]["v"] == 1
    _escribir_json(ruta, {"paginas": [{"pagina": "pagina_001.webp", "v": 22}]})
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert origen.fragmento_pagina(ruta, "pagina_001.webp")["pagina"]["v"] == 22


# -- Cajas ----------------------------------------------------------------------------------------------------

def test_caja_a_porcentajes():
    assert origen.caja_pct({"bbox_x": 180, "bbox_y": 100, "bbox_ancho": 360, "bbox_alto": 50}, 1800, 1000) == {
        "left": 10.0, "top": 10.0, "width": 20.0, "height": 5.0}
    assert origen.caja_pct({"x": 900, "y": 0, "ancho": 900, "alto": 500}, 1800, 1000) == {
        "left": 50.0, "top": 0.0, "width": 50.0, "height": 50.0}


def test_caja_se_recorta_a_la_imagen_y_descarta_invalidas():
    assert origen.caja_pct({"x": 1700, "y": 900, "ancho": 200, "alto": 200}, 1800, 1000) == {
        "left": 94.444, "top": 90.0, "width": 5.556, "height": 10.0}
    assert origen.caja_pct({"x": 10, "y": 10, "ancho": 0, "alto": 5}, 1800, 1000) is None
    assert origen.caja_pct({"x": 10, "y": 10}, 1800, 1000) is None
    assert origen.caja_pct({"x": 10, "y": 10, "ancho": 5, "alto": 5}, None, 1000) is None
    assert origen.caja_pct({"x": 2000, "y": 10, "ancho": 5, "alto": 5}, 1800, 1000) is None
    assert origen.caja_pct({"bbox_x": None, "bbox_y": 1, "bbox_ancho": 1, "bbox_alto": 1}, 10, 10) is None


def test_marcar_bloques_por_caja_exacta_y_por_superposicion():
    pagina = {"pagina": "pagina_001.webp", "bloques": [
        {"texto": "otro", "bbox": {"x": 0, "y": 0, "ancho": 10, "alto": 10}},
        {"texto": "$27.90", "bbox": {"x": 100, "y": 100, "ancho": 50, "alto": 20}},
        {"texto": "LECHE", "bbox": {"x": 300, "y": 50, "ancho": 80, "alto": 20}},
        {"texto": "LALA 1L", "bbox": {"x": 300, "y": 72, "ancho": 80, "alto": 20}},
    ]}
    cajas = {
        "precio": {"bbox_x": 100, "bbox_y": 100, "bbox_ancho": 50, "bbox_alto": 20},
        "producto": {"bbox_x": 295, "bbox_y": 48, "bbox_ancho": 90, "bbox_alto": 46},  # union de dos bloques
    }
    assert origen.marcar_bloques(pagina, cajas) == {"bloques": {"precio": [1], "producto": [2, 3]}}
    assert origen.marcar_bloques(pagina, {"precio": {"bbox_x": 900, "bbox_y": 900, "bbox_ancho": 5,
                                                     "bbox_alto": 5}}) == {}


# -- Combinacion por id ----------------------------------------------------------------------------------------

def test_combinar_procedencia_no_duplica_ni_pierde_filas():
    filas = [{"id": 3, "precio": 1}, {"id": 1, "precio": 2}, {"id": 3, "precio": 3}, {"id": 99, "precio": 4}]
    proc = {
        1: {"pagina_id": 10, "numero_pagina": 1, "folleto_id": 5, "folleto_id_fuente": "A", "folleto_titulo": "t",
            "url_origen": None},
        3: {"pagina_id": 30, "numero_pagina": 3, "folleto_id": 5, "folleto_id_fuente": "A", "folleto_titulo": "t",
            "url_origen": "https://x"},
    }
    salida = origen.combinar_procedencia(filas, proc)
    assert len(salida) == 4
    assert [f["precio"] for f in salida] == [1, 2, 3, 4]
    assert [f["pagina_id"] for f in salida] == [30, 10, 30, None]
    assert salida[3]["folleto_id_fuente"] is None


def test_agregar_procedencia_consulta_ids_unicos(monkeypatch):
    vistos = []

    def falso(ids):
        vistos.append(list(ids))
        return {7: {"pagina_id": 1, "numero_pagina": 2}}

    monkeypatch.setattr(queries, "procedencia_por_ids", falso)
    filas = queries.agregar_procedencia([{"id": 7}, {"id": 8}, {"id": 7}])
    assert len(filas) == 3 and [f["numero_pagina"] for f in filas] == [2, None, 2]
    assert sorted(set(vistos[0])) == [7, 8]


def test_url_origen_segura():
    assert origen.url_origen_segura("https://www.tiendeo.mx/Catalogos/1") == "https://www.tiendeo.mx/Catalogos/1"
    assert origen.url_origen_segura("javascript:alert(1)") is None
    assert origen.url_origen_segura("") is None and origen.url_origen_segura(None) is None


# -- Vistas: metodo, 404, imagen y JSON ----------------------------------------------------------------------

VISTAS_GET = [
    (views.pagina_origen_extraccion, {"extraccion_id": 1}),
    (views.pagina_origen_pagina, {"pagina_id": 1}),
    (views.imagen_pagina, {"pagina_id": 1}),
    (views.api_origen_pagina, {"pagina_id": 1}),
    (views.api_origen_extraccion, {"extraccion_id": 1}),
    (views.api_origen_json, {"pagina_id": 1, "tipo": "ocr"}),
]


@pytest.mark.parametrize("vista,kwargs", VISTAS_GET)
@pytest.mark.parametrize("metodo", ["post", "put", "delete"])
def test_solo_get(vista, kwargs, metodo):
    resp = vista(getattr(rf, metodo)("/x"), **kwargs)
    assert resp.status_code == 405


@pytest.mark.parametrize("vista,kwargs", VISTAS_GET)
def test_id_inexistente_da_404(monkeypatch, vista, kwargs):
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: None)
    monkeypatch.setattr(queries, "contexto_pagina", lambda pid: None)
    monkeypatch.setattr(queries, "origen_extraccion", lambda eid: None)
    with pytest.raises(Http404):
        vista(rf.get("/x"), **kwargs)


def test_urls_solo_aceptan_ids_enteros():
    assert resolve("/origen/pagina/12.webp").func is views.imagen_pagina
    assert resolve("/origen/pagina/12").func is views.pagina_origen_pagina
    assert resolve("/origen/extraccion/5").func is views.pagina_origen_extraccion
    assert resolve("/api/origen/pagina/12/nlp").func is views.api_origen_json
    for url in ("/origen/pagina/..%2F..%2Fsettings.webp", "/origen/pagina/abc.webp", "/origen/pagina/-1.webp",
                "/origen/extraccion/1.5"):
        with pytest.raises(Resolver404):
            resolve(url)


def _base_con_imagen(tmp_path, version_dir="processed"):
    base = tmp_path / version_dir
    img = base / "tiendeo" / "la_comer" / "425961" / "pagina_002.webp"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
    return base, img


def test_imagen_se_sirve_inline_con_cabeceras_seguras(tmp_path, monkeypatch):
    base, img = _base_con_imagen(tmp_path)
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: _pagina())
    with override_settings(ORIGEN_PROCESSED_DIR=base, ORIGEN_RAW_DIR=tmp_path / "raw"):
        resp = views.imagen_pagina(rf.get("/origen/pagina/7.webp"), pagina_id=7)
        try:
            assert resp.status_code == 200
            assert resp["Content-Type"] == "image/webp"
            assert resp["X-Content-Type-Options"] == "nosniff"
            assert resp["Content-Disposition"].startswith("inline")
            assert resp["Cache-Control"] == "private, max-age=3600"
            assert b"".join(resp.streaming_content) == img.read_bytes()
        finally:
            resp.close()
        # version raw: no existe en la base raw -> 404; version desconocida -> 404
        with pytest.raises(Http404):
            views.imagen_pagina(rf.get("/x", {"version": "raw"}), pagina_id=7)
        with pytest.raises(Http404):
            views.imagen_pagina(rf.get("/x", {"version": "../../"}), pagina_id=7)


@pytest.mark.parametrize("pagina", [
    _pagina(archivo="../../../settings.webp"),
    _pagina(archivo="pagina_002.py"),
    _pagina(folleto="../425961"),
    _pagina(fuente="local"),
])
def test_imagen_con_datos_de_bd_invalidos_da_404(tmp_path, monkeypatch, pagina):
    base, _ = _base_con_imagen(tmp_path)
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: pagina)
    with override_settings(ORIGEN_PROCESSED_DIR=base, ORIGEN_RAW_DIR=base):
        with pytest.raises(Http404):
            views.imagen_pagina(rf.get("/x"), pagina_id=7)


def test_api_json_devuelve_solo_el_fragmento_y_marcas(tmp_path, monkeypatch):
    base = tmp_path / "processed"
    _escribir_json(base / "tiendeo" / "la_comer" / "425961" / "ocr_resultado.json", {"fuente": "tiendeo", "paginas": [
        {"pagina": "pagina_001.webp", "bloques": [{"texto": "no", "bbox": {"x": 10, "y": 20, "ancho": 30, "alto": 40}}]},
        {"pagina": "pagina_002.webp", "bloques": [
            {"texto": "x", "bbox": {"x": 0, "y": 0, "ancho": 5, "alto": 5}},
            {"texto": "$27.90", "bbox": {"x": 10, "y": 20, "ancho": 30, "alto": 40}},
        ]},
    ]})
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: _pagina())
    monkeypatch.setattr(queries, "origen_extraccion", lambda eid: {"extraccion": _ext(), "producto": None})
    with override_settings(ORIGEN_PROCESSED_DIR=base):
        resp = views.api_origen_json(rf.get("/x", {"e": "100"}), pagina_id=7, tipo="ocr")
        datos = json.loads(resp.content)
        assert datos["estado"] == "ok" and datos["archivo"] == "ocr_resultado.json"
        assert datos["pagina"]["pagina"] == "pagina_002.webp"
        assert "fuente" not in datos["pagina"]  # no devuelve el archivo completo
        assert datos["marcas"] == {"bloques": {"precio": [1]}}
        # NLP ausente: estado, no error
        datos_nlp = json.loads(views.api_origen_json(rf.get("/x"), pagina_id=7, tipo="nlp").content)
        assert datos_nlp["estado"] == "ausente"
        with pytest.raises(Http404):
            views.api_origen_json(rf.get("/x"), pagina_id=7, tipo="settings")


def test_visor_renderiza_con_ids_en_json_script(monkeypatch):
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: _pagina())
    monkeypatch.setattr(queries, "origen_extraccion", lambda eid: {"extraccion": _ext(pid=7), "producto": None})
    html = views.pagina_origen_extraccion(rf.get("/origen/extraccion/100"), extraccion_id=100).content.decode()
    assert 'id="datoPaginaId" type="application/json">7<' in html
    assert 'id="datoExtraccionId" type="application/json">100<' in html
    html = views.pagina_origen_pagina(rf.get("/origen/pagina/7"), pagina_id=7).content.decode()
    assert 'id="datoExtraccionId" type="application/json">null<' in html


def test_api_extraccion_cajas_en_porcentaje(tmp_path, monkeypatch):
    monkeypatch.setattr(queries, "origen_extraccion", lambda eid: {
        "extraccion": _ext(x=180, y=100, w=360, h=50, prod=101),
        "producto": _ext(eid=101, tipo="PRODUCTO", x=0, y=0, w=900, h=500),
    })
    monkeypatch.setattr(queries, "pagina_origen", lambda pid: _pagina())
    monkeypatch.setattr(origen, "dimensiones_imagen", lambda ruta: (1800, 1000))
    with override_settings(ORIGEN_PROCESSED_DIR=tmp_path):
        datos = json.loads(views.api_origen_extraccion(rf.get("/x"), extraccion_id=100).content)
    assert datos["extraccion"]["caja_pct"] == {"left": 10.0, "top": 10.0, "width": 20.0, "height": 5.0}
    assert datos["producto"]["caja_pct"] == {"left": 0.0, "top": 0.0, "width": 50.0, "height": 50.0}
    assert datos["producto"]["otra_pagina"] is False


@pytest.mark.parametrize("tienda,folleto,archivo", [
    ("casa_ley\n", "425961", "pagina_001.webp"),
    ("casa_ley", "425961\n", "pagina_001.webp"),
    ("casa_ley", "425961", "pagina_001.webp\n"),
])
def test_salto_de_linea_al_final_se_rechaza(tmp_path, tienda, folleto, archivo):
    # QA (13-oct-2026): con re.match y "$" un "\n" final pasaba la validacion; ahora es fullmatch
    with pytest.raises(origen.RutaInvalida):
        origen.ruta_imagen(tmp_path, "tiendeo", tienda, folleto, archivo)


@pytest.mark.parametrize("url", ["https://x\njavascript:alert(1)", "https://x y", "https://"])
def test_url_origen_con_espacios_o_saltos_se_descarta(url):
    assert origen.url_origen_segura(url) is None
