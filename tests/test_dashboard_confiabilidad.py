"""Panel "Confiabilidad del dato por tienda": lector de corridas del evaluador y etiqueta (sin BD)."""

import json
import os

import pytest

from dashboard import confiabilidad as c


def _corrida(fecha="2026-10-12T14:19:17", split="dev", sucio=False, valida=True, commit="abc1234",
             tiendas=None):
    if tiendas is None:
        tiendas = {"walmart": _tienda(0.3958, [0.3038, 0.4959], 96)}
    return {
        "meta": {"fecha": fecha, "split": split, "codigo": {"commit": commit, "cambios_sin_commit": sucio}},
        "integridad": {"valida": valida, "problemas": []},
        "metricas": {"global": {"conteos": {"paginas": 158}, "precision": 0.1278, "recall": 0.115},
                     "tiendas": tiendas},
        "detalle": {"articulos": {}, "registros": {}},
    }


def _tienda(precision, ic95, registros, paginas=10, articulos=90, errores=None):
    return {
        "conteos": {"paginas": paginas, "registros_dashboard": registros, "articulos_con_precio": articulos},
        "precision": precision, "precision_ic95": ic95, "recall": 0.4,
        "errores_registro": errores or {"precio_mal_leido": 5, "asociacion_producto": 9, "precio_huerfano": 2},
    }


def _escribir(directorio, nombre, datos):
    ruta = directorio / nombre
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    return ruta


@pytest.fixture(autouse=True)
def _limpiar_cache():
    c._cache.clear()
    yield
    c._cache.clear()


# -- Lector de corridas ------------------------------------------------------------------------------------

def test_elige_la_mas_reciente_por_meta_fecha(tmp_path):
    _escribir(tmp_path, "20261011_100000_aaa1111_dev.json", _corrida(fecha="2026-10-11T10:00:00", commit="aaa1111"))
    _escribir(tmp_path, "20261012_141917_bbb2222_dev.json", _corrida(fecha="2026-10-12T14:19:17", commit="bbb2222"))
    _escribir(tmp_path, "20261012_090000_ccc3333_dev.json", _corrida(fecha="2026-10-12T09:00:00", commit="ccc3333"))
    assert c.corrida_vigente(tmp_path)["meta"]["codigo"]["commit"] == "bbb2222"


def test_meta_fecha_manda_sobre_el_nombre(tmp_path):
    # Nombre fuera de convencion (se parsea) con meta.fecha mas reciente que la del nombre "mas nuevo".
    _escribir(tmp_path, "20261012_235959_aaa1111_dev.json", _corrida(fecha="2026-10-12T08:00:00", commit="aaa1111"))
    _escribir(tmp_path, "corrida_manual.json", _corrida(fecha="2026-10-12T20:00:00", commit="zzz9999"))
    assert c.corrida_vigente(tmp_path)["meta"]["codigo"]["commit"] == "zzz9999"


def test_ignora_sucias_holdout_e_invalidas(tmp_path):
    _escribir(tmp_path, "20261012_100000_aaa1111_dev.json", _corrida(fecha="2026-10-12T10:00:00", commit="aaa1111"))
    # Mas recientes pero descartables:
    _escribir(tmp_path, "20261012_110000_bbb2222-sucio_dev.json", _corrida(fecha="2026-10-12T11:00:00", sucio=True))
    _escribir(tmp_path, "20261012_120000_ccc3333_holdout.json", _corrida(fecha="2026-10-12T12:00:00", split="holdout"))
    _escribir(tmp_path, "20261012_130000_ddd4444_dev.json", _corrida(fecha="2026-10-12T13:00:00", valida=False))
    # Nombre fuera de convencion pero meta sucia / holdout: se parsea y se descarta por meta.
    _escribir(tmp_path, "otra_sucia.json", _corrida(fecha="2026-10-12T14:00:00", sucio=True))
    _escribir(tmp_path, "otra_holdout.json", _corrida(fecha="2026-10-12T15:00:00", split="holdout"))
    # Nombre limpio que miente: meta dice sucio.
    _escribir(tmp_path, "20261012_160000_eee5555_dev.json", _corrida(fecha="2026-10-12T16:00:00", sucio=True))
    assert c.corrida_vigente(tmp_path)["meta"]["codigo"]["commit"] == "aaa1111"


def test_json_corrupto_o_incompleto_no_rompe(tmp_path):
    (tmp_path / "20261012_100000_aaa1111_dev.json").write_text("{no es json", encoding="utf-8")
    _escribir(tmp_path, "20261012_110000_bbb2222_dev.json", {"meta": {"split": "dev"}})
    assert c.corrida_vigente(tmp_path) is None


def test_sin_corridas_o_sin_directorio(tmp_path):
    assert c.corrida_vigente(tmp_path) is None
    assert c.corrida_vigente(tmp_path / "no_existe") is None


def test_cache_se_invalida_por_mtime(tmp_path):
    ruta = _escribir(tmp_path, "20261012_100000_aaa1111_dev.json", _corrida(commit="aaa1111"))
    assert c.corrida_vigente(tmp_path)["meta"]["codigo"]["commit"] == "aaa1111"
    datos = _corrida(commit="aaa1111", valida=False)
    ruta.write_text(json.dumps(datos) + " " * 10, encoding="utf-8")
    st = ruta.stat()
    os.utime(ruta, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert c.corrida_vigente(tmp_path) is None


def test_resumen_no_guarda_el_detalle(tmp_path):
    _escribir(tmp_path, "20261012_100000_aaa1111_dev.json", _corrida())
    resumen = c.corrida_vigente(tmp_path)
    assert set(resumen) == {"archivo", "meta", "integridad", "global", "tiendas"}


def test_info_corrida():
    tiendas = {"walmart": _tienda(0.4, [0.3, 0.5], 96),
               "costco": _tienda(None, None, 0, paginas=0, articulos=0)}
    info = c.info_corrida({"archivo": "x.json", "meta": _corrida()["meta"],
                           "global": _corrida()["metricas"]["global"], "tiendas": tiendas})
    assert info["commit"] == "abc1234"
    assert info["tiendas_en_split"] == 2
    assert info["tiendas_medidas"] == 1
    assert info["paginas_evaluadas"] == 158
    assert c.info_corrida(None) is None


# -- Etiqueta de confiabilidad -----------------------------------------------------------------------------

@pytest.mark.parametrize("precision, ic_inf, registros, esperado", [
    (None, None, None, c.SIN_MEDIR),
    (0.3, 0.2, 0, c.SIN_MEDIR),
    (0.3, 0.2, None, c.SIN_MEDIR),
    (0.25, 0.09, 12, c.MUESTRA_INSUFICIENTE),      # waldos
    (0.0, 0.0, 29, c.MUESTRA_INSUFICIENTE),        # limite: 29 < 30
    (0.0, 0.0, 30, c.BAJA),                        # limite: 30 ya se clasifica
    (0.0, 0.0, 208, c.BAJA),                       # casa_ley
    (0.0999, 0.05, 100, c.BAJA),
    (0.10, 0.06, 100, c.MEDIA),                    # limite inferior de Media
    (0.1901, 0.1341, 142, c.MEDIA),                # heb
    (0.2499, 0.20, 100, c.MEDIA),
    (0.25, 0.15, 100, c.ACEPTABLE),                # limites exactos de Aceptable
    (0.25, 0.1499, 100, c.MEDIA),                  # precision alta sin evidencia -> Media
    (0.30, None, 100, c.MEDIA),                    # sin IC95 no puede ser Aceptable
    (0.3958, 0.3038, 96, c.ACEPTABLE),             # walmart
    (0.3462, 0.2501, 78, c.ACEPTABLE),             # tiendas_3b
])
def test_etiqueta_confiabilidad(precision, ic_inf, registros, esperado):
    assert c.etiqueta_confiabilidad(precision, ic_inf, registros) == esperado


@pytest.mark.parametrize("pct, esperado", [(None, False), (0.0, True), (19.9, True), (20.0, False), (38.8, False)])
def test_base_heuristica(pct, esperado):
    assert c.es_base_heuristica(pct) is esperado


def test_umbrales_aprobados():
    assert c.UMBRAL_REGISTROS_MINIMOS == 30
    assert c.UMBRAL_PRECISION_MEDIA == 0.10
    assert c.UMBRAL_PRECISION_ACEPTABLE == 0.25
    assert c.UMBRAL_IC95_INFERIOR_ACEPTABLE == 0.15
    assert c.UMBRAL_PCT_CATALOGO_BASE_HEURISTICA == 20.0


# -- Metricas por tienda y union con la BD ------------------------------------------------------------------

def test_metricas_tienda_medida():
    m = c.metricas_tienda(_tienda(0.3958, [0.3038, 0.4959], 96))
    assert m["precision"] == 0.3958
    assert m["precision_ic95_inf"] == 0.3038 and m["precision_ic95_sup"] == 0.4959
    assert m["registros_evaluados"] == 96
    assert m["error_dominante"] == "asociacion_producto"
    assert m["etiqueta"] == c.ACEPTABLE


def test_metricas_tienda_sin_paginas_es_sin_medir():
    # costco/oxxo: estan en el split pero sin articulos con precio en el GT
    m = c.metricas_tienda({"conteos": {"paginas": 0, "registros_dashboard": 0, "articulos_con_precio": 0},
                           "precision": None, "precision_ic95": None, "recall": None,
                           "errores_registro": {"precio_mal_leido": 0}})
    assert m["etiqueta"] == c.SIN_MEDIR
    assert m["precision"] is None and m["error_dominante"] is None


def test_metricas_tienda_ausente_es_sin_medir():
    m = c.metricas_tienda(None)
    assert m["etiqueta"] == c.SIN_MEDIR
    assert all(m[k] is None for k in ("precision", "recall", "precision_ic95_inf", "registros_evaluados"))


def test_unir_confiabilidad_con_y_sin_corrida():
    filas = [{"tienda_slug": "walmart", "pct_catalogo": 5.3},
             {"tienda_slug": "merco", "pct_catalogo": 38.8},
             {"tienda_slug": "calimax", "pct_catalogo": 21.7}]
    resumen = {"tiendas": {"walmart": _tienda(0.3958, [0.3038, 0.4959], 96),
                           "merco": _tienda(0.0361, [0.0124, 0.101], 83)}}
    unidas = {f["tienda_slug"]: f for f in c.unir_confiabilidad(filas, resumen)}
    assert unidas["walmart"]["etiqueta"] == c.ACEPTABLE and unidas["walmart"]["base_heuristica"] is True
    assert unidas["merco"]["etiqueta"] == c.BAJA and unidas["merco"]["base_heuristica"] is False
    assert unidas["calimax"]["etiqueta"] == c.SIN_MEDIR

    sin = c.unir_confiabilidad(filas, None)
    assert [f["etiqueta"] for f in sin] == [c.SIN_MEDIR] * 3
    assert sin[0]["base_heuristica"] is True
    assert "etiqueta" not in filas[0]  # no muta la entrada


def test_descartable_por_nombre():
    assert c._descartable_por_nombre("20261012_120244_5823d76-sucio_dev.json")
    assert c._descartable_por_nombre("20261012_124445_5823d76_holdout.json")
    assert not c._descartable_por_nombre("20261012_141917_e4184da_dev.json")
    assert not c._descartable_por_nombre("20261012_141917_sin-git_dev.json")
    assert not c._descartable_por_nombre("cualquier_cosa.json")


def test_corridas_parciales_no_son_vigentes(tmp_path):
    # 26-oct-2026: una corrida de una sola tienda o con OCR experimental no representa al pipeline completo
    completa = _corrida(fecha="2026-10-12T08:00:00", commit="aaa1111")
    una_tienda = _corrida(fecha="2026-10-12T09:00:00", commit="bbb2222")
    una_tienda["meta"]["tienda"] = "heb"
    ocr_exp = _corrida(fecha="2026-10-12T10:00:00", commit="ccc3333")
    ocr_exp["meta"]["ocr_exp"] = "gpu_1800"
    _escribir(tmp_path, "20261012_080000_aaa1111_dev.json", completa)
    _escribir(tmp_path, "20261012_090000_bbb2222_dev.json", una_tienda)
    _escribir(tmp_path, "20261012_100000_ccc3333_dev.json", ocr_exp)
    assert c.corrida_vigente(tmp_path)["meta"]["codigo"]["commit"] == "aaa1111"
