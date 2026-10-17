"""Promociones por niveles, Fase 1 (aprobada 15-oct-2026, docs/bi/metricas.md seccion 7).

Sin BD: la conexion queda bloqueada; las consultas se sustituyen por dobles. Se verifica el mapa provisional de
nombres de evento a slugs canonicos (con los nombres reales de la BD al 15-oct-2026 y con los slugs que producira el
pipeline), que el espejo SQL use las mismas reglas, que las etiquetas no agreguen ni quiten filas, los filtros
(EXISTS, sin joins en la consulta externa), la pagina Promociones (grano y KPIs) y la UI.
Los conteos reales se validan con docs/bi/consultas/promociones_validacion.sql.
"""

import json
import os
import re
from pathlib import Path

import pytest

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
import django  # noqa: E402

django.setup()

from django.test import RequestFactory  # noqa: E402

from dashboard import promociones as p, queries, views  # noqa: E402
from dashboard.models import Extraccion, VComparativaPrecios, VPreciosActuales  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
CONSULTAS = RAIZ / "docs" / "bi" / "consultas"
rf = RequestFactory()


@pytest.fixture(autouse=True)
def _sin_bd(monkeypatch):
    from django.db.backends.base.base import BaseDatabaseWrapper

    def _prohibido(self, *a, **k):
        raise AssertionError("estas pruebas no deben tocar la BD")

    monkeypatch.setattr(BaseDatabaseWrapper, "ensure_connection", _prohibido)


# -- Mapa de nombres de evento -----------------------------------------------------------------------------

# Nombres reales de eventos_promo al 15-oct-2026 (prefijos de hasta 40 caracteres) -> (clase, slug)
NOMBRES_REALES = [
    ("julioregalado", "campania", "julio_regalado"), ("julio_regalado", "campania", "julio_regalado"),
    ("julioregaladods", "campania", "julio_regalado"), ("julioregaladoe", "campania", "julio_regalado"),
    ("este_hot_sale_obtn_con", "campania", "hot_sale"), ("liquidacion_deropa", "campania", "liquidacion"),
    ("en_navidad", "campania", "navidad"), ("navidad", "campania", "navidad"), ("n_navidad", "campania", "navidad"),
    ("back_to_school", "campania", "regreso_a_clases"), ("regreso_a_clases", "campania", "regreso_a_clases"),
    ("el_regreso_a_clases_empieza_con_el", "campania", "regreso_a_clases"),
    ("en_regreso_a_clases", "campania", "regreso_a_clases"), ("para_el_regreso_a_clases", "campania", "regreso_a_clases"),
    ("excepto_cdigos_de_liquidacin", "legal", None), ("excepto_cdigos_en_liquidacin", "legal", None),
    ("excepto_codigos_de_liquidacin", "legal", None), ("en_todas_nuestras_sucursales_para_manten", "legal", None),
    ("lasitendas_participantes_no_apllcan_dcvo", "legal", None),
    ("precios_bajos_todos_los_das_nos_reservam", "lema", None), ("nuestros_precios_bajos_todos_los_das_nos", "lema", None),
    ("calidad_a_precios_bajos_todos_los_das", "lema", None), ("de_los_precios_bajos", "lema", None),
    ("delos_precios_bajos", "lema", None), ("de_ios_precios_bajos", "lema", None),
    ("la_supercampeona_de_los_precios_bajos", "lema", None), ("lasupercampeona_de_los_precios_bajos", "lema", None),
    ("lasupercampcana_de_los_precios_bajos", "lema", None), ("precio_especial", "lema", None),
    ("precio_especial_de", "lema", None), ("precios_bajos", "lema", None), ("precios_bajos_todo_el_ao", "lema", None),
    ("precios_bajos_todo_elao", "lema", None), ("precios_bajos_todos", "lema", None),
    ("precios_bajos_tcdos_ics_dlas", "lema", None), ("precios_bajos_todcs_ios_dias", "lema", None),
    ("precios_bajos_todos_los_das_para", "lema", None), ("super_oferta", "lema", None),
    ("back_to_school_hojas", "producto", None), ("bao_navidad", "producto", None),
    ("diferentes_halloween_da_de_muertos_navid", "producto", None), ("figura_navidad_c_ml", "producto", None),
    ("navidad_ao_nuevo_cumpleaos", "producto", None), ("vela_aromtica_navidad_santa", "producto", None),
]


@pytest.mark.parametrize("nombre, clase, slug", NOMBRES_REALES)
def test_mapa_nombres_reales(nombre, clase, slug):
    assert p.clasificar_evento(nombre) == (clase, slug)


@pytest.mark.parametrize("slug", list(p.CAMPANIAS))
def test_slugs_canonicos_del_pipeline_se_aceptan_tal_cual(slug):
    assert p.clasificar_evento(slug) == ("campania", slug)
    assert p.clasificar_evento(f"  {slug.upper()} ") == ("campania", slug)


def test_slugs_acordados_con_el_pipeline():
    assert list(p.CAMPANIAS) == [
        "julio_regalado", "hot_sale", "buen_fin", "regreso_a_clases", "navidad", "halloween_dia_de_muertos",
        "liquidacion", "aniversario", "ofertones", "fiestas_patrias",
    ]
    assert p.CAMPANIAS["julio_regalado"] == "Julio Regalado"


@pytest.mark.parametrize("nombre, slug", [
    ("aniversario_72", "aniversario"), ("ofertn", "ofertones"), ("los_ofertones", "ofertones"),
    ("buen_fin_2026", "buen_fin"), ("dia_de_muertos", "halloween_dia_de_muertos"), ("hotsale", "hot_sale"),
])
def test_variantes_futuras(nombre, slug):
    assert p.clasificar_evento(nombre) == ("campania", slug)


@pytest.mark.parametrize("nombre", [None, "", "  "])
def test_vacio_es_otro(nombre):
    assert p.clasificar_evento(nombre) == ("otro", None)


@pytest.mark.parametrize("archivo", ["promociones_campanias.sql", "promociones_validacion.sql"])
def test_espejo_sql_usa_las_mismas_reglas(archivo):
    sql = (CONSULTAS / archivo).read_text(encoding="utf-8")
    for patron in (p.REGLA_PRODUCTO, p.REGLA_LEGAL, *[r for _, r in p.REGLAS_CAMPANIA]):
        assert f"'{patron}'" in sql, patron
    for slug in p.CAMPANIAS:
        assert f"'{slug}'" in sql, slug
    if archivo == "promociones_campanias.sql":
        assert f"'{p.REGLA_LEMA}'" in sql


# -- Etiquetas por registro --------------------------------------------------------------------------------

def test_campanias_por_folleto_solo_campanias_sin_repetir_y_en_orden():
    eventos = [
        {"folleto_id": 1, "nombre_evento": "julioregalado"},
        {"folleto_id": 1, "nombre_evento": "julio_regalado"},       # mismo slug: una vez
        {"folleto_id": 1, "nombre_evento": "precios_bajos"},        # lema: fuera
        {"folleto_id": 1, "nombre_evento": "este_hot_sale_obtn_con"},
        {"folleto_id": 2, "nombre_evento": "excepto_cdigos_de_liquidacin"},  # legal: fuera
    ]
    r = p.campanias_por_folleto(eventos)
    assert r == {1: [{"slug": "julio_regalado", "nombre": "Julio Regalado"}, {"slug": "hot_sale", "nombre": "Hot Sale"}]}


def test_combinar_promos_no_agrega_ni_quita_filas():
    filas = [{"id": 1, "folleto_id": 10}, {"id": 2, "folleto_id": 11}, {"id": 3, "folleto_id": 10}, {"id": 4}]
    camp = {10: [{"slug": "navidad", "nombre": "Navidad"}]}
    salida = p.combinar_promos(filas, camp)
    assert [f["id"] for f in salida] == [1, 2, 3, 4]
    assert salida[0]["promos"] == {"campania": [{"slug": "navidad", "nombre": "Navidad"}], "producto": [], "bancaria": []}
    assert salida[1]["promos"]["campania"] == [] and salida[3]["promos"]["campania"] == []
    salida[0]["promos"]["campania"].append("x")
    assert salida[2]["promos"]["campania"] == [{"slug": "navidad", "nombre": "Navidad"}]  # listas independientes


def test_agregar_promos_consulta_una_vez_por_lote(monkeypatch):
    pedidos = []
    monkeypatch.setattr(queries, "campanias_de_folletos", lambda ids: pedidos.append(sorted(set(ids))) or {})
    filas = queries.agregar_promos([{"folleto_id": 3}, {"folleto_id": 3}, {"folleto_id": 5}])
    assert pedidos == [[3, 5]] and len(filas) == 3


def test_campanias_de_folletos_vacio_no_consulta():
    assert queries.campanias_de_folletos([None, None]) == {}


# -- Parametros --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("valor, esperado", [("con", "con"), (" SIN ", "sin"), ("", None), (None, None), ("x", None)])
def test_normalizar_promocion(valor, esperado):
    assert p.normalizar_promocion(valor) == esperado


@pytest.mark.parametrize("valor, esperado", [("campania", "campania"), ("producto", "producto"), ("x", None), (None, None)])
def test_normalizar_nivel(valor, esperado):
    assert p.normalizar_nivel(valor) == esperado


def test_normalizar_campanias():
    assert p.normalizar_campanias(["navidad", "x", " JULIO_REGALADO ", "navidad"]) == ["julio_regalado", "navidad"]
    assert p.normalizar_campanias(None) == []


# -- Filtros (EXISTS) --------------------------------------------------------------------------------------

def _where(qs):
    sql = re.sub(r"\s+", " ", str(qs.query))
    return sql


def test_sin_filtro_no_toca_el_queryset():
    qs = VPreciosActuales.objects.all()
    assert queries.filtrar_promocion(qs) is qs
    assert queries.filtrar_promocion(qs, nivel="campania") is qs  # nivel solo no filtra


@pytest.mark.parametrize("promocion, negado", [("con", False), ("sin", True)])
def test_vista_usa_exists_por_llave_natural(monkeypatch, promocion, negado):
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: [7, 8])
    sql = _where(queries.filtrar_promocion(VPreciosActuales.objects.all(), promocion))
    externa = sql.split("EXISTS", 1)[0]
    assert " JOIN " not in externa
    assert ("NOT EXISTS" in sql) is negado
    assert '= ("v_precios_actuales"."fuente")' in sql
    assert '= ("v_precios_actuales"."folleto_id_fuente")' in sql
    assert re.search(r'"id" IN \(7, 8\)', sql)


def test_extraccion_usa_folleto_id(monkeypatch):
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: [7])
    sql = _where(queries.filtrar_promocion(Extraccion.objects.all(), "con", modo="extraccion"))
    assert '"folleto_id" = ("extracciones"."folleto_id")' in sql
    assert " JOIN " not in sql.split("EXISTS", 1)[0]


def test_comparativa_exists_anidado_sin_join_externo(monkeypatch):
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: [7])
    sql = _where(queries.filtrar_promocion(VComparativaPrecios.objects.all(), "con", modo="comparativa"))
    assert sql.count("EXISTS") == 2
    assert " JOIN " not in sql.split("EXISTS", 1)[0]
    assert '"texto_norm" = ("v_comparativa_precios"."producto")' in sql


def test_campania_sola_equivale_a_con(monkeypatch):
    recibido = []
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: recibido.append((nivel, camp)) or [1])
    sql = _where(queries.filtrar_promocion(VPreciosActuales.objects.all(), campanias=["navidad", "inventada"]))
    assert recibido == [(None, ["navidad"])]
    assert "EXISTS" in sql and "NOT EXISTS" not in sql


def test_sin_eventos_que_cumplan(monkeypatch):
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: [])
    qs = VPreciosActuales.objects.all()
    assert queries.filtrar_promocion(qs, "con").query.is_empty()  # "con" sin eventos -> vacio (qs.none())
    assert queries.filtrar_promocion(qs, "sin") is qs


@pytest.mark.parametrize("nivel", ["producto", "bancaria"])
def test_niveles_sin_datos_no_consultan_y_dan_vacio(nivel):
    assert queries._ids_eventos_promocion(nivel, []) == []  # _sin_bd fallaria si consultara


def test_modo_desconocido(monkeypatch):
    monkeypatch.setattr(queries, "_ids_eventos_promocion", lambda nivel, camp: [1])
    with pytest.raises(ValueError):
        queries.filtrar_promocion(VPreciosActuales.objects.all(), "con", modo="otro")


# -- Pagina Promociones ------------------------------------------------------------------------------------

class _Cadena:
    """Doble de queryset: filter/all devuelven el mismo objeto; values/values_list devuelven los datos."""

    def __init__(self, filas=(), conteos=()):
        self.filas, self.conteos, self.filtros = list(filas), list(conteos), []

    def all(self):
        return self

    def filter(self, *a, **k):
        self.filtros.append(k)
        return self

    def values(self, *a):
        return self.filas

    def values_list(self, *a):
        return self

    def annotate(self, **k):
        return self.conteos


class _Modelo:
    def __init__(self, cadena):
        self.objects = cadena


EVENTOS = [
    {"id": 1, "folleto_id": 10, "nombre_evento": "julioregalado", "texto_raw": "JULIOREGALADO"},
    {"id": 2, "folleto_id": 10, "nombre_evento": "julio_regalado", "texto_raw": "JULIO REGALADO"},
    {"id": 3, "folleto_id": 10, "nombre_evento": "este_hot_sale_obtn_con", "texto_raw": "Este Hot Sale"},
    {"id": 4, "folleto_id": 11, "nombre_evento": "navidad", "texto_raw": "Navidad"},
    {"id": 5, "folleto_id": 12, "nombre_evento": "precios_bajos", "texto_raw": "precios bajos"},
]
FOLLETOS = [
    {"id": 10, "tienda": "Soriana Híper", "fuente": "tiendeo", "folleto_id_fuente": "100", "titulo": "t",
     "fecha_inicio": None, "fecha_fin": None, "anomalia_fecha": None, "vigente": True, "vigente_dudoso": False,
     "proximo": False},
    {"id": 11, "tienda": "Waldos", "fuente": "tiendeo", "folleto_id_fuente": "110", "titulo": None,
     "fecha_inicio": None, "fecha_fin": None, "anomalia_fecha": None, "vigente": False, "vigente_dudoso": False,
     "proximo": False},
    {"id": 12, "tienda": "Walmart", "fuente": "tiendeo", "folleto_id_fuente": "120", "titulo": None,
     "fecha_inicio": None, "fecha_fin": None, "anomalia_fecha": None, "vigente": False, "vigente_dudoso": False,
     "proximo": True},
]


def _pagina(monkeypatch, conteos=((10, 50), (11, 7), (12, 3))):
    precios = _Cadena(conteos=list(conteos))
    monkeypatch.setattr(queries, "EventoPromo", _Modelo(_Cadena(EVENTOS)))
    monkeypatch.setattr(queries, "VFolletosVigencia", _Modelo(_Cadena(FOLLETOS)))
    monkeypatch.setattr(queries, "Extraccion", _Modelo(precios))
    monkeypatch.setattr(queries, "_primeras_paginas", lambda ids: {i: i * 100 for i in ids})
    return precios


def test_pagina_grano_folleto_campania_y_kpis_por_folleto(monkeypatch):
    _pagina(monkeypatch)
    r = queries.promociones_por_folleto()
    claves = [(f["folleto_id_fuente"], f["campania"]) for f in r["filas"]]
    assert sorted(claves) == [("100", "hot_sale"), ("100", "julio_regalado"), ("110", "navidad")]
    jr = next(f for f in r["filas"] if f["campania"] == "julio_regalado")
    assert jr["eventos"] == 2 and jr["textos_detectados"] == ["JULIO REGALADO", "JULIOREGALADO"]
    assert jr["nombre"] == "Julio Regalado" and jr["precios_en_folleto"] == 50 and jr["primera_pagina_id"] == 1000
    # el folleto 100 tiene 2 campanias pero sus 50 precios se suman una vez
    assert r["kpis"] == {"filas": 3, "folletos": 2, "campanias": 3, "tiendas": 2, "precios_en_folletos": 57,
                         "vigentes": 1}


def test_pagina_clase_lema_y_todas(monkeypatch):
    _pagina(monkeypatch)
    lemas = queries.promociones_por_folleto(clase="lema")["filas"]
    assert [(f["folleto_id_fuente"], f["nombre"], f["campania"]) for f in lemas] == [("120", "precios_bajos", None)]
    assert queries.promociones_por_folleto(clase="todas")["kpis"]["filas"] == 4
    assert queries.promociones_por_folleto(clase="inventada")["kpis"]["filas"] == 3  # invalido -> campania


def test_pagina_filtros(monkeypatch):
    _pagina(monkeypatch)
    assert queries.promociones_por_folleto(tiendas=["Waldos"])["kpis"]["filas"] == 1
    assert queries.promociones_por_folleto(campanias=["hot_sale"])["kpis"]["filas"] == 1
    assert queries.promociones_por_folleto(vigencia="vigente")["kpis"]["folletos"] == 1
    assert queries.promociones_por_folleto(vigencia="fuera")["filas"][0]["folleto_id_fuente"] == "110"


def test_pagina_categoria_cuenta_solo_esas_y_oculta_ceros(monkeypatch):
    precios = _pagina(monkeypatch, conteos=((10, 4),))
    r = queries.promociones_por_folleto(categorias=["alimentos"])
    assert {"categoria_nlp__in": ["alimentos"]} in precios.filtros
    assert {f["folleto_id_fuente"] for f in r["filas"]} == {"100"}


# -- Vistas (API) ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista, funcion, url", [
    ("api_precios", "precios_actuales", "/api/precios"),
    ("api_comparativa", "comparativa_precios", "/api/comparativa"),
    ("api_historico", "historico_precios", "/api/historico?producto=leche"),
])
def test_api_pasa_filtros_de_promocion(monkeypatch, vista, funcion, url):
    recibido = {}
    monkeypatch.setattr(queries, funcion, lambda *a, **k: recibido.update(k) or [])
    sep = "&" if "?" in url else "?"
    getattr(views, vista)(rf.get(f"{url}{sep}promocion=con&nivel=campania&campania=navidad&campania=hot_sale"))
    assert recibido["promocion"] == "con" and recibido["nivel"] == "campania"
    assert recibido["campanias"] == ["navidad", "hot_sale"]


def test_api_sin_filtros_de_promocion(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "precios_actuales", lambda **k: recibido.update(k) or [])
    views.api_precios(rf.get("/api/precios"))
    assert recibido["promocion"] is None and recibido["nivel"] is None and recibido["campanias"] is None


def test_api_promociones(monkeypatch):
    recibido = {}
    monkeypatch.setattr(queries, "promociones_por_folleto", lambda **k: recibido.update(k) or {"kpis": {}, "filas": []})
    views.api_promociones(rf.get("/api/promociones?tienda=Waldos&folleto=%20110%20&campania=navidad&vigencia=vigente"
                                 "&clase=lema&categoria=alimentos"))
    assert recibido == {"tiendas": ["Waldos"], "folleto": "110", "campanias": ["navidad"], "vigencia": "vigente",
                        "clase": "lema", "categorias": ["alimentos"]}


def test_api_filtros_promociones():
    d = json.loads(views.api_filtros_promociones(rf.get("/")).content)
    assert [c["slug"] for c in d["campanias"]] == list(p.CAMPANIAS)
    assert {n["nivel"]: n["con_datos"] for n in d["niveles"]} == {"campania": True, "producto": False, "bancaria": False}
    assert [v["vigencia"] for v in d["vigencias"]] == list(queries.VIGENCIAS)


def test_api_eventos_ya_no_existe():
    assert not hasattr(views, "api_eventos")
    assert not hasattr(queries, "eventos_promo")


def test_visor_origen_incluye_promos(monkeypatch):
    pag = {"id": 7, "numero_pagina": 1, "archivo_imagen": "pagina_001.webp", "folleto_id": 3,
           "folleto__fuente": "tiendeo", "folleto__folleto_id_fuente": "1", "folleto__tienda__slug": "waldos",
           "folleto__tienda__nombre": "Waldos", "folleto__titulo": None, "folleto__url_origen": None,
           "folleto__fecha_inicio": None, "folleto__fecha_fin": None, "folleto__total_paginas": 1}
    promos = {"campania": [{"slug": "navidad", "nombre": "Navidad"}], "producto": [], "bancaria": []}
    monkeypatch.setattr(queries, "contexto_pagina", lambda i: {"pagina": pag, "vecinas": {}, "bloques": [], "promos": promos})
    monkeypatch.setattr(views, "_dimensiones_proc", lambda pag: None)
    d = json.loads(views.api_origen_pagina(rf.get("/"), 7).content)
    assert d["pagina"]["promos"] == promos


# -- Paginas y JS ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("vista", ["pagina_precios", "pagina_comparativa", "pagina_historico"])
def test_paginas_pintan_filtros_de_promocion(vista):
    html = getattr(views, vista)(rf.get("/")).content.decode("utf-8")
    assert '<select id="fPromocion"' in html and '<option value="" selected>Todos</option>' in html
    assert '<option value="producto" disabled>Producto (pendiente de carga)</option>' in html
    assert '<option value="bancaria" disabled>Bancaria (pendiente de carga)</option>' in html
    assert '<select id="fCampania" multiple hidden>' in html


def test_pagina_promociones_sin_v_eventos_activos():
    html = views.pagina_promociones(rf.get("/")).content.decode("utf-8")
    assert "/api/promociones" in html and "/api/eventos" not in html
    assert "Precios en el folleto" in html and "/precios?folleto=" in html


def test_explorador_muestra_campania(monkeypatch):
    camp = {"campania": [{"slug": "navidad", "nombre": "Navidad"}], "producto": [], "bancaria": []}
    monkeypatch.setattr(queries, "listar_tiendas_detalle", lambda: [])
    monkeypatch.setattr(queries, "listar_folletos", lambda **k: [{"id": 5, "promos": camp}])
    monkeypatch.setattr(queries, "listar_tipos_extraccion", lambda: [])
    monkeypatch.setattr(queries, "listar_extracciones", lambda **k: [{"id": 9, "folleto_id": 5, "promos": camp}])
    html = views.pagina_explorador(rf.get("/datos")).content.decode("utf-8")
    assert html.count("<td>Navidad</td>") == 2


def test_js_render_promos_escapa():
    js = (RAIZ / "dashboard" / "static" / "dashboard" / "dashboard.js").read_text(encoding="utf-8")
    bloque = js[js.index("function renderPromos"):js.index("// Texto plano (tooltips")]
    assert "escaparHtml(p.nombre" in bloque and "escaparHtml(cfg.titulo)" in bloque
