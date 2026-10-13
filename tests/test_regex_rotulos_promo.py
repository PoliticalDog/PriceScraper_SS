"""Rotulos sueltos de promocion, condicion, financiamiento, lealtad, servicio y vigencia no son PRODUCTO
(12-oct-2026, BI: promos como nombre de producto en el dashboard)."""
import pytest

from load.load import construir_registros_pagina
from nlp.normalizador import Normalizador
from nlp.regex_extractor import RegexExtractor
from nlp.salida_json import clasificar_paginas_ocr, resultado_nlp

EX = RegexExtractor()


def _bloque(texto, x, y, ancho=120, alto=40, confianza=0.9):
    return {"texto": texto, "confianza": confianza, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


def _pagina(bloques):
    return EX.procesar_pagina({"imagen": "p.webp", "bloques": bloques, "ancho_pagina": 1500})


ROTULOS = {
    "financiamiento": [
        "Intereses", "intereses", "INTERESES", "Intcrcscs", "Interescs", "Intercses", "Intercsos", "iintereses",
        "sin Intereses'", "sinIntereses'", "Meses", "MESES", "Meses sln", "Heses sin", "HESES SIH", "HESES SIM",
        "HESESSIN", "Mesessin", "Mcscssin", "Mcscs sin", "MESES DE", "Meses de", "12 MESES", "18 MESES", "MES SIN INTERESES",
        "12 meses sin intereses", "meses sinintereses", "quincenas", "en 3 quincenas", "En Un SOLO Pago",
    ],
    "lealtad": [
        "puntos", "Puntos", "PUNTOS", "Puhtos", "PUnTOS", "[puntos", "'300 puntos", "60 puntos",
        "TODAS TUS COMPRAS TE DAN PUNTOS.", "Teregala", "'Teregala", "Te regala", "7e Regala", "Tc regala",
        "Toregala", "Teregalal", "Te bonificamos*", "BONIFICAMOSENTU", "MONEDERO", "[MONEDERO",
        "tu monedero", "omonedero electrónico", "Ticket de compra", "Tlcket de compra", "TICKET*",
    ],
    "precio_generico": [
        "SÚPER", "'SÚPER", "SUPER", "Súper", "PRECIAZO", "[PRECIAZO", "PRECIAZO]", "[PRECIAZO]", "PRECiAZO",
        "PPRECIAZO", "PPaEcIAzo", "Preciazo", "Desde:", "DESDE.", "DESDE ,", "[DESDE ,", "'DESCUENTO",
        "Hasta", "HASTA", "Hasta:", "Multiahorro", "PROMO", "PROMO AHORRO", "[Precio", "Preció", "Precios",
        "Precio regular", "Antes:", "'KILO",
    ],
    "condicion_compra": [
        "Adicional", "Adicionales", "ADICIONAL", "Adicionale;", "ELIGES", "[COMPRANDO", "COMPRANDO", "Comprando",
        "ESCOGER", "A ESCOGER", "AESCOGER", "Exclusivos", "EXCLUSIVAS", "Exclusivo en línea", "Exclusivoenlínea",
        "Exclusivo con", "Exclusivo en waldos com mx", "Exclusivo en waldoscommx", "Exclusivo en waldos.corn mx",
        "(no incluye producto de ambientación)", "(noincluyen producto de ambientación)", "(no incluyen rines)",
        "INCLUYE", "Incluye:", "de compra", "de compra en todos los", "DE COMPRA EN COLCHONES",
        "Aplica solo en paqueteria", "No aplica temporada", "'Precio aplica solo", "aplica en el de menor precio",
        "menor precio que el de compra.", "CADA", "cada", "CaDa", "YLLÉVATE", "Llevate más", "LLÉVATELA",
    ],
    "servicio": [
        "Envío", "Envio", "1año de envío*", "Recarga", "recargas", "Recarga tiempo aire", "Haz tu RECARGA",
        "Garantía", "GARANTIA", "tu Garantía", "al extender tu Garantía", "Garantía Extendida", "PROTECCIÓN",
        "MESES DE PROTECCIÓN", "'Seguro de protección", "3 Meses de suscripción Online",
    ],
    "vigencia": [
        "12 al 18 de Junio de 2026", "Del 03 al 21 de junio 2026", "14 al 20 de Agosto del 2026",
        "28 AL 30 DE JULIO", "Del 02 al 16 de octubre 2026",
    ],
}


@pytest.mark.parametrize("texto", [t for lista in ROTULOS.values() for t in lista])
def test_rotulo_promo_suelto_no_es_producto(texto):
    res = _pagina([_bloque(texto, 100, 100), _bloque("$949", 100, 160)])
    assert [p.texto_raw for p in res.productos] == []
    assert [e.valor for e in res.precios] == [949.0]


# Nombres reales (o atributos) que contienen esas palabras: el ancla al bloque completo los protege
@pytest.mark.parametrize("texto", [
    "Súper Value", "Salvo", "Hasta 35 horas de batería", "Incluye 2 juegos Astro Bot", "Incluye 1 control dualsense",
    "Crema Facial Protección Eucerin 50", "Ellmina puntos de presión para mejor descanso", "Talla: 0 - 6 meses",
    "Tradicional", "Detergente Cada Dia", "Super Pollo", "Pierna Premium con hueso", "Picante", "Mesa plegable",
    "Garantía de 1 año Samsung TV", "Puntos de luz LED 20 m", "Recargas Telcel Amigo","Protector solar", "LITRO A ESCOGER",
    "Exclusivo en Chedraui: Pantalla TCL 55", "Aplicación", "Adicionalmente", "Teresa", "Interior", "Messi",
    "Monederos de piel", "COMPRANDO A 18 0 36 MSI", "Precio de mayoreo Coca Cola",
])
def test_nombre_con_palabra_de_promo_sigue_siendo_producto(texto):
    res = _pagina([_bloque(texto, 100, 100), _bloque("$949", 100, 160)])
    assert [p.texto_raw for p in res.productos] == [texto]


# Las promos que hoy son PROMO no cambian de tipo (el juez y el dashboard las leen como promo)
@pytest.mark.parametrize("texto", ["GRATIS)", "(GRATIS", "de bonificación", "Envío gratis"])
def test_promo_sigue_siendo_promo(texto):
    res = _pagina([_bloque(texto, 100, 100), _bloque("$949", 100, 160)])
    assert [p.texto_raw for p in res.promos] == [texto]


# Un monto minimo de compra dentro de una condicion "Aplica ..." no se toca (regla de precio, fuera de alcance)
def test_condicion_aplica_con_monto_conserva_su_lectura():
    texto = "Aplica también en tiendas físicas:. Mínimo de compra $5,000.00."
    assert not EX._es_descarte(EX._limpiar_texto(texto))


def test_precio_toma_el_nombre_real_en_vez_del_rotulo():
    """Soriana: "Puntos" queda entre el nombre y el precio; el registro debe llevar el nombre real."""
    ocr = {"paginas": [{"pagina": "p.webp", "ancho_pagina": 1500, "bloques": [
        _bloque("Detergente Ariel 4 kg", 100, 40, ancho=300),
        _bloque("Puntos", 100, 100),
        _bloque("$149", 100, 160),
    ]}]}
    nlp = resultado_nlp(ocr, clasificar_paginas_ocr(ocr, EX))
    registros = construir_registros_pagina(nlp["paginas"][0], None, Normalizador())["precios"]
    assert [(r["producto"] or {}).get("texto") for r in registros] == ["Detergente Ariel 4 kg"]
