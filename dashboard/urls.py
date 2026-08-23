from django.urls import path

from dashboard import views

urlpatterns = [
    # Paginas
    path("", views.pagina_resumen, name="resumen"),
    path("precios", views.pagina_precios, name="precios"),
    path("comparativa", views.pagina_comparativa, name="comparativa"),
    path("historico", views.pagina_historico, name="historico"),
    path("calidad", views.pagina_calidad, name="calidad"),
    path("promociones", views.pagina_promociones, name="promociones"),

    # API
    path("api/filtros/tiendas", views.api_filtros_tiendas),
    path("api/filtros/categorias", views.api_filtros_categorias),
    path("api/resumen", views.api_resumen),
    path("api/precios", views.api_precios),
    path("api/comparativa", views.api_comparativa),
    path("api/comparativa/<str:producto>/por-tienda", views.api_comparativa_por_tienda),
    path("api/historico", views.api_historico),
    path("api/productos/sugerencias", views.api_productos_sugerencias),
    path("api/calidad", views.api_calidad),
    path("api/eventos", views.api_eventos),
]
