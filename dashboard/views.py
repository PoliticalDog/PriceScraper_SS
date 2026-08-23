"""
dashboard/views.py
PriceScraper - Vistas del dashboard interno (Django).

Migrado desde FastAPI (dashboard/app.py, 23-ago-2026) para cumplir el stack
documentado en Propuesta_PriceScraper_SS.docx. dashboard/queries.py no se
tocó -- sigue siendo SQL crudo vía load/db_builder.py, reusado tal cual.
"""

from django.http import JsonResponse
from django.shortcuts import render

from dashboard import queries


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


def pagina_promociones(request):
    return render(request, "dashboard/promociones.html", {"activo": "promociones"})


# -- API (JSON) -------------------------------------------------------------------

def api_filtros_tiendas(request):
    return JsonResponse(queries.listar_tiendas(), safe=False)


def api_filtros_categorias(request):
    return JsonResponse(queries.listar_categorias(), safe=False)


def api_resumen(request):
    return JsonResponse({
        "kpis": queries.resumen_kpis(),
        "top_categorias": queries.resumen_top_categorias(),
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
    )
    return JsonResponse(datos, safe=False)


def api_comparativa(request):
    datos = queries.comparativa_precios(
        categorias=request.GET.getlist("categoria") or None,
        q=request.GET.get("q") or None,
        min_tiendas=int(request.GET.get("min_tiendas", 1)),
    )
    return JsonResponse(datos, safe=False)


def api_comparativa_por_tienda(request, producto):
    return JsonResponse(queries.comparativa_por_tienda(producto), safe=False)


def api_historico(request):
    producto = request.GET.get("producto", "")
    datos = queries.historico_precios(
        producto,
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
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
    )
    return JsonResponse(datos, safe=False)


def api_eventos(request):
    datos = queries.eventos_promo(
        tiendas=request.GET.getlist("tienda") or None,
        desde=request.GET.get("desde") or None,
        hasta=request.GET.get("hasta") or None,
    )
    return JsonResponse(datos, safe=False)
