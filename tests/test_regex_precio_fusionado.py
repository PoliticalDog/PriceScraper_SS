"""Precio repartido en 2 bloques: entero grande + centavos en superindice (_detectar_precios_fusionados)."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _bloque(texto, x, y, ancho, alto, confianza=0.99):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _fusiones(bloques, ancho_pagina=1500):
    fe = ancho_pagina / EX.ANCHO_REFERENCIA_UMBRALES
    return sorted((e["texto"], c["texto"], v) for e, c, v in EX._detectar_precios_fusionados(bloques, fe))


def test_entero_y_centavos_alineados_arriba_se_fusionan():
    # alsuper 416306 p2: "99" + "90" a su derecha, mas chico y alineado arriba -> $99.90
    bloques = [_bloque("99", 1169, 1237, 86, 64), _bloque("90", 1247, 1235, 50, 42)]
    assert _fusiones(bloques) == [("99", "90", 99.9)]


def test_centavos_de_otra_fila_mas_arriba_no_se_fusionan():
    # merco 426175 p1 (geometria real): "51" de otra casilla, 1157 px debajo del "99" de "78⁹⁹";
    # antes se leia 51.99
    bloques = [_bloque("78", 281, 653, 138, 88), _bloque("99", 407, 661, 52, 36),
               _bloque("51", 286, 1818, 147, 78)]
    assert _fusiones(bloques, 1350) == [("78", "99", 78.99)]


def test_centavos_de_otra_fila_no_vuelven_ambiguo_el_par_real():
    # calimax 135706 p1 (geometria real): "34" + "90" de $34⁹⁰; el "90" de "32⁹⁰", 800 px mas
    # arriba en la misma columna, ya no cuenta como segundo candidato
    bloques = [_bloque("32", 376, 598, 142, 113), _bloque("90", 498, 602, 72, 55),
               _bloque("34", 357, 1419, 126, 96), _bloque("90", 461, 1416, 68, 51)]
    assert _fusiones(bloques, 1800) == [("32", "90", 32.9), ("34", "90", 34.9)]


def test_centavos_bajo_la_mitad_del_entero_no_se_fusionan():
    # Regla original: el superindice va en la mitad superior del entero
    bloques = [_bloque("45", 100, 100, 80, 60), _bloque("90", 185, 140, 40, 30)]
    assert _fusiones(bloques) == []


def test_centavos_mas_altos_que_el_entero_no_se_fusionan():
    bloques = [_bloque("45", 100, 100, 80, 40), _bloque("90", 185, 100, 40, 50)]
    assert _fusiones(bloques) == []


# --- entero con el "$" diminuto pegado o de 3 digitos (PATRON_ENTERO_FUSION) ---

def test_tres_digitos_ambiguos_no_se_fusionan():
    # merco 428269 p1: "$79⁹⁹" -> "879" + "99" (el "$" leido 8), pero en casa_ley 427141 p1
    # "544" + "90" es $544⁹⁰: el bloque solo no distingue "$" + 2 digitos de 3 digitos
    assert _fusiones([_bloque("879", 682, 704, 168, 96), _bloque("99", 839, 717, 52, 36)], 1350) == []
    assert _fusiones([_bloque("544", 27, 497, 60, 42), _bloque("90", 83, 501, 26, 20)], 1800) == []
    assert _fusiones([_bloque("114", 100, 100, 110, 68), _bloque("90", 215, 96, 45, 42)]) == []


def test_signo_leido_como_cero_mas_entero_y_centavos():
    # merco 428269 p8: "$74⁹⁹" -> "074" + "99"; ningun precio empieza con 0
    bloques = [_bloque("074", 244, 1212, 146, 74), _bloque("99", 377, 1209, 60, 42)]
    assert _fusiones(bloques, 1350) == [("074", "99", 74.99)]


def test_signo_literal_mas_entero_y_centavos():
    # arteli 135652 p1: "$19" + "90" -> $19.90 (antes $19)
    bloques = [_bloque("$19", 125, 1850, 121, 84), _bloque("90", 236, 1859, 56, 38)]
    assert _fusiones(bloques, 1800) == [("$19", "90", 19.9)]


def test_signo_literal_con_tres_digitos_no_se_fusiona():
    # merco: "$54⁹⁹" -> "$545" + "99" (el 5 sobrante es parte del "$"); no es $545.99
    bloques = [_bloque("$545", 100, 100, 150, 80), _bloque("99", 255, 100, 50, 40)]
    assert _fusiones(bloques) == []


def test_signo_leido_como_s_mas_un_digito():
    bloques = [_bloque("s9", 100, 100, 60, 98), _bloque("95", 165, 101, 40, 44)]
    assert _fusiones(bloques) == [("s9", "95", 9.95)]


def test_forma_nueva_exige_superindice_claramente_mas_chico():
    # heb 426190 p2: "s59" (122 px) + "52" (102 px) no es un superindice
    bloques = [_bloque("s59", 100, 100, 110, 122), _bloque("52", 215, 112, 60, 102)]
    assert _fusiones(bloques) == []


def test_forma_nueva_no_fusiona_cero():
    bloques = [_bloque("000", 100, 100, 110, 80), _bloque("00", 215, 100, 45, 40)]
    assert _fusiones(bloques) == []


def test_precio_fusionado_reemplaza_al_entero_en_la_pagina():
    # merco 422684 p10: "$24" + "99" se leia $24
    texto = [_bloque("Refresco cola 600 ml", 900, 100, 250, 30), _bloque("Galletas surtidas", 900, 400, 250, 30)]
    bloques = texto + [_bloque("$24", 1134, 1860, 134, 76), _bloque("99", 1267, 1861, 58, 42)]
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1350})
    assert [e.valor for e in res.precios] == [24.99]
