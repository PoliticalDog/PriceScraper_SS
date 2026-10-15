from django.urls import path

from dashboard import views

urlpatterns = [
    # Paginas
    path("", views.pagina_resumen, name="resumen"),
    path("precios", views.pagina_precios, name="precios"),
    path("comparativa", views.pagina_comparativa, name="comparativa"),
    path("historico", views.pagina_historico, name="historico"),
    path("calidad", views.pagina_calidad, name="calidad"),
    path("cobertura", views.pagina_cobertura, name="cobertura"),
    path("promociones", views.pagina_promociones, name="promociones"),
    path("errores", views.pagina_errores, name="errores"),
    path("datos", views.pagina_explorador, name="explorador"),

    # Procedencia por registro (solo GET, solo ids enteros)
    path("origen/extraccion/<int:extraccion_id>", views.pagina_origen_extraccion, name="origen_extraccion"),
    path("origen/pagina/<int:pagina_id>", views.pagina_origen_pagina, name="origen_pagina"),
    path("origen/pagina/<int:pagina_id>.webp", views.imagen_pagina, name="origen_imagen"),

    # API
    path("api/filtros/tiendas", views.api_filtros_tiendas),
    path("api/filtros/categorias", views.api_filtros_categorias),
    path("api/filtros/folleto", views.api_filtros_folleto),
    path("api/resumen", views.api_resumen),
    path("api/precios", views.api_precios),
    path("api/comparativa", views.api_comparativa),
    path("api/comparativa/<str:producto>/por-tienda", views.api_comparativa_por_tienda),
    path("api/historico", views.api_historico),
    path("api/productos/sugerencias", views.api_productos_sugerencias),
    path("api/calidad", views.api_calidad),
    path("api/confiabilidad", views.api_confiabilidad),
    path("api/cobertura", views.api_cobertura),
    path("api/cobertura/semanal", views.api_cobertura_semanal),
    path("api/eventos", views.api_eventos),
    path("api/filtros/errores", views.api_filtros_errores),
    path("api/errores", views.api_errores),
    path("api/origen/pagina/<int:pagina_id>", views.api_origen_pagina),
    path("api/origen/pagina/<int:pagina_id>/<str:tipo>", views.api_origen_json),
    path("api/origen/extraccion/<int:extraccion_id>", views.api_origen_extraccion),
]
