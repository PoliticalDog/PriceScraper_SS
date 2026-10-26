# Consultas del dashboard de visualizacion via Django ORM.

from typing import Optional

from django.db import connection
from django.db.models import CharField, Count, Exists, F, Max, OuterRef, Q, Value
from django.db.models.functions import Coalesce, Trim

from dashboard import confiabilidad, origen, promociones
from dashboard.models import (
    ErrorCarga,
    EventoPromo,
    Extraccion,
    Folleto,
    Pagina,
    Tienda,
    VCalidadPipeline,
    VComparativaPrecios,
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

# Filtro "Con / sin categoria" (aprobado por la persona 14-oct-2026; docs/bi/metricas.md seccion 5).
# Parametro de querystring con_categoria: ausente/vacio = todos (default, no cambia nada), "si" o "no".
# Un registro esta SIN categoria si la categoria que muestra el dashboard es NULL, cadena vacia o solo espacios:
#     COALESCE(BTRIM(extracciones.categoria_nlp), '') = ''
# Esa columna es la "categoria" de v_precios_actuales, v_comparativa_precios y v_historico_precios (fila PRECIO).
# No se usa productos_canonicos.categoria: no es la que ve el usuario y difiere en 392 registros (verificado
# 14-oct-2026). En la BD no hay categorias genericas tipo "otros"/"sin categoria" (18 categorias, todas especificas).
# Se combina en AND con el resto de filtros (incluida la lista de categorias). Con valores invalidos no filtra.
CON_CATEGORIA_SI = "si"
CON_CATEGORIA_NO = "no"


def normalizar_con_categoria(valor) -> Optional[str]:
    """'si' | 'no' | None (todos). Cualquier otro valor se trata como todos."""
    v = (valor or "").strip().lower()
    return v if v in (CON_CATEGORIA_SI, CON_CATEGORIA_NO) else None


def filtrar_con_categoria(qs, con_categoria: Optional[str], campo: str = "categoria"):
    """Aplica el filtro con/sin categoria a un queryset sobre `campo` (misma regla que _SQL_CON_CATEGORIA).
    Solo filtra filas (WHERE): no agrega joins ni cambia el grano."""
    con_categoria = normalizar_con_categoria(con_categoria)
    if con_categoria is None:
        return qs
    qs = qs.alias(_categoria_limpia=Trim(campo))
    vacia = Q(_categoria_limpia__isnull=True) | Q(_categoria_limpia="")
    return qs.exclude(vacia) if con_categoria == CON_CATEGORIA_SI else qs.filter(vacia)


# Misma regla para las consultas SQL crudas (columna e.categoria_nlp de la fila PRECIO).
# %(con_categoria)s: NULL = todos, 'si' = con categoria, 'no' = sin categoria.
_SQL_CON_CATEGORIA = (
    "(%(con_categoria)s::text IS NULL"
    " OR (COALESCE(BTRIM(e.categoria_nlp), '') <> '') = (%(con_categoria)s::text = 'si'))"
)


# Filtro "Folleto" (aprobado por la persona 14-oct-2026; docs/bi/metricas.md seccion 6).
# Parametro de querystring folleto: el ID DE LA FUENTE (folletos.folleto_id_fuente: el de Tiendeo/Ofertomat, el que
# muestra la celda "Origen" y el nombre de la carpeta data/raw/<fuente>/<tienda>/<id>). Coincidencia exacta tras
# quitar espacios de los extremos; vacio/ausente = todos. Un id inexistente o mal escrito da vacio (no se ignora).
# No se acepta el folleto.id interno: no lo ve el usuario (salvo en /datos, que ya filtra por el con folleto_id).
# Hoy folleto_id_fuente es unico en toda la tabla (694/694, 6 digitos); el esquema solo garantiza unicidad por
# (fuente, folleto_id_fuente): si un dia se repite entre fuentes, el filtro traeria ambos folletos (sin duplicar filas).
def normalizar_folleto(valor) -> Optional[str]:
    """ID de la fuente sin espacios en los extremos, o None (todos)."""
    v = (valor or "").strip()
    return v or None


def filtrar_folleto(qs, folleto: Optional[str], campo: str = "folleto_id_fuente"):
    """Filtra por el id de la fuente del folleto (igualdad exacta). Las vistas traen la columna; en extracciones el
    campo es folleto__folleto_id_fuente (FK N:1 a folletos: el join no duplica filas)."""
    folleto = normalizar_folleto(folleto)
    return qs if folleto is None else qs.filter(**{campo: folleto})


# Misma regla en SQL crudo (requiere un alias f de folletos o la columna folleto_id_fuente calificada).
# %(folleto)s: NULL = todos.
_SQL_FOLLETO = "(%(folleto)s::text IS NULL OR f.folleto_id_fuente = %(folleto)s::text)"

# Estados del folleto filtrado, para los avisos de las paginas (aprobado 14-oct-2026; metricas.md seccion 6):
#   no_existe   ningun folleto con ese folleto_id_fuente (aunque pueda tener errores de carga: si fallo entero no
#               tiene fila en folletos)
#   sin_precios el folleto existe pero no tiene registros del dashboard (= v_precios_actuales; 76 de 694 al 14-oct)
#   con_precios existe y tiene registros (sin aviso)
FOLLETO_NO_EXISTE = "no_existe"
FOLLETO_SIN_PRECIOS = "sin_precios"
FOLLETO_CON_PRECIOS = "con_precios"


def estado_folleto(folleto: Optional[str]) -> Optional[dict]:
    """None si el filtro esta vacio. Si no, si el folleto existe, sus datos basicos, cuantos registros de precio y
    cuantos errores de carga tiene. Conteos sobre una sola tabla/vista cada uno (sin joins que dupliquen)."""
    folleto = normalizar_folleto(folleto)
    if folleto is None:
        return None
    folletos = list(
        Folleto.objects.filter(folleto_id_fuente=folleto)
        .order_by("fuente", "id")
        .values("fuente", "tienda__nombre")
    )
    registros = VPreciosActuales.objects.filter(folleto_id_fuente=folleto).count() if folletos else 0
    estado = (
        FOLLETO_NO_EXISTE if not folletos
        else FOLLETO_SIN_PRECIOS if registros == 0
        else FOLLETO_CON_PRECIOS
    )
    return {
        "folleto": folleto,
        "estado": estado,
        "folletos": len(folletos),
        "tiendas": sorted({f["tienda__nombre"] for f in folletos}),
        "fuentes": sorted({str(f["fuente"]) for f in folletos}),
        "registros": registros,
        "errores_carga": ErrorCarga.objects.filter(folleto_id_fuente=folleto).count(),
    }


def listar_tiendas() -> list[dict]:
    return list(
        Tienda.objects.filter(activa=True).order_by("nombre").values("id", "nombre", "slug")
    )


def listar_categorias() -> list[str]:
    # 14-oct-2026 (aprobado por la persona): sale de la categoria del registro (v_precios_actuales.categoria =
    # categoria_nlp), la misma que filtran los paneles; antes salia de productos_canonicos.categoria.
    return list(
        filtrar_con_categoria(VPreciosActuales.objects.all(), CON_CATEGORIA_SI)
        .order_by("categoria")
        .values_list("categoria", flat=True)
        .distinct()
    )


# -- Resumen (home) -----------------------------------------------------------

def resumen_kpis(con_categoria: Optional[str] = None, folleto: Optional[str] = None) -> dict:
    # Corregido 12-oct-2026 (aprobado por la persona, docs/bi/metricas.md "3. KPIs del Resumen"):
    # - "productos_con_precio" contaba PRECIO con valor (28,867) e incluia filas sin texto_norm que ningun
    #   panel muestra; ahora son los registros del dashboard = v_precios_actuales (28,634).
    # - "folleto_mas_reciente" (MAX(fecha_inicio)) mostraba 2026-12-25 por fechas anomalas; se reemplaza por
    #   folletos vigentes hoy segun v_folletos_vigencia (unica definicion de vigencia).
    vigencia = VFolletosVigencia.objects.aggregate(
        vigentes=Count("id", filter=Q(vigente=True)),
        dudosos=Count("id", filter=Q(vigente_dudoso=True)),
    )
    # 14-oct-2026: los filtros con/sin categoria y folleto solo aplican a "Precios detectados" (los otros KPIs no son
    # de registros).
    registros_todos = VPreciosActuales.objects.count()
    con_categoria = normalizar_con_categoria(con_categoria)
    folleto = normalizar_folleto(folleto)
    registros = (
        registros_todos if con_categoria is None and folleto is None
        else filtrar_folleto(filtrar_con_categoria(VPreciosActuales.objects.all(), con_categoria), folleto).count()
    )
    # KPI "Categorias" (17-oct-2026): denominador = registros del folleto/filtro sin el filtro con/sin categoria
    registros_base = (
        registros_todos if folleto is None
        else filtrar_folleto(VPreciosActuales.objects.all(), folleto).count()
    )
    categorias = None
    registros_con_categoria = None
    if con_categoria != CON_CATEGORIA_NO:
        categorias = qs_categorias_distintas(folleto).count()
        registros_con_categoria = filtrar_folleto(
            filtrar_con_categoria(VPreciosActuales.objects.all(), CON_CATEGORIA_SI), folleto
        ).count()
    return {
        "tiendas_activas": Tienda.objects.filter(activa=True).count(),
        "total_folletos": Folleto.objects.count(),
        "registros_dashboard": registros,
        "registros_dashboard_todos": registros_todos,
        "con_categoria": con_categoria,
        "folleto": folleto,
        "folletos_vigentes": vigencia["vigentes"],
        "folletos_vigentes_dudosos": vigencia["dudosos"],
        **kpi_categorias(categorias, registros_con_categoria, registros_base, con_categoria),
    }


# KPI "Categorias" del Resumen (aprobado por la persona 17-oct-2026; docs/bi/metricas.md "3. KPIs del Resumen").
# Categorias distintas de v_precios_actuales.categoria (= categoria_nlp de la fila PRECIO) con TRIM y sin vacia/NULL:
# misma regla que filtrar_con_categoria y la grafica Top 10. Respeta el filtro de folleto; con "sin categoria" no
# aplica (None -> "—"). "Frutas y Verduras" no es categoria propia: nlp/normalizador.py la funde en alimentos.
# Verificado 17-oct-2026: 18 categorias, 12,495 de 32,073 registros con categoria (39.0%).

def qs_categorias_distintas(folleto: Optional[str] = None):
    """Una fila por categoria distinta (TRIM) entre los registros del dashboard con categoria. Sin joins."""
    return (
        filtrar_folleto(filtrar_con_categoria(VPreciosActuales.objects.all(), CON_CATEGORIA_SI), folleto)
        .annotate(_categoria=Trim("categoria"))
        .order_by()
        .values("_categoria")
        .distinct()
    )


def kpi_categorias(
    categorias: Optional[int], registros_con_categoria: Optional[int], registros_base: int,
    con_categoria: Optional[str] = None,
) -> dict:
    """Arma el KPI: con el filtro "sin categoria" no aplica (todo None); % con 1 decimal, None si no hay registros."""
    if normalizar_con_categoria(con_categoria) == CON_CATEGORIA_NO:
        categorias = registros_con_categoria = None
    pct = (
        round(100.0 * registros_con_categoria / registros_base, 1)
        if registros_con_categoria is not None and registros_base else None
    )
    return {
        "categorias": categorias,
        "registros_con_categoria": registros_con_categoria,
        "registros_base": registros_base,
        "pct_con_categoria": pct,
    }


def resumen_top_categorias(
    limite: int = 10, con_categoria: Optional[str] = None, folleto: Optional[str] = None,
) -> list[dict]:
    # 14-oct-2026 (aprobado por la persona): cuenta por la categoria del registro sobre los registros del dashboard
    # (v_precios_actuales.categoria = categoria_nlp), igual que Precios/Comparativa/Historico y el KPI
    # "Precios detectados". Antes contaba por productos_canonicos.categoria sobre todas las filas PRECIO y no cuadraba.
    # Siempre excluye la categoria vacia, asi que con el filtro "no" la grafica queda vacia.
    if normalizar_con_categoria(con_categoria) == CON_CATEGORIA_NO:
        return []
    qs = (
        filtrar_folleto(filtrar_con_categoria(VPreciosActuales.objects.all(), CON_CATEGORIA_SI), folleto)
        .values("categoria")
        .annotate(n=Count("id"))
        .order_by("-n", "categoria")[:limite]
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
    con_categoria: Optional[str] = None,
    folleto: Optional[str] = None,
    promocion: Optional[str] = None,
    nivel: Optional[str] = None,
    campanias: Optional[list[str]] = None,
    limite: int = 500,
) -> list[dict]:
    qs = filtrar_folleto(filtrar_con_categoria(VPreciosActuales.objects.all(), con_categoria), folleto)
    qs = filtrar_promocion(qs, promocion, nivel, campanias, "vista")

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
    return agregar_promos(agregar_procedencia(filas))


# -- Comparativa entre tiendas --------------------------------------------------

def comparativa_precios(
    categorias: Optional[list[str]] = None,
    q: Optional[str] = None,
    min_tiendas: int = 1,
    con_categoria: Optional[str] = None,
    folleto: Optional[str] = None,
    promocion: Optional[str] = None,
    nivel: Optional[str] = None,
    campanias: Optional[list[str]] = None,
    limite: int = 300,
) -> list[dict]:
    # La vista agrupa por (texto_norm, categoria_nlp): cada fila tiene una sola categoria y el filtro la clasifica
    # entera (no parte grupos).
    qs = filtrar_con_categoria(VComparativaPrecios.objects.filter(num_tiendas__gte=min_tiendas), con_categoria)
    # Folleto (14-oct-2026): la vista no tiene folleto (agrega todas las fechas y folletos). Se dejan los grupos
    # (texto, categoria) que tienen al menos un registro del folleto, con EXISTS (no une ni duplica); min/max/
    # diferencia siguen siendo entre todas las tiendas, que es el sentido de comparar.
    folleto = normalizar_folleto(folleto)
    if folleto is not None:
        qs = qs.filter(_en_folleto(folleto))
    # Promocion (15-oct-2026): "con" = el producto tiene al menos un registro en un folleto con promocion
    qs = filtrar_promocion(qs, promocion, nivel, campanias, "comparativa")

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


def _en_folleto(folleto: str) -> Exists:
    """EXISTS: el grupo (producto, categoria) de v_comparativa_precios tiene un registro del dashboard en el folleto.
    Misma base que la vista (PRECIO, valor y texto_norm no nulos); la categoria se compara con COALESCE(..., '')
    porque la vista agrupa NULL como su propio grupo."""
    return Exists(_registros_del_grupo().filter(folleto__folleto_id_fuente=folleto))


def _registros_del_grupo():
    """Registros del dashboard del grupo (producto, categoria) de la fila externa de v_comparativa_precios
    (OuterRef). Base de los EXISTS de Comparativa: nunca se une a la vista, no duplica grupos."""
    vacia = Value("", output_field=CharField())
    return (
        Extraccion.objects
        .filter(tipo="PRECIO", valor__isnull=False, texto_norm=OuterRef("producto"))
        .alias(_cat=Coalesce("categoria_nlp", vacia))
        .filter(_cat=Coalesce(OuterRef("categoria"), vacia, output_field=CharField()))
    )


def qs_precios_del_grupo(producto: str, con_categoria: Optional[str] = None, categoria: Optional[str] = None):
    """PRECIO del grupo (texto_norm, categoria_nlp) de v_comparativa_precios. 26-oct-2026: sin la categoria el detalle
    mezclaba dos grupos con el mismo nombre. categoria None = sin filtro (llamadas viejas); "" = el grupo sin categoria."""
    qs = filtrar_con_categoria(
        Extraccion.objects.filter(tipo="PRECIO", valor__isnull=False, texto_norm=producto),
        con_categoria, "categoria_nlp",
    )
    if categoria is None:
        return qs
    if categoria == "":
        return qs.filter(Q(categoria_nlp__isnull=True) | Q(categoria_nlp=""))
    return qs.filter(categoria_nlp=categoria)


def comparativa_por_tienda(producto: str, con_categoria: Optional[str] = None,
                           categoria: Optional[str] = None) -> list[dict]:
    # Folleto (14-oct-2026): el detalle NO se filtra por folleto (quedaria una sola tienda y no habria que comparar);
    # la pagina marca las filas del folleto filtrado.
    # Mismo motivo que resumen_folletos_por_tienda(): "tienda" colisiona con
    # el campo FK real de Extraccion, no se puede usar como alias en .values().
    # 13-oct-2026: + vigencia y procedencia (folleto/pagina) por registro para el detalle por tienda.
    # Mismo filtro que v_comparativa_precios (texto_norm no nulo queda implicito en texto_norm=producto).
    # 14-oct-2026: el detalle respeta el filtro con/sin categoria de la tabla (sin filtro, igual que antes).
    qs = (
        qs_precios_del_grupo(producto, con_categoria, categoria)
        .values(
            "id", "tienda__nombre", "valor", "folleto__fecha_inicio", "folleto__fecha_fin",
            "pagina_id", "pagina__numero_pagina", "folleto_id", "folleto__folleto_id_fuente",
            "folleto__titulo", "folleto__url_origen",
        )
        .order_by("valor", "id")
    )
    return agregar_promos([{
        "id": f["id"],
        "tienda": f["tienda__nombre"],
        "precio": f["valor"],
        "vigencia_desde": f["folleto__fecha_inicio"],
        "vigencia_hasta": f["folleto__fecha_fin"],
        **_procedencia_de_valores(f),
    } for f in qs])


# -- Historico de precios --------------------------------------------------------

def historico_precios(
    producto: str,
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    con_categoria: Optional[str] = None,
    folleto: Optional[str] = None,
    promocion: Optional[str] = None,
    nivel: Optional[str] = None,
    campanias: Optional[list[str]] = None,
) -> list[dict]:
    # iexact (19-oct-2026): escribir "leche entera" a mano tambien encuentra "Leche entera"
    qs = filtrar_folleto(
        filtrar_con_categoria(VHistoricoPrecios.objects.filter(producto__iexact=producto), con_categoria), folleto,
    )
    qs = filtrar_promocion(qs, promocion, nivel, campanias, "vista")

    if tiendas:
        qs = qs.filter(tienda__in=tiendas)
    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)

    qs = qs.order_by("fecha", "id")
    filas = list(qs.values("id", "tienda", "producto", "categoria", "fecha", "precio", "precio_anterior"))
    return agregar_promos(agregar_procedencia(filas))


def sugerir_productos(q: str, limite: int = 20) -> list[str]:
    """Sugerencias del Historico (19-oct-2026): solo productos que tienen historico, los de mas registros primero.
    Antes salian de productos_canonicos en orden alfabetico (80k nombres, ~67k sin ningun precio en el historico)."""
    if not q:
        return []
    return list(
        VHistoricoPrecios.objects
        .filter(producto__icontains=q)
        .values("producto")
        .annotate(n=Count("id"))
        .order_by("-n", "producto")
        .values_list("producto", flat=True)[:limite]
    )


# -- Calidad del pipeline ---------------------------------------------------------

def calidad_pipeline(
    tiendas: Optional[list[str]] = None,
    fuente: Optional[str] = None,
    estado: Optional[str] = None,
    tasa_util_min: Optional[float] = None,
    folleto: Optional[str] = None,
    limite: int = 500,
) -> list[dict]:
    qs = filtrar_folleto(VCalidadPipeline.objects.all(), folleto)  # una fila por folleto: queda 0 o 1

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
# registros). PRECIO -> PRODUCTO (producto_extraccion_id) es N:1: no duplica filas de PRECIO. metodo_norm es el del
# nombre que muestra el PRECIO (load lo guarda desde 25-oct-2026: con nombre unido difiere del de la fila PRODUCTO);
# cargas anteriores lo tienen NULL y caen al de la fila PRODUCTO. Sin exclusiones: describe el dato tal como lo ve el
# dashboard.
_SQL_CONFIABILIDAD = """
WITH base AS (
    SELECT e.id, e.tienda_id, e.folleto_id, e.pagina_id, e.texto_norm, e.valor, e.confianza_ocr,
           e.categoria_nlp, COALESCE(e.metodo_norm, p.metodo_norm) AS metodo_norm
    FROM extracciones e
    JOIN extracciones p ON p.id = e.producto_extraccion_id
    JOIN folletos f ON f.id = e.folleto_id
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND (%(desde)s::date IS NULL OR f.fecha_inicio >= %(desde)s::date)
      AND (%(hasta)s::date IS NULL OR f.fecha_inicio <= %(hasta)s::date)
      AND """ + _SQL_CON_CATEGORIA + """
      AND """ + _SQL_FOLLETO + """
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
           COUNT(*) FILTER (WHERE COALESCE(BTRIM(categoria_nlp), '') = '')          AS reg_sin_categoria,
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
  -- con folleto: solo la tienda duenia del folleto (EXISTS, sin join); id inexistente -> sin filas
  AND (%(folleto)s::text IS NULL
       OR EXISTS (SELECT 1 FROM folletos fx WHERE fx.tienda_id = t.id AND fx.folleto_id_fuente = %(folleto)s::text))
ORDER BY registros DESC, t.nombre
"""


def confiabilidad_por_tienda(
    tiendas: Optional[list[str]] = None,
    desde: Optional[str] = None,
    hasta: Optional[str] = None,
    con_categoria: Optional[str] = None,
    folleto: Optional[str] = None,
) -> dict:
    filas = _filas_sql(_SQL_CONFIABILIDAD, {
        "tiendas": tiendas or None, "desde": desde, "hasta": hasta,
        "con_categoria": normalizar_con_categoria(con_categoria),
        "folleto": normalizar_folleto(folleto),
    })
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
    SELECT e.folleto_id, COUNT(*) AS precios
    FROM extracciones e
    WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL
      AND """ + _SQL_CON_CATEGORIA + """
    GROUP BY e.folleto_id
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


def cobertura_por_tienda(tiendas: Optional[list[str]] = None, con_categoria: Optional[str] = None) -> dict:
    # con_categoria (14-oct-2026) solo afecta los conteos de precios (CTE pre); folletos, paginas, fechas y errores no
    # son de producto. "Pags. con precio" sale de paginas.total_precios y no se puede filtrar por categoria.
    params = {
        "tiendas": tiendas or None, "anom": list(ANOMALIAS_INICIO_NO_CONFIABLE),
        "con_categoria": normalizar_con_categoria(con_categoria),
    }
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


def listar_folletos(tienda_id: Optional[str] = None, folleto: Optional[str] = None, limite: int = 200) -> list[dict]:
    qs = filtrar_folleto(Folleto.objects.all(), folleto)
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
    return agregar_promos(filas, campo="id")


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
    con_categoria: Optional[str] = None,
    folleto: Optional[str] = None,
    limite: int = 200,
) -> list[dict]:
    # folleto = id de la fuente (filtro "Folleto"); folleto_id = id interno (enlaces del explorador). Van en AND.
    qs = filtrar_folleto(
        filtrar_con_categoria(Extraccion.objects.all(), con_categoria, "categoria_nlp"),
        folleto, "folleto__folleto_id_fuente",
    )
    if tienda_id:
        qs = qs.filter(tienda_id=tienda_id)
    if folleto_id:
        qs = qs.filter(folleto_id=folleto_id)
    if tipo:
        qs = qs.filter(tipo=tipo)

    qs = qs.order_by("-created_at")[:limite]
    return agregar_promos(list(qs.values(
        "id", "tienda__nombre", "folleto_id", "tipo", "texto_raw", "texto_norm",
        "categoria_nlp", "valor", "valor_anterior", "texto_promo", "confianza_ocr",
        "producto_canonico__nombre_canonico", "created_at", "pagina_id", "pagina__numero_pagina",
    )))


# -- Promociones y eventos ---------------------------------------------------------

# Fase 1 aprobada por la persona 15-oct-2026 (docs/bi/metricas.md seccion 7). Sin vistas: eventos_promo se lee
# directo y se clasifica en Python (dashboard/promociones.py). Ya no se usa v_eventos_activos: no tiene fechas (todas
# NULL -> todos "vigentes"), junta folletos y su num_precios_asociados cuenta cada precio una vez por evento.

def campanias_de_folletos(folleto_ids) -> dict:
    """{folleto_id: [etiqueta de campania, ...]} para los folletos dados. Una consulta por PK de folleto
    (indice uq_evento_folleto); el agrupado es en Python, asi que nunca multiplica las filas de quien la usa."""
    ids = sorted({i for i in folleto_ids if i is not None})
    if not ids:
        return {}
    return promociones.campanias_por_folleto(
        EventoPromo.objects.filter(folleto_id__in=ids).values("folleto_id", "nombre_evento")
    )


def agregar_promos(filas: list[dict], campo: str = "folleto_id") -> list[dict]:
    """Agrega fila["promos"] = {campania, producto, bancaria}; mismas filas, mismo orden."""
    return promociones.combinar_promos(filas, campanias_de_folletos(f.get(campo) for f in filas), campo)


def _ids_eventos_promocion(nivel: Optional[str], campanias: list[str]) -> list[int]:
    """ids de eventos_promo que cuentan como promocion para el nivel y las campanias pedidas.
    Producto y bancaria aun no tienen datos (pendiente de carga): lista vacia."""
    if nivel is not None and nivel not in promociones.NIVELES_CON_DATOS:
        return []
    ids = []
    for ev in EventoPromo.objects.values("id", "nombre_evento"):  # 92 filas al 15-oct-2026
        clase, slug = promociones.clasificar_evento(ev["nombre_evento"])
        if clase == promociones.CLASE_CAMPANIA and (not campanias or slug in campanias):
            ids.append(ev["id"])
    return ids


def filtrar_promocion(qs, promocion=None, nivel=None, campanias=None, modo: str = "vista"):
    """Filtros "Promocion" (con/sin), "Nivel" y "Campania" con EXISTS sobre eventos_promo (no une, no duplica).
    - Campania sin "Promocion" equivale a "con" esas campanias; "sin" + campanias = registros fuera de ellas.
    - Nivel solo (con Promocion = todos) no filtra.
    modo: "vista" (v_precios_actuales / v_historico_precios: folleto por (fuente, folleto_id_fuente)),
          "extraccion" (extracciones.folleto_id), "comparativa" (grupo de v_comparativa_precios con al menos un
          registro en un folleto con promocion)."""
    promocion = promociones.normalizar_promocion(promocion)
    nivel = promociones.normalizar_nivel(nivel)
    campanias = promociones.normalizar_campanias(campanias)
    if promocion is None and campanias:
        promocion = "con"
    if promocion is None:
        return qs
    ids = _ids_eventos_promocion(nivel, campanias)
    if not ids:
        return qs.none() if promocion == "con" else qs
    if modo == "vista":
        cond = Exists(EventoPromo.objects.filter(
            id__in=ids, folleto__fuente=OuterRef("fuente"), folleto__folleto_id_fuente=OuterRef("folleto_id_fuente"),
        ))
    elif modo == "extraccion":
        cond = Exists(EventoPromo.objects.filter(id__in=ids, folleto_id=OuterRef("folleto_id")))
    elif modo == "comparativa":
        cond = Exists(_registros_del_grupo().filter(
            Exists(EventoPromo.objects.filter(id__in=ids, folleto_id=OuterRef("folleto_id")))
        ))
    else:
        raise ValueError(f"modo desconocido: {modo}")
    return qs.filter(cond) if promocion == "con" else qs.filter(~cond)


def promos_de_folleto(folleto_id: Optional[int]) -> dict:
    promos = promociones.promos_vacias()
    promos["campania"] = campanias_de_folletos([folleto_id]).get(folleto_id, [])
    return promos


# -- Pagina Promociones: grano (folleto, campania) ------------------------------------------------------------
VIGENCIAS = ("vigente", "vigente_dudoso", "proximo", "fuera")
NOMBRES_VIGENCIA = {
    "vigente": "Vigente hoy",
    "vigente_dudoso": "Vigente (fecha dudosa)",
    "proximo": "Próximo",
    "fuera": "Fuera de vigencia",
}


def _estado_vigencia(v: dict) -> str:
    """Una sola categoria por folleto, desde v_folletos_vigencia (unica definicion de vigencia del dashboard)."""
    if v.get("vigente"):
        return "vigente"
    if v.get("vigente_dudoso"):
        return "vigente_dudoso"
    if v.get("proximo"):
        return "proximo"
    return "fuera"


def promociones_por_folleto(
    tiendas: Optional[list[str]] = None,
    folleto: Optional[str] = None,
    campanias: Optional[list[str]] = None,
    vigencia: Optional[str] = None,
    clase: Optional[str] = None,
    categorias: Optional[list[str]] = None,
) -> dict:
    """Filas (folleto, campania) para la pagina Promociones.
    clase: 'campania' por defecto; 'lema' | 'legal' | 'producto' | 'otro' para revisar lo que no es campania;
    'todas' para todo. En las clases que no son campania el grano es (folleto, nombre_evento).
    "Precios en el folleto" = registros del dashboard del folleto (nivel folleto, no producto); con categorias, solo
    los de esas categorias y se ocultan los folletos que quedan en 0. Los KPIs suman cada folleto una sola vez."""
    clase = clase if clase in promociones.CLASES or clase == "todas" else promociones.CLASE_CAMPANIA
    campanias = promociones.normalizar_campanias(campanias)
    vigencia = vigencia if vigencia in VIGENCIAS else None

    eventos = filtrar_folleto(EventoPromo.objects.all(), folleto, "folleto__folleto_id_fuente")
    grupos: dict = {}
    for ev in eventos.values("id", "folleto_id", "nombre_evento", "texto_raw"):
        cl, slug = promociones.clasificar_evento(ev["nombre_evento"])
        if clase != "todas" and cl != clase:
            continue
        if campanias and slug not in campanias:
            continue
        clave = (ev["folleto_id"], cl, slug or ev["nombre_evento"])
        g = grupos.setdefault(clave, {"textos": set(), "eventos": 0})
        g["textos"].add((ev["texto_raw"] or ev["nombre_evento"]).strip())
        g["eventos"] += 1

    fids = sorted({k[0] for k in grupos})
    fol = {
        v["id"]: v for v in VFolletosVigencia.objects.filter(id__in=fids).values(
            "id", "tienda", "fuente", "folleto_id_fuente", "titulo", "fecha_inicio", "fecha_fin",
            "anomalia_fecha", "vigente", "vigente_dudoso", "proximo",
        )
    }
    precios_qs = Extraccion.objects.filter(
        tipo="PRECIO", valor__isnull=False, texto_norm__isnull=False, folleto_id__in=fids,
    )
    if categorias:
        precios_qs = precios_qs.filter(categoria_nlp__in=categorias)
    precios = dict(precios_qs.values_list("folleto_id").annotate(n=Count("id")))
    primeras = _primeras_paginas(fids)

    filas = []
    for (fid, cl, clave), g in grupos.items():
        v = fol.get(fid)
        if v is None:
            continue
        if tiendas and v["tienda"] not in tiendas:
            continue
        estado = _estado_vigencia(v)
        if vigencia and estado != vigencia:
            continue
        n = precios.get(fid, 0)
        if categorias and n == 0:
            continue
        es_campania = cl == promociones.CLASE_CAMPANIA
        filas.append({
            "folleto_id": fid,
            "tienda": v["tienda"],
            "fuente": v["fuente"],
            "folleto_id_fuente": v["folleto_id_fuente"],
            "folleto_titulo": v["titulo"],
            "vigencia_desde": v["fecha_inicio"],
            "vigencia_hasta": v["fecha_fin"],
            "anomalia_fecha": v["anomalia_fecha"],
            "vigencia": estado,
            "vigencia_nombre": NOMBRES_VIGENCIA[estado],
            "clase": cl,
            "clase_nombre": promociones.NOMBRES_CLASE[cl],
            "campania": clave if es_campania else None,
            "nombre": promociones.CAMPANIAS[clave] if es_campania else clave,
            "textos_detectados": sorted(g["textos"]),
            "eventos": g["eventos"],
            "precios_en_folleto": n,
            "primera_pagina_id": primeras.get(fid),
        })
    filas.sort(key=lambda f: (f["vigencia"] != "vigente", f["tienda"], f["folleto_id_fuente"], f["nombre"]))

    por_folleto = {f["folleto_id"]: f["precios_en_folleto"] for f in filas}
    return {
        "kpis": {
            "filas": len(filas),
            "folletos": len(por_folleto),
            "campanias": len({f["campania"] for f in filas if f["campania"]}),
            "tiendas": len({f["tienda"] for f in filas}),
            "precios_en_folletos": sum(por_folleto.values()),  # cada folleto una vez
            "vigentes": len({f["folleto_id"] for f in filas if f["vigencia"] == "vigente"}),
        },
        "filas": filas,
    }


# -- Errores de carga (tabla errores_carga) ---------------------------------------

def listar_tiendas_error() -> list[str]:
    return list(
        ErrorCarga.objects
        .exclude(tienda_slug__isnull=True)
        .order_by("tienda_slug")
        .values_list("tienda_slug", flat=True)
        .distinct()
    )


def _filtrar_errores(categorias, tiendas, fuente, estado, folleto=None):
    # errores_carga guarda el id de la fuente (sin FK a folletos: un folleto que fallo entero no tiene fila alli)
    qs = filtrar_folleto(ErrorCarga.objects.all(), folleto)
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
    folleto: Optional[str] = None,
    limite: int = 1000,
) -> dict:
    # KPIs sobre toda la tabla (estado general); grafica y tabla respetan los filtros (incluido folleto, 14-oct-2026)
    abiertos = ErrorCarga.objects.filter(resuelto=False)
    kpis = {
        "abiertos": abiertos.count(),
        "folletos_afectados": abiertos.values("fuente", "folleto_id_fuente").distinct().count(),
        "resueltos": ErrorCarga.objects.filter(resuelto=True).count(),
        "ultima_corrida": ErrorCarga.objects.aggregate(m=Max("corrida_at"))["m"],
    }

    qs = _filtrar_errores(categorias, tiendas, fuente, estado, folleto)

    # Todas las categorias, aunque tengan 0, para que el eje no cambie con los filtros
    conteo = dict(qs.values_list("categoria").annotate(n=Count("id")))
    por_categoria = [{"categoria": c, "n": conteo.get(c, 0)} for c in ErrorCarga.CATEGORIAS]

    filas = list(qs.order_by("-corrida_at", "fuente", "folleto_id_fuente", "pagina")[:limite].values(
        "id", "corrida_at", "fuente", "tienda_slug", "folleto_id_fuente", "pagina",
        "categoria", "sqlstate", "mensaje", "detalle", "ruta_archivo", "resuelto", "resuelto_at",
    ))
    return {
        "kpis": kpis, "por_categoria": por_categoria, "filas": filas,
        "ocultos_por_estado": errores_ocultos_por_estado(categorias, tiendas, fuente, estado, folleto),
    }


def errores_ocultos_por_estado(categorias, tiendas, fuente, estado, folleto=None) -> Optional[dict]:
    """Errores que cumplen todos los demas filtros (incluido folleto) pero quedan fuera por el filtro de Estado
    (aviso aprobado 14-oct-2026). Con estado "abiertos" son los resueltos y viceversa; sin filtro de estado, None.
    Solo con un folleto escrito (decision de la persona 15-oct-2026): sin folleto, None y la vista por defecto
    no muestra aviso. Es un COUNT sobre errores_carga sola (sin joins)."""
    opuesto = {"abiertos": "resueltos", "resueltos": "abiertos"}.get(estado)
    if opuesto is None or normalizar_folleto(folleto) is None:
        return None
    n = _filtrar_errores(categorias, tiendas, fuente, opuesto, folleto).count()
    return {"n": n, "estado_oculto": opuesto, "estado_filtro": estado}


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
        "promos": promos_de_folleto(pag["folleto_id"]),  # campania del folleto (15-oct-2026)
        **precios_de_pagina(pagina_id),  # pestana "Precios" del visor (17-oct-2026)
    }


# Pestana "Precios" del visor (aprobada por la persona 17-oct-2026; docs/bi/metricas.md "4. Procedencia por registro").
# Pares precio-producto de la pagina: registros del dashboard (mismo filtro que v_precios_actuales: PRECIO con valor y
# texto_norm) que ademas tienen fila PRODUCTO (hoy coinciden: los 300 PRECIO sin producto tampoco tienen texto_norm).
# Grano: una fila por PRECIO; los joins a la fila PRODUCTO y a productos_canonicos son N:1 por PK (verificado con
# consulta.py: 32,073 filas = 32,073 ids). Orden de lectura: bbox_y, bbox_x, id.
METODOS_CATALOGO = frozenset({"exacto", "fuzzy", "fuzzy_bajo"})

_CAMPOS_PRECIO_PAGINA = (
    "id", "valor", "valor_anterior", "texto_norm", "texto_raw", "categoria_nlp", "confianza_ocr",
    "producto_canonico__nombre_canonico", "bbox_x", "bbox_y", "bbox_ancho", "bbox_alto", "producto_extraccion_id",
    "metodo_norm",
)
_CAMPOS_PRODUCTO_PAGINA = (
    "pagina_id", "texto_raw", "texto_norm", "metodo_norm", "confianza_norm",
    "bbox_x", "bbox_y", "bbox_ancho", "bbox_alto",
)


def _descuento_pct(valor, anterior) -> Optional[float]:
    """Mismo calculo que v_precios_actuales.descuento_pct: solo si el precio anterior es mayor que el actual."""
    if valor is None or anterior is None or anterior <= valor or anterior <= 0:
        return None
    return round((anterior - valor) / anterior * 100, 1)


def armar_precios_pagina(filas: list[dict]) -> list[dict]:
    """Filas planas de .values() -> un dict por precio con su "producto" anidado. No agrega ni quita filas.
    repetido = hay otro precio en la pagina con el mismo texto y valor (son cajas distintas, no filas duplicadas)."""
    claves = {}
    for f in filas:
        clave = (f["texto_norm"], f["valor"])
        claves[clave] = claves.get(clave, 0) + 1
    salida = []
    for f in filas:
        precio = {c: f[c] for c in _CAMPOS_PRECIO_PAGINA}
        producto = {"id": f["producto_extraccion_id"],
                    **{c: f[f"producto_extraccion__{c}"] for c in _CAMPOS_PRODUCTO_PAGINA}}
        # catalogo segun el nombre que muestra el PRECIO (= KPI "% catalogo"): metodo_norm del PRECIO desde
        # 25-oct-2026 (con nombre unido difiere del de la fila PRODUCTO); NULL en cargas anteriores
        producto["es_catalogo"] = (precio["metodo_norm"] or producto["metodo_norm"]) in METODOS_CATALOGO
        precio["descuento_pct"] = _descuento_pct(f["valor"], f["valor_anterior"])
        precio["repetido"] = claves[(f["texto_norm"], f["valor"])] > 1
        precio["producto"] = producto
        salida.append(precio)
    return salida


def qs_precios_de_pagina(pagina_id: int):
    """Pares precio-producto de la pagina, una fila por PRECIO, en orden de lectura."""
    return (
        Extraccion.objects.filter(
            pagina_id=pagina_id, tipo="PRECIO",
            valor__isnull=False, texto_norm__isnull=False, producto_extraccion__isnull=False,
        )
        .order_by("bbox_y", "bbox_x", "id")
        .values(*_CAMPOS_PRECIO_PAGINA, *(f"producto_extraccion__{c}" for c in _CAMPOS_PRODUCTO_PAGINA))
    )


def precios_de_pagina(pagina_id: int) -> dict:
    """{"precios": [...], "precios_sin_producto": N}. N = PRECIO de la pagina que no se listan (sin valor, sin
    texto_norm o sin fila PRODUCTO), para el aviso de la pestana."""
    filas = list(qs_precios_de_pagina(pagina_id))
    total = Extraccion.objects.filter(pagina_id=pagina_id, tipo="PRECIO").count()
    return {"precios": armar_precios_pagina(filas), "precios_sin_producto": total - len(filas)}


def origen_extraccion(extraccion_id: int) -> Optional[dict]:
    """Extraccion + su fila PRODUCTO asociada (producto_extraccion_id, N:1). None si no existe."""
    ext = Extraccion.objects.filter(id=extraccion_id).values(*_CAMPOS_EXTRACCION).first()
    if ext is None:
        return None
    producto = None
    if ext["producto_extraccion_id"]:
        producto = Extraccion.objects.filter(id=ext["producto_extraccion_id"]).values(*_CAMPOS_EXTRACCION).first()
    return {"extraccion": ext, "producto": producto}
