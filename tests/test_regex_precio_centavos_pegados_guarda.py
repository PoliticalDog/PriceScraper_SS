"""Guarda de los centavos pegados (_entero_confirmado, condicion de QA 25-oct-2026): "$dddd"/"$ddddd" se queda
entero cuando la casilla lo confirma (mensualidad N x cuota, precio anterior, otro monto con coma en el mismo bloque)
y no confirma el valor /100. Cajas reales de produccion. Contrapruebas: los /100 legitimos de soriana."""
from nlp.regex_extractor import RegexExtractor

EX = RegexExtractor()


def _b(texto, x, y, ancho, alto, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _precios(bloques, ancho_pagina):
    res = EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": ancho_pagina})
    return {e.texto_raw: e.valor for e in res.precios}


# --- enteros reales con la coma perdida (los 9 de QA, Engram #275) ---

def test_chedraui_428354_p8_batidora_mensualidad():
    # "9MSI | $28833" = 9 x $288.33 = $2,594.97 -> $2,595 (y el anticipo "825950" = $259.50)
    bloques = [_b("S2,995", 414, 644, 195, 68), _b("$2595", 655, 643, 195, 72), _b("$1,495", 913, 647, 184, 64),
               _b("Apártalo con", 667, 715, 96, 16), _b("825950", 775, 706, 87, 31),
               _b("9MSI | $28833", 666, 742, 118, 24), _b("Batidora 850 W", 660, 770, 166, 28),
               _b("Mod. Planetaria", 660, 794, 160, 24)]
    assert _precios(bloques, 1200)["$2595"] == 2595.0


def test_chedraui_424418_p1_cafetera_mensualidad_en_bloque_aparte():
    # "S2295 $2495": "9MSI" + "$27722" = 9 x $277.22 = $2,494.98
    bloques = [_b("S2295 $2495", 687, 1432, 474, 86), _b("9 MSI", 704, 1516, 58, 24), _b("$255", 770, 1516, 60, 24),
               _b("9MSI", 942, 1514, 56, 24), _b("$27722", 1006, 1512, 76, 28),
               _b("Batidora 850 W", 696, 1548, 198, 30), _b("Cafetera Genio plus", 933, 1549, 244, 36)]
    assert _precios(bloques, 1200)["S2295 $2495"] == 2495.0


def test_chedraui_413467_p15_colchon_otro_monto_con_coma_en_el_bloque():
    # "S1,990 $2590": individual $1,990 y matrimonial $2,590 en un bloque; el "Antes $3,195" se lee "$2435" y
    # la mensualidad "$287⁷⁸" se lee "52877", ninguna sirve
    bloques = [_b("Antes: $2295", 496, 450, 134, 26), _b("Antes: $2435", 690, 450, 134, 26),
               _b("S1,990 $2590", 493, 469, 354, 68), _b("Individual", 494, 527, 108, 26),
               _b("9MSI", 699, 529, 48, 20), _b("52877", 754, 526, 64, 24), _b("Matrimonial", 691, 555, 126, 26)]
    assert _precios(bloques, 1200)["S1,990 $2590"] == 2590.0


def test_soriana_mercado_415099_p5_tv_de_x_a():
    # "DE $6,1900 A" = $6,199⁰⁰ antes de $4,290
    bloques = [_b('40"', 788, 1715, 228, 122), _b("DE $6,1900 A", 886, 1914, 176, 32), _b("$4290", 806, 1944, 315, 98),
               _b("SMART", 782, 2056, 96, 30), _b("TV", 810, 2080, 40, 28), _b("HD", 910, 2068, 44, 30)]
    assert _precios(bloques, 1800)["$4290"] == 4290.0


def test_soriana_mercado_415099_p17_motos_de_x_a():
    # Moto $65,999 "DE$77,.49900 a" (ilegible para _extraer_precio_anterior) y cuatrimoto $45,999 "DE +58,99900 A"
    bloques = [_b("Capacidadldel tanque lleno: 12L", 680, 2090, 340, 30), _b("DE$77,.49900 a", 733, 2123, 232, 41),
               _b("$65999", 685, 2157, 322, 80), _b("DE +58,99900 A", 1317, 1160, 234, 42),
               _b("$45999", 1270, 1190, 323, 87)]
    precios = _precios(bloques, 1800)
    assert precios["$65999"] == 65999.0 and precios["$45999"] == 45999.0


def test_soriana_hiper_415102_p22_minisplit_recuadro_meses_sin_intereses():
    # Recuadro aparte: "18" / "Meses sin" / "Intereses" / "899944" = 18 x $999.44 = $17,989.92
    bloques = [_b("18", 772, 978, 80, 54), _b("Meses sin", 756, 1026, 104, 24), _b("Intereses", 756, 1044, 104, 24),
               _b("899944", 756, 1078, 104, 36), _b("BBVA", 764, 1166, 87, 36), _b("24000 BTUs", 326, 1228, 156, 30),
               _b("A SOLO", 630, 1246, 108, 30), _b("$17990", 533, 1271, 305, 81)]
    assert _precios(bloques, 1800)["$17990"] == 17990.0


def test_soriana_hiper_424731_p8_laptop_recuadro_al_lado():
    # El recuadro de la laptop va a su derecha, a 368 px: "18" / "Hescs sin" / "Intcrcscs" / "838833" = 18 x $388.33;
    # el de la izquierda ("5166"" = $166.11) es de la impresora y no cuadra
    bloques = [_b("374", 580, 1952, 50, 28), _b("18", 573, 2003, 56, 40), _b("Antcrescs", 567, 2055, 72, 14),
               _b('5166"', 564, 2074, 76, 26), _b("Laptop HP Pcntium", 734, 1974, 218, 32),
               _b("DEs8,7904:", 755, 2097, 178, 36), _b("$6990", 703, 2116, 230, 88),
               _b("874", 1156, 1952, 52, 28), _b("18", 1151, 2003, 54, 42), _b("Hescs sin", 1142, 2040, 75, 18),
               _b("Intcrcscs", 1145, 2055, 70, 14), _b("838833", 1136, 2074, 86, 26)]
    assert _precios(bloques, 1800)["$6990"] == 6990.0


def test_soriana_hiper_425716_p17_librero_seis_meses():
    # "Mcscs sin" / "intcrcscs" / "541650" = 6 x $416.50 = $2,499
    bloques = [_b("6", 521, 1423, 38, 40), _b("Mcscs sin", 490, 1460, 98, 24), _b("intcrcscs", 493, 1479, 92, 20),
               _b("Librero plegable 5 niveles", 618, 1477, 303, 40), _b("541650", 487, 1508, 104, 36),
               _b("Home Style Design", 619, 1507, 242, 36), _b("$2499", 612, 1538, 346, 100)]
    assert _precios(bloques, 1800)["$2499"] == 2499.0


# --- contrapruebas: centavos pegados legitimos de soriana que se siguen dividiendo ---

def test_soriana_hiper_416269_p1_cebolla_1880():
    bloques = [_b("$1880", 1399, 743, 282, 160), _b("KILO", 1586, 850, 76, 50), _b("CEBOLLA", 1434, 934, 188, 54),
               _b("BLANCA", 1450, 980, 154, 48)]
    assert _precios(bloques, 1800)["$1880"] == 18.8


def test_soriana_mercado_417964_p2_mojarra_3450():
    bloques = [_b("Mojarra tilapia", 149, 1787, 232, 42), _b("$3450", 490, 1757, 291, 103),
               _b("MEDIO", 686, 1816, 84, 26), _b("congelada", 177, 1821, 173, 48), _b("KILO", 694, 1840, 64, 26)]
    assert _precios(bloques, 1800)["$3450"] == 34.5


def test_de_x_a_que_confirma_las_dos_lecturas_sigue_dividiendo():
    # soriana_mercado 433057 p5 "DE $36⁹⁰ A" leido "DE 5362A:" y soriana_hiper 413734 p21 "DE s18900 A" + "$13200"
    a = [_b("Gerber 4 L.", 1526, 1564, 120, 28), _b("DE 5362A:", 1562, 1602, 132, 32), _b("$2990", 1553, 1631, 148, 64)]
    b = [_b("DE s18900 A", 1128, 1556, 152, 32), _b("$13200", 1098, 1581, 214, 64),
         _b("Caja con tapa y asa", 1051, 1657, 304, 44)]
    assert _precios(a, 1800)["$2990"] == 29.9
    assert _precios(b, 1800)["$13200"] == 132.0


def test_soriana_mercado_422726_p6_brandy_anterior_ilegible_no_protege():
    # "DE $444⁰⁰ A $319⁰⁰": el anterior se lee "DE: 54141.00" (sin la "A"); no debe proteger $31,900
    bloques = [_b("Brandy Torres", 250, 2090, 176, 32), _b("1o de 700ml", 256, 2118, 162, 30),
               _b("DE: 54141.00", 281, 2171, 116, 20), _b("$31900|", 249, 2187, 182, 60),
               _b("DE: $75.50", 694, 2170, 108, 24), _b("85490", 670, 2186, 155, 60)]
    assert _precios(bloques, 1800)["$31900|"] == 319.0


def test_mensualidad_que_cuadra_con_las_dos_lecturas_no_protege():
    # "3 MSI" + "$997" se lee $9.97 o $997: 3 x 997 = 2,991 y 3 x 9.97 = 29.91; si confirma las dos, divide
    bloques = [_b("$2991", 500, 500, 200, 80), _b("3 MSI", 500, 590, 50, 20), _b("$997", 560, 590, 60, 20)]
    assert _precios(bloques, 1500)["$2991"] == 29.91


def test_mensualidad_que_solo_cuadra_con_el_dividido_no_protege():
    bloques = [_b("$2990", 500, 500, 200, 80), _b("3 MSI", 500, 590, 50, 20), _b("$997", 560, 590, 60, 20)]
    assert _precios(bloques, 1500)["$2990"] == 29.9
