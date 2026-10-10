# Consultas del dashboard de visualizacion via Django ORM.

from typing import Optional

from django.db.models import Count, F, Max, Q

from dashboard.models import (
    ErrorCarga,
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


# -- Explorador crudo de la BD (sin agregaciones de negocio) --------------------

def listar_tiendas_detalle() -> list[dict]:
    return list(
        Tienda.objects
        .annotate(num_folletos=Count("folletos"))
        .order_by("nombre")
        .values("id", "nombre", "slug", "fuente_slug", "activa", "created_at", "num_folletos")
    )


def listar_folletos(tienda_id: Optional[str] = None, limite: int = 200) -> list[dict]:
    qs = Folleto.objects.all()
    if tienda_id:
        qs = qs.filter(tienda_id=tienda_id)
    qs = qs.order_by("-created_at")[:limite]
    return list(qs.values(
        "id", "tienda__nombre", "fuente", "folleto_id_fuente", "titulo",
        "fecha_inicio", "fecha_fin", "total_paginas", "estado", "scrapeado_at", "created_at",
    ))


def listar_tipos_extraccion() -> list[str]:
    return list(
        Extraccion.objects.order_by("tipo").values_list("tipo", flat=True).distinct()
    )


def listar_extracciones(
    tienda_id: Optional[str] = None,
    folleto_id: Optional[str] = None,
    tipo: Optional[str] = None,
    limite: int = 200,
) -> list[dict]:
    qs = Extraccion.objects.all()
    if tienda_id:
        qs = qs.filter(tienda_id=tienda_id)
    if folleto_id:
        qs = qs.filter(folleto_id=folleto_id)
    if tipo:
        qs = qs.filter(tipo=tipo)

    qs = qs.order_by("-created_at")[:limite]
    return list(qs.values(
        "id", "tienda__nombre", "folleto_id", "tipo", "texto_raw", "texto_norm",
        "categoria_nlp", "valor", "valor_anterior", "texto_promo", "confianza_ocr",
        "producto_canonico__nombre_canonico", "created_at",
    ))


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


# -- Errores de carga (tabla errores_carga) ---------------------------------------

def listar_tiendas_error() -> list[str]:
    return list(
        ErrorCarga.objects
        .exclude(tienda_slug__isnull=True)
        .order_by("tienda_slug")
        .values_list("tienda_slug", flat=True)
        .distinct()
    )


def _filtrar_errores(categorias, tiendas, fuente, estado):
    qs = ErrorCarga.objects.all()
    if categorias:
        qs = qs.filter(categoria__in=categorias)
    if tiendas:
        qs = qs.filter(tienda_slug__in=tiendas)
    if fuente:
        qs = qs.filter(fuente=fuente)
    if estado == "abiertos":
        qs = qs.filter(resuelto=False)
    elif estado == "resueltos":
        qs = qs.filter(resuelto=True)
    return qs


def errores_carga(
    categorias: Optional[list[str]] = None,
    tiendas: Optional[list[str]] = None,
    fuente: Optional[str] = None,
    estado: Optional[str] = None,
    limite: int = 1000,
) -> dict:
    # KPIs sobre toda la tabla (estado general); grafica y tabla respetan los filtros
    abiertos = ErrorCarga.objects.filter(resuelto=False)
    kpis = {
        "abiertos": abiertos.count(),
        "folletos_afectados": abiertos.values("fuente", "folleto_id_fuente").distinct().count(),
        "resueltos": ErrorCarga.objects.filter(resuelto=True).count(),
        "ultima_corrida": ErrorCarga.objects.aggregate(m=Max("corrida_at"))["m"],
    }

    qs = _filtrar_errores(categorias, tiendas, fuente, estado)

    # Todas las categorias, aunque tengan 0, para que el eje no cambie con los filtros
    conteo = dict(qs.values_list("categoria").annotate(n=Count("id")))
    por_categoria = [{"categoria": c, "n": conteo.get(c, 0)} for c in ErrorCarga.CATEGORIAS]

    filas = list(qs.order_by("-corrida_at", "fuente", "folleto_id_fuente", "pagina")[:limite].values(
        "id", "corrida_at", "fuente", "tienda_slug", "folleto_id_fuente", "pagina",
        "categoria", "sqlstate", "mensaje", "detalle", "ruta_archivo", "resuelto", "resuelto_at",
    ))
    return {"kpis": kpis, "por_categoria": por_categoria, "filas": filas}
