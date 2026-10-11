"""
Compara los registros de una pagina contra sus articulos del GT.

1. Emparejamiento uno a uno (asignacion optima, scipy.linear_sum_assignment): un registro
   nunca cuenta como acierto de dos articulos.
2. Un monto igual NO basta: dos productos pueden costar lo mismo. El puntaje combina precio
   y nombre, y un registro solo es correcto si el nombre tambien corresponde.
3. Cada registro equivocado y cada articulo perdido reciben UN codigo de error: el de la
   primera etapa donde fallo.
"""
import re
from dataclasses import dataclass, field

import numpy as np
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from nlp.evaluador_calidad import TOLERANCIA_PRECIO, corpus_de_bloques, recall_texto, tokens_significativos
from nlp.regex_extractor import RegexExtractor

from .gt import ArticuloGT
from .pipeline import PaginaPipeline, Registro

# Reglas del evaluador (protegidas: ver evaluador/integridad.py)
UMBRAL_PRODUCTO = 0.5      # similitud minima para que el producto "corresponda" (= UMBRAL_RECALL_TEXTO)
UMBRAL_CANDIDATO = 0.3     # sin precio igual, nombre minimo para considerar el par
PESO_PRECIO, PESO_NOMBRE = 0.6, 0.4
FUZZY_TOKEN = 85           # rapidfuzz.ratio para tokens de 4+ letras ("platano" ~ "piatano")

ERRORES_REGISTRO = ("precio_mal_leido", "asociacion_producto", "asociacion_antes",
                    "promo_como_producto", "duplicado", "precio_huerfano")
ERRORES_ARTICULO = ("ocr_no_leido", "clasificacion", "precio_mal_leido", "producto_descartado",
                    "asociacion_producto", "asociacion_antes")

_extractor_promos = RegexExtractor()


def precio_igual(a: float | None, b: float | None) -> bool:
    # Misma regla que nlp/evaluador_calidad: al centavo
    return a is not None and b is not None and abs(a - b) < TOLERANCIA_PRECIO


def anterior_igual(a: float | None, b: float | None) -> bool:
    return (a is None and b is None) or precio_igual(a, b)


def _token_coincide(t: str, otros: list[str]) -> bool:
    return t in otros or (len(t) >= 4 and any(len(o) >= 4 and fuzz.ratio(t, o) >= FUZZY_TOKEN for o in otros))


def tokens_tienda(tienda: str) -> set[str]:
    """'bodega_aurrera' -> {'bodega', 'aurrera'}: el nombre de la tienda no identifica un producto."""
    return set(tokens_significativos(tienda.replace("_", " ").replace("-", "")))


def similitud_nombre(nombre_gt: str, texto: str | None, ignorar: set[str] = frozenset()) -> float:
    """
    F1 de tokens significativos (tokens_significativos de evaluador_calidad: sin acentos,
    sin stopwords, 3+ letras). Precision = cuanto del registro esta en el nombre GT; recall =
    cuanto del nombre GT dice el registro. "Pan de caja" vs "Pan de caja Bimbo 680g" = 0.67.
    `ignorar`: tokens que no cuentan (el nombre de la tienda: "Alsuper Kg" no es "Queso poroso Alsuper").
    """
    tg = [t for t in tokens_significativos(nombre_gt) if t not in ignorar]
    tr = [t for t in tokens_significativos(texto or "") if t not in ignorar]
    if not tg or not tr:
        return 0.0
    p = sum(_token_coincide(t, tg) for t in tr) / len(tr)
    r = sum(_token_coincide(t, tr) for t in tg) / len(tg)
    return 0.0 if p + r == 0 else 2 * p * r / (p + r)


@dataclass
class Par:
    registro: Registro
    articulo: ArticuloGT
    precio_ok: bool
    similitud: float
    anterior_ok: bool
    categoria_ok: bool | None

    @property
    def producto_ok(self) -> bool:
        return self.similitud >= UMBRAL_PRODUCTO

    @property
    def basico_ok(self) -> bool:
        return self.precio_ok and self.producto_ok

    @property
    def completo_ok(self) -> bool:
        return self.basico_ok and self.anterior_ok

    @property
    def error(self) -> str | None:
        if self.completo_ok:
            return None
        if not self.precio_ok:
            return "precio_mal_leido"
        if not self.producto_ok:
            return "asociacion_producto"
        return "asociacion_antes"


@dataclass
class ResultadoPagina:
    pagina: PaginaPipeline
    pares: list[Par] = field(default_factory=list)
    registros_sobrantes: list[tuple[Registro, str]] = field(default_factory=list)   # (registro, codigo)
    articulos_perdidos: list[tuple[ArticuloGT, str]] = field(default_factory=list)  # (articulo, codigo)

    @property
    def registros_dashboard(self) -> list[Registro]:
        return [r for r in self.pagina.registros if r.en_dashboard]

    @property
    def articulos_con_precio(self) -> list[ArticuloGT]:
        return [a for a in self.pagina.gt.articulos if a.precio is not None]

    @property
    def evaluable(self) -> bool:
        # Pagina del GT sin ningun precio (ej. Costco con productos listados sin monto): no hay contra que
        # medir los registros, asi que la pagina no entra en las metricas en vez de contarlos como huerfanos
        return bool(self.articulos_con_precio)


def _puntaje(r: Registro, a: ArticuloGT) -> tuple[float, bool, float] | None:
    p_ok = precio_igual(r.precio, a.precio)
    sim = similitud_nombre(a.producto, r.producto, tokens_tienda(a.tienda))
    if not p_ok and sim < UMBRAL_CANDIDATO:
        return None
    return PESO_PRECIO * p_ok + PESO_NOMBRE * sim, p_ok, sim


def emparejar(registros: list[Registro], articulos: list[ArticuloGT]) -> list[tuple[Registro, ArticuloGT, bool, float]]:
    """Asignacion uno a uno que maximiza el puntaje total; pares sin candidatura quedan fuera."""
    if not registros or not articulos:
        return []
    info = {}
    m = np.zeros((len(registros), len(articulos)))
    for i, r in enumerate(registros):
        for j, a in enumerate(articulos):
            pts = _puntaje(r, a)
            if pts:
                m[i, j] = pts[0]
                info[i, j] = pts
    filas, cols = linear_sum_assignment(m, maximize=True)
    return [(registros[i], articulos[j], info[i, j][1], info[i, j][2])
            for i, j in zip(filas, cols) if (i, j) in info]


def _es_promo(texto: str, promociones: list[str]) -> bool:
    if not texto:
        return False
    if _extractor_promos._es_promo_fuerte(texto) or _extractor_promos._es_promo_debil(texto):
        return True
    return any(similitud_nombre(p, texto) >= UMBRAL_PRODUCTO for p in promociones)


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _firmas_precio(precio: float) -> list[str]:
    """Como puede aparecer el monto en el OCR: 29.90 -> '2990', '29' (centavos en superindice aparte)."""
    entero, centavos = int(precio), round((precio - int(precio)) * 100)
    firmas = [f"{entero}{centavos:02d}"] if centavos else []
    if len(str(entero)) >= 2 or not centavos:
        firmas.append(str(entero))
    return firmas


def _diagnosticar_perdida(a: ArticuloGT, pp: PaginaPipeline, registros_sin_producto: list[Registro]) -> str:
    """Primera etapa donde se perdio un articulo que no quedo en ningun par."""
    bloques = pp.ocr.get("bloques", []) if pp.ocr else []
    firmas = _firmas_precio(a.precio)
    if not any(f in _digitos(b.get("texto")) for b in bloques for f in firmas):
        return "ocr_no_leido"

    nlp = pp.nlp or {}
    precios_nlp = nlp.get("precios", [])
    if not any(precio_igual(p.get("valor"), a.precio) for p in precios_nlp):
        # El OCR lo leyo. Si algun PRECIO salio de un bloque con esos digitos, se leyo mal el monto;
        # si no, el bloque se clasifico como otra cosa (antes, ahorro, producto, descarte)
        if any(f in _digitos(p.get("texto")) for p in precios_nlp for f in firmas):
            return "precio_mal_leido"
        return "clasificacion"

    # Precio extraido bien: el problema es el producto
    if any(precio_igual(r.precio, a.precio) for r in registros_sin_producto):
        en_nlp, _ = recall_texto(a.producto, corpus_de_bloques(pp.productos_nlp))
        en_aceptados, _ = recall_texto(a.producto, corpus_de_bloques(pp.productos_aceptados))
        if en_nlp and not en_aceptados:
            return "producto_descartado"
    return "asociacion_producto"


def comparar_pagina(pp: PaginaPipeline) -> ResultadoPagina:
    res = ResultadoPagina(pp)
    if not res.evaluable:
        return res
    dashboard = res.registros_dashboard
    articulos = res.articulos_con_precio

    for r, a, p_ok, sim in emparejar(dashboard, articulos):
        cat_ok = None if a.categoria is None else (r.categoria == a.categoria)
        res.pares.append(Par(r, a, p_ok, sim, anterior_igual(r.precio_anterior, a.precio_anterior), cat_ok))

    emparejados_r = {id(p.registro) for p in res.pares}
    emparejados_a = {id(p.articulo) for p in res.pares}

    # Firmas de 3+ digitos: "20" aparece en casi cualquier texto, "219" o "2990" ya identifican el monto
    firmas_gt = {f for a in articulos for f in _firmas_precio(a.precio) if len(f) >= 3}
    for r in dashboard:
        if id(r) in emparejados_r:
            continue
        if _es_promo(r.producto, pp.gt.promociones) or _es_promo(r.producto_texto, pp.gt.promociones):
            codigo = "promo_como_producto"
        elif any(p.completo_ok and precio_igual(p.registro.precio, r.precio) for p in res.pares):
            codigo = "duplicado"
        elif any(f in _digitos(r.precio_texto) for f in firmas_gt):
            # "5219" -> 52.19 cuando el folleto dice $219: monto mal leido y, ademas, producto sin parecido
            codigo = "precio_mal_leido"
        else:
            codigo = "precio_huerfano"
        res.registros_sobrantes.append((r, codigo))

    sin_producto = [r for r in pp.registros if r.precio is not None and r.producto is None]
    for a in articulos:
        if id(a) not in emparejados_a:
            res.articulos_perdidos.append((a, _diagnosticar_perdida(a, pp, sin_producto)))
    return res
