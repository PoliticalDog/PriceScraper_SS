"""
dashboard/queries.py
PriceScraper - Consultas del dashboard de visualizacion via Django ORM.

Migrado de SQL crudo (psycopg directo) a QuerySets (23-ago-2026) para cumplir
"Django ORM para la capa de acceso" segun Propuesta_PriceScraper_SS.docx.
load/load.py (la fase de ETL/carga) sigue en SQL crudo a proposito -- ver
memoria de la sesion: reescribirlo se considero mas riesgo que beneficio
justo despues de haberlo validado a fondo contra Postgres real.

Nota de tipos: columnas definidas como ROUND(...::NUMERIC) en load/vistas.sql
(descuento_pct, precio_promedio, confianza_ocr_prom, tasa_util_prom) llegan
como Decimal via el ORM -- Django las serializaria como string en JSON
(DjangoJSONEncoder), distinto al comportamiento anterior con psycopg+FastAPI
(que las devolvia como numero). Se castea a float explicitamente donde
aplica para mantener el mismo contrato de API.
"""

from typing import Optional

from django.db.models import Count, F, Max, Q

from dashboard.models import (
    Extraccion,
    Folleto,
    ProductoCanonico,
    Tienda,
    VCalidadPipeline,
    VComparativaPrecios,
    VEventosActivos,
    VHistoricoPrecios,
    VPreciosActuales,
)


def _num(valor):
    """Castea Decimal/None a float, para que el JSON de salida sea numero."""
    return float(valor) if valor is not None else None


# -- Filtros compartidos ------------------------------------------------------

def listar_tiendas() -> list[dict]:
    return list(
        Tienda.objects.filter(activa=True).order_by("nombre").values("id", "nombre", "slug")
    )


def listar_categorias() -> list[str]:
    return list(
        ProductoCanonico.objects
        .exclude(categoria__isnull=True)
        .exclude(categoria="")
        .order_by("categoria")
        .values_list("categoria", flat=True)
        .distinct()
    )


# -- Resumen (home) -----------------------------------------------------------

def resumen_kpis() -> dict:
    return {
        "tiendas_activas": Tienda.objects.filter(activa=True).count(),
        "total_folletos": Folleto.objects.count(),
        "productos_con_precio": Extraccion.objects.filter(tipo="PRECIO", valor__isnull=False).count(),
        "folleto_mas_reciente": Folleto.objects.aggregate(m=Max("fecha_inicio"))["m"],
    }


def resumen_top_categorias(limite: int = 10) -> list[dict]:
    qs = (
        Extraccion.objects
        .filter(tipo="PRECIO")
        .exclude(producto_canonico__categoria__isnull=True)
        .exclude(producto_canonico__categoria="")
        .values(categoria=F("producto_canonico__categoria"))
        .annotate(n=Count("id"))
        .order_by("-n")[:limite]
    )
    return list(qs)


def resumen_folletos_por_tienda() -> list[dict]:
    # "tienda" no se puede usar como alias en .values() -- Folleto ya tiene un
    # campo real llamado "tienda" (la FK) y Django rechaza la colision con
    # ValueError("The annotation 'tienda' conflicts with a field on the
    # model."). Se pide "tienda__nombre" tal cual y se renombra la clave
    # despues de materializar.
    qs = (
        Folleto.objects
        .values("tienda__nombre")
        .annotate(n=Count("id"))
        .order_by("-n")
    )
    return [{"tienda": f["tienda__nombre"], "n": f["n"]} for f in qs]


# -- Precios actuales -----------------------------------------------------------

def precios_actuales(
    tiendas: Optional[list[str]] = None,
    categorias: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    q: Optional[str] = None,
    solo_descuento: bool = False,
    limite: int = 500,
) -> list[dict]:
    qs = VPreciosActuales.objects.all()

    if tiendas:
        qs = qs.filter(tienda__in=tiendas)
    if categorias:
        qs = qs.filter(categoria__in=categorias)
    if desde:
        qs = qs.filter(vigencia_desde__gte=desde)
    if hasta:
        qs = qs.filter(vigencia_hasta__lte=hasta)
    if q:
        qs = qs.filter(producto__icontains=q)
    if solo_descuento:
        qs = qs.exclude(descuento_pct__isnull=True)

    qs = qs.order_by(F("descuento_pct").desc(nulls_last=True))[:limite]

    filas = list(qs.values(
        "tienda", "producto", "categoria", "precio_actual", "precio_anterior",
        "descuento_pct", "vigencia_desde", "vigencia_hasta", "confianza_ocr",
    ))
    for f in filas:
        f["descuento_pct"] = _num(f["descuento_pct"])
    return filas


# -- Comparativa entre tiendas --------------------------------------------------

def comparativa_precios(
    categorias: Optional[list[str]] = None,
    q: Optional[str] = None,
    min_tiendas: int = 1,
    limite: int = 300,
) -> list[dict]:
    qs = VComparativaPrecios.objects.filter(num_tiendas__gte=min_tiendas)

    if categorias:
        qs = qs.filter(categoria__in=categorias)
    if q:
        qs = qs.filter(producto__icontains=q)

    qs = qs.order_by("-diferencia")[:limite]

    filas = list(qs.values(
        "producto", "categoria", "precio_min", "precio_max", "precio_promedio",
        "diferencia", "num_registros", "num_tiendas", "tiendas",
    ))
    for f in filas:
        f["precio_promedio"] = _num(f["precio_promedio"])
    return filas


def comparativa_por_tienda(producto: str) -> list[dict]:
    # Mismo motivo que resumen_folletos_por_tienda(): "tienda" colisiona con
    # el campo FK real de Extraccion, no se puede usar como alias en .values().
    qs = (
        Extraccion.objects
        .filter(tipo="PRECIO", valor__isnull=False, texto_norm=producto)
        .values("tienda__nombre", "valor")
        .order_by("valor")
    )
    return [{"tienda": f["tienda__nombre"], "precio": f["valor"]} for f in qs]


# -- Historico de precios --------------------------------------------------------

def historico_precios(
    producto: str,
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
) -> list[dict]:
    qs = VHistoricoPrecios.objects.filter(producto=producto)

    if tiendas:
        qs = qs.filter(tienda__in=tiendas)
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)

    qs = qs.order_by("fecha")
    return list(qs.values("tienda", "producto", "categoria", "fecha", "precio", "precio_anterior"))


def sugerir_productos(q: str, limite: int = 20) -> list[str]:
    if not q:
        return []
    return list(
        ProductoCanonico.objects
        .filter(nombre_canonico__icontains=q)
        .order_by("nombre_canonico")
        .values_list("nombre_canonico", flat=True)
        .distinct()[:limite]
    )


# -- Calidad del pipeline ---------------------------------------------------------

def calidad_pipeline(
    tiendas: Optional[list[str]] = None,
    fuente: Optional[str] = None,
    estado: Optional[str] = None,
    tasa_util_min: Optional[float] = None,
    limite: int = 500,
) -> list[dict]:
    qs = VCalidadPipeline.objects.all()

    if tiendas:
        qs = qs.filter(tienda__in=tiendas)
    if fuente:
        qs = qs.filter(fuente=fuente)
    if estado:
        qs = qs.filter(estado=estado)
    if tasa_util_min is not None:
        qs = qs.filter(Q(tasa_util_prom__isnull=True) | Q(tasa_util_prom__gte=tasa_util_min))

    qs = qs.order_by(F("tasa_util_prom").asc(nulls_last=True))[:limite]

    filas = list(qs.values(
        "folleto_id", "tienda", "folleto_id_fuente", "fuente", "fecha_inicio",
        "total_paginas", "paginas_procesadas", "confianza_ocr_prom", "tasa_util_prom", "estado",
    ))
    for f in filas:
        f["confianza_ocr_prom"] = _num(f["confianza_ocr_prom"])
        f["tasa_util_prom"] = _num(f["tasa_util_prom"])
    return filas


# -- Promociones y eventos ---------------------------------------------------------

def eventos_promo(
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    limite: int = 300,
) -> list[dict]:
    qs = VEventosActivos.objects.all()

    if tiendas:
        qs = qs.filter(tienda__in=tiendas)
    if desde:
        qs = qs.filter(fecha_inicio__gte=desde)
    if hasta:
        qs = qs.filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__lte=hasta))

    qs = qs.order_by("-fecha_inicio")[:limite]

    return list(qs.values("nombre_evento", "tienda", "fecha_inicio", "fecha_fin", "num_precios_asociados"))
