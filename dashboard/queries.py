# Consultas del dashboard de visualizacion via Django ORM.

from typing import Optional

from django.db import connection
from django.db.models import Count, F, Max, Q

from dashboard import confiabilidad, origen
from dashboard.models import (
    ErrorCarga,
    Extraccion,
    Folleto,
    Pagina,
    ProductoCanonico,
    Tienda,
    VCalidadPipeline,
    VComparativaPrecios,
    VEventosActivos,
    VFolletosVigencia,
    VHistoricoPrecios,
    VPreciosActuales,
)


def _num(valor):
    """Castea Decimal/None a float, para que el JSON de salida sea numero."""
    return float(valor) if valor is not None else None


def _filas_sql(sql: str, params: dict) -> list[dict]:
    """Ejecuta un SELECT de solo lectura y devuelve una lista de dicts."""
    with connection.cursor() as cur:
        cur.execute(sql, params)
        columnas = [c[0] for c in cur.description]
        return [dict(zip(columnas, fila)) for fila in cur.fetchall()]


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
    # Corregido 12-oct-2026 (aprobado por la persona, docs/bi/metricas.md "3. KPIs del Resumen"):
    # - "productos_con_precio" contaba PRECIO con valor (28,867) e incluia filas sin texto_norm que ningun
    #   panel muestra; ahora son los registros del dashboard = v_precios_actuales (28,634).
    # - "folleto_mas_reciente" (MAX(fecha_inicio)) mostraba 2026-12-25 por fechas anomalas; se reemplaza por
    #   folletos vigentes hoy segun v_folletos_vigencia (unica definicion de vigencia).
    vigencia = VFolletosVigencia.objects.aggregate(
        vigentes=Count("id", filter=Q(vigente=True)),
        dudosos=Count("id", filter=Q(vigente_dudoso=True)),
    )
    return {
        "tiendas_activas": Tienda.objects.filter(activa=True).count(),
        "total_folletos": Folleto.objects.count(),
        "registros_dashboard": VPreciosActuales.objects.count(),
        "folletos_vigentes": vigencia["vigentes"],
        "folletos_vigentes_dudosos": vigencia["dudosos"],
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
        "id", "tienda", "producto", "categoria", "precio_actual", "precio_anterior",
        "descuento_pct", "vigencia_desde", "vigencia_hasta", "confianza_ocr",
    ))
    for f in filas:
        f["descuento_pct"] = _num(f["descuento_pct"])
    return agregar_procedencia(filas)


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
    # 13-oct-2026: + vigencia y procedencia (folleto/pagina) por registro para el detalle por tienda.
    # Mismo filtro que v_comparativa_precios (texto_norm no nulo queda implicito en texto_norm=producto).
    qs = (
        Extraccion.objects
        .filter(tipo="PRECIO", valor__isnull=False, texto_norm=producto)
        .values(
            "id", "tienda__nombre", "valor", "folleto__fecha_inicio", "folleto__fecha_fin",
            "pagina_id", "pagina__numero_pagina", "folleto_id", "folleto__folleto_id_fuente",
            "folleto__titulo", "folleto__url_origen",
        )
        .order_by("valor", "id")
    )
    return [{
        "id": f["id"],
        "tienda": f["tienda__nombre"],
        "precio": f["valor"],
        "vigencia_desde": f["folleto__fecha_inicio"],
        "vigencia_hasta": f["folleto__fecha_fin"],
        **_procedencia_de_valores(f),
    } for f in qs]


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

    qs = qs.order_by("fecha", "id")
    filas = list(qs.values("id", "tienda", "producto", "categoria", "fecha", "precio", "precio_anterior"))
    return agregar_procedencia(filas)


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


# -- Confiabilidad del dato por tienda (Panel 1, docs/bi/metricas.md seccion 1) ----------
# Parte BD = docs/bi/consultas/confiabilidad_por_tienda.sql con filtros. Grano: tienda (todas, aunque no tengan
# registros). PRECIO -> PRODUCTO (producto_extraccion_id) es N:1: no duplica filas de PRECIO. metodo_norm vive en
# la fila PRODUCTO. Sin exclusiones: describe el dato tal como lo ve el dashboard.
_SQL_CONFIABILIDAD = """
WITH base AS (
    SELECT e.id, e.tienda_id, e.folleto_id, e.pagina_id, e.texto_norm, e.valor, e.confianza_ocr,
           e.categoria_nlp, p.metodo_norm
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND (%(desde)s::date IS NULL OR f.fecha_inicio >= %(desde)s::date)
      AND (%(hasta)s::date IS NULL OR f.fecha_inicio <= %(hasta)s::date)
),
dup AS (
    SELECT tienda_id, SUM(n - 1)::bigint AS sobrantes
    FROM (SELECT tienda_id, folleto_id, pagina_id, texto_norm, valor, COUNT(*) AS n
          FROM base GROUP BY 1, 2, 3, 4, 5 HAVING COUNT(*) > 1) d
    GROUP BY tienda_id
),
agg AS (
    SELECT tienda_id,
           COUNT(*)                                                                 AS registros,
           COUNT(*) FILTER (WHERE metodo_norm IN ('exacto', 'fuzzy', 'fuzzy_bajo')) AS reg_catalogo,
           COUNT(*) FILTER (WHERE metodo_norm = 'heuristico')                       AS reg_heuristico,
           COUNT(*) FILTER (WHERE COALESCE(categoria_nlp, '') = '')                 AS reg_sin_categoria,
           COUNT(*) FILTER (WHERE valor < 1 OR valor > 100000)                      AS reg_atipicos,
           AVG(confianza_ocr)                                                       AS conf_ocr_media,
           PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY confianza_ocr)               AS conf_ocr_mediana,
           COUNT(DISTINCT folleto_id)                                               AS folletos
    FROM base GROUP BY tienda_id
)
SELECT t.slug                                                                     AS tienda_slug,
       t.nombre                                                                   AS tienda,
       COALESCE(a.registros, 0)                                                   AS registros,
       COALESCE(a.reg_catalogo, 0)                                                AS reg_catalogo,
       COALESCE(a.reg_sin_categoria, 0)                                           AS reg_sin_categoria,
       COALESCE(a.folletos, 0)                                                    AS folletos_con_precio,
       ROUND(100.0 * a.reg_catalogo      / NULLIF(a.registros, 0), 1)::float8     AS pct_catalogo,
       ROUND(100.0 * a.reg_heuristico    / NULLIF(a.registros, 0), 1)::float8     AS pct_heuristico,
       ROUND(100.0 * a.reg_sin_categoria / NULLIF(a.registros, 0), 1)::float8     AS pct_sin_categoria,
       ROUND(a.conf_ocr_media::numeric, 3)::float8                                AS conf_ocr_media,
       ROUND(a.conf_ocr_mediana::numeric, 3)::float8                              AS conf_ocr_mediana,
       ROUND(100.0 * COALESCE(d.sobrantes, 0) / NULLIF(a.registros, 0), 1)::float8 AS pct_duplicados,
       COALESCE(a.reg_atipicos, 0)                                                AS atipicos
FROM tiendas t
LEFT JOIN agg a ON a.tienda_id = t.id
LEFT JOIN dup d ON d.tienda_id = t.id
WHERE (%(tiendas)s::text[] IS NULL OR t.nombre = ANY(%(tiendas)s::text[]))
ORDER BY registros DESC, t.nombre
"""


def confiabilidad_por_tienda(
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
) -> dict:
    filas = _filas_sql(_SQL_CONFIABILIDAD, {"tiendas": tiendas or None, "desde": desde, "hasta": hasta})
    corrida = confiabilidad.corrida_vigente()
    total = sum(f["registros"] for f in filas)
    catalogo = sum(f["reg_catalogo"] for f in filas)
    sin_categoria = sum(f["reg_sin_categoria"] for f in filas)
    return {
        "corrida": confiabilidad.info_corrida(corrida),
        "totales": {
            "registros": total,
            "pct_catalogo": round(100.0 * catalogo / total, 1) if total else None,
            "pct_heuristico": round(100.0 * (total - catalogo) / total, 1) if total else None,
            "pct_sin_categoria": round(100.0 * sin_categoria / total, 1) if total else None,
        },
        "umbrales": {
            "registros_minimos": confiabilidad.UMBRAL_REGISTROS_MINIMOS,
            "precision_media": confiabilidad.UMBRAL_PRECISION_MEDIA,
            "precision_aceptable": confiabilidad.UMBRAL_PRECISION_ACEPTABLE,
            "ic95_inferior_aceptable": confiabilidad.UMBRAL_IC95_INFERIOR_ACEPTABLE,
            "pct_catalogo_base_heuristica": confiabilidad.UMBRAL_PCT_CATALOGO_BASE_HEURISTICA,
        },
        "filas": confiabilidad.unir_confiabilidad(filas, corrida),
    }


# -- Cobertura y frescura (Panel 2, docs/bi/metricas.md seccion 2) --------------------------
# Vigencia: UNICA definicion = v_folletos_vigencia (load/vistas.sql). Los umbrales viven en la vista; estas
# constantes los replican solo para mostrarlos en el panel y documentarlos (si cambia la vista, cambiarlas aqui).
DIAS_INICIO_ANTIGUO = 365        # fecha_inicio < scrapeado_at - 365 dias -> inicio_antiguo
DIAS_INICIO_FUTURO = 30          # fecha_inicio > scrapeado_at + 30 dias  -> inicio_futuro_vs_scrapeo
DIAS_VIGENCIA_LARGA = 120        # fecha_fin - fecha_inicio > 120 dias    -> vigencia_larga
# Etiquetas cuya fecha de INICIO no es confiable: se excluyen de "ultimo folleto" y de la serie semanal.
# vigencia_larga si cuenta (su inicio es plausible; lo dudoso es el fin).
ANOMALIAS_INICIO_NO_CONFIABLE = ("sin_fecha", "fin_antes_inicio", "inicio_antiguo", "inicio_futuro_vs_scrapeo")
# Serie semanal por defecto: ultimas 26 semanas hasta 30 dias adelante (incluye proximos).
DIAS_SERIE_ATRAS = 182
DIAS_SERIE_ADELANTE = 30

# paginas y extracciones se agregan a grano folleto POR SEPARADO antes de unir (unirlas directo multiplicaria
# paginas x precios). errores_carga no tiene FK: se une por tienda_slug.
_SQL_COBERTURA = """
WITH pag AS (
    SELECT folleto_id, COUNT(*) AS paginas, COUNT(*) FILTER (WHERE total_precios > 0) AS paginas_con_precio
    FROM paginas GROUP BY folleto_id
),
pre AS (
    SELECT folleto_id, COUNT(*) AS precios
    FROM extracciones
    WHERE tipo = 'PRECIO' AND valor IS NOT NULL AND texto_norm IS NOT NULL
    GROUP BY folleto_id
),
err AS (
    SELECT tienda_slug, COUNT(*) FILTER (WHERE NOT resuelto) AS abiertos, COUNT(*) AS total
    FROM errores_carga GROUP BY tienda_slug
),
x AS (
    SELECT v.tienda_id,
           COUNT(*)                                                     AS folletos_total,
           COUNT(*) FILTER (WHERE v.vigente)                            AS folletos_vigentes,
           COUNT(*) FILTER (WHERE v.vigente_dudoso)                     AS vigentes_fecha_dudosa,
           COUNT(*) FILTER (WHERE v.proximo)                            AS proximos,
           COUNT(*) FILTER (WHERE v.anomalia_fecha IS NOT NULL)         AS folletos_fecha_anomala,
           MAX(v.fecha_inicio) FILTER (WHERE v.fecha_inicio <= CURRENT_DATE
                 AND (v.anomalia_fecha IS NULL OR v.anomalia_fecha <> ALL(%(anom)s::text[])))
                                                                        AS fecha_ultimo_folleto,
           MAX(v.scrapeado_at)                                          AS ultimo_scrapeo,
           -- ::bigint: SUM de un COUNT es numeric y Django lo serializaria como texto en el JSON
           SUM(COALESCE(p.paginas, 0))::bigint                                  AS paginas_total,
           SUM(COALESCE(p.paginas, 0)) FILTER (WHERE v.vigente)::bigint         AS paginas_vigentes,
           SUM(COALESCE(p.paginas_con_precio, 0)) FILTER (WHERE v.vigente)::bigint AS paginas_vig_con_precio,
           SUM(COALESCE(r.precios, 0)) FILTER (WHERE v.vigente)::bigint         AS precios_vigentes,
           SUM(COALESCE(r.precios, 0))::bigint                                  AS precios_total
    FROM v_folletos_vigencia v
    LEFT JOIN pag p ON p.folleto_id = v.id
    LEFT JOIN pre r ON r.folleto_id = v.id
    GROUP BY v.tienda_id
)
SELECT t.slug                                         AS tienda_slug,
       t.nombre                                       AS tienda,
       COALESCE(x.folletos_total, 0)                  AS folletos_total,
       COALESCE(x.folletos_vigentes, 0)               AS folletos_vigentes,
       COALESCE(x.vigentes_fecha_dudosa, 0)           AS vigentes_fecha_dudosa,
       COALESCE(x.proximos, 0)                        AS proximos,
       x.fecha_ultimo_folleto,
       CURRENT_DATE - x.fecha_ultimo_folleto          AS dias_desde_ultimo,
       x.ultimo_scrapeo::date                         AS ultimo_scrapeo,
       COALESCE(x.paginas_vigentes, 0)                AS paginas_vigentes,
       COALESCE(x.paginas_vig_con_precio, 0)          AS paginas_vig_con_precio,
       COALESCE(x.precios_vigentes, 0)                AS precios_vigentes,
       COALESCE(x.paginas_total, 0)                   AS paginas_total,
       COALESCE(x.precios_total, 0)                   AS precios_total,
       COALESCE(x.folletos_fecha_anomala, 0)          AS folletos_fecha_anomala,
       COALESCE(e.abiertos, 0)                        AS errores_abiertos,
       COALESCE(e.total, 0)                           AS errores_total
FROM tiendas t
LEFT JOIN x   ON x.tienda_id = t.id
LEFT JOIN err e ON e.tienda_slug = t.slug
WHERE (%(tiendas)s::text[] IS NULL OR t.nombre = ANY(%(tiendas)s::text[]))
ORDER BY folletos_vigentes DESC, dias_desde_ultimo NULLS LAST, t.nombre
"""

_SQL_FOLLETOS_SEMANA = """
SELECT DATE_TRUNC('week', v.fecha_inicio)::date AS semana,
       v.tienda                                  AS tienda,
       COUNT(*)                                  AS folletos
FROM v_folletos_vigencia v
WHERE (v.anomalia_fecha IS NULL OR v.anomalia_fecha <> ALL(%(anom)s::text[]))
  AND v.fecha_inicio >= COALESCE(%(desde)s::date, CURRENT_DATE - %(atras)s::int)
  AND v.fecha_inicio <= COALESCE(%(hasta)s::date, CURRENT_DATE + %(adelante)s::int)
  AND (%(tiendas)s::text[] IS NULL OR v.tienda = ANY(%(tiendas)s::text[]))
GROUP BY 1, 2
ORDER BY 1, 2
"""

# 13-oct-2026 (procedencia): + url_origen y la primera pagina del folleto. folletos se une por PK (1:1 con la vista)
# y la pagina es subconsulta escalar: ninguno duplica filas.
_SQL_FOLLETOS_DUDOSOS = """
SELECT v.tienda, v.folleto_id_fuente, v.fuente, v.titulo, v.fecha_inicio, v.fecha_fin,
       v.scrapeado_at::date AS scrapeado, v.anomalia_fecha, v.vigente_dudoso,
       f.url_origen,
       (SELECT p.id FROM paginas p WHERE p.folleto_id = v.id
        ORDER BY p.numero_pagina LIMIT 1)                       AS primera_pagina_id
FROM v_folletos_vigencia v
JOIN folletos f ON f.id = v.id
WHERE v.anomalia_fecha IS NOT NULL
  AND (%(tiendas)s::text[] IS NULL OR v.tienda = ANY(%(tiendas)s::text[]))
ORDER BY v.anomalia_fecha, v.tienda, v.fecha_inicio
"""


def cobertura_por_tienda(tiendas: Optional[list[str]] = None) -> dict:
    params = {"tiendas": tiendas or None, "anom": list(ANOMALIAS_INICIO_NO_CONFIABLE)}
    filas = _filas_sql(_SQL_COBERTURA, params)
    ultimo_scrapeo = max((f["ultimo_scrapeo"] for f in filas if f["ultimo_scrapeo"]), default=None)
    return {
        "kpis": {
            "tiendas": len(filas),
            "tiendas_con_vigente": sum(1 for f in filas if f["folletos_vigentes"]),
            "folletos_vigentes": sum(f["folletos_vigentes"] for f in filas),
            "vigentes_fecha_dudosa": sum(f["vigentes_fecha_dudosa"] for f in filas),
            "proximos": sum(f["proximos"] for f in filas),
            "precios_vigentes": sum(f["precios_vigentes"] for f in filas),
            "paginas_vigentes": sum(f["paginas_vigentes"] for f in filas),
            "ultimo_scrapeo": ultimo_scrapeo,
        },
        "umbrales": {
            "dias_inicio_antiguo": DIAS_INICIO_ANTIGUO,
            "dias_inicio_futuro": DIAS_INICIO_FUTURO,
            "dias_vigencia_larga": DIAS_VIGENCIA_LARGA,
        },
        "filas": filas,
        "dudosos": _dudosos(tiendas),
    }


def _dudosos(tiendas: Optional[list[str]]) -> list[dict]:
    filas = _filas_sql(_SQL_FOLLETOS_DUDOSOS, {"tiendas": tiendas or None})
    for f in filas:
        f["url_origen"] = origen.url_origen_segura(f["url_origen"])
    return filas


def folletos_por_semana(
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
) -> list[dict]:
    return _filas_sql(_SQL_FOLLETOS_SEMANA, {
        "tiendas": tiendas or None,
        "anom": list(ANOMALIAS_INICIO_NO_CONFIABLE),
        "desde": desde,
        "hasta": hasta,
        "atras": DIAS_SERIE_ATRAS,
        "adelante": DIAS_SERIE_ADELANTE,
    })


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
    filas = list(qs.values(
        "id", "tienda__nombre", "fuente", "folleto_id_fuente", "titulo",
        "fecha_inicio", "fecha_fin", "total_paginas", "estado", "scrapeado_at", "created_at", "url_origen",
    ))
    primeras = _primeras_paginas([f["id"] for f in filas])
    for f in filas:
        f["url_origen"] = origen.url_origen_segura(f["url_origen"])
        f["primera_pagina_id"] = primeras.get(f["id"])
    return filas


def _primeras_paginas(folleto_ids: list[int]) -> dict:
    """folleto_id -> id de su pagina con menor numero_pagina (una consulta, sin join)."""
    primeras = {}
    for p in (
        Pagina.objects.filter(folleto_id__in=folleto_ids)
        .order_by("folleto_id", "numero_pagina")
        .values("id", "folleto_id")
    ):
        primeras.setdefault(p["folleto_id"], p["id"])
    return primeras


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
        "producto_canonico__nombre_canonico", "created_at", "pagina_id", "pagina__numero_pagina",
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


# -- Procedencia por registro (docs/bi/metricas.md, "Procedencia por registro") -----------------------------
# Opcion A aprobada 13-oct-2026: sin tocar las vistas. Las filas de v_precios_actuales / v_historico_precios traen
# id = extracciones.id; la procedencia se resuelve con una segunda consulta por PK (id__in) y se combina en Python
# (origen.combinar_procedencia). extracciones -> paginas y -> folletos son N:1 y la busqueda es por PK: no duplica
# ni pierde filas (verificado con --contar: 27,760 = 27,760).

def _procedencia_de_valores(f: dict) -> dict:
    return {
        "pagina_id": f["pagina_id"],
        "numero_pagina": f["pagina__numero_pagina"],
        "folleto_id": f["folleto_id"],
        "folleto_id_fuente": f["folleto__folleto_id_fuente"],
        "folleto_titulo": f["folleto__titulo"],
        "url_origen": origen.url_origen_segura(f["folleto__url_origen"]),
    }


def procedencia_por_ids(ids) -> dict:
    ids = sorted({i for i in ids if i is not None})
    if not ids:
        return {}
    qs = Extraccion.objects.filter(id__in=ids).values(
        "id", "pagina_id", "pagina__numero_pagina", "folleto_id", "folleto__folleto_id_fuente",
        "folleto__titulo", "folleto__url_origen",
    )
    return {f["id"]: _procedencia_de_valores(f) for f in qs}


def agregar_procedencia(filas: list[dict]) -> list[dict]:
    return origen.combinar_procedencia(filas, procedencia_por_ids([f.get("id") for f in filas]))


_CAMPOS_PAGINA = (
    "id", "numero_pagina", "archivo_imagen", "folleto_id", "folleto__fuente", "folleto__folleto_id_fuente",
    "folleto__tienda__slug", "folleto__tienda__nombre", "folleto__titulo", "folleto__url_origen",
    "folleto__fecha_inicio", "folleto__fecha_fin", "folleto__total_paginas",
)

_CAMPOS_EXTRACCION = (
    "id", "tipo", "texto_raw", "texto_norm", "valor", "valor_anterior", "confianza_ocr",
    "bbox_x", "bbox_y", "bbox_ancho", "bbox_alto", "pagina_id", "producto_extraccion_id", "metodo_norm",
    "producto_canonico__nombre_canonico",
)


def pagina_origen(pagina_id: int) -> Optional[dict]:
    """Datos de una pagina para armar la ruta de su imagen y de sus JSON. None si no existe."""
    return Pagina.objects.filter(id=pagina_id).values(*_CAMPOS_PAGINA).first()


def contexto_pagina(pagina_id: int) -> Optional[dict]:
    """Pagina + paginas vecinas del mismo folleto + todos los bloques extraidos de la pagina. None si no existe."""
    pag = pagina_origen(pagina_id)
    if pag is None:
        return None
    hermanas = Pagina.objects.filter(folleto_id=pag["folleto_id"])
    ant = hermanas.filter(numero_pagina__lt=pag["numero_pagina"]).order_by("-numero_pagina").values("id").first()
    sig = hermanas.filter(numero_pagina__gt=pag["numero_pagina"]).order_by("numero_pagina").values("id").first()
    bloques = list(
        Extraccion.objects.filter(pagina_id=pagina_id)
        .order_by("bbox_y", "bbox_x", "id")
        .values("id", "tipo", "texto_raw", "valor", "bbox_x", "bbox_y", "bbox_ancho", "bbox_alto")
    )
    return {
        "pagina": pag,
        "vecinas": {"anterior": ant["id"] if ant else None, "siguiente": sig["id"] if sig else None},
        "bloques": bloques,
    }


def origen_extraccion(extraccion_id: int) -> Optional[dict]:
    """Extraccion + su fila PRODUCTO asociada (producto_extraccion_id, N:1). None si no existe."""
    ext = Extraccion.objects.filter(id=extraccion_id).values(*_CAMPOS_EXTRACCION).first()
    if ext is None:
        return None
    producto = None
    if ext["producto_extraccion_id"]:
        producto = Extraccion.objects.filter(id=ext["producto_extraccion_id"]).values(*_CAMPOS_EXTRACCION).first()
    return {"extraccion": ext, "producto": producto}
