# PriceScraper - Promociones por niveles en el dashboard (Fase 1 aprobada por la persona 15-oct-2026,
# docs/bi/metricas.md seccion 7). Modulo puro: sin BD, solo reglas y armado de estructuras.
#
# Niveles: promos = {"campania": [...], "producto": [...], "bancaria": [...]}.
#   campania  : campania del folleto (eventos_promo, ligada solo a folleto). Unico nivel con datos hoy.
#   producto  : 2x1, 3x2, %... (PROMO ligada a producto) -> pendiente de carga (load).
#   bancaria  : MSI, bancos -> pendiente de carga (load/NLP).
#
# Mapa PROVISIONAL de eventos_promo.nombre_evento a slugs canonicos. Los slugs son los acordados con el especialista
# de producto, que hace el arreglo de fondo en el pipeline (slugs canonicos, lemas y letra chica fuera, fechas desde
# el folleto). Acepta tanto las variantes actuales (OCR, frases) como los slugs ya canonicos: cuando se recargue con
# el pipeline nuevo el dashboard sigue igual. Las mismas reglas estan en SQL en
# docs/bi/consultas/promociones_campanias.sql (si cambian aqui, cambiar alla; lo vigila una prueba).

import re
from typing import Iterable, Optional

# slug canonico -> nombre legible (orden = orden de presentacion)
CAMPANIAS = {
    "julio_regalado": "Julio Regalado",
    "hot_sale": "Hot Sale",
    "buen_fin": "Buen Fin",
    "regreso_a_clases": "Regreso a clases",
    "navidad": "Navidad",
    "halloween_dia_de_muertos": "Halloween / Día de Muertos",
    "liquidacion": "Liquidación",
    "aniversario": "Aniversario",
    "ofertones": "Ofertones",
    "fiestas_patrias": "Fiestas Patrias",
}

CLASE_CAMPANIA = "campania"
CLASE_LEMA = "lema"
CLASE_LEGAL = "legal"
CLASE_PRODUCTO = "producto"
CLASE_OTRO = "otro"
CLASES = (CLASE_CAMPANIA, CLASE_LEMA, CLASE_LEGAL, CLASE_PRODUCTO, CLASE_OTRO)
NOMBRES_CLASE = {
    CLASE_CAMPANIA: "Campaña",
    CLASE_LEMA: "Lema de la tienda",
    CLASE_LEGAL: "Texto legal",
    CLASE_PRODUCTO: "Nombre de producto",
    CLASE_OTRO: "Otro",
}

NIVELES = ("campania", "producto", "bancaria")
NIVELES_CON_DATOS = ("campania",)  # producto y bancaria: pendiente de carga

# Reglas en orden de precedencia (se evalua sobre nombre_evento en minusculas). Los nombres actuales vienen como
# slug del texto con los acentos perdidos ("liquidacin", "da_de_muertos"), por eso los patrones son prefijos cortos.
# 1) nombre de producto que contiene la palabra de temporada ("vela aromatica navidad", "back to school 100 hojas")
REGLA_PRODUCTO = r"(vela|figura|bao_navidad|hojas|cumplea|diferentes_)"
# 2) letra chica / condiciones ("excepto codigos de liquidacion", "tiendas participantes", "sucursales")
REGLA_LEGAL = r"(excepto|participantes|sucursales|apllcan|aplican|restriccion)"
# 3) campanias (slug canonico -> patron)
REGLAS_CAMPANIA = (
    ("julio_regalado", r"julio_?regalad"),
    ("hot_sale", r"hot_?sale"),
    ("buen_fin", r"buen_?fin"),
    ("regreso_a_clases", r"(regreso_a_clases|back_to_school)"),
    ("halloween_dia_de_muertos", r"(halloween|muertos)"),
    ("navidad", r"navid"),
    ("liquidacion", r"liquidaci"),
    ("aniversario", r"aniversario"),
    ("ofertones", r"ofert(o)?n"),
    ("fiestas_patrias", r"fiestas?_?patrias"),
)
# 4) lemas permanentes ("precios bajos todos los dias", "la supercampeona", "precio especial", "super oferta")
REGLA_LEMA = r"(precio|supercamp|calidad_a|oferta)"


def clasificar_evento(nombre_evento: Optional[str]) -> tuple[str, Optional[str]]:
    """(clase, slug). slug solo para clase campania. Un slug canonico se acepta tal cual."""
    nombre = (nombre_evento or "").strip().lower()
    if nombre in CAMPANIAS:
        return CLASE_CAMPANIA, nombre
    if re.search(REGLA_PRODUCTO, nombre):
        return CLASE_PRODUCTO, None
    if re.search(REGLA_LEGAL, nombre):
        return CLASE_LEGAL, None
    for slug, patron in REGLAS_CAMPANIA:
        if re.search(patron, nombre):
            return CLASE_CAMPANIA, slug
    if re.search(REGLA_LEMA, nombre):
        return CLASE_LEMA, None
    return CLASE_OTRO, None


def etiqueta(slug: str) -> dict:
    return {"slug": slug, "nombre": CAMPANIAS.get(slug, slug)}


def _orden(slug: str) -> int:
    return list(CAMPANIAS).index(slug) if slug in CAMPANIAS else len(CAMPANIAS)


def campanias_por_folleto(eventos: Iterable[dict]) -> dict:
    """eventos: dicts con folleto_id y nombre_evento -> {folleto_id: [etiqueta, ...]} solo clase campania,
    sin repetir slug por folleto (p. ej. "julioregalado" y "julio_regalado" en el mismo folleto cuentan una vez)."""
    por_folleto: dict = {}
    for ev in eventos:
        clase, slug = clasificar_evento(ev["nombre_evento"])
        if clase == CLASE_CAMPANIA:
            por_folleto.setdefault(ev["folleto_id"], set()).add(slug)
    return {f: [etiqueta(s) for s in sorted(slugs, key=_orden)] for f, slugs in por_folleto.items()}


def promos_vacias() -> dict:
    return {nivel: [] for nivel in NIVELES}


def combinar_promos(filas: list[dict], campanias: dict, campo: str = "folleto_id") -> list[dict]:
    """Agrega fila["promos"] a cada fila sin agregar ni quitar filas (len de salida = len de entrada)."""
    for fila in filas:
        promos = promos_vacias()
        promos["campania"] = list(campanias.get(fila.get(campo), []))
        fila["promos"] = promos
    return filas


def normalizar_promocion(valor) -> Optional[str]:
    """Filtro "Promocion": 'con' | 'sin' | None (todos)."""
    v = (valor or "").strip().lower()
    return v if v in ("con", "sin") else None


def normalizar_nivel(valor) -> Optional[str]:
    """Filtro "Nivel": 'campania' | 'producto' | 'bancaria' | None (todos los niveles)."""
    v = (valor or "").strip().lower()
    return v if v in NIVELES else None


def normalizar_campanias(valores) -> list[str]:
    """Filtro "Campania": solo slugs canonicos conocidos, sin repetir, en orden canonico."""
    return sorted({v.strip().lower() for v in (valores or []) if v and v.strip().lower() in CAMPANIAS}, key=_orden)
