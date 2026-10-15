# PriceScraper - Vistas del dashboard interno (Django).

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from dashboard import origen, queries


def _con_categoria(request):
    """Filtro "Con / sin categoria" (?con_categoria=si|no; vacio o invalido = todos). Ver queries.filtrar_con_categoria."""
    return queries.normalizar_con_categoria(request.GET.get("con_categoria"))


def _folleto(request):
    """Filtro "Folleto" (?folleto=<id de la fuente>, exacto; vacio = todos). Ver queries.filtrar_folleto."""
    return queries.normalizar_folleto(request.GET.get("folleto"))


# -- Paginas (HTML) -------------------------------------------------------------

def pagina_resumen(request):
    return render(request, "dashboard/resumen.html", {"activo": "resumen"})


def pagina_precios(request):
    return render(request, "dashboard/precios.html", {"activo": "precios"})


def pagina_comparativa(request):
    return render(request, "dashboard/comparativa.html", {"activo": "comparativa"})


def pagina_historico(request):
    return render(request, "dashboard/historico.html", {"activo": "historico"})


def pagina_calidad(request):
    return render(request, "dashboard/calidad.html", {"activo": "calidad"})


def pagina_cobertura(request):
    return render(request, "dashboard/cobertura.html", {"activo": "cobertura"})


def pagina_promociones(request):
    return render(request, "dashboard/promociones.html", {"activo": "promociones"})


def pagina_errores(request):
    return render(request, "dashboard/errores.html", {"activo": "errores"})


def pagina_explorador(request):
    """Vista plana de solo lectura sobre la BD cruda (tiendas/folletos/extracciones),
    sin agregaciones de negocio, para inspeccionar datos cargados sin escribir SQL."""
    tienda_id = request.GET.get("tienda_id") or None
    folleto_id = request.GET.get("folleto_id") or None
    tipo = request.GET.get("tipo") or None
    con_categoria = _con_categoria(request)
    folleto_fuente = _folleto(request)

    contexto = {
        "tiendas": queries.listar_tiendas_detalle(),
        "folletos": queries.listar_folletos(tienda_id=tienda_id, folleto=folleto_fuente),
        "tipos": queries.listar_tipos_extraccion(),
        "extracciones": queries.listar_extracciones(
            tienda_id=tienda_id, folleto_id=folleto_id, tipo=tipo, con_categoria=con_categoria,
            folleto=folleto_fuente,
        ),
        "tienda_id": tienda_id,
        "folleto_id": folleto_id,
        "tipo": tipo,
        "con_categoria": con_categoria,
        "folleto_fuente": folleto_fuente,
        "estado_folleto": queries.estado_folleto(folleto_fuente),
    }
    return render(request, "dashboard/explorador.html", contexto)


# -- API (JSON) -------------------------------------------------------------------

def api_filtros_tiendas(request):
    return JsonResponse(queries.listar_tiendas(), safe=False)


def api_filtros_folleto(request):
    """Estado del folleto filtrado para el aviso de las paginas: {"estado": null} si el filtro esta vacio."""
    return JsonResponse(queries.estado_folleto(_folleto(request)) or {"estado": None})


def api_filtros_categorias(request):
    return JsonResponse(queries.listar_categorias(), safe=False)


def api_resumen(request):
    con_categoria = _con_categoria(request)
    folleto = _folleto(request)
    return JsonResponse({
        "kpis": queries.resumen_kpis(con_categoria=con_categoria, folleto=folleto),
        "top_categorias": queries.resumen_top_categorias(con_categoria=con_categoria, folleto=folleto),
        "folletos_por_tienda": queries.resumen_folletos_por_tienda(),
    })


def api_precios(request):
    datos = queries.precios_actuales(
        tiendas=request.GET.getlist("tienda") or None,
        categorias=request.GET.getlist("categoria") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
        q=request.GET.get("q") or None,
        solo_descuento=request.GET.get("solo_descuento") == "true",
        con_categoria=_con_categoria(request),
        folleto=_folleto(request),
    )
    return JsonResponse(datos, safe=False)


def api_comparativa(request):
    datos = queries.comparativa_precios(
        categorias=request.GET.getlist("categoria") or None,
        q=request.GET.get("q") or None,
        min_tiendas=int(request.GET.get("min_tiendas", 1)),
        con_categoria=_con_categoria(request),
        folleto=_folleto(request),
    )
    return JsonResponse(datos, safe=False)


def api_comparativa_por_tienda(request, producto):
    return JsonResponse(
        queries.comparativa_por_tienda(producto, con_categoria=_con_categoria(request)), safe=False
    )


def api_historico(request):
    producto = request.GET.get("producto", "")
    datos = queries.historico_precios(
        producto,
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
        con_categoria=_con_categoria(request),
        folleto=_folleto(request),
    )
    return JsonResponse(datos, safe=False)


def api_productos_sugerencias(request):
    return JsonResponse(queries.sugerir_productos(request.GET.get("q", "")), safe=False)


def api_calidad(request):
    tasa_util_min = request.GET.get("tasa_util_min")
    datos = queries.calidad_pipeline(
        tiendas=request.GET.getlist("tienda") or None,
        fuente=request.GET.get("fuente") or None,
        estado=request.GET.get("estado") or None,
        tasa_util_min=float(tasa_util_min) if tasa_util_min else None,
        folleto=_folleto(request),
    )
    return JsonResponse(datos, safe=False)


def api_confiabilidad(request):
    datos = queries.confiabilidad_por_tienda(
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
        con_categoria=_con_categoria(request),
        folleto=_folleto(request),
    )
    return JsonResponse(datos)


def api_cobertura(request):
    return JsonResponse(queries.cobertura_por_tienda(
        tiendas=request.GET.getlist("tienda") or None,
        con_categoria=_con_categoria(request),
    ))


def api_cobertura_semanal(request):
    datos = queries.folletos_por_semana(
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
    )
    return JsonResponse(datos, safe=False)


def api_eventos(request):
    datos = queries.eventos_promo(
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
    )
    return JsonResponse(datos, safe=False)


def api_filtros_errores(request):
    return JsonResponse({
        "categorias": queries.ErrorCarga.CATEGORIAS,
        "tiendas": queries.listar_tiendas_error(),
    })


def api_errores(request):
    datos = queries.errores_carga(
        categorias=request.GET.getlist("categoria") or None,
        tiendas=request.GET.getlist("tienda") or None,
        fuente=request.GET.get("fuente") or None,
        estado=request.GET.get("estado") or None,
        folleto=_folleto(request),
    )
    return JsonResponse(datos)


# -- Procedencia: visor de pagina, imagen y fragmentos OCR/NLP (docs/bi/metricas.md, "Procedencia por registro") --
# Solo lectura y solo GET. Las URLs reciben unicamente ids enteros; la ruta al archivo se arma con datos de la BD
# (fuente, tienda.slug, folleto_id_fuente, archivo_imagen) y se valida en dashboard/origen.py. Cualquier ruta
# invalida o archivo ausente responde 404 sin detallar el motivo.

def _base(version: str):
    return settings.ORIGEN_PROCESSED_DIR if version == "proc" else settings.ORIGEN_RAW_DIR


def _ruta_imagen_pagina(pag: dict, version: str):
    return origen.ruta_imagen(
        _base(version), pag["folleto__fuente"], pag["folleto__tienda__slug"],
        pag["folleto__folleto_id_fuente"], pag["archivo_imagen"],
    )


def _pagina_o_404(pagina_id: int) -> dict:
    pag = queries.pagina_origen(pagina_id)
    if pag is None:
        raise Http404("pagina inexistente")
    return pag


def _dimensiones_proc(pag: dict):
    try:
        return origen.dimensiones_imagen(_ruta_imagen_pagina(pag, "proc"))
    except origen.RutaInvalida:
        return None


def _cajas(fila: dict, dims) -> dict:
    return {**fila, "caja_pct": origen.caja_pct(fila, *dims) if dims else None}


def _meta_pagina(pag: dict) -> dict:
    return {
        "pagina_id": pag["id"],
        "numero_pagina": pag["numero_pagina"],
        "archivo_imagen": pag["archivo_imagen"],
        "total_paginas": pag["folleto__total_paginas"],
        "tienda": pag["folleto__tienda__nombre"],
        "fuente": pag["folleto__fuente"],
        "folleto_id": pag["folleto_id"],
        "folleto_id_fuente": pag["folleto__folleto_id_fuente"],
        "folleto_titulo": pag["folleto__titulo"],
        "vigencia_desde": pag["folleto__fecha_inicio"],
        "vigencia_hasta": pag["folleto__fecha_fin"],
        "url_origen": origen.url_origen_segura(pag["folleto__url_origen"]),
    }


@require_GET
def pagina_origen_extraccion(request, extraccion_id: int):
    datos = queries.origen_extraccion(extraccion_id)
    if datos is None:
        raise Http404("extraccion inexistente")
    return render(request, "dashboard/origen.html", {
        "activo": "", "pagina_id": datos["extraccion"]["pagina_id"], "extraccion_id": extraccion_id,
    })


@require_GET
def pagina_origen_pagina(request, pagina_id: int):
    _pagina_o_404(pagina_id)
    return render(request, "dashboard/origen.html", {"activo": "", "pagina_id": pagina_id, "extraccion_id": None})


@require_GET
def imagen_pagina(request, pagina_id: int):
    version = request.GET.get("version", "proc")
    if version not in origen.VERSIONES_IMAGEN:
        raise Http404("version no permitida")
    pag = _pagina_o_404(pagina_id)
    try:
        ruta = _ruta_imagen_pagina(pag, version)
        tipo = origen.tipo_contenido(ruta)
    except origen.RutaInvalida:
        raise Http404("ruta invalida")
    if not ruta.is_file():
        raise Http404("imagen no encontrada")
    resp = FileResponse(open(ruta, "rb"), content_type=tipo, as_attachment=False, filename=ruta.name)
    resp["Content-Disposition"] = f'inline; filename="{ruta.name}"'
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "private, max-age=3600"
    return resp


@require_GET
def api_origen_pagina(request, pagina_id: int):
    ctx = queries.contexto_pagina(pagina_id)
    if ctx is None:
        raise Http404("pagina inexistente")
    pag = ctx["pagina"]
    dims = _dimensiones_proc(pag)
    return JsonResponse({
        "pagina": _meta_pagina(pag),
        "vecinas": ctx["vecinas"],
        "imagen": {
            "proc": f"/origen/pagina/{pag['id']}.webp?version=proc",
            "raw": f"/origen/pagina/{pag['id']}.webp?version=raw",
            "dimensiones_proc": list(dims) if dims else None,
        },
        "bloques": [_cajas(b, dims) for b in ctx["bloques"]],
    })


@require_GET
def api_origen_extraccion(request, extraccion_id: int):
    datos = queries.origen_extraccion(extraccion_id)
    if datos is None:
        raise Http404("extraccion inexistente")
    pag = queries.pagina_origen(datos["extraccion"]["pagina_id"])
    dims = _dimensiones_proc(pag) if pag else None
    producto = datos["producto"]
    # la caja del producto solo se dibuja si esta en la misma pagina (hoy 27,760 / 27,760)
    if producto is None:
        producto_out = None
    elif producto["pagina_id"] != datos["extraccion"]["pagina_id"]:
        producto_out = {**producto, "otra_pagina": True, "caja_pct": None}
    else:
        producto_out = {**_cajas(producto, dims), "otra_pagina": False}
    return JsonResponse({
        "extraccion": _cajas(datos["extraccion"], dims),
        "producto": producto_out,
    })


@require_GET
def api_origen_json(request, pagina_id: int, tipo: str):
    if tipo not in origen.ARCHIVOS_JSON:
        raise Http404("tipo no permitido")
    pag = _pagina_o_404(pagina_id)
    try:
        ruta = origen.ruta_json(
            settings.ORIGEN_PROCESSED_DIR, pag["folleto__fuente"], pag["folleto__tienda__slug"],
            pag["folleto__folleto_id_fuente"], tipo,
        )
    except origen.RutaInvalida:
        raise Http404("ruta invalida")
    frag = origen.fragmento_pagina(ruta, pag["archivo_imagen"])
    salida = {"archivo": origen.ARCHIVOS_JSON[tipo], "pagina_archivo": pag["archivo_imagen"], **frag}

    # ?e=<extraccion_id>: marca los elementos que coinciden con la caja del precio y del producto asociado
    e = request.GET.get("e")
    if frag.get("estado") == "ok" and e and e.isdigit():
        datos = queries.origen_extraccion(int(e))
        if datos and datos["extraccion"]["pagina_id"] == pagina_id:
            cajas = {"precio": datos["extraccion"]}
            if datos["producto"] and datos["producto"]["pagina_id"] == pagina_id:
                cajas["producto"] = datos["producto"]
            salida["marcas"] = origen.marcar_bloques(frag["pagina"], cajas)
    return JsonResponse(salida)
