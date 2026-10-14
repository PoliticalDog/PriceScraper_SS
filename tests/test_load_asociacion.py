"""Asociacion precio -> producto por cercania (load.asociar_por_cercania)."""
from load.load import MARGEN_DEBAJO_PRECIO, asociar_por_cercania


def _bloque(texto, x, y, ancho=100, alto=30):
    return {"texto": texto, "bbox": {"x": x, "y": y, "ancho": ancho, "alto": alto}}


PRECIO = _bloque("$199", 500, 1000, alto=60)


def test_sin_admitir_debajo_conserva_solo_arriba():
    lejos_arriba = _bloque("ruido", 500, 700)
    debajo = _bloque("Audifonos Vibe Beam 2", 505, 1068)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, debajo]) is lejos_arriba


def test_nombre_justo_debajo_gana_a_bloque_lejano_arriba():
    # Chedraui/Walmart: el nombre va debajo del precio y lo mas cercano arriba es otro articulo
    lejos_arriba = _bloque("Ioow", 500, 700)
    debajo = _bloque("Audifonos Vibe Beam 2", 505, 1068)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, debajo], admitir_debajo=True) is debajo


def test_nombre_a_la_misma_altura():
    # Alsuper: el nombre a la izquierda del precio, misma fila
    lejos_arriba = _bloque("RGYADA", 500, 740)
    lado = _bloque("DURAZNO", 382, 994)
    assert asociar_por_cercania(PRECIO, [lejos_arriba, lado], admitir_debajo=True) is lado


def test_debajo_fuera_del_margen_no_cuenta():
    debajo_lejos = _bloque("siguiente articulo", 500, 1000 + 60 + MARGEN_DEBAJO_PRECIO + 1)
    assert asociar_por_cercania(PRECIO, [debajo_lejos], admitir_debajo=True) is None


def test_arriba_mas_cercano_que_debajo_sigue_ganando():
    # El bloque de abajo no esta alineado con el precio (dx 40 > ALINEACION_DEBAJO_PX): regla general
    arriba = _bloque("Crema acida", 500, 950)
    debajo = _bloque("200 g", 540, 1080)
    assert asociar_por_cercania(PRECIO, [debajo, arriba], admitir_debajo=True) is arriba


def test_empate_prefiere_arriba():
    arriba = _bloque("arriba", 500, 950)
    debajo = _bloque("debajo", 540, 1050)
    assert asociar_por_cercania(PRECIO, [debajo, arriba], admitir_debajo=True) is arriba


# -- Nombre alineado bajo el precio (ALINEACION_DEBAJO_PX) ---------------------------------

def test_alineado_debajo_gana_a_columna_vecina_mas_cercana():
    # Chedraui 416057 p15: "Lavadora" de la columna vecina (dx -228) empataba con "Lavasecadora"
    vecina = _bloque("Lavadora", 272, 1080)
    alineado = _bloque("Lavasecadora", 507, 1080)
    assert asociar_por_cercania(PRECIO, [vecina, alineado], admitir_debajo=True) is alineado


def test_alineado_debajo_gana_a_basura_junto_al_precio():
    # Chedraui 416057 p13: "Veloc" (OCR de la foto, al lado del precio) contra "Motocicleta" debajo
    junto = _bloque("Veloc", 719, 1040, alto=16)
    alineado = _bloque("Motoneta VENTO", 508, 1100, alto=24)
    assert asociar_por_cercania(PRECIO, [junto, alineado], admitir_debajo=True) is alineado


def test_alineado_debajo_gana_al_primero_de_la_pila():
    primera = _bloque("Colchon matrimonial en caja", 506, 1072, alto=28)
    segunda = _bloque("Mod. Notte Azul", 506, 1096, alto=26)
    assert asociar_por_cercania(PRECIO, [segunda, primera], admitir_debajo=True) is primera


def test_alineado_debajo_gana_aunque_haya_nombre_arriba():
    # Costo conocido (S-Mart 423050: "Melon" pegado encima, "Tuna blanca" alineada debajo):
    # el bloque alineado debajo gana. Medido en dev: +23 / -7 articulos.
    arriba = _bloque("Melon", 500, 950)
    alineado = _bloque("Tuna blanca", 500, 1080)
    assert asociar_por_cercania(PRECIO, [arriba, alineado], admitir_debajo=True) is alineado


def test_segunda_linea_de_nombre_que_empieza_arriba_no_cuenta():
    # 3B 428040: "Tostadas de Maiz" a la altura del precio y "Horneadas" (su 2a linea) alineada debajo
    nombre = _bloque("Tostadas de Maiz", 380, 1010, ancho=200, alto=30)
    segunda = _bloque("Horneadas", 500, 1045, alto=30)
    assert asociar_por_cercania(PRECIO, [segunda, nombre], admitir_debajo=True) is nombre


def test_alineado_debajo_respeta_margen_y_centro_del_precio():
    # Empieza por encima del centro del precio: no es "debajo"; mas alla del margen: no cuenta
    a_la_altura = _bloque("a la altura", 505, 1020)
    lejos = _bloque("lejos", 505, 1000 + 60 + MARGEN_DEBAJO_PRECIO + 1)
    assert asociar_por_cercania(PRECIO, [lejos, a_la_altura], admitir_debajo=True) is a_la_altura


def test_nombre_arriba_y_casilla_siguiente_con_su_precio_gana_arriba():
    # Casa Ley 422328 p1 (reticula, nombre arriba y precio al pie): "Pimiento" (casilla de abajo)
    # queda pegado bajo "$299" y alineado, pero tiene su propio precio debajo -> gana "Aceite"
    arriba = _bloque("Aceite", 500, 950)
    siguiente = _bloque("Pimiento", 500, 1065)
    precio_siguiente = _bloque("$557", 505, 1170, alto=60)
    assert asociar_por_cercania(PRECIO, [siguiente, arriba], admitir_debajo=True,
                                precios=[PRECIO, precio_siguiente]) is arriba


def test_empate_con_casilla_siguiente_con_su_precio_prefiere_arriba():
    # Equivalente a test_empate_prefiere_arriba con el bloque de abajo alineado
    arriba = _bloque("arriba", 500, 950)
    debajo = _bloque("debajo", 500, 1050)
    precio_siguiente = _bloque("$10", 500, 1120, alto=60)
    assert asociar_por_cercania(PRECIO, [debajo, arriba], admitir_debajo=True,
                                precios=[precio_siguiente, PRECIO]) is arriba


def test_precio_propio_lejano_no_bloquea_el_alineado():
    # Chedraui 416057 p13: el precio de la fila siguiente esta a ~350 px de "Motocicleta"
    alineado = _bloque("Motocicleta", 508, 1100, alto=24)
    junto = _bloque("Veloc", 719, 1040, alto=16)
    otra_fila = _bloque("$18,999", 505, 1100 + 350, alto=74)
    assert asociar_por_cercania(PRECIO, [junto, alineado], admitir_debajo=True,
                                precios=[PRECIO, otra_fila]) is alineado


def test_precio_propio_debe_estar_alineado():
    # Un precio debajo pero en otra columna (dx 60) no convierte al alineado en casilla siguiente
    alineado = _bloque("Lavasecadora", 507, 1080)
    vecina = _bloque("Lavadora", 272, 1080)
    precio_otra_columna = _bloque("$9", 567, 1150, alto=60)
    assert asociar_por_cercania(PRECIO, [vecina, alineado], admitir_debajo=True,
                                precios=[PRECIO, precio_otra_columna]) is alineado


# -- Diseno de la pagina (diseno_nombre_debajo) --------------------------------------------

def _pagina_nombre_debajo():
    # Chedraui/Walmart: precio y debajo, alineado, su nombre; filas separadas por ~470 px
    precios, productos = [], []
    for x in (100, 500, 900):
        for y in (400, 870):
            precios.append(_bloque("$999", x, y, alto=70))
            productos.append(_bloque("Motocicleta", x + 8, y + 100, alto=24))
    return precios, productos


def _pagina_reticula_nombre_arriba():
    # Casa Ley: nombre arriba, precio al pie y el nombre de la casilla siguiente pegado debajo
    precios, productos = [], []
    for x in (100, 300, 500):
        for fila in range(4):
            y = 300 + 145 * fila
            productos.append(_bloque("Aceite", x, y, alto=30))
            precios.append(_bloque("$299", x + 5, y + 100, alto=40))
    return precios, productos


def test_detecta_pagina_nombre_debajo():
    from load.load import diseno_nombre_debajo
    assert diseno_nombre_debajo(*_pagina_nombre_debajo()) is True


def test_reticula_nombre_arriba_no_es_nombre_debajo():
    from load.load import diseno_nombre_debajo
    assert diseno_nombre_debajo(*_pagina_reticula_nombre_arriba()) is False


def test_pagina_sin_vecinos_alineados_no_es_nombre_debajo():
    from load.load import diseno_nombre_debajo
    precios = [_bloque("$10", 100, 400, alto=60)]
    productos = [_bloque("lejos al lado", 400, 420)]
    assert diseno_nombre_debajo(precios, productos) is False
    assert diseno_nombre_debajo([], []) is False


def test_reticula_nombre_arriba_conserva_la_regla_general_en_toda_la_pagina():
    # Con alinear_debajo=False (pagina no "nombre debajo") gana el nombre pegado arriba aunque
    # el de la casilla siguiente este alineado debajo y SIN precio propio leido
    from load.load import construir_registros_pagina

    class _Norm:
        def normalizar(self, texto):
            from types import SimpleNamespace
            return SimpleNamespace(descartado=False, metodo="exacto", categoria="x", nombre_canonico=texto)

    precios, productos = _pagina_reticula_nombre_arriba()
    precios = precios[:1]  # solo se leyo un precio: la guarda de precio propio no puede actuar
    # Descripcion de la casilla propia (recuadro sangrado) pegada encima del precio, como en Casa Ley
    descripcion = _bloque("Carton 12/400 ml", 135, 370, alto=24)
    pag = {"productos": productos + [descripcion], "precios": precios, "precios_anteriores": []}
    registro = construir_registros_pagina(pag, None, _Norm())["precios"][0]
    assert registro["producto"]["texto"] == "Carton 12/400 ml"  # no "Aceite" de la casilla de abajo (y=445)


def test_alineacion_no_aplica_a_atributos():
    arriba = _bloque("arriba", 500, 950)
    alineado = _bloque("alineado", 500, 1080)
    assert asociar_por_cercania(PRECIO, [arriba, alineado]) is arriba


def test_atributos_conservan_distancia_solo_vertical():
    # Sin admitir_debajo el criterio no cambia: el mas cercano arriba por dy, sin mirar dx
    lado = _bloque("lejos al lado", 850, 980)
    encima = _bloque("encima", 500, 900)
    assert asociar_por_cercania(PRECIO, [encima, lado]) is lado


# -- Columna propia sobre la casilla vecina en diagonal ----------------------------------------

def test_vecina_en_diagonal_cede_a_nombre_de_la_propia_columna():
    # Casa Ley 426471 p3: "$305.66" (Pinol) tomaba "lalo" de la casilla vecina (dx -368, mas cerca
    # en vertical) teniendo "Aceite De Pino Pinol" encima, en su columna
    vecina = _bloque("lalo", 250, 960, alto=30)          # otra columna y otra fila, dy 40
    propia = _bloque("Aceite De Pino", 510, 900, alto=30)  # traslapa en x con el precio, dy 100
    assert asociar_por_cercania(PRECIO, [vecina, propia], admitir_debajo=True) is propia


def test_vecina_debajo_en_diagonal_cede_a_la_propia_columna():
    vecina = _bloque("Paquete", 760, 1065, alto=14)                  # debajo, dx 260, dy 65
    propia = _bloque("Toallitas humedas", 490, 930, ancho=120)       # arriba, dy 70
    assert asociar_por_cercania(PRECIO, [vecina, propia], admitir_debajo=True) is propia


def test_vecina_en_diagonal_sin_alternativa_en_la_columna_se_mantiene():
    vecina = _bloque("vecina", 250, 960, alto=30)
    otra = _bloque("otra mas lejos", 800, 900)  # tampoco traslapa en x con el precio
    assert asociar_por_cercania(PRECIO, [otra, vecina], admitir_debajo=True) is vecina


def test_merco_nombre_a_la_izquierda_en_la_fila_no_cambia():
    # Merco 415805 (fila_izq): el nombre va a la izquierda, a la altura del precio, sin traslape en x;
    # lo de encima en la columna del precio (otro articulo, titulo) no le gana
    precio = _bloque("$7.99", 400, 871, ancho=100, alto=68)
    nombre = _bloque("SANDIA ROJA", 223, 901, ancho=145, alto=49)
    encima = _bloque("ARMA AQUI", 380, 700, ancho=600, alto=60)
    assert asociar_por_cercania(precio, [encima, nombre], admitir_debajo=True) is nombre


def test_chedraui_nombre_alineado_debajo_no_cambia():
    # Pagina "nombre debajo": la regla de alineacion decide antes que la de columna
    vecina = _bloque("Lavadora", 272, 960, alto=30)     # diagonal arriba, dy 40
    alineado = _bloque("Lavasecadora", 507, 1080)
    assert asociar_por_cercania(PRECIO, [vecina, alineado], admitir_debajo=True,
                                alinear_debajo=True) is alineado


def test_reticula_encabezado_de_abajo_cede_al_nombre_de_arriba():
    # Casa Ley 430500 p1: "$68.04" (Inflallantas) con la casilla vecina en diagonal; en su columna el
    # mas cercano es "Protector", encabezado de la casilla de abajo sin precio leido
    vecina = _bloque("Pieza", 250, 1065, alto=14)          # diagonal, dy 65
    abajo = _bloque("Protector", 495, 1070)                 # columna, debajo, dy 70
    arriba = _bloque("Inflallantas", 495, 900)              # columna, arriba, dy 100
    prods = [vecina, abajo, arriba]
    assert asociar_por_cercania(PRECIO, prods, admitir_debajo=True, alinear_debajo=False) is abajo
    assert asociar_por_cercania(PRECIO, prods, admitir_debajo=True, alinear_debajo=False,
                                reticula=True) is arriba


def test_reticula_sin_nombre_arriba_en_la_columna_usa_el_de_abajo():
    vecina = _bloque("Pieza", 250, 1065, alto=14)
    abajo = _bloque("Protector", 495, 1070)
    assert asociar_por_cercania(PRECIO, [vecina, abajo], admitir_debajo=True, alinear_debajo=False,
                                reticula=True) is abajo


def test_reticula_detectada_por_vecinos_alineados_en_ambos_lados():
    from load.load import _es_reticula, conteo_vecinos_alineados
    assert _es_reticula(conteo_vecinos_alineados(*_pagina_reticula_nombre_arriba())) is True
    assert _es_reticula(conteo_vecinos_alineados(*_pagina_nombre_debajo())) is False


def test_paginas_de_dev_con_nombre_propio_debajo_no_son_reticula():
    # Conteos reales: Soriana Hiper 422326 p13 ("Tapete de bano" debajo del precio) y 3B 419897 p13
    # ("Mermelada de Fresa"); en reticula perdian su nombre por el de la casilla de arriba
    from load.load import _es_reticula
    assert _es_reticula({"solo_debajo": 0, "solo_arriba": 5, "ambos": 1}) is False
    assert _es_reticula({"solo_debajo": 0, "solo_arriba": 1, "ambos": 0}) is False
    # pocas casillas: no basta con que "ambos" sea mayoria
    assert _es_reticula({"solo_debajo": 0, "solo_arriba": 0, "ambos": 2}) is False


def test_pagina_no_reticula_conserva_el_nombre_propio_debajo():
    # Como Soriana Hiper 422326 p13: el nombre propio en la columna, debajo y mas cerca que el de la
    # casilla de arriba; la casilla vecina en diagonal. Fuera de reticula gana el de debajo
    from load.load import construir_registros_pagina

    class _Norm:
        def normalizar(self, texto):
            from types import SimpleNamespace
            return SimpleNamespace(descartado=False, metodo="exacto", categoria="x", nombre_canonico=texto)

    precio = _bloque("$199", 500, 1000, alto=60)
    productos = [_bloque("Cobertor", 250, 1065, alto=14),            # diagonal
                 _bloque("Tapete de bano", 530, 1070),              # columna, debajo (no alineado)
                 _bloque("MATRIMONIAL", 530, 880)]                  # columna, arriba
    pag = {"productos": productos, "precios": [precio], "precios_anteriores": []}
    registro = construir_registros_pagina(pag, None, _Norm())["precios"][0]
    assert registro["producto"]["texto"] == "Tapete de bano"


def test_columna_propia_no_aplica_a_atributos():
    vecina = _bloque("vecina", 250, 960, alto=30)
    propia = _bloque("propia", 510, 900, alto=30)
    assert asociar_por_cercania(PRECIO, [vecina, propia]) is vecina


def test_tolerancia_horizontal_se_mantiene():
    debajo_otra_columna = _bloque("otro", 950, 1020)
    assert asociar_por_cercania(PRECIO, [debajo_otra_columna], admitir_debajo=True) is None
