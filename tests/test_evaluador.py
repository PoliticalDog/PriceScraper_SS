"""Pruebas del evaluador de registros (python -m pytest tests/)."""
import json

import pytest

from evaluador import splits
from evaluador.comparar import comparar_pagina, emparejar, similitud_nombre
from evaluador.gt import ArticuloGT, PaginaGT, cargar_gt, huella_gt
from evaluador.metricas import agregar, comparar_corridas, wilson
from evaluador.pipeline import PaginaPipeline, Registro


def reg(producto, precio, antes=None, idx=0, texto_precio=None):
    return Registro("t/f/p", idx, precio, texto_precio or f"${precio}", {}, producto, producto, None, None, antes)


def art(producto, precio, antes=None, id_=1):
    return ArticuloGT("t", "f", "p", id_, producto, None, precio, antes, None)


def pagina(registros, articulos, promociones=()):
    gt = PaginaGT("t", "f", "p", list(articulos), list(promociones))
    return PaginaPipeline(gt, {"precios": []}, {"bloques": []}, list(registros), [], [])


# -- Similitud de nombre --------------------------------------------------------------

def test_similitud_ignora_acentos_y_stopwords():
    assert similitud_nombre("Melón Chino", "Melon chino") == 1.0


def test_similitud_nombre_parcial_correcto():
    assert similitud_nombre("Pan de caja Bimbo 680g", "Pan de caja") >= 0.5


def test_similitud_producto_distinto():
    assert similitud_nombre("Audifonos soundcore Mod. A3994", "Desodorante") == 0.0


def test_similitud_tolera_una_letra():
    assert similitud_nombre("Salchichas o bologna de pollo", "Salchkchas Bologna") >= 0.5


# -- Ajuste 2: un monto igual NO implica asociacion correcta -----------------------------

def test_mismo_precio_se_empareja_por_nombre():
    """Dos productos a $25: cada registro debe quedar con SU articulo, no con el primero."""
    r_jugo, r_leche = reg("Jugo Jumex 1L", 25.0), reg("Leche Lala 1L", 25.0, idx=1)
    a_leche, a_jugo = art("Leche Lala entera 1L", 25.0, id_=1), art("Jugo Jumex mango 1L", 25.0, id_=2)
    res = comparar_pagina(pagina([r_jugo, r_leche], [a_leche, a_jugo]))
    asignacion = {p.registro.producto: p.articulo.producto for p in res.pares}
    assert asignacion == {"Jugo Jumex 1L": "Jugo Jumex mango 1L", "Leche Lala 1L": "Leche Lala entera 1L"}
    assert all(p.completo_ok for p in res.pares)


def test_precio_correcto_producto_equivocado_no_cuenta():
    """El caso de los audifonos: $320 correcto pero el dashboard dice 'Desodorante'."""
    res = comparar_pagina(pagina([reg("Desodorante", 320.0)], [art("Audifonos soundcore", 320.0)]))
    assert len(res.pares) == 1 and res.pares[0].precio_ok
    assert not res.pares[0].completo_ok
    assert res.pares[0].error == "asociacion_producto"
    assert agregar([res])["precision"] == 0.0


def test_productos_intercambiados_no_reciben_credito():
    """Leche $25 y Jugo $30 con los nombres cruzados: ningun registro es correcto."""
    res = comparar_pagina(pagina([reg("Jugo Jumex", 25.0), reg("Leche Lala", 30.0, idx=1)],
                                 [art("Leche Lala", 25.0, id_=1), art("Jugo Jumex", 30.0, id_=2)]))
    assert not any(p.completo_ok for p in res.pares)
    assert agregar([res])["precision"] == 0.0


def test_tres_articulos_mismo_precio_dos_registros():
    """Un articulo del mismo precio queda sin registro: se cuenta como perdido, no se regala."""
    articulos = [art("Atun Dolores agua", 19.9, id_=1), art("Sardina Calmex", 19.9, id_=2), art("Frijol Isadora", 19.9, id_=3)]
    res = comparar_pagina(pagina([reg("Atun Dolores", 19.9), reg("Frijol Isadora", 19.9, idx=1)], articulos))
    assert sorted(p.articulo.producto for p in res.pares if p.completo_ok) == ["Atun Dolores agua", "Frijol Isadora"]
    assert [a.producto for a, _ in res.articulos_perdidos] == ["Sardina Calmex"]


def test_registro_duplicado():
    res = comparar_pagina(pagina([reg("Leche Lala", 25.0), reg("Leche Lala", 25.0, idx=1)], [art("Leche Lala 1L", 25.0)]))
    assert len(res.pares) == 1
    assert [c for _, c in res.registros_sobrantes] == ["duplicado"]


def test_emparejamiento_es_uno_a_uno():
    pares = emparejar([reg("Leche", 25.0), reg("Leche", 25.0, idx=1)], [art("Leche", 25.0)])
    assert len(pares) == 1


# -- Tipos de error y precio anterior --------------------------------------------------

def test_promo_como_producto():
    res = comparar_pagina(pagina([reg("3x2 en todos los productos", 10.0)], [art("Leche", 25.0)],
                                 promociones=["3x2 en todos los productos del comal"]))
    assert [c for _, c in res.registros_sobrantes] == ["promo_como_producto"]


def test_precio_mal_leido_sin_nombre_parecido():
    """'5219' -> 52.19 cuando el folleto dice $219, con un producto sin parecido."""
    res = comparar_pagina(pagina([reg("Todos los Dias", 52.19, texto_precio="5219")], [art("Whisky Chivas", 219.0)]))
    assert [c for _, c in res.registros_sobrantes] == ["precio_mal_leido"]


def test_falta_precio_anterior():
    res = comparar_pagina(pagina([reg("Bistec de res", 189.0)], [art("Bistec de res", 189.0, antes=239.0)]))
    p = res.pares[0]
    assert p.basico_ok and not p.completo_ok and p.error == "asociacion_antes"


def test_precio_anterior_correcto():
    res = comparar_pagina(pagina([reg("Bistec de res", 189.0, antes=239.0)], [art("Bistec de res", 189.0, antes=239.0)]))
    m = agregar([res])
    assert m["precision"] == 1.0 and m["precision_antes"] == 1.0


# -- Metricas y regresiones ----------------------------------------------------------

def test_wilson_acotado():
    assert wilson(0, 10)[0] == 0.0 and wilson(10, 10)[1] == 1.0


def _metricas(ok, regs, arts):
    c = {"completos_ok": ok, "registros_dashboard": regs, "articulos_con_precio": arts}
    m = {"conteos": c, "precision": ok / regs, "recall": ok / arts, "f1": None}
    return {"global": m, "tiendas": {"heb": m}}


def test_regresion_significativa_bloquea():
    comp = comparar_corridas(_metricas(60, 100, 100), _metricas(40, 100, 100))
    reg_heb = [r for r in comp["regresiones"] if r["ambito"] == "heb" and r["metrica"] == "precision"][0]
    assert reg_heb["significativa"] and reg_heb["bloquea"]


def test_muestra_chica_no_bloquea():
    comp = comparar_corridas(_metricas(6, 10, 10), _metricas(4, 10, 10))
    assert comp["regresiones"] and not any(r["bloquea"] for r in comp["regresiones"])


# -- Splits e integridad -------------------------------------------------------------

@pytest.fixture(scope="module")
def gt():
    return cargar_gt()


def test_splits_deterministas(gt):
    assert splits.generar(gt) == splits.generar(gt)


def test_splits_congelados_coinciden_con_la_regla(gt):
    assert splits.cargar()["holdout"] == splits.generar(gt)["holdout"]


def test_splits_estratificados(gt):
    particion = splits.cargar()
    tiendas = lambda lado: {f.split("/")[0] for f in particion[lado]}
    assert tiendas("dev") == tiendas("holdout") == {p.tienda for p in gt}
    assert not set(particion["dev"]) & set(particion["holdout"])


def test_holdout_con_precio_anterior_donde_existe(gt):
    holdout = set(splits.cargar()["holdout"])
    con_antes = {(p.tienda, p.folleto) for p in gt if any(a.precio_anterior for a in p.articulos)}
    for tienda in {t for t, _ in con_antes}:
        assert any((tienda, f.split("/")[1]) in con_antes for f in holdout if f.startswith(tienda + "/")), tienda


def test_huella_gt_detecta_cambios(tmp_path):
    origen = sorted(cargar_gt.__globals__["RAIZ_GT"].rglob("*_contenido.json"))[0]
    copia = tmp_path / "tienda" / origen.name
    copia.parent.mkdir()
    copia.write_bytes(origen.read_bytes())
    antes = huella_gt(tmp_path)
    datos = json.loads(copia.read_text(encoding="utf-8"))
    datos["paginas"][0]["articulos"][0]["precio"] = 999999
    copia.write_text(json.dumps(datos), encoding="utf-8")
    assert huella_gt(tmp_path) != antes


def test_nombre_de_tienda_no_identifica_producto():
    a = ArticuloGT("alsuper", "f", "p", 1, "Queso poroso Alsuper", None, 179.9, None, None)
    res = comparar_pagina(PaginaPipeline(PaginaGT("alsuper", "f", "p", [a], []), {"precios": []}, {"bloques": []},
                                         [reg("Alsuper Kg", 179.9)], [], []))
    assert not res.pares[0].completo_ok


def test_concordancia_ignora_dudosos():
    from evaluador.validacion import concordancia
    muestra = {"casos": [
        {"id": "c1", "pagina": "p", "producto": "x", "precio": 1, "juez": {"juez_producto_ok": True, "juez_precio_ok": True}},
        {"id": "c2", "pagina": "p", "producto": "y", "precio": 1, "juez": {"juez_producto_ok": False, "juez_precio_ok": True}},
        {"id": "c3", "pagina": "p", "producto": "z", "precio": 1, "juez": {"juez_producto_ok": True, "juez_precio_ok": True}},
    ]}
    r = concordancia(muestra, {"c1": {"producto": "si", "precio": "si"}, "c2": {"producto": "si", "precio": "si"},
                               "c3": {"producto": "dudoso", "precio": "si"}})
    assert (r["evaluados"], r["acuerdos"], r["dudosos"]) == (2, 1, 1)


def test_pagina_gt_sin_precios_no_cuenta():
    """Costco: GT con productos pero sin montos -> los registros no son huerfanos ni bajan la precision."""
    res = comparar_pagina(pagina([reg("Hidrolizado", 91.0)], [art("Colageno hidrolizado", None)]))
    assert not res.evaluable and not res.registros_sobrantes
    m = agregar([res, comparar_pagina(pagina([reg("Leche", 25.0)], [art("Leche", 25.0)]))])
    assert (m["precision"], m["conteos"]["registros_dashboard"], m["conteos"]["paginas_sin_precio_gt"]) == (1.0, 1, 1)


def test_concordancia_excluye_paginas_sin_precio():
    from evaluador.validacion import concordancia
    muestra = {"casos": [
        {"id": "c1", "pagina": "costco/p", "producto": "x", "precio": 1, "juez": {"juez_producto_ok": False, "juez_precio_ok": False}},
        {"id": "c2", "pagina": "heb/p", "producto": "y", "precio": 1, "juez": {"juez_producto_ok": True, "juez_precio_ok": True}},
    ]}
    r = concordancia(muestra, {"c1": {"producto": "si", "precio": "si"}, "c2": {"producto": "si", "precio": "si"}}, {"costco/p"})
    assert (r["evaluados"], r["acuerdos"], r["excluidos"]) == (1, 1, ["c1"])


def test_ocr_experimental_nombre_seguro():
    from evaluador.ocr_experimental import carpeta_exp
    assert carpeta_exp("base_heb").name == "base_heb"
    for malo in ("../x", "a/b", r"a\b", "x.y", "", " x"):
        with pytest.raises(ValueError):
            carpeta_exp(malo)


def test_ocr_exp_obliga_nlp_memoria():
    from evaluador.pipeline import FuentePipeline
    with pytest.raises(ValueError):
        FuentePipeline(nlp="disco", ocr_exp="base_heb")
