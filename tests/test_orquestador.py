"""Orquestador del pipeline: orden de las etapas, seguir y reportar si una falla, codigo de salida (sin red ni BD)."""
import json

import pytest

import orquestador as oq


def _etapa(nombre, llamadas, errores=0, truena=False):
    def f(op):
        llamadas.append(nombre)
        if truena:
            raise RuntimeError("se cayo")
        return {"procesados": 3, "errores": errores, "detalle": nombre}
    return f


def test_etapas_en_orden_del_pipeline_aunque_se_pidan_desordenadas():
    llamadas = []
    funciones = {e: _etapa(e, llamadas) for e in oq.ETAPAS}
    r = oq.correr_etapas(["load", "scraper", "nlp"], oq.parsear([]), funciones)
    assert llamadas == ["scraper", "nlp", "load"] and all(x["ok"] for x in r)


def test_una_etapa_que_truena_no_detiene_las_siguientes():
    llamadas = []
    funciones = {e: _etapa(e, llamadas, truena=(e == "vision")) for e in oq.ETAPAS}
    r = oq.correr_etapas(list(oq.ETAPAS), oq.parsear([]), funciones)
    assert llamadas == list(oq.ETAPAS)
    por_etapa = {x["etapa"]: x for x in r}
    assert por_etapa["vision"]["ok"] is False and "se cayo" in por_etapa["vision"]["detalle"]
    assert por_etapa["nlp"]["ok"] and por_etapa["load"]["ok"]


def test_errores_parciales_marcan_la_etapa(monkeypatch, tmp_path):
    llamadas = []
    for e in oq.ETAPAS:
        monkeypatch.setitem(oq.FUNCIONES, e, _etapa(e, llamadas, errores=2 if e == "nlp" else 0))
    monkeypatch.setattr(oq, "configurar_logs", lambda: None)
    monkeypatch.setattr(oq, "RESUMEN", tmp_path / "resumen.json")
    assert oq.main(["--etapas", "vision", "nlp"]) == 1
    resumen = json.loads((tmp_path / "resumen.json").read_text(encoding="utf-8"))
    assert [x["etapa"] for x in resumen["etapas"]] == ["vision", "nlp"]
    assert resumen["etapas"][1]["errores"] == 2


def test_sin_errores_sale_con_cero(monkeypatch, tmp_path):
    for e in oq.ETAPAS:
        monkeypatch.setitem(oq.FUNCIONES, e, _etapa(e, []))
    monkeypatch.setattr(oq, "configurar_logs", lambda: None)
    monkeypatch.setattr(oq, "RESUMEN", tmp_path / "resumen.json")
    assert oq.main([]) == 0


def test_tienda_inexistente_se_rechaza_antes_de_empezar(monkeypatch):
    monkeypatch.setattr(oq, "configurar_logs", lambda: None)
    with pytest.raises(SystemExit) as e:
        oq.main(["--tiendas", "noexiste"])
    assert "noexiste" in str(e.value)


def test_por_defecto_cuatro_etapas_sin_gpu_ni_respaldo():
    op = oq.parsear([])
    assert op.etapas == list(oq.ETAPAS) and not op.gpu and not op.respaldo and op.tiendas is None
