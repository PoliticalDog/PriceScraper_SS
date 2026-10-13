# Lee nlp_resultado.json, asocia productos-precios por proximidad bbox e inserta en PostgreSQL

import json
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from vision.preprocessor import obtener_preprocesador
from vision.region_detector import detectar_regiones, calificar_regiones, asociar_producto_por_region

from nlp.normalizador import Normalizador

from .db_builder import get_connection, get_cursor

# incia el loggin en consola
logger = logging.getLogger(__name__)

# variables de path
DATA_PROCESSED = Path("data/processed")
DATA_RAW = Path("data/raw")
RUTA_REGISTRO_SCRAPER = Path("data/registro_folletos_scrapeados.json")

# = fuente_enum de schema.sql. Solo data/processed/<fuente>/<tienda>/<folleto>/ es produccion;
# las demas carpetas (_v*, *_anterior_*) son experimentos o respaldos con los mismos folleto_id.
FUENTES = ("tiendeo", "ofertomat")


def rutas_nlp(data_processed: Path = DATA_PROCESSED) -> list[Path]:
    data_processed = Path(data_processed)
    rutas = []
    for fuente in FUENTES:
        rutas += (data_processed / fuente).glob("*/*/nlp_resultado.json")
    return sorted(rutas)

# (fuente, slug_scraper) -> (slug, nombre). La entrada ("tiendeo", "walmart") -> soriana
# se quito el 08-oct-2026: los folletos de tiendeo/walmart si son de Walmart.
CORRECCION_TIENDAS: dict[tuple[str, str], tuple[str, str]] = {}

# tiendas que se benefician de ROI
TIENDAS_ROI_HIBRIDO = {"walmart", "chedraui", "soriana_hiper", "soriana_mercado"}

_preprocesador_roi = None

# -- Precio anterior --------------------------------------------------------------
# Hasta oct-2026 cada precio tomaba el "antes" con la esquina mas cercana (<=300px) sin
# validar nada: un mismo "antes" acababa en varios precios (incluidas mensualidades MSI)
# y casi la mitad de los descuentos salian >70%. Ahora el par debe compartir columna,
# ir pegado arriba o abajo, ser uno a uno y dar un descuento creible.
DESCUENTO_MIN = 0.03   # ground truth (266 pares): minimo real 7%
DESCUENTO_MAX = 0.50   # p95 real 47%; arriba casi siempre es un precio o un tachado mal leido
_PATRON_FINANCIAMIENTO = re.compile(r"msi|meses|quincena|semana|\|", re.IGNORECASE)


def _costo_par(bbox_ant: dict, bbox_precio: dict) -> Optional[float]:
    """Que tan probable es que el "antes" pertenezca al precio (menor = mejor); None si no puede."""
    ax, ay, aw, ah = (bbox_ant.get(k, 0) for k in ("x", "y", "ancho", "alto"))
    px, py, pw, ph = (bbox_precio.get(k, 0) for k in ("x", "y", "ancho", "alto"))
    if min(aw, ah, pw, ph) <= 0:
        return None
    # Misma columna: Chedraui/HEB/Soriana alinean el "antes" con el precio, Walmart igual pero abajo
    if min(ax + aw, px + pw) - max(ax, px) < 0.3 * min(aw, pw):
        return None
    alto = max(ah, ph)
    gap = py - (ay + ah) if ay + ah / 2 < py + ph / 2 else ay - (py + ph)   # arriba o abajo del precio
    if gap < -0.6 * min(ah, ph) or gap > 1.2 * alto:
        return None
    desfase_x = abs((ax + aw / 2) - (px + pw / 2)) / max(aw, pw)
    # El precio vigente es el numero grande; el chico de al lado suele ser centavos o unidad
    return max(gap, 0) / alto + desfase_x + (0.5 if ph < ah else 0)


def _es_creible(anterior: float, actual: float) -> bool:
    return DESCUENTO_MIN <= (anterior - actual) / anterior <= DESCUENTO_MAX


def _lectura_coherente(candidatos: list[float], precio: dict) -> Optional[float]:
    actual = precio.get("valor")
    if not actual or actual <= 0:
        return None
    for c in candidatos:
        if c and _es_creible(c, actual):
            # "5107" (Walmart, "$" leido como 5) se guardo como 51.07 pero suele ser $107:
            # si esa otra lectura tambien cuadra, no se sabe cual es el precio real
            m = re.match(r"([58])(\d[\d,]*)$", precio.get("texto", ""))
            if m:
                alterno = float(m[2].replace(",", ""))
                if alterno != actual and _es_creible(c, alterno):
                    return None
            return c
    return None


def emparejar_precios_anteriores(precios: list[dict], precios_ant: list[dict]) -> list[Optional[float]]:
    """Precio anterior de cada precio de la pagina (misma posicion que `precios`), o None."""
    resultado: list[Optional[float]] = [None] * len(precios)
    pares = []
    for i, precio in enumerate(precios):
        if _PATRON_FINANCIAMIENTO.search(precio.get("texto", "")):
            continue
        for j, ant in enumerate(precios_ant):
            costo = _costo_par(ant.get("bbox", {}), precio.get("bbox", {}))
            if costo is not None:
                pares.append((costo, i, j))

    ants_usados = set()
    for _, i, j in sorted(pares):
        if resultado[i] is not None or j in ants_usados:
            continue
        ant = precios_ant[j]
        valor = _lectura_coherente(ant.get("candidatos") or [ant.get("valor")], precios[i])
        if valor is not None:
            resultado[i] = valor
            ants_usados.add(j)
    return resultado


# -- Asociacion de una pagina (sin BD) ----------------------------------------------
# Todo lo que load decide en una pagina, separado de los INSERT: que productos sobreviven
# al normalizador y que producto y precio anterior lleva cada precio. El evaluador
# (evaluador/) llama a estas mismas funciones para medir exactamente lo que llega al dashboard.

def candidatas_roi_pagina(fuente: str, slug_raw: str, folleto_id: str, nombre_pag: str) -> list[dict] | None:
    """Recuadros candidatos de la imagen, solo por geometria (lo costoso: preprocesa la imagen).
    None si la tienda no usa ROI o falta la imagen."""
    if slug_raw not in TIENDAS_ROI_HIBRIDO:
        return None
    ruta_imagen = DATA_RAW / fuente / slug_raw / folleto_id / nombre_pag
    if not ruta_imagen.exists():
        return None
    return detectar_regiones(_obtener_preprocesador_roi().procesar(ruta_imagen))


def regiones_con_precio(candidatas: list[dict], precios: list[dict]) -> list[dict]:
    """Candidatas que contienen al menos un precio del NLP (las que usa la asociacion ROI)."""
    bloques_precio = [{"texto": p.get("texto", ""), "bbox": p.get("bbox", {})} for p in precios]
    return [r for r in calificar_regiones(candidatas, bloques_precio) if r["tiene_precio"]]


# Precio -> producto por cercania: tambien se admite un nombre a la misma altura o justo debajo
# del precio (su borde superior a lo mas alto_precio + este margen bajo el borde superior del precio).
# Dev 11-oct-2026: en 153 de 266 precios bien leidos con el producto equivocado, el bloque con
# el nombre correcto estaba al lado o debajo del precio (Chedraui/Walmart electronica, 3B, Bodega
# Aurrera, Alsuper con el nombre a la izquierda del precio), y 130 de ellos a <100px del borde
# inferior del precio; el criterio "solo arriba" tomaba una linea lejana o ruido.
MARGEN_DEBAJO_PRECIO = 100

# Nombre alineado bajo el precio: con admitir_debajo, si un producto empieza debajo del centro
# del precio (dentro del margen de arriba) y su borde izquierdo coincide con el del precio a
# lo mas ALINEACION_DEBAJO_PX, gana el mas cercano de esos aunque otro bloque este unos pixeles
# mas cerca en vertical. Dev 12-oct-2026 (Chedraui electronica/linea blanca/motos, Chedraui
# pantallas): en 32 de 51 precios mal asociados ganaba un bloque de la columna vecina
# (dx 180-400: "Lavadora" contra "Lavasecadora" empatados a 146 px, "Pantalla Sharp 75" contra
# "Pantalla Daewoo") o basura OCR junto al precio ("Veloc", "Mororo", "Ocla- Coro"), mientras
# el nombre correcto estaba debajo con |dx| <= 13. Sin bloque alineado se usa la regla general.
ALINEACION_DEBAJO_PX = 20


def _continua_otro_bloque(prod: dict, productos: list) -> bool:
    """True si `prod` es la 2a linea de un nombre que empieza en otro bloque producto: hay uno
    justo encima (separacion vertical de a lo mas una linea de `prod`) que se le traslapa en x.
    Dev 12-oct-2026: en 3B/Soriana/Alsuper el nombre empieza a la altura del precio y su 2a linea
    queda alineada debajo ("Tostadas de Maiz" / "Horneadas", "MANZANA" / "COLDEN EN BOLSA");
    ahi la linea alineada no es el inicio del nombre y decide la regla general.
    No se aplica al precio mismo (nombre pegado encima del precio): recuperaba 5 articulos de
    S-Mart/Waldos/HEB pero la basura OCR pegada sobre el precio en Chedraui ("KRUPS", "Ocla- Coro")
    desactivaba la regla y chedraui caia de 21.0% a 16.1% de precision."""
    b = prod.get("bbox", {})
    x0, x1, y, alto = b.get("x", 0), b.get("x", 0) + b.get("ancho", 0), b.get("y", 0), b.get("alto", 0)
    for otro in productos:
        if otro is prod:
            continue
        o = otro.get("bbox", {})
        separacion = y - (o.get("y", 0) + o.get("alto", 0))
        traslape_x = min(x1, o.get("x", 0) + o.get("ancho", 0)) - max(x0, o.get("x", 0))
        if o.get("y", 0) < y and -alto / 2 <= separacion <= alto and traslape_x > 0:
            return True
    return False


def _tiene_precio_propio(prod: dict, precio: dict, precios: list) -> bool:
    """True si `prod` (alineado bajo `precio`) tiene OTRO precio alineado debajo de el, a lo mas
    alto_de_ese_precio + MARGEN_DEBAJO_PRECIO (el mismo alcance con que un precio llega a un nombre):
    entonces `prod` es el nombre de la casilla siguiente. Dev 12-oct-2026 (QA): en Casa Ley
    (reticula con el nombre arriba y el precio al pie) el nombre de la casilla de abajo queda
    pegado bajo el precio ("Aceite $299" -> "Pimiento") y 136 de 208 precios cambiaban hacia la
    casilla de abajo; ese nombre tiene su propio precio alineado a 103-160 px. En Chedraui el
    precio propio del nombre, cuando lo hay, esta a 239-481 px."""
    b = prod.get("bbox", {})
    x, y = b.get("x", 0), b.get("y", 0)
    for otro in precios:
        o = otro.get("bbox", {})
        if otro is precio or o == precio.get("bbox"):
            continue
        if (abs(o.get("x", 0) - x) <= ALINEACION_DEBAJO_PX
                and y < o.get("y", 0) <= y + o.get("alto", 0) + MARGEN_DEBAJO_PRECIO):
            return True
    return False


def diseno_nombre_debajo(precios: list, productos: list) -> bool:
    """
    Diseno de la pagina sin GT ni tienda: True si es "nombre debajo del precio". Para cada precio
    se mira si hay un producto alineado (|dx| <= ALINEACION_DEBAJO_PX) arriba (borde superior hasta
    alto + MARGEN_DEBAJO_PRECIO por encima) y/o debajo (misma ventana que la regla de alineacion).
    La pagina es "nombre debajo" si los precios con vecino alineado SOLO debajo son mayoria estricta
    sobre los que lo tienen solo arriba o en ambos lados.
    Dev 12-oct-2026: en la reticula de Casa Ley (nombre arriba, precio al pie y el nombre de la
    casilla siguiente pegado debajo) domina "ambos" en las 9 paginas; en Walmart 413251/413647 y
    Chedraui domina "solo debajo"; en S-Mart, La Comer, Soriana Hiper 422326 domina "solo arriba".
    """
    solo_debajo = otros = 0
    for precio in precios:
        b = precio.get("bbox", {})
        x, y, alto = b.get("x", 0), b.get("y", 0), b.get("alto", 0)
        limite = alto + MARGEN_DEBAJO_PRECIO
        arriba = debajo = False
        for prod in productos:
            q = prod.get("bbox", {})
            if abs(q.get("x", 0) - x) > ALINEACION_DEBAJO_PX:
                continue
            qy = q.get("y", 0)
            arriba = arriba or y - limite <= qy < y
            debajo = debajo or y + alto / 2 <= qy <= y + limite
        if debajo and not arriba:
            solo_debajo += 1
        elif arriba:
            otros += 1
    return solo_debajo > otros


def asociar_por_cercania(item: dict, productos: list, admitir_debajo: bool = False,
                         precios: list | None = None, alinear_debajo: bool = True) -> dict | None:
    """
    Empareja un item (precio o atributo) con el producto reconocido mas
    cercano verticalmente arriba, dentro de una tolerancia horizontal de
    400px. Antes se llamaba "_asociar_producto" y solo se usaba para
    precios -- generalizado (22-ago-2026) para reutilizarse tambien con
    atributos.

    admitir_debajo (solo precios): tambien compiten los productos cuyo borde superior
    esta a la misma altura o debajo del precio, hasta alto_precio + MARGEN_DEBAJO_PRECIO.
    Gana la menor distancia vertical entre bordes superiores; en empate, el de arriba.
    Excepcion (ver ALINEACION_DEBAJO_PX): si hay productos alineados a la izquierda con el
    precio que empiezan debajo de su centro, gana el mas alto de ellos, salvo que sea la 2a
    linea de otro nombre (_continua_otro_bloque) o el nombre de la casilla siguiente, con su
    propio precio debajo (_tiene_precio_propio; `precios` = todos los precios de la pagina).
    alinear_debajo=False desactiva esa excepcion (paginas que no son de diseno "nombre debajo",
    ver diseno_nombre_debajo).
    """
    if not productos:
        return None

    item_x = item.get("bbox", {}).get("x", 0)
    item_y = item.get("bbox", {}).get("y", 0)
    alto = item.get("bbox", {}).get("alto", 0)
    limite_debajo = alto + MARGEN_DEBAJO_PRECIO

    if admitir_debajo and alinear_debajo:
        alineados = [
            p for p in productos
            if abs(p.get("bbox", {}).get("x", 0) - item_x) <= ALINEACION_DEBAJO_PX
            and item_y + alto / 2 <= p.get("bbox", {}).get("y", 0) <= item_y + limite_debajo
        ]
        if alineados:
            primero = min(alineados, key=lambda p: p.get("bbox", {}).get("y", 0))
            if not (_continua_otro_bloque(primero, productos)
                    or _tiene_precio_propio(primero, item, precios or [])):
                return primero

    mejor, menor_dist, mejor_es_debajo = None, float("inf"), False

    for prod in productos:
        prod_bbox = prod.get("bbox", {})
        prod_x    = prod_bbox.get("x", 0)
        prod_y    = prod_bbox.get("y", 0)

        if abs(prod_x - item_x) > 400:
            continue

        diff_y = item_y - prod_y
        if not admitir_debajo:
            if 0 < diff_y < menor_dist:
                menor_dist, mejor = diff_y, prod
            continue

        if diff_y <= 0 and -diff_y > limite_debajo:
            continue
        es_debajo = diff_y <= 0
        dist = abs(diff_y)
        if dist < menor_dist or (dist == menor_dist and mejor_es_debajo and not es_debajo):
            menor_dist, mejor, mejor_es_debajo = dist, prod, es_debajo

    return mejor


# -- Unidad de presentacion como ultima linea del nombre ------------------------------
# Dev 12-oct-2026 (base 20261012_231957_6d0670b; BI: 1,267 registros del dashboard con una
# unidad como nombre, casa_ley 826): el OCR parte la descripcion de la casilla en un bloque por
# linea y la ultima suele ser la presentacion ("Elote" / "Dorado" / "Del Monte" / "Carton";
# "Grano DE" / "DORADO" / "JACQUES 410" / "GRAMOS"). Por cercania gana esa ultima linea, la mas
# proxima al precio, y el dashboard muestra "Carton". Quitarla (descarte/atributo) solo pasa el
# precio a la linea anterior ("Envoltura", "JACQUES 410"), otro fragmento. En su lugar, el nombre
# del registro es la pila de lineas producto contiguas encima de la unidad (misma regla de
# contiguidad que _continua_otro_bloque) mas la unidad: "en Barra Urio Envoltura carton".
# Solo bloques que son SOLO la unidad (con cantidad opcional: "25 Piezas", "00 GRAMOS");
# "Paquete escolar", "Producto Bimbo", "Canon" no entran. Variantes OCR de Carton vistas en
# produccion: Cartón, Carron, Crton, Garton, Canton, Caron, Canón. Sin linea contigua encima
# (p. ej. el "1 Pieza" del cintillo GRATIS) el registro no cambia.
# La pila se corta en una linea que tambien queda justo encima de un bloque de OTRA columna: la
# banda de seccion de casa_ley ("GUIDADODELAROPALIMPIEZADELHOGAR", y encima "mayoreo" y el titulo
# "VeRANOde AHoRROS") va pegada sobre los encabezados de dos casillas ("Detergente" y "Jabon").
# Un corte por ancho (linea > 3x la pila) cortaba nombres legitimos centrados sobre la unidad
# ("Pan dulce Tia Rosa Cuernitos rebanados," / "piezas", "Recogedor con baston" / "pieza").
PATRON_UNIDAD_SUELTA = re.compile(
    r"^[\W_]*(?:\d{1,3}\s*)?(?:"
    r"(?:[cg]a?r{1,2}t?|[cg]ant)[oóò]n|[cg]a[nñ][óò]n|"
    r"p[iíl1]ez[ao]s?|pzas?|"
    r"paq(?:uete)?s?|"
    r"gr[aá]mos?|productos?|rol{1,2}[oa]s?|"
    r"variedad(?:es)?(?:\s+d[eaf])?"
    r")[\W_]*$",
    re.IGNORECASE,
)
MAX_LINEAS_DESCRIPCION = 6
# Guarda de columna (QA 13-oct-2026): la union solo se aplica si la unidad esta en la columna del
# precio, es decir, su bbox traslapa en x con el del precio ampliado MARGEN_COLUMNA_UNIDAD_PX por
# cada lado. Sin guarda, en 4 paginas revisadas fuera de dev/holdout solo 9/36 nombres unidos eran
# de su propia casilla: el precio ya tomaba la unidad de la columna vecina (|dx| 200-300 px) y la
# union convertia "Paquete" en "Suavelastic Paquete" para 9 precios ajenos (Huggies incluido), un
# error creible en vez de basura visible. Margen fijo, no proporcional al ancho del precio: el OCR
# parte el precio ("$39" + "79", 26 px de ancho) y un margen proporcional se encoge justo ahi.
# 50 px: casa_ley 422328 p1 "Jabon ... Lirio ... Carton" deja 22 px entre el precio y la burbuja
# (con 0 px se pierde); la casilla vecina queda a 200+ px. QA: 30 y 50 px dan lo mismo en dev
# (+7/-0); en produccion, con 50 px se aplica a 313 de 729 uniones y ~9/10 son de su casilla.
MARGEN_COLUMNA_UNIDAD_PX = 50


def es_unidad_suelta(texto: str) -> bool:
    return bool(PATRON_UNIDAD_SUELTA.match(texto or ""))


def _linea_encima(otro: dict, prod: dict) -> bool:
    """True si `otro` es la linea inmediatamente superior de `prod` (criterio de _continua_otro_bloque)."""
    b, o = prod.get("bbox", {}), otro.get("bbox", {})
    x0, x1, y, alto = b.get("x", 0), b.get("x", 0) + b.get("ancho", 0), b.get("y", 0), b.get("alto", 0)
    separacion = y - (o.get("y", 0) + o.get("alto", 0))
    traslape_x = min(x1, o.get("x", 0) + o.get("ancho", 0)) - max(x0, o.get("x", 0))
    return o.get("y", 0) < y and -alto / 2 <= separacion <= alto and traslape_x > 0


def unidad_en_columna_del_precio(prod: dict, precio: dict, margen: float = MARGEN_COLUMNA_UNIDAD_PX) -> bool:
    """True si el bbox de `prod` traslapa en x con el de `precio` ampliado `margen` px por lado."""
    b, p = prod.get("bbox", {}), precio.get("bbox", {})
    x0, x1 = b.get("x", 0), b.get("x", 0) + b.get("ancho", 0)
    px0, px1 = p.get("x", 0) - margen, p.get("x", 0) + p.get("ancho", 0) + margen
    return min(x1, px1) - max(x0, px0) > 0


def _es_banda(otro: dict, lineas: list, productos: list) -> bool:
    """True si `otro` tambien es la linea de encima de un bloque fuera de la columna de la pila
    (sin traslape en x con ella): cubre mas de una casilla, asi que no es parte de esta descripcion."""
    x0 = min(l.get("bbox", {}).get("x", 0) for l in lineas)
    x1 = max(l.get("bbox", {}).get("x", 0) + l.get("bbox", {}).get("ancho", 0) for l in lineas)
    for q in productos:
        if q is otro or any(q is l for l in lineas):
            continue
        b = q.get("bbox", {})
        fuera = b.get("x", 0) >= x1 or b.get("x", 0) + b.get("ancho", 0) <= x0
        if fuera and _linea_encima(otro, q):
            return True
    return False


def nombre_con_unidad(prod: dict, productos: list, normalizador: Normalizador) -> dict:
    """Si `prod` es una unidad suelta con lineas contiguas encima, devuelve una copia cuyo nombre es
    esa pila + la unidad (bbox = union); si no, `prod` tal cual. _idx/_resultado no cambian: la fila
    PRODUCTO enlazada sigue siendo la de la unidad, solo cambia el nombre que muestra el precio."""
    if not es_unidad_suelta(prod.get("texto", "")):
        return prod
    lineas, actual = [prod], prod
    while len(lineas) <= MAX_LINEAS_DESCRIPCION:
        encima = [o for o in productos if all(o is not l for l in lineas) and _linea_encima(o, actual)]
        if not encima:
            break
        siguiente = max(encima, key=lambda o: o.get("bbox", {}).get("y", 0) + o.get("bbox", {}).get("alto", 0))
        if _es_banda(siguiente, lineas, productos):
            break
        actual = siguiente
        lineas.append(actual)
    if len(lineas) == 1:
        return prod
    lineas.reverse()
    texto = " ".join(l.get("texto", "").strip() for l in lineas)
    resultado = normalizador.normalizar(texto)
    bbs = [l.get("bbox", {}) for l in lineas]
    x0, y0 = min(b.get("x", 0) for b in bbs), min(b.get("y", 0) for b in bbs)
    x1 = max(b.get("x", 0) + b.get("ancho", 0) for b in bbs)
    y1 = max(b.get("y", 0) + b.get("alto", 0) for b in bbs)
    return {
        **prod,
        "texto": texto,
        "bbox": {"x": x0, "y": y0, "ancho": x1 - x0, "alto": y1 - y0},
        "_nombre_norm": (resultado.nombre_canonico or texto) if not resultado.descartado else texto,
        "categoria": resultado.categoria or prod.get("categoria", ""),
    }


# -- Filtro de legibilidad del nombre -----------------------------------------------
# Desde ecbaa5d, si el canonico no cubre el texto, el dashboard muestra el texto del folleto
# (metodo "heuristico"). Con OCR ilegible eso llega como "Cansbca", "Chuiea", "BRcRE", "Sskrvih".
# Senal medida en dev (11-oct-2026, bloques heuristicos que llegaban al dashboard): la confianza
# OCR del bloque. Con < 0.30 caian 142 bloques de nombre sucio, 19 limpios que ya daban registro
# erroneo y 2 que daban registro correcto ("fACAPUNTAS" 0.20 se pierde); las senales de texto
# (consonantes seguidas, mayusculas a media palabra, simbolos, sin vocales) atrapaban casi tantos
# legitimos como basura ("Hass", "Kit", "candstilla", "Salchkchas"), asi que no se usan.
# No se filtra si el normalizador dio canonico (exacto/fuzzy) ni si el texto cae en una categoria
# del catalogo ("8- Shampoo Savile 7C0 ml" 0.23, "Fabuloso)" 0.35, "DuraZno" 0.44 son correctos).
# Las marcas fuera del catalogo (Chamoy, Morena, Hass, Sabritas, Minecraft...) llegan con
# confianza alta y no se tocan.
CONFIANZA_MINIMA_HEURISTICO = 0.30


def _ilegible(prod: dict, resultado) -> bool:
    """True si el nombre a mostrar seria texto OCR crudo de baja confianza."""
    if resultado.metodo != "heuristico" or resultado.categoria:
        return False
    confianza = prod.get("confianza")
    return confianza is not None and confianza < CONFIANZA_MINIMA_HEURISTICO


def productos_aceptados(productos: list[dict], normalizador: Normalizador,
                        incluir_ilegibles: bool = False) -> list[dict]:
    """
    Productos que el normalizador no descarta, en su orden original, enriquecidos con:
      _idx          -> posicion entre los legibles (load la usa para ligar el id de la fila insertada);
                       None en los ilegibles, que no se insertan
      _ilegible     -> ver _ilegible(); solo aparecen con incluir_ilegibles=True
      _resultado    -> ResultadoNorm completo
      _nombre_norm  -> nombre canonico o heuristico
      categoria     -> sobreescrita con la categoria del normalizador

    Los legibles son los unicos que pueden dar nombre a un precio/atributo: antes CUALQUIER
    bloque PRODUCTO (incluyendo ruido: "Exclusivo en", nombres de tienda, fragmentos OCR)
    era candidato.
    """
    aceptados = []
    n_legibles = 0
    for prod in productos:
        resultado = normalizador.normalizar(prod.get("texto", ""))
        if resultado.descartado:
            continue
        ilegible = _ilegible(prod, resultado)
        if ilegible and not incluir_ilegibles:
            continue
        aceptados.append({
            **prod,
            "_idx": None if ilegible else n_legibles,
            "_ilegible": ilegible,
            "_resultado": resultado,
            "_nombre_norm": resultado.nombre_canonico or prod.get("texto", ""),
            "categoria": resultado.categoria or prod.get("categoria", ""),
        })
        n_legibles += not ilegible
    return aceptados


def construir_registros_pagina(pag_data: dict, regiones_confiables: list[dict] | None,
                               normalizador: Normalizador) -> dict:
    """
    Registros de una pagina tal como load los insertaria, sin tocar la BD:
      productos -> productos_aceptados()
      precios   -> [{"precio", "producto" (de `productos` o None), "valor_anterior"}], orden del NLP
      atributos -> [{"atributo", "producto"}]
    Precio: primero ROI (solo tiendas de TIENDAS_ROI_HIBRIDO, si hay regiones), si no cercania.
    Atributos: solo cercania (ROI no validado para atributos todavia).
    Bloques ilegibles (_ilegible): ROI los sigue viendo, porque el texto fisicamente esta en la casilla
    y cuenta para la dispersion de candidatos (quitarlos cambiaba ROI/cercania en Walmart y perdia
    "Figura Captain Tsubasa"); si ROI elige uno, el precio pasa a cercania entre los legibles.
    """
    candidatos = productos_aceptados(pag_data.get("productos", []), normalizador, incluir_ilegibles=True)
    productos = [p for p in candidatos if not p["_ilegible"]]
    precios = pag_data.get("precios", [])
    anteriores = emparejar_precios_anteriores(precios, pag_data.get("precios_anteriores", []))

    nombre_debajo = diseno_nombre_debajo(precios, productos)

    registros_precio = []
    for precio, valor_anterior in zip(precios, anteriores):
        producto = None
        if regiones_confiables:
            producto = asociar_producto_por_region(precio, candidatos, regiones_confiables)
            if producto is not None and producto["_ilegible"]:
                producto = None
        if producto is None:
            producto = asociar_por_cercania(precio, productos, admitir_debajo=True, precios=precios,
                                            alinear_debajo=nombre_debajo)
        if producto is not None and unidad_en_columna_del_precio(producto, precio):
            producto = nombre_con_unidad(producto, productos, normalizador)
        registros_precio.append({"precio": precio, "producto": producto, "valor_anterior": valor_anterior})

    registros_atributo = [
        {"atributo": atributo, "producto": asociar_por_cercania(atributo, productos)}
        for atributo in pag_data.get("atributos", [])
    ]
    return {"productos": productos, "precios": registros_precio, "atributos": registros_atributo}


def _obtener_preprocesador_roi():
    global _preprocesador_roi
    if _preprocesador_roi is None:
        _preprocesador_roi = obtener_preprocesador("color_normal")
    return _preprocesador_roi


# SQLSTATE -> categoria_error_enum (schema.sql). Se usa el codigo y no el texto
# del mensaje porque el mensaje depende del idioma del servidor.
_CATEGORIA_POR_SQLSTATE = {
    "22001": "tamano_excesivo",
    "22003": "valor_fuera_de_rango",
    "22P02": "formato_invalido",
    "22007": "formato_invalido",
    "22008": "formato_invalido",
}


def categorizar_error(e: Exception) -> tuple[str, str | None]:
    sqlstate = getattr(e, "sqlstate", None)
    if sqlstate:
        if sqlstate in _CATEGORIA_POR_SQLSTATE:
            return _CATEGORIA_POR_SQLSTATE[sqlstate], sqlstate
        if sqlstate.startswith("23"):
            return "violacion_integridad", sqlstate
        return "otro", sqlstate
    if isinstance(e, json.JSONDecodeError):
        return "json_corrupto", None
    if isinstance(e, FileNotFoundError):
        return "archivo_faltante", None
    return "otro", None


def _detalle_error(e: Exception) -> str:
    diag = getattr(e, "diag", None)
    partes = [p for p in (getattr(diag, "message_detail", None), getattr(diag, "context", None)) if p]
    return " | ".join(partes) if partes else type(e).__name__

# Clase principal para cargar datos en la base de datos
class Loader:

    def __init__(self):
        self.conn = get_connection()
        self._normalizador = Normalizador()
        self._corrida_at = None
        logger.info("[Load] Loader inicializado")

    @classmethod
    def desde_conexion(cls, conn) -> "Loader":
        instance = cls.__new__(cls)
        instance.conn = conn
        instance._normalizador = Normalizador()
        instance._corrida_at = None
        return instance

    def cerrar(self):
        if self.conn and not self.conn.closed:
            self.conn.close()
            logger.info("[Load] Conexion cerrada")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()

    # ----------------- API publica -----------------
    def cargar_folleto(self, ruta_nlp: Path, metadata: dict | None = None,
                       reemplazar: bool = False) -> dict:
        ruta_nlp = Path(ruta_nlp)
        corrida_at = self._corrida_at or datetime.now()
        # Identidad desde la ruta (processed/<fuente>/<tienda>/<folleto>/) por si el JSON no se puede leer
        partes = ruta_nlp.parts
        fuente, slug_raw, folleto_id = (partes[-4], partes[-3], partes[-2]) if len(partes) >= 4 else ("", "", "")
        errores: list[dict] = []

        def registrar(e: Exception, pagina: str | None = None):
            categoria, sqlstate = categorizar_error(e)
            errores.append({
                "pagina": pagina, "categoria": categoria, "sqlstate": sqlstate,
                "mensaje": str(e).strip(), "detalle": _detalle_error(e),
            })

        resumen = {
            "fuente": fuente, "tienda": slug_raw, "folleto_id": folleto_id,
            "extracciones_insertadas": 0, "precios_sin_producto": 0,
            "eventos_insertados": 0, "paginas_procesadas": 0, "errores": 0,
            "errores_por_categoria": {},
        }

        try:
            if not ruta_nlp.exists():
                raise FileNotFoundError(f"[Load] No existe: {ruta_nlp}")

            with open(ruta_nlp, encoding="utf-8") as f:
                nlp = json.load(f)

            fuente     = nlp.get("fuente", "") or fuente
            slug_raw   = nlp.get("tienda", "") or slug_raw
            folleto_id = nlp.get("folleto_id", "") or folleto_id
            meta       = dict(metadata or self._leer_metadata(fuente, folleto_id))
            ocr        = self._leer_ocr(ruta_nlp)
            ocr_por_pagina = {p.get("pagina"): p for p in ocr.get("paginas", [])}
            # El registro del scraper no trae estos campos; salen de los JSON del pipeline
            meta["perfil_ocr"]    = meta.get("perfil_ocr") or ocr.get("perfil_imagen")
            meta["motor_ocr"]     = meta.get("motor_ocr") or ocr.get("motor_ocr") or "easyocr"
            meta["total_paginas"] = nlp.get("total_paginas") or len(nlp.get("paginas", []))
            slug, nombre_tienda = self._corregir_tienda(fuente, slug_raw)
            resumen.update(fuente=fuente, tienda=slug, folleto_id=folleto_id)

            logger.info(f"[Load] -- {fuente}/{slug}/{folleto_id} --")

            with get_cursor(self.conn) as cur:
                tienda_id     = self._upsert_tienda(cur, slug, nombre_tienda, slug_raw)
                folleto_id_bd = self._upsert_folleto(cur, tienda_id, folleto_id, fuente, meta, reemplazar)

                # Sin esto, recargar un folleto ya cargado duplica sus extracciones
                # (extracciones no tiene llave natural). Va en la misma transaccion:
                # si la carga falla, el rollback deshace tambien el borrado.
                if reemplazar:
                    cur.execute("DELETE FROM eventos_promo WHERE folleto_id = %s", (folleto_id_bd,))
                    cur.execute("DELETE FROM paginas WHERE folleto_id = %s", (folleto_id_bd,))  # cascada a extracciones

                for pag_data in nlp.get("paginas", []):
                    nombre_pag = pag_data.get("pagina", "?")
                    try:
                        regiones_confiables = self._detectar_regiones_pagina(fuente, slug_raw, folleto_id, pag_data)
                        # SAVEPOINT por pagina: un error SQL descarta solo esta pagina. Sin el,
                        # la transaccion quedaba abortada y el commit final revertia el folleto entero.
                        with self.conn.transaction():
                            r = self._procesar_pagina(cur, tienda_id, folleto_id_bd, pag_data, regiones_confiables,
                                                      ocr_por_pagina.get(nombre_pag))
                        resumen["extracciones_insertadas"] += r["extracciones"]
                        resumen["precios_sin_producto"]    += r["sin_producto"]
                        resumen["eventos_insertados"]      += r["eventos"]
                        resumen["paginas_procesadas"]      += 1
                    except Exception as e:
                        logger.error(f"[Load] Error en pagina {nombre_pag}: {e}")
                        resumen["errores"] += 1
                        registrar(e, nombre_pag)

        except Exception as e:
            logger.error(f"[Load] Error cargando {folleto_id}: {e}")
            registrar(e)
            self._guardar_errores(errores, corrida_at, fuente, slug_raw, folleto_id, ruta_nlp, folleto_ok=False)
            raise

        self._guardar_errores(errores, corrida_at, fuente, slug_raw, folleto_id, ruta_nlp, folleto_ok=True)
        for err in errores:
            resumen["errores_por_categoria"][err["categoria"]] = resumen["errores_por_categoria"].get(err["categoria"], 0) + 1

        logger.info(
            f"[Load] OK {folleto_id} -> "
            f"{resumen['extracciones_insertadas']} extracciones | "
            f"{resumen['precios_sin_producto']} sin producto | "
            f"{resumen['eventos_insertados']} eventos"
            + (f" | {resumen['errores']} paginas con error" if resumen["errores"] else "")
        )
        return resumen

    def _guardar_errores(self, errores: list[dict], corrida_at: datetime, fuente: str, tienda_slug: str,
                         folleto_id: str, ruta_nlp: Path, folleto_ok: bool) -> None:
        """
        Corre DESPUES de que la transaccion del folleto termino (commit o rollback), asi el
        rollback de un folleto fallido no se lleva tambien su registro de error.
        Si el folleto cargo, los errores abiertos de cargas anteriores quedan resueltos:
        la carga nueva reemplaza a la anterior y los que sigan ocurriendo se registran de nuevo.
        """
        try:
            with get_cursor(self.conn) as cur:
                if folleto_ok:
                    cur.execute("""
                        UPDATE errores_carga SET resuelto = TRUE, resuelto_at = NOW()
                        WHERE fuente = %s AND folleto_id_fuente = %s AND NOT resuelto
                    """, (fuente, folleto_id))
                for err in errores:
                    cur.execute("""
                        INSERT INTO errores_carga (
                            corrida_at, fuente, tienda_slug, folleto_id_fuente, pagina,
                            categoria, sqlstate, mensaje, detalle, ruta_archivo
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        corrida_at, fuente, tienda_slug, folleto_id, err["pagina"],
                        err["categoria"], err["sqlstate"], err["mensaje"], err["detalle"], str(ruta_nlp),
                    ))
        except Exception as e:
            # Registrar el error nunca debe tumbar la carga
            logger.error(f"[Load] No se pudo registrar errores de {folleto_id} en errores_carga: {e}")

    # ----------------- Carga batch -----------------
    def cargar_batch(self, data_processed: Path = DATA_PROCESSED, forzar: bool = False) -> dict:
        data_processed = Path(data_processed)
        rutas = rutas_nlp(data_processed)

        if not rutas:
            logger.warning(f"[Load] Sin nlp_resultado.json en {data_processed}")
            return {}

        logger.info(f"[Load] {len(rutas)} folletos encontrados")
        totales = {"procesados": 0, "omitidos": 0, "errores": 0, "paginas_con_error": 0,
                   "extracciones_total": 0, "eventos_total": 0, "errores_por_categoria": {}}

        def sumar_categoria(categoria: str, n: int = 1):
            totales["errores_por_categoria"][categoria] = totales["errores_por_categoria"].get(categoria, 0) + n

        self._corrida_at = datetime.now()
        totales["corrida_at"] = self._corrida_at
        try:
            for i, ruta in enumerate(rutas, 1):
                ruta_rel = ruta.parent.relative_to(data_processed)

                if not forzar and self._ya_cargado(ruta):
                    logger.info(f"[Load] [{i}/{len(rutas)}] Ya cargado: {ruta_rel}")
                    totales["omitidos"] += 1
                    continue

                logger.info(f"[Load] [{i}/{len(rutas)}] {ruta_rel}")
                try:
                    r = self.cargar_folleto(ruta, reemplazar=forzar)
                    totales["procesados"]         += 1
                    totales["paginas_con_error"]  += r["errores"]
                    totales["extracciones_total"] += r["extracciones_insertadas"]
                    totales["eventos_total"]      += r["eventos_insertados"]
                    for categoria, n in r["errores_por_categoria"].items():
                        sumar_categoria(categoria, n)
                except Exception as e:
                    logger.error(f"[Load] Error en {ruta_rel}: {e}")
                    totales["errores"] += 1
                    sumar_categoria(categorizar_error(e)[0])
        finally:
            self._corrida_at = None

        logger.info(
            f"[Load] Batch completo: "
            f"procesados={totales['procesados']} "
            f"omitidos={totales['omitidos']} "
            f"errores={totales['errores']} "
            f"paginas_con_error={totales['paginas_con_error']} | "
            f"extracciones={totales['extracciones_total']} "
            f"eventos={totales['eventos_total']}"
        )
        return totales

    # --------------- Procesamiento de pagina ---------------
    # Corre deteccion ROI solo para las tiendas grid-friendly validadas
    def _detectar_regiones_pagina(self, fuente: str, slug_raw: str, folleto_id: str, pag_data: dict) -> list[dict] | None:
        nombre_pag = pag_data.get("pagina", "")
        try:
            candidatas = candidatas_roi_pagina(fuente, slug_raw, folleto_id, nombre_pag)
            if candidatas is None:
                return None
            return regiones_con_precio(candidatas, pag_data.get("precios", []))
        except Exception as e:
            logger.warning(f"[Load] ROI fallo en {slug_raw}/{folleto_id}/{nombre_pag}: {e} -- fallback a distancia")
            return None

    def _procesar_pagina(self, cur, tienda_id: int, folleto_id: int, pag_data: dict,
                         regiones_confiables: list[dict] | None = None,
                         ocr_pagina: dict | None = None) -> dict:
        nombre_pag = pag_data.get("pagina", "")
        num_pagina = self._extraer_numero_pagina(nombre_pag)
        pagina_id  = self._upsert_pagina(cur, folleto_id, num_pagina, nombre_pag)

        productos     = pag_data.get("productos", [])
        precios       = pag_data.get("precios", [])
        promos        = pag_data.get("promos", [])
        eventos_promo = pag_data.get("eventos_promo", [])
        atributos     = pag_data.get("atributos", [])

        contadores = {"extracciones": 0, "sin_producto": 0, "eventos": 0}

        registros = construir_registros_pagina(pag_data, regiones_confiables, self._normalizador)
        ids_producto = self._insertar_productos(cur, pagina_id, folleto_id, tienda_id, registros["productos"])
        contadores["extracciones"] += len(ids_producto)

        # Precios
        for registro in registros["precios"]:
            precio, producto_match = registro["precio"], registro["producto"]
            precio_ant_val = registro["valor_anterior"]
            prod_id, prod_canonico_id = ids_producto[producto_match["_idx"]] if producto_match else (None, None)
            bbox           = precio.get("bbox", {})

            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, categoria_nlp,
                    valor, valor_anterior, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto,
                    producto_extraccion_id, producto_canonico_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "PRECIO",
                precio.get("texto", ""),
                producto_match.get("_nombre_norm") if producto_match else None,
                producto_match.get("categoria") if producto_match else None,
                precio.get("valor"), precio_ant_val, precio.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
                prod_id, prod_canonico_id,
            ))
            contadores["extracciones"] += 1
            if not producto_match:
                contadores["sin_producto"] += 1

        # Atributos: mismo criterio de cercania que precios (sin ROI, no
        # validado para atributos todavia). Antes no se persistian en
        # absoluto pese a que el enum tipo_extraccion_enum ya los soportaba.
        for registro in registros["atributos"]:
            atributo, producto_match = registro["atributo"], registro["producto"]
            bbox = atributo.get("bbox", {})
            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, categoria_nlp, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto, producto_extraccion_id
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "ATRIBUTO", atributo.get("texto", ""), atributo.get("texto", ""),
                atributo.get("categoria") or None, atributo.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
                ids_producto[producto_match["_idx"]][0] if producto_match else None,
            ))
            contadores["extracciones"] += 1

        # Promos
        for promo in promos:
            bbox = promo.get("bbox", {})
            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "PROMO", promo.get("texto", ""), promo.get("texto", ""),
                promo.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
            ))
            contadores["extracciones"] += 1

        # Eventos promo
        for evento in eventos_promo:
            texto_evento = evento.get("texto", "")
            nombre_norm  = self._normalizar_nombre_evento(texto_evento)
            bbox         = evento.get("bbox", {})

            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, confianza_ocr,
                    bbox_x, bbox_y, bbox_ancho, bbox_alto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                pagina_id, folleto_id, tienda_id,
                "EVENTO_PROMO", texto_evento, nombre_norm,
                evento.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
            ))
            contadores["extracciones"] += 1

            if self._upsert_evento_promo(cur, folleto_id, tienda_id, nombre_norm, texto_evento):
                contadores["eventos"] += 1

        # Metricas OCR de la pagina (ocr_resultado.json). Sin OCR quedan NULL, no 0,
        # para distinguir "no hay dato" de "la pagina no tenia texto".
        total_bloques = confianza_ocr = tasa_util = None
        if ocr_pagina is not None:
            total_bloques = len(ocr_pagina.get("bloques", []))
            confianza_ocr = ocr_pagina.get("confianza_prom")
            # = schema.sql: entidades utiles / total bloques OCR. Utiles = todo lo que el NLP
            # no descarto (mismas clases que la tasa_util del resumen de probar_nlp.py)
            utiles = sum(len(pag_data.get(k, [])) for k in (
                "productos", "precios", "precios_anteriores", "ahorros",
                "promos", "eventos_promo", "atributos",
            ))
            tasa_util = round(utiles / total_bloques, 3) if total_bloques else None

        # Actualizar metricas de pagina
        cur.execute("""
            UPDATE paginas SET
                total_productos = %s, total_precios = %s,
                total_promos = %s, total_atributos = %s,
                total_bloques_ocr = %s, confianza_ocr_prom = %s, tasa_util = %s,
                procesado_at = %s
            WHERE id = %s
        """, (
            len(productos), len(precios),
            len(promos) + len(eventos_promo), len(atributos),
            total_bloques, confianza_ocr, tasa_util,
            datetime.utcnow(), pagina_id,
        ))

        return contadores

    # ----------------- Productos y normalización ---------------------------------------------

    def _insertar_productos(self, cur, pagina_id: int, folleto_id: int, tienda_id: int,
                            aceptados: list[dict]) -> list[tuple[int, Optional[int]]]:
        """
        Inserta los productos que ya acepto el normalizador (productos_aceptados()) como
        fila propia tipo=PRODUCTO, upserteando su identidad canonica en productos_canonicos.
        Devuelve (id en extracciones, id en productos_canonicos o None) en el orden de
        `aceptados`, es decir, indexado por su `_idx`.
        """
        ids = []
        for prod in aceptados:
            resultado = prod["_resultado"]
            producto_canonico_id = None
            if resultado.nombre_canonico:
                producto_canonico_id = self._upsert_producto_canonico(cur, resultado)

            bbox = prod.get("bbox", {})
            cur.execute("""
                INSERT INTO extracciones (
                    pagina_id, folleto_id, tienda_id,
                    tipo, texto_raw, texto_norm, categoria_nlp,
                    confianza_ocr, bbox_x, bbox_y, bbox_ancho, bbox_alto,
                    producto_canonico_id, confianza_norm, metodo_norm
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                pagina_id, folleto_id, tienda_id,
                "PRODUCTO", prod.get("texto", ""),
                resultado.nombre_canonico or None,
                resultado.categoria or prod.get("categoria") or None,
                prod.get("confianza"),
                bbox.get("x"), bbox.get("y"), bbox.get("ancho"), bbox.get("alto"),
                producto_canonico_id, resultado.confianza_norm, resultado.metodo,
            ))
            ids.append((cur.fetchone()["id"], producto_canonico_id))
        return ids

    def _upsert_producto_canonico(self, cur, resultado) -> int:
        # Alias nuevo: solo cuando el match fue por fuzzy (no exacto, no
        # heuristico -- ahi el texto YA ES el nombre_canonico, no hace falta
        # guardarlo aparte). Se persiste la forma normalizada que disparo el
        # match para que la proxima vez ese mismo texto OCR matchee "exacto".
        alias_nuevo = (
            resultado.texto_norm_base
            if resultado.metodo in ("fuzzy", "fuzzy_bajo") and resultado.texto_norm_base
            else None
        )
        cur.execute("""
            INSERT INTO productos_canonicos (nombre_canonico, categoria, marca, aliases)
            VALUES (%s, %s, %s, CASE WHEN %s::text IS NULL THEN '{}' ELSE ARRAY[%s] END)
            ON CONFLICT (nombre_canonico) DO UPDATE SET
                categoria = COALESCE(productos_canonicos.categoria, EXCLUDED.categoria),
                marca     = COALESCE(productos_canonicos.marca, EXCLUDED.marca),
                aliases   = CASE
                    WHEN %s::text IS NULL THEN productos_canonicos.aliases
                    WHEN %s = ANY(productos_canonicos.aliases) THEN productos_canonicos.aliases
                    ELSE array_append(productos_canonicos.aliases, %s)
                END
            RETURNING id
        """, (
            resultado.nombre_canonico, resultado.categoria or None, resultado.marca,
            alias_nuevo, alias_nuevo,
            alias_nuevo, alias_nuevo, alias_nuevo,
        ))
        return cur.fetchone()["id"]

    # ----------------- Upserts SQL -----------------

    def _upsert_tienda(self, cur, slug: str, nombre: str, fuente_slug: str) -> int:
        cur.execute("""
            INSERT INTO tiendas (nombre, slug, fuente_slug, activa)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (slug) DO NOTHING
            RETURNING id
        """, (nombre, slug, fuente_slug))

        row = cur.fetchone()
        if row:
            logger.info(f"[Load] Nueva tienda: {nombre} (slug={slug})")
            return row["id"]

        cur.execute("SELECT id FROM tiendas WHERE slug = %s", (slug,))
        return cur.fetchone()["id"]

    def _upsert_folleto(self, cur, tienda_id: int, folleto_id_fuente: str,
                        fuente: str, meta: dict, reemplazar: bool = False) -> int:
        # Al reemplazar se actualiza la tienda y la metadata que venga; si un campo viene
        # vacio se conserva el que ya estaba (el registro del scraper no siempre lo trae).
        conflicto = """
            DO UPDATE SET
                tienda_id    = EXCLUDED.tienda_id,
                titulo       = COALESCE(EXCLUDED.titulo,       folletos.titulo),
                fecha_inicio = COALESCE(EXCLUDED.fecha_inicio, folletos.fecha_inicio),
                fecha_fin    = COALESCE(EXCLUDED.fecha_fin,    folletos.fecha_fin),
                url_origen   = COALESCE(EXCLUDED.url_origen,   folletos.url_origen),
                perfil_ocr   = COALESCE(EXCLUDED.perfil_ocr,   folletos.perfil_ocr),
                motor_ocr    = COALESCE(EXCLUDED.motor_ocr,    folletos.motor_ocr),
                total_paginas = EXCLUDED.total_paginas,
                scrapeado_at = COALESCE(EXCLUDED.scrapeado_at, folletos.scrapeado_at),
                estado       = EXCLUDED.estado
        """ if reemplazar else "DO NOTHING"
        cur.execute(f"""
            INSERT INTO folletos (
                tienda_id, folleto_id_fuente, fuente,
                titulo, fecha_inicio, fecha_fin, url_origen,
                perfil_ocr, motor_ocr, total_paginas, scrapeado_at, estado
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (fuente, folleto_id_fuente) {conflicto}
            RETURNING id
        """, (
            tienda_id, folleto_id_fuente, fuente,
            meta.get("titulo"),
            self._parsear_fecha(meta.get("fecha_inicio")),
            self._parsear_fecha(meta.get("fecha_fin")),
            meta.get("url_origen"),
            meta.get("perfil_ocr"),
            meta.get("motor_ocr", "easyocr"),
            meta.get("total_paginas", 0),
            self._parsear_datetime(meta.get("scrapeado_at")),
            "done",
        ))

        row = cur.fetchone()
        if row:
            logger.info(f"[Load] Nuevo folleto: {folleto_id_fuente}")
            return row["id"]

        cur.execute("""
            SELECT id FROM folletos WHERE fuente = %s AND folleto_id_fuente = %s
        """, (fuente, folleto_id_fuente))
        return cur.fetchone()["id"]

    def _upsert_pagina(self, cur, folleto_id: int, numero_pagina: int,
                       archivo_imagen: str) -> int:
        cur.execute("""
            INSERT INTO paginas (folleto_id, numero_pagina, archivo_imagen)
            VALUES (%s, %s, %s)
            ON CONFLICT (folleto_id, numero_pagina) DO NOTHING
            RETURNING id
        """, (folleto_id, numero_pagina, archivo_imagen))

        row = cur.fetchone()
        if row:
            return row["id"]

        cur.execute("""
            SELECT id FROM paginas WHERE folleto_id = %s AND numero_pagina = %s
        """, (folleto_id, numero_pagina))
        return cur.fetchone()["id"]

    def _upsert_evento_promo(self, cur, folleto_id: int, tienda_id: int,
                             nombre_evento: str, texto_raw: str) -> bool:
        cur.execute("""
            INSERT INTO eventos_promo (folleto_id, tienda_id, nombre_evento, texto_raw)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (folleto_id, nombre_evento) DO NOTHING
            RETURNING id
        """, (folleto_id, tienda_id, nombre_evento, texto_raw))
        return cur.fetchone() is not None

    # ----------------- Utilidades -----------------

    def _corregir_tienda(self, fuente: str, slug_raw: str) -> tuple[str, str]:
        if (fuente, slug_raw) in CORRECCION_TIENDAS:
            slug_correcto, nombre = CORRECCION_TIENDAS[(fuente, slug_raw)]
            logger.info(f"[Load] Correccion tienda: '{slug_raw}' -> '{slug_correcto}'")
            return slug_correcto, nombre
        return slug_raw, slug_raw.replace("_", " ").title()

    def _normalizar_nombre_evento(self, texto: str) -> str:
        texto = texto.lower().strip()
        texto = re.sub(r"\s*\d{4}$", "", texto)
        texto = re.sub(r"[^a-z\s]", "", texto)
        texto = re.sub(r"\s+", "_", texto.strip())
        return texto[:100]

    def _parsear_fecha(self, fecha_str: str | None) -> Optional[date]:
        if not fecha_str:
            return None
        try:
            return datetime.strptime(fecha_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    def _parsear_datetime(self, dt_str: str | None) -> Optional[datetime]:
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str)
        except (ValueError, TypeError):
            return None

    def _extraer_numero_pagina(self, nombre_archivo: str) -> int:
        match = re.search(r"(\d+)", nombre_archivo)
        return int(match.group(1)) if match else 0

    def _ya_cargado(self, ruta_nlp: Path) -> bool:
        try:
            with open(ruta_nlp, encoding="utf-8") as f:
                data = json.load(f)
            fuente     = data.get("fuente", "")
            folleto_id = data.get("folleto_id", "")
            if not fuente or not folleto_id:
                return False
            with get_cursor(self.conn) as cur:
                cur.execute("""
                    SELECT 1 FROM folletos
                    WHERE fuente = %s AND folleto_id_fuente = %s
                """, (fuente, folleto_id))
                return cur.fetchone() is not None
        except Exception:
            return False

    def _leer_ocr(self, ruta_nlp: Path) -> dict:
        # ocr_resultado.json vive junto a nlp_resultado.json. Si falta o esta roto el folleto
        # se carga igual, solo sin metricas OCR (quedan NULL en paginas).
        ruta_ocr = Path(ruta_nlp).with_name("ocr_resultado.json")
        try:
            with open(ruta_ocr, encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.warning(f"[Load] Sin metricas OCR para {ruta_ocr.parent}: {e}")
            return {}

    def _leer_metadata(self, fuente: str, folleto_id: str) -> dict:
        if not RUTA_REGISTRO_SCRAPER.exists():
            return {}
        try:
            with open(RUTA_REGISTRO_SCRAPER, encoding="utf-8") as f:
                registro = json.load(f)
        except Exception:
            return {}

        entrada = registro.get(f"{fuente}:{folleto_id}")
        if not entrada:
            return {}

        return {
            "titulo":       entrada.get("titulo"),
            "fecha_inicio": entrada.get("fecha_inicio"),
            "fecha_fin":    entrada.get("fecha_fin"),
            "scrapeado_at": entrada.get("procesado_at"),
            "url_origen":   entrada.get("url_folleto"),
        }