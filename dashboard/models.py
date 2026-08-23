"""
dashboard/models.py
PriceScraper - Modelos Django ORM mapeados a las tablas y vistas que ya
existen en Postgres (definidas en load/schema.sql y load/vistas.sql).

Todos managed=False: Django NO crea, altera ni borra estas tablas via
migrations -- el schema sigue siendo propiedad de schema.sql/vistas.sql,
ejecutado por load/db_builder.py. Estos modelos solo describen lo que ya
existe para poder usar el ORM en la capa de lectura del dashboard.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models


# =============================================================================
# Tablas base (load/schema.sql)
# =============================================================================

class Tienda(models.Model):
    nombre = models.CharField(max_length=100)
    slug = models.CharField(max_length=60, unique=True)
    fuente_slug = models.CharField(max_length=60, null=True, blank=True)
    activa = models.BooleanField(default=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "tiendas"

    def __str__(self):
        return self.nombre


class Folleto(models.Model):
    tienda = models.ForeignKey(
        Tienda, on_delete=models.DO_NOTHING, db_column="tienda_id", related_name="folletos"
    )
    folleto_id_fuente = models.CharField(max_length=30)
    fuente = models.CharField(max_length=20)
    titulo = models.CharField(max_length=200, null=True, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    url_origen = models.TextField(null=True, blank=True)
    total_paginas = models.IntegerField(default=0)
    perfil_ocr = models.CharField(max_length=40, null=True, blank=True)
    motor_ocr = models.CharField(max_length=20, null=True, blank=True)
    scrapeado_at = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "folletos"

    def __str__(self):
        return f"{self.fuente}/{self.folleto_id_fuente}"


class Pagina(models.Model):
    folleto = models.ForeignKey(
        Folleto, on_delete=models.DO_NOTHING, db_column="folleto_id", related_name="paginas"
    )
    numero_pagina = models.IntegerField()
    archivo_imagen = models.CharField(max_length=100, null=True, blank=True)
    total_bloques_ocr = models.IntegerField(default=0)
    confianza_ocr_prom = models.FloatField(null=True, blank=True)
    total_productos = models.IntegerField(default=0)
    total_precios = models.IntegerField(default=0)
    total_promos = models.IntegerField(default=0)
    total_atributos = models.IntegerField(default=0)
    tasa_util = models.FloatField(null=True, blank=True)
    procesado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "paginas"


class ProductoCanonico(models.Model):
    nombre_canonico = models.CharField(max_length=150, unique=True)
    categoria = models.CharField(max_length=60, null=True, blank=True)
    marca = models.CharField(max_length=80, null=True, blank=True)
    aliases = ArrayField(models.CharField(max_length=200), default=list, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "productos_canonicos"

    def __str__(self):
        return self.nombre_canonico


class Extraccion(models.Model):
    id = models.BigAutoField(primary_key=True)
    pagina = models.ForeignKey(
        Pagina, on_delete=models.DO_NOTHING, db_column="pagina_id", related_name="extracciones"
    )
    folleto = models.ForeignKey(
        Folleto, on_delete=models.DO_NOTHING, db_column="folleto_id", related_name="extracciones"
    )
    tienda = models.ForeignKey(
        Tienda, on_delete=models.DO_NOTHING, db_column="tienda_id", related_name="extracciones"
    )
    tipo = models.CharField(max_length=20)
    texto_raw = models.TextField()
    texto_norm = models.CharField(max_length=300, null=True, blank=True)
    categoria_nlp = models.CharField(max_length=60, null=True, blank=True)
    valor = models.FloatField(null=True, blank=True)
    valor_anterior = models.FloatField(null=True, blank=True)
    texto_promo = models.CharField(max_length=300, null=True, blank=True)
    confianza_ocr = models.FloatField(null=True, blank=True)
    bbox_x = models.IntegerField(null=True, blank=True)
    bbox_y = models.IntegerField(null=True, blank=True)
    bbox_ancho = models.IntegerField(null=True, blank=True)
    bbox_alto = models.IntegerField(null=True, blank=True)
    producto_extraccion = models.ForeignKey(
        "self", on_delete=models.DO_NOTHING, db_column="producto_extraccion_id",
        null=True, blank=True, related_name="asociados",
    )
    producto_canonico = models.ForeignKey(
        ProductoCanonico, on_delete=models.DO_NOTHING, db_column="producto_canonico_id",
        null=True, blank=True, related_name="extracciones",
    )
    confianza_norm = models.FloatField(null=True, blank=True)
    metodo_norm = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "extracciones"


class EventoPromo(models.Model):
    folleto = models.ForeignKey(
        Folleto, on_delete=models.DO_NOTHING, db_column="folleto_id", related_name="eventos_promo"
    )
    tienda = models.ForeignKey(
        Tienda, on_delete=models.DO_NOTHING, db_column="tienda_id", related_name="eventos_promo"
    )
    nombre_evento = models.CharField(max_length=100)
    texto_raw = models.CharField(max_length=200, null=True, blank=True)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "eventos_promo"


class Alerta(models.Model):
    tienda = models.ForeignKey(
        Tienda, on_delete=models.DO_NOTHING, db_column="tienda_id",
        null=True, blank=True, related_name="alertas",
    )
    slug_producto = models.CharField(max_length=200)
    umbral_precio = models.FloatField()
    activa = models.BooleanField(default=True)
    disparada_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "alertas"


# =============================================================================
# Vistas BI de solo lectura (load/vistas.sql)
# Todas managed=False -- son SELECT, Django nunca escribe en ellas.
# =============================================================================

class VPreciosActuales(models.Model):
    id = models.BigIntegerField(primary_key=True)
    tienda = models.CharField(max_length=100)
    tienda_slug = models.CharField(max_length=60)
    producto = models.CharField(max_length=300, null=True)
    categoria = models.CharField(max_length=60, null=True)
    precio_actual = models.FloatField(null=True)
    precio_anterior = models.FloatField(null=True)
    descuento_pct = models.FloatField(null=True)
    vigencia_desde = models.DateField(null=True)
    vigencia_hasta = models.DateField(null=True)
    fuente = models.CharField(max_length=20)
    folleto_id_fuente = models.CharField(max_length=30)
    confianza_ocr = models.FloatField(null=True)
    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "v_precios_actuales"


class VComparativaPrecios(models.Model):
    # Sin id natural (fila agregada por GROUP BY producto+categoria) --
    # "producto" es unico dentro de la vista (HAVING num_tiendas > 1 sobre
    # ese agrupamiento), se usa como pk solo para satisfacer al ORM.
    producto = models.CharField(max_length=300, primary_key=True)
    categoria = models.CharField(max_length=60, null=True)
    precio_min = models.FloatField()
    precio_max = models.FloatField()
    precio_promedio = models.FloatField()
    diferencia = models.FloatField()
    num_registros = models.IntegerField()
    num_tiendas = models.IntegerField()
    tiendas = models.TextField()

    class Meta:
        managed = False
        db_table = "v_comparativa_precios"


class VCalidadPipeline(models.Model):
    folleto_id = models.IntegerField(primary_key=True)
    tienda = models.CharField(max_length=100)
    folleto_id_fuente = models.CharField(max_length=30)
    fuente = models.CharField(max_length=20)
    fecha_inicio = models.DateField(null=True)
    total_paginas = models.IntegerField()
    paginas_procesadas = models.IntegerField()
    total_productos = models.IntegerField(null=True)
    total_precios = models.IntegerField(null=True)
    total_promos = models.IntegerField(null=True)
    confianza_ocr_prom = models.FloatField(null=True)
    tasa_util_prom = models.FloatField(null=True)
    perfil_ocr = models.CharField(max_length=40, null=True)
    motor_ocr = models.CharField(max_length=20, null=True)
    estado = models.CharField(max_length=20)
    scrapeado_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = "v_calidad_pipeline"


class VHistoricoPrecios(models.Model):
    id = models.BigIntegerField(primary_key=True)
    tienda = models.CharField(max_length=100)
    tienda_slug = models.CharField(max_length=60)
    producto = models.CharField(max_length=300, null=True)
    categoria = models.CharField(max_length=60, null=True)
    fecha = models.DateField()
    precio = models.FloatField(null=True)
    precio_anterior = models.FloatField(null=True)
    folleto_id_fuente = models.CharField(max_length=30)
    fuente = models.CharField(max_length=20)

    class Meta:
        managed = False
        db_table = "v_historico_precios"


class VEventosActivos(models.Model):
    id = models.IntegerField(primary_key=True)
    nombre_evento = models.CharField(max_length=100)
    tienda = models.CharField(max_length=100)
    fecha_inicio = models.DateField(null=True)
    fecha_fin = models.DateField(null=True)
    texto_raw = models.CharField(max_length=200, null=True)
    num_precios_asociados = models.IntegerField()

    class Meta:
        managed = False
        db_table = "v_eventos_activos"
