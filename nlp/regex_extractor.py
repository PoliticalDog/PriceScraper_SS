# Toma los bloques de texto del OCR y los clasifica en categorías:
#       PRECIO, PRECIO_ANTERIOR, AHORRO, PROMO, EVENTO_PROMO, PRODUCTO, ATRIBUTO, DESCARTE

import re
import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from .catalogo_productos import buscar_categoria

# configuración de logging
logger = logging.getLogger(__name__)


# --------------- Modelos de datos ---------------

# pieza de informacion extraida de la pagina
@dataclass
class EntidadExtraida:
    tipo:       str    # PRECIO | PRECIO_ANTERIOR | AHORRO | PROMO | EVENTO_PROMO | PRODUCTO | ATRIBUTO | DESCARTE
    texto_raw:  str
    texto_norm: str
    valor:      Optional[float] = None  # Valor numérico (precios, ahorros)
    confianza:  float = 0.0
    bbox:       dict = field(default_factory=dict)
    categoria:  str = ""                # Categoría del catálogo (PRODUCTO/ATRIBUTO)

# Agrupacion de informacion extraida de una pagina completa
@dataclass
class ResultadoPagina:
    imagen:           str
    productos:        list[EntidadExtraida] = field(default_factory=list)
    precios:          list[EntidadExtraida] = field(default_factory=list)
    precios_anteriores: list[EntidadExtraida] = field(default_factory=list)
    ahorros:          list[EntidadExtraida] = field(default_factory=list)
    promos:           list[EntidadExtraida] = field(default_factory=list)
    eventos_promo:    list[EntidadExtraida] = field(default_factory=list)
    atributos:        list[EntidadExtraida] = field(default_factory=list)
    descartes:        list[EntidadExtraida] = field(default_factory=list)

    def resumen(self) -> str:
        return (f"Página: {self.imagen} | "
                f"Prod:{len(self.productos)} Prec:{len(self.precios)} "
                f"PrecAnt:{len(self.precios_anteriores)} Ahorro:{len(self.ahorros)} "
                f"Promo:{len(self.promos)} Evento:{len(self.eventos_promo)} "
                f"Attr:{len(self.atributos)} Desc:{len(self.descartes)}")


# --------------- Extractor principal ---------------

class RegexExtractor:
    """
    Flujo de clasificación (orden de prioridad):
      1. Limpiar texto OCR
      2. ¿Es descarte?          → DESCARTE
      3. ¿Es precio anterior?   → PRECIO_ANTERIOR
      4. ¿Es ahorro?            → AHORRO
      5. ¿Es evento promo?      → EVENTO_PROMO
      6. ¿Es precio?            → PRECIO
      7. ¿Es promoción?         → PROMO
      8. ¿En catálogo?          → PRODUCTO o ATRIBUTO
      9. ¿Heurística producto?  → PRODUCTO
     10. Por defecto            → DESCARTE
    """

    # --------------- PRECIO ANTERIOR ---------------
    # "Antes: $699" / "Antos; $3495" / "precio anterior $1,200" / "'Antes:$2495"
    PATRON_PRECIO_ANTERIOR = re.compile(
        r"""
        (?:antes\s*[;:,.]?\s*|antos\s*[;:,.]?\s*|precio\s+anterior\s*:?\s*)
        \$?\s*
        (
            \d{4,6}
            |
            \d{1,3}(?:[,\.]\d{3})*
            (?:[,\.]\d{1,2})?
        )
        [a-zA-Z/_]*
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # --------------- AHORRO ---------------
    # "Ahorras $32.90" / "Ahorra $49.90" / "Ahorras 5755.00" (OCR $ → 5)
    PATRON_AHORRO = re.compile(
        r"""
        \bahorr[ao]s?\b\s*
        [\$5]?\s*       # $ o '5' (confusión OCR frecuente)
        (
            \d{1,3}(?:[,\.]\d{3})*
            (?:[,\.]\d{1,2})?
            |
            \d{2,6}
        )
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # --------------- PRECIO ---------------
    # v3: añade prefijos DESDE/A sólo/desde:/a solo: y sufijo C/U
    # Captura: $18.50 / $1,568 / $2,498 / $10,999 / $10.999 / $359c
    # También: DESDE $69.90 / A sólo $149.00 / $99.90 C/U
    PATRON_PRECIO = re.compile(
        r"""
        (?:desde\s*\.{0,3}\s*|a\s+s[oó]lo\s*:?\s*|desde\s*:\s*|a\s+solo\s*:?\s*)?
        (?:^\$|(?<!\w)\$)
        \s*
        (
            \d{4,6}
            |
            \d{1,3}(?:[,\.]\d{3})*
            (?:[,\.]\d{1,2})?
        )
        [a-zA-Z/_]*             # sufijos OCR: c, e, u, c/u etc.
        (?:\s*(?:c/u|c\.u\.))? # sufijo C/U explícito
        (?:\s*(?:MXN|pesos?))?
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # Precio con $ OCR corrupto (fresko): s/8/S + 4-6 dígitos (últimos 2 = centavos)
    # s9989 → $99.89 | 82990 → $29.90 | s15790 → $157.90
    PATRON_PRECIO_OCR_CORRUPTO = re.compile(
        r"""
        ^               # bloque completo
        [s8S]           # $ leído como s, 8 o S
        (\d{2,4})       # dígitos enteros
        (\d{2})         # siempre 2 dígitos = centavos
        [*.]?           # sufijo ocasional
        $
        """,
        re.VERBOSE
    )

    # ERROR #18 — "DE $5,490 A $X" (soriana rebajas)
    # El primer precio es el anterior, el segundo es el actual.
    # Se detecta ANTES del PATRON_PRECIO normal para no extraer solo el primer número.
    PATRON_DE_A = re.compile(
        r"""
        ^DE\s+          # literal "DE " al inicio
        \$?\s*
        ([\d,\.]+)      # precio anterior
        \s+A\b          # "A" como separador
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # --------------- PRECIO SIN SIMBOLO ("$" perdido o mal leido por el OCR) ---------------
    # Tipografia de "tag de oferta" (digito entero grande + centavos en superindice, sin "$"
    # ni punto decimal como caracteres separados) hace que EasyOCR pierda el "$" por completo
    # o lo lea como 5/6/8 (confundible con el glifo "$" en esa fuente). Confirmado empiricamente
    # en Casa Ley, S-Mart, Soriana Hiper/Mercado, Walmart, Bodega Aurrera, HEB y Chedraui (jul 2026).
    # Solo se activa si hay contexto de precio cerca del bloque (ver _hay_contexto_precio) --
    # nunca se aplica a un bloque aislado, para no confundir SKUs/cantidades/paginas con precios.

    # Regla A: caracter espurio (el "$" mal leido) + precio ENTERO sin centavos. Ej: "8249" -> $249
    # Remanente fijo a 3 digitos -- es lo unico validado empiricamente (299/266/249/169/229/599).
    # No se generaliza a 2 o 4 digitos por falta de casos confirmados.
    # "s/S" se agrega ademas de 5/6/8 porque ya es un sustituto de "$" conocido y documentado
    # (ver PATRON_PRECIO_OCR_CORRUPTO) -- confirmado en folleto de referencia: "s599" -> $599.
    # Sufijo opcional tolerado despues del digito espurio + 3 digitos: unidades/cortes
    # de OCR pegados directo al numero (ej. "5199c/u" -> $199 c/u, confirmado en
    # bodega_aurrera). No participa en el valor extraido, solo se tolera para no
    # romper el anclaje ^...$.
    PATRON_DIGITO_ESPURIO = re.compile(r"^[568sS](\d{3})(?:c/u|c\.u\.|[a-zA-Z]{1,4})?$")

    # Regla A2: digito espurio + numero que YA trae su propio punto decimal + sufijo
    # opcional de unidad (ej. "824.95k6" -> $24.95/kg, confirmado en HEB -- el sufijo
    # tolera digitos porque el OCR confunde "kg" con "k6"). Se separa de la Regla A
    # porque esta no sintetiza centavos -- el decimal ya viene explicito.
    PATRON_DIGITO_ESPURIO_DECIMAL = re.compile(r"^[568sS](\d{1,3}[.,]\d{2})[a-zA-Z0-9]{0,4}$")

    # Regla A-miles: digito espurio + remanente con coma de miles (ej. "58,999" ->
    # $8,999, "53,999" -> $3,999 -- verificado contra la imagen real: el "5" inicial
    # SI era el "$" corrompido, no un digito real del precio). Tiene prioridad sobre
    # la Regla C cuando el string empieza con un digito espurio valido, porque en los
    # casos reales verificados esa interpretacion fue siempre la correcta.
    PATRON_DIGITO_ESPURIO_MILES = re.compile(r"^[568sS](\d{1,3},\d{3})[a-zA-Z]{0,4}$")

    # Regla C: numero suelto con coma de miles que NO empieza con un digito espurio
    # valido -- aqui no hay ambiguedad posible con un "$" corrompido, se lee completo.
    # El formato "N,NNN" ya es una senal fuerte por si solo (SKUs/codigos de barra que
    # lee el OCR no vienen agrupados con coma), por eso esta regla NO exige contexto
    # de precio cercano a diferencia de A/A2/B.
    PATRON_BARE_MILES = re.compile(r"^(\d{1,3},\d{3})[a-zA-Z]{0,4}$")

    # Regla B: digitos puros sin espurio -- ultimos 2 digitos son centavos. Ej: "999" -> $9.99
    # Total 3-4 digitos (1-2 enteros + 2 centavos) -- es lo unico validado empiricamente.
    # NO se generaliza a 5-6 digitos: sin la senal extra del digito espurio, un bare de
    # esa longitud es mas probable que sea un SKU/codigo de barras que un precio real
    # (confirmado: "541583"/"559944" cerca de contexto fuerte pero claramente no precios).
    # A proposito SIN sufijo tolerado (a diferencia de la Regla A): permitirlo abriria
    # de nuevo ese mismo hueco de SKU de 5-6 digitos (ej. "541583" pasaria como
    # "54"+"15"+sufijo"83"). Sin evidencia real de un caso que lo necesite, se deja
    # anclado estricto.
    #
    # Separada en 3 vs 4 digitos (07-ago-2026) tras medir contra el dataset de
    # etiquetado manual: de los bloques bare-digit que coincidian con un precio
    # REAL y COMPLETO del ground truth, 92/93 eran de 4 digitos y solo 1 de 3.
    # Los de 3 digitos casi siempre son una lectura TRUNCADA del OCR -- a esta
    # tipografia (precio entero grande + centavos en superindice chico) le suele
    # faltar un digito del superindice (ej. "199" leido en vez de "1990" para
    # $19.90) -- por eso 3 digitos exige contexto fuerte (ver mas abajo, sin
    # cambios); aceptarlo con contexto de producto solamente produciria un VALOR
    # incorrecto (ej. $1.99 en vez de $19.90), peor que no extraerlo.
    PATRON_BARE_DIGITOS_3 = re.compile(r"^(\d{1})(\d{2})$")
    PATRON_BARE_DIGITOS_4 = re.compile(r"^(\d{2})(\d{2})$")

    # Regla B-2: precio entero <$100 SIN centavos (ej. "15" -> $15, "69" -> $69).
    # Frecuente en tiendas_3b/bodega_aurrera. Es el mas ambiguo de todos (facil
    # de confundir con cantidades "2 pzas", pesos, fragmentos de SKU) -- por eso
    # exige el gate MAS estricto disponible: solo contexto fuerte, igual que la
    # Regla de 3 digitos, nunca el OR con "producto cerca" que usa la de 4.
    # Agregado 19-ago-2026 tras medir contra el dataset manual: 293 precios que
    # el bloque OCR lee completo y correcto no se extraian por falta de este
    # patron (ver sources/nlp/04_cobertura_bare_digits_2_5.md).
    PATRON_BARE_DIGITOS_2 = re.compile(r"^(\d{2})$")

    # Regla B-5: precio >=$100 CON centavos (ej. "15490" -> $154.90). Frecuente
    # en casa_ley (productos de bulto/carton, precios altos). RIESGO YA
    # DOCUMENTADO arriba (Regla B): un bare de 5-6 digitos se probo y se
    # rechazo en jul-2026 por confundirse con SKU/codigo de barras
    # ("541583"/"559944"). Para reabrir 5 digitos sin repetir ese problema, el
    # gate es el mas estricto posible: contexto fuerte Y producto cerca A LA
    # VEZ (no OR como la Regla de 4 digitos). Agregado 19-ago-2026, ver
    # sources/nlp/04_cobertura_bare_digits_2_5.md.
    PATRON_BARE_DIGITOS_5 = re.compile(r"^(\d{3})(\d{2})$")

    # Evita interpretar un año de vigencia ("2026") como precio
    PATRON_ANIO_PLAUSIBLE = re.compile(r"^20[12]\d$")

    # Contexto "fuerte": palabras que solo aparecen junto a un precio, nunca junto a
    # una cantidad/peso de producto. Suficiente por si solo para la Regla A o B.
    PATRON_CONTEXTO_PRECIO_FUERTE = re.compile(
        r"""
        \b(?:
            a\s+s[oó]lo|de\s+oferta|antes|ahorr[ao]s?|cada\s+un[oa]|paquete|c/u|c\.u\.
        )\b
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # Contexto "de unidad": kg/ml/g/etc tambien describen cantidades de producto
    # ("355 ml", "100 g") sin relacion con el precio -- por si solo es ambiguo.
    # Solo se usa para reforzar la Regla A, que ya tiene la senal extra del digito
    # espurio; la Regla B (sin esa senal) exige contexto fuerte para no confundir
    # cantidades con precios (confirmado: "100" cerca de "ml" NO es un precio).
    PATRON_CONTEXTO_UNIDAD = re.compile(
        r"\b(?:kg|kgs|gr|grs|g|ml|lt|l|pza|pzas|pieza|piezas)\b",
        re.IGNORECASE
    )

    # Palabras que descartan la interpretacion de precio aunque haya contexto cerca
    # (ej. "150 puntos" de tarjeta de lealtad, no un precio). El "." tolera errores
    # de OCR de un caracter en medio (confirmado: "Puhtos" en vez de "Puntos")
    PATRON_EXCLUSION_CONTEXTO_PRECIO = re.compile(r"\bp?u.tos?\b", re.IGNORECASE)

    # Distancia maxima (px) para considerar un bloque de contexto "cercano".
    # Calibrada contra paginas escaladas a ANCHO_REFERENCIA_UMBRALES (ver mas abajo).
    # Si la pagina se proceso a un ancho distinto, procesar_pagina() calcula un
    # factor_escala y esta distancia se multiplica por el antes de usarse -- ver
    # _hay_contexto_precio / _hay_producto_cerca. Sin esto, subir la resolucion de
    # OCR (ej. 1500->2500px) reduce el alcance EFECTIVO de este umbral en la misma
    # proporcion, porque las distancias reales entre bloques crecen con la imagen
    # pero el umbral se queda fijo -- confirmado empiricamente 11-ago-2026 (prioridad
    # 6 del plan de mejora): PRECIOS en alsuper cayo ~9pts en promedio al subir a
    # 2500px sin este fix, mientras que PROD se mantuvo plano (no es un problema de
    # OCR, es este umbral quedandose corto).
    DISTANCIA_MAX_CONTEXTO_PRECIO = 220

    # Ancho (px) contra el que estan calibrados DISTANCIA_MAX_CONTEXTO_PRECIO y
    # GAP_HORIZONTAL_MIN/MAX de _detectar_precios_fusionados -- debe coincidir con
    # preprocessor.ANCHO_OBJETIVO_DEFAULT (el estandar historico de produccion).
    ANCHO_REFERENCIA_UMBRALES = 1500

    # --------------- PROMOCIONES ---------------
    # Separadas en "fuerte" (mecanica de promo especifica e inequivoca -- casi nunca
    # aparece si no hay una promocion real detras, ej. "4x3") vs "debil" (ambigua,
    # puede ser un banner suelto de portada sin ninguna promo/producto real cerca,
    # ej. "hasta 40%"). Ver uso en _clasificar: la fuerte no exige que la pagina
    # tenga un precio en pesos, la debil si (gate agregado para evitar banners
    # publicitarios aislados -- ver PATRONES_PROMO_DEBIL).
    PATRONES_PROMO_FUERTE = [
        re.compile(r"\d+\s*[xX×]\s*(?:\$\s*)?\d+", re.IGNORECASE),
        re.compile(r"\$\s*\d+\s*por\s*cada\s*\$\s*\d+", re.IGNORECASE),
        # "compra uno y llévate el segundo a mitad de precio"
        re.compile(r"mitad\s+de\s+precio", re.IGNORECASE),
        re.compile(r"segunda?\s+a\s+mitad", re.IGNORECASE),
        re.compile(r"compra\s+(?:uno|una)\s+y\s+ll[eé]vate", re.IGNORECASE),
        # ERROR #17 — "1x$33.90 3x$67.80 Ahorras $X" (soriana paquetes)
        # Detecta el patrón Nx$Y repetido — es mecánica de paquete, no precio simple
        re.compile(r"\d+\s*[xX×]\s*[\$5s]\s*\d+[\.,]\d+\s+\d+\s*[xX×]", re.IGNORECASE),
    ]

    PATRONES_PROMO_DEBIL = [
        re.compile(r"\d+\s*%\s*(?:off|desc(?:uento)?|de\s+desc)?", re.IGNORECASE),
        re.compile(r"\b(?:te\s+regalamos|lleva|paga|gratis|bonificaci[oó]n)\b", re.IGNORECASE),
        re.compile(r"precio\s+(?:ya\s+)?con\s+(?:la\s+)?promo", re.IGNORECASE),
        re.compile(r"\b(?:hasta|descuento\s+de)\s+\d+\s*%", re.IGNORECASE),
    ]

    # Compatibilidad: union de ambos grupos, usada donde no importa la distincion
    PATRONES_PROMO = PATRONES_PROMO_FUERTE + PATRONES_PROMO_DEBIL

    # --------------- EVENTOS PROMOCIONALES ---------------
    # Campañas, eventos comerciales y etiquetas de oferta que NO son mecánica de precio.
    # Se guardan como metadata de campaña — útiles para análisis temporal en BI.
    PATRONES_EVENTO_PROMO = re.compile(
        r"""
        \b(?:
            # Campañas mexicanas conocidas
            julio\s+regalado | hot\s+sale | buen\s+fin | el\s+buen\s+fin |
            cyber\s+monday | black\s+friday | navidad | temporada\s+navide[ñn]a |
            dia\s+de\s+las\s+madres | dia\s+del\s+ni[ñn]o | dia\s+de\s+reyes |
            regreso\s+a\s+clases | back\s+to\s+school | temporada\s+escolar |
            semana\s+santa | dia\s+de\s+muertos |

            # Etiquetas de oferta de tienda (sueltas, no como parte de frase larga)
            precio\s+bajo | precios?\s+bajos | precio\s+especial |
            oferta\s+especial | super\s+oferta | mega\s+oferta |
            oferta\s+de\s+temporada | liquidaci[oó]n |
            descuento\s+exclusivo | descuentos?\s+exclusivos |

            # Fusiones OCR de campañas
            julioregalado | julioregaladoe | julio\s*regalado[a-z]{0,3}
        )\b
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # --------------- DESCARTE ---------------
    PATRONES_DESCARTE = [
        # 1-2 caracteres -- EXCEPTO 2 digitos puros ("15", "69"), que pueden
        # ser un precio entero sin centavos (ver PATRON_BARE_DIGITOS_2/Regla
        # B-2 mas abajo). Sin esta excepcion, este descarte corria ANTES que
        # Regla B-2 en _clasificar y la dejaba inalcanzable siempre -- bug
        # encontrado al medir 0 extracciones via B-2 en todo el corpus
        # (19-ago-2026). La decision de aceptarlo como precio sigue
        # dependiendo del gate de contexto de B-2, no de esta linea.
        re.compile(r"^(?!\d{2}$).{1,2}$"),
        # Solo símbolos
        re.compile(r"^[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\$]+$"),
        # URLs
        re.compile(r"(?:www\.|\.(com|mx|org))", re.IGNORECASE),
        # Fechas de vigencia
        re.compile(r"vigencia|vencimiento|v[aá]lido|del\s+\d+\s+de", re.IGNORECASE),
        # Pie de página legal
        re.compile(
            r"hasta\s+agotar|sujeto\s+a|en\s+tiendas\s+que|aplica\s+[uú]nicamente|"
            r"t[eé]rminos\s+y\s+condiciones|consulta\s+t[eé]rminos",
            re.IGNORECASE
        ),
        # Demasiados caracteres especiales
        re.compile(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\s\$\.,\-%]{3,}"),
        # Marcas de tienda solas (pie de página)
        re.compile(
            r"^(?:lacomer|fresko|walmart|soriana|chedraui|costco|heb|oxxo|"
            r"bodega\s+aurrera|s-mart|subogeda|tiendas?\s+neto|waldos?|"
            r"zorro|alsuper|merco|tiendas?\s+3b)(?:\.com(?:\.mx)?)?$",
            re.IGNORECASE
        ),
        # Metadata de tallas
        re.compile(r"^tallas?\s*:\s*[A-Za-z0-9]{2,}", re.IGNORECASE),
        # Specs técnicas sueltas sin contexto
        re.compile(r"^\d+\s*(?:gb|mb|ghz|mhz|watts?|w\b|mpx|pulgadas)", re.IGNORECASE),

        # ── Estados y geografía de México ──────────────────────────────────────
        re.compile(
            r"^(?:"
            r"aguascalientes|baja\s+california(?:\s+sur)?|campeche|"
            r"chiapas|chihuahua|ciudad\s+de\s+m[eé]xico|cdmx|"
            r"coahuila|colima|durango|guanajuato|guerrero|hidalgo|"
            r"jalisco|m[eé]xico|michoac[aá]n|morelos|nayarit|"
            r"nuevo\s+le[oó]n|oaxaca|puebla|quer[eé]taro|"
            r"quintana\s+roo|san\s+luis\s+potos[íi]|sinaloa|sonora|"
            r"tabasco|tamaulipas|tlaxcala|veracruz|yucat[aá]n|zacatecas|"
            r"luis\s+potos[íi]|potosi|quintana|le[oó]n|xico|"
            r"uevo|hapas|couma|estado\s+de\s+m[eé]xico"
            r")$",
            re.IGNORECASE
        ),
        re.compile(
            r"^(?:CDMX|DF|NL|BC|BCS|AGS|CHIS|CHIH|COAH|COL|DGO|GTO|GRO|"
            r"HGO|JAL|MEX|MICH|MOR|NAY|OAX|PUE|QRO|QROO|SLP|SIN|SON|"
            r"TAB|TAMPS|TLAX|VER|YUC|ZAC)$"
        ),

        # ── Financiero / bancario ───────────────────────────────────────────────
        re.compile(
            r"^(?:bbva|banamex|banorte|santander|hsbc|citibanamex|"
            r"scotiabank|inbursa|banbajio|afirme|invex|american\s+express|"
            r"amex|sam['\"]?s\s+club|walmart\s+invex|bradescard|"
            r"clip|mercado\s+pago|oxxo\s+pay|codi)$",
            re.IGNORECASE
        ),
        re.compile(r"\b(?:inbursa|amcrican|american)\b", re.IGNORECASE),
        re.compile(r"\bwalmart\b.{0,30}\binvex\b", re.IGNORECASE),
        re.compile(
            r"^(?:pagando\s+con|meses\s+sin(?:\s+intereses)?|"
            r"tarjetas?\s+de\s+cr[eé]dito|tarjetas?\s+participantes|"
            r"con\s+tu\s+tarjeta|a\s+\d+\s+meses|sin\s+intereses|"
            r"en\s+toda\s+la\s+tienda|en\s+tiendas\s+participantes)$",
            re.IGNORECASE
        ),
        re.compile(
            r"\b(?:banamex|banorte|santander|hsbc|inbursa|bradescard)\b"
            r".{0,50}"
            r"\b(?:banamex|banorte|santander|hsbc|inbursa|bradescard|"
            r"walmart|invex|liverpool|coppel)\b",
            re.IGNORECASE
        ),
        # Monto minimo de compra a meses/financiamiento (ej. "$6,000 MN." de Costco
        # Banamex) -- "MN." (moneda nacional) es una notacion que casi nunca aparece
        # en un precio de producto real del folleto, solo en letra chica financiera.
        re.compile(r"^\$\s*[\d,]+\s*MN\.?$", re.IGNORECASE),

        # ── Slogans y frases de campaña cross-tienda ───────────────────────────
        # El "¡" de apertura se pierde en el OCR y queda como una "i" pegada al
        # verbo ("iConsiente", "iRenueva"). Bug corregido: "(?:i¡)?" exigía la
        # secuencia literal de 2 caracteres "i¡" (nunca ocurre en OCR real) en vez
        # de "[i¡]?" -- un solo caracter opcional, "i" O "¡".
        re.compile(
            r"^[i¡]?(?:consiente|encuentra|renueva|aprovecha|celebra|"
            r"descubre|cuida|disfruta)\b",
            re.IGNORECASE
        ),
        re.compile(
            r"\b(?:sin\s+gastar\s+de\s+m[aá]s|lo\s+que\s+necesita|"
            r"lo\s+que\s+le\s+gustar[ií]a|espacio\s+de\s+mam[aá]|"
            r"consiente\s+a\s+mam[aá]|renueva\s+el\s+espacio)\b",
            re.IGNORECASE
        ),
        re.compile(
            r"^(?:hasta\s+[Ii]o\s+que|hasta\s+lo\s+que)\b.{0,30}[!;]?$",
            re.IGNORECASE
        ),

        # ── Condiciones MSI: lista de categorias separadas por coma ────────────
        # "En Electrónica, Cómputo, Fotografía, Videojuegos..." -- condicion de
        # letra chica de "Meses Sin Intereses", no un nombre de producto.
        re.compile(
            r"^en\s+\w+(?:\s+\w+)*(?:\s*,\s*\w+(?:\s+\w+)*){2,}",
            re.IGNORECASE
        ),

        # ── Slogans específicos de tienda detectados en análisis ───────────────
        re.compile(
            r"^(?:"
            # tolera espacios totalmente fundidos por el OCR (ej. "Entiendayen inea",
            # "En tiendayen linea") y la "l" leida como "(" (ej. "en tienda y en (inea")
            r"en\s*tienda\s*y\s*en\s*[l(]?[ií]nea|s[oó]lo\s+en\s+tienda|"
            r"en\s+tienda\s*\+\s*en\s*l[ií]nea|"
            r"en\s*tienda[y\s]+en\s+l[ií]nea|"
            r"en\s+tienda|en\s+linea|en\s+l[ií]nea|"       # solos sin contexto
            r"enlinea|enl[ií]nea|"                          # fusiones OCR costco
            r"s[oó]loenlinea|s[oó]loen\s+tienda|s[oó]loen\s+l[ií]nea|"
            r"s[oó]lo\s+enlinea|s[oó]lo\s+en\s+l[ií]nea|"  # con espacio: "SÓLO ENLINEA"
            r"s[oó]lqen\s+l[ií]nea|s[oó]lqen\s+linea|"     # ERROR #19: Q→O por OCR
            r"h[ií]per|"
            r"rebajado|"
            r"sale|"
            r"el\s+mejor|"
            r"cuesta\s+menos|nos\s+cuesta\s+menos|"
            r"llevarte\s+m[aá]s|"
            r"precios?\s+bajos?\s+todos\s+los\s+d[ií]as\.?|"
            r"sucursales|"
            r"de\s+cashback|"
            r"dinero\s+electr[oó]nico|"
            r"(?:pesos?\s+)?de\s+descuento|pesos\s+dedescuento|dedescuento|"
            r"descuentos?\s+exclusivos?|"
            r"precio\s+bajo|"
            r"cashback|"
            r"para\s+socios|"                               # costco header
            r"patrocinadores|"                              # costco
            r"precio\s+por\s+kilo"                          # costco
            r")$",
            re.IGNORECASE
        ),

        # ── Palabras sueltas de folleto que pasan isupper() ────────────────────
        re.compile(
            r"^(?:desde|ahora|antes|sale|rebajado|h[ií]per|kilo|kilos|"
            r"oferta|ofertas|promocion|promoci[oó]n|exclusivo|exclusiva|"
            r"descuento|descuentos|ahorro|ahorros|vigente|vigentes|"
            r"temporada|liquidaci[oó]n|especial|gratis|bonificaci[oó]n)$",
            re.IGNORECASE
        ),

        # ── Marcas-logo de envase (fresko / alsuper) ───────────────────────────
        # Cubre: Golden, Hills, variantes OCR solas Y combinaciones compuestas
        re.compile(
            r"^['\"\`]?"                                    # comilla inicial OCR
            r"(?:[IJSHMT]|[a-z])??"                         # prefijo OCR espurio opcional
            r"(?:golden|gulden|golfen|galten|galden|gafen|golilen|galfen|"
            r"lolden|colgen|goldcn|goldei|goiden|goldeni|golaen|"
            r"golde[nr]?|jgolden|igolder|lolde|iolde|solden|folden|"
            r"ggolden|golden\s*hills?[t*.:'\-\s]?|goldenhills?[t*]?)"
            r"(?:\s*[,\.'\"\s]*"
            r"(?:hills?|hilis?|hilils?|hiiis?|iiilis?|hifls|hilIs|"
            r"hiiis|hilis|hiis|h[ií]lls?|fls|blanqueado\s+hills?))??"
            r"['\"\`\.\-\s*]*$",
            re.IGNORECASE
        ),
        # Hills solo o con prefijo OCR
        re.compile(
            r"^['\"\`]?(?:[IJSHMT])??"
            r"(?:hills?|hilis?|hilils?|hiiis?|iiilis?)[\.:'\s*]*$",
            re.IGNORECASE
        ),

        # ── Header repetido de folleto (fresko Golden Hills) ─────────────────
        re.compile(
            r"^(?:un\s+brillo(?:\s+de\s+calidad)?|de\s+calidad|decalidad)$",
            re.IGNORECASE
        ),

        # ── Textos de portada / cierre de folleto ────────────────────────────
        re.compile(
            r"^(?:como\s+te\s+gusta|exploralo\s+en|s[ií]guenos\s+en|"
            r"libera|el\s+potencial|de\s+tu\s+suv|"
            r"consulte\s+a\s+su\s+m[eé]dico|ver\s+bien\s+es\s+importante)$",
            re.IGNORECASE
        ),

        # ── Slogan "precio bajo" de Bodega Aurrera ──────────────────────────────
        # El OCR nunca lee "precio bodega" limpio en este folleto -- variantes
        # garbled confirmadas: "PREçIQ"/"BGDEGA", "PREçO"/"DEGA", "PREçI".
        re.compile(r"^(?:precio\s*bodega|pre[cç][ií]?[oq]?|bgdega|dega)$", re.IGNORECASE),

        # ── Ruido OCR puro (consonantes sin vocales) ───────────────────────────
        re.compile(
            r"^(?:[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}\s+){1,3}"
            r"[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}$"
        ),
    ]

    # --------------- Keywords de producto ---------------
    KEYWORDS_PRODUCTO = re.compile(
        r"\b(?:lampara|l[aá]mpara|gabinete|carro|carrito|pintura|sellador|"
        r"impermeabilizante|escalera|taburete|herramienta|caja|silla|mesa|"
        r"organizador|leche|aceite|detergente|jab[oó]n|papel|carne|pollo|"
        r"refresco|cerveza|yogurt|queso|mantequilla|harina|az[uú]car|sal|"
        r"shampoo|crema|desodorante|pa[ñn]al|botella|lata|bolsa|paquete|"
        r"litro|[Ll]t\.?|[Kk][Gg]\.?|[Gg]r?\.?|[Mm][Ll]\.?|pieza|pza)\b",
        re.IGNORECASE
    )

    # --------------- Correcciones OCR ---------------
    CORRECCIONES_OCR = [
        (re.compile(r"@"),                        "o"),
        (re.compile(r"(?<!\w)0(?=\d{2,})"),       "o"),
        # 'o' minúscula entre coma de miles y dígitos: $16,o00 → $16,000
        (re.compile(r"(\d[,\.])o(\d{2,3})"),      r"\g<1>0\2"),
        (re.compile(r"\$\s+"),                     "$"),
        (re.compile(r"(\d),(\d{3})(?!\d)"),        r"\1,\2"),
        (re.compile(r"(\d)\.(\d{3})(?!\d)"),       r"\1,\2"),
        (re.compile(r"\s{2,}"),                    " "),
        (re.compile(r"[|¡!]{2,}"),                 ""),
    ]

    CONFIANZA_MINIMA = 0.15

    def __init__(self, confianza_minima: float = None):
        self.confianza_minima = confianza_minima or self.CONFIANZA_MINIMA

    # --------------- Método principal ---------------

    def procesar_pagina(self, datos_pagina: dict) -> ResultadoPagina:
        resultado = ResultadoPagina(imagen=datos_pagina["imagen"])
        bloques_pagina = datos_pagina["bloques"]  # contexto espacial para precios sin simbolo

        # Factor de escala de los umbrales de distancia en px (ver
        # ANCHO_REFERENCIA_UMBRALES). "ancho_pagina" es opcional -- si el OCR no lo
        # trae (datos generados antes de este campo), se asume el ancho de
        # referencia y el factor queda en 1.0 (comportamiento identico al anterior).
        ancho_pagina = datos_pagina.get("ancho_pagina") or self.ANCHO_REFERENCIA_UMBRALES
        factor_escala = ancho_pagina / self.ANCHO_REFERENCIA_UMBRALES

        hay_precio_en_pagina = self._pagina_tiene_precio(bloques_pagina, factor_escala)

        # Pre-paso: precios repartidos en 2 bloques adyacentes (entero + centavos,
        # ver _detectar_precios_fusionados). Va ANTES del loop normal porque un
        # entero de 1-2 digitos nunca llegaria a clasificarse por si solo.
        bloques_consumidos = set()
        for bloque_entero, bloque_centavos, valor in self._detectar_precios_fusionados(bloques_pagina, factor_escala):
            resultado.precios.append(EntidadExtraida(
                "PRECIO",
                f"{bloque_entero['texto']}+{bloque_centavos['texto']}",
                f"{bloque_entero['texto']}.{bloque_centavos['texto']}",
                valor=valor,
                confianza=min(bloque_entero["confianza"], bloque_centavos["confianza"]),
                bbox=bloque_entero["bbox"],
            ))
            bloques_consumidos.add(id(bloque_entero))

        for bloque in bloques_pagina:
            if id(bloque) in bloques_consumidos:
                continue

            texto_raw = bloque["texto"]
            confianza = bloque["confianza"]
            bbox      = bloque.get("bbox", {})

            if confianza < self.confianza_minima:
                continue

            texto_limpio = self._limpiar_texto(texto_raw)
            if not texto_limpio:
                continue

            entidad = self._clasificar(texto_limpio, texto_raw, confianza, bbox, bloques_pagina,
                                       hay_precio_en_pagina, factor_escala)

            tipo = entidad.tipo
            if tipo == "PRECIO":
                resultado.precios.append(entidad)
            elif tipo == "PRECIO_ANTERIOR":
                resultado.precios_anteriores.append(entidad)
            elif tipo == "AHORRO":
                resultado.ahorros.append(entidad)
            elif tipo == "PROMO":
                resultado.promos.append(entidad)
            elif tipo == "EVENTO_PROMO":
                resultado.eventos_promo.append(entidad)
            elif tipo == "PRODUCTO":
                resultado.productos.append(entidad)
            elif tipo == "ATRIBUTO":
                resultado.atributos.append(entidad)
            else:
                resultado.descartes.append(entidad)

        return resultado

    def procesar_json_ocr(self, datos_ocr: list[dict]) -> list[ResultadoPagina]:
        resultados = []
        for pagina in datos_ocr:
            r = self.procesar_pagina(pagina)
            resultados.append(r)
            logger.info(r.resumen())
        return resultados

    # --------------- Clasificador ---------------

    def _clasificar(self, texto, texto_raw, confianza, bbox, bloques_pagina=None,
                    hay_precio_en_pagina: bool = True, factor_escala: float = 1.0) -> EntidadExtraida:

        # 1. Descarte rápido
        if self._es_descarte(texto):
            return EntidadExtraida("DESCARTE", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 1b. Condiciones de compra — descartar antes de extraer precios
        # "Válido en compras mayores a $238", "En compras desde $500"
        if re.search(
            r"\b(?:en\s+compras?|compras?\s+mayores?\s+a|v[aá]\w*\s+en\s+compras?)\b",
            texto, re.IGNORECASE
        ):
            return EntidadExtraida("DESCARTE", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 2. Precio anterior ("Antes: $X" / "DE $X A")
        valor_ant = self._extraer_precio_anterior(texto)
        if valor_ant is not None:
            return EntidadExtraida("PRECIO_ANTERIOR", texto_raw, texto,
                                   valor=valor_ant, confianza=confianza, bbox=bbox)

        # 3. Ahorro ("Ahorras $X") — verificar ANTES que no sea paquete Nx$Y
        # Si el texto contiene patrón de paquete (1x$33 3x$67), va como PROMO
        # Mecanica "fuerte" (NxM, "compra uno y llevate", etc.) es lo bastante
        # inequivoca para aceptarse aunque la pagina no tenga ningun precio en
        # pesos (ej. "4x3" en categoria de llantas, sin precio unitario visible).
        # Mecanica "debil" (%, "hasta X%") SI exige que la PAGINA tenga al menos
        # un precio real -- sin eso es casi siempre un banner publicitario aislado
        # (ej. "hasta 40%" en una portada sin productos con precio), no una
        # promocion real de producto. Las promos bancarias/MSI ya se descartan
        # antes, en PATRONES_DESCARTE -- esto no las afecta.
        if self._es_promo_fuerte(texto) or (self._es_promo_debil(texto) and hay_precio_en_pagina):
            return EntidadExtraida("PROMO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        valor_ahorro = self._extraer_ahorro(texto)
        if valor_ahorro is not None:
            return EntidadExtraida("AHORRO", texto_raw, texto,
                                   valor=valor_ahorro, confianza=confianza, bbox=bbox)

        # 4. Evento promocional (Julio Regalado, Hot Sale…)
        if self.PATRONES_EVENTO_PROMO.search(texto):
            return EntidadExtraida("EVENTO_PROMO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 5. Precio actual
        precio_valor = self._extraer_precio(texto)
        if precio_valor is not None:
            return EntidadExtraida("PRECIO", texto_raw, texto,
                                   valor=precio_valor, confianza=confianza, bbox=bbox)

        # 5b. Precio sin símbolo — "$" perdido o mal leído por el OCR (tag de oferta).
        # Solo aplica si hay contexto de precio cerca del bloque (ver PATRON_CONTEXTO_PRECIO).
        precio_sin_simbolo = self._extraer_precio_sin_simbolo(texto, bbox, bloques_pagina, factor_escala)
        if precio_sin_simbolo is not None:
            return EntidadExtraida("PRECIO", texto_raw, texto,
                                   valor=precio_sin_simbolo, confianza=confianza, bbox=bbox)

        # 6. Catálogo → PRODUCTO o ATRIBUTO
        en_catalogo, categoria, es_atributo = buscar_categoria(texto)
        if en_catalogo:
            tipo = "ATRIBUTO" if es_atributo else "PRODUCTO"
            return EntidadExtraida(tipo, texto_raw, texto,
                                   confianza=confianza, bbox=bbox, categoria=categoria)

        # 7. Heurística de producto
        if self._es_probable_producto(texto):
            return EntidadExtraida("PRODUCTO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 8. Por defecto
        return EntidadExtraida("DESCARTE", texto_raw, texto,
                               confianza=confianza, bbox=bbox)

    # --------------- Reglas individuales ---------------

    def _limpiar_texto(self, texto: str) -> str:
        texto = texto.strip()
        for patron, reemplazo in self.CORRECCIONES_OCR:
            texto = patron.sub(reemplazo, texto)
        return texto.strip()

    def _es_descarte(self, texto: str) -> bool:
        for patron in self.PATRONES_DESCARTE:
            if patron.search(texto):
                return True
        chars_raros = sum(1 for c in texto
                         if not c.isalnum() and c not in " $.,-%áéíóúÁÉÍÓÚñÑ")
        if len(texto) > 3 and chars_raros / len(texto) > 0.4:
            return True
        return False

    def _extraer_precio_anterior(self, texto: str) -> Optional[float]:
        # Patrón estándar: "Antes: $X", "Antos; $X", "precio anterior $X"
        match = self.PATRON_PRECIO_ANTERIOR.search(texto)
        if match:
            return self._parsear_numero(match.group(1))
        # ERROR #18 — "DE $5,4900 A $3,990": el precio anterior es el primero
        # OCR fusiona el punto decimal: "$5,490.00" → "$5,4900"
        # Corrección: si hay coma de miles + 4 dígitos, los últimos 2 son centavos
        m_de_a = self.PATRON_DE_A.match(texto)
        if m_de_a:
            num_str = m_de_a.group(1)
            # Corregir fusión OCR: "$5,490.00" → OCR lee "$5,4900"
            # coma + más de 3 dígitos → los últimos 2 son centavos
            num_str = re.sub(
                r"(\d+),(\d{4,})$",
                lambda m: m.group(1) + "," + m.group(2)[:-2] + "." + m.group(2)[-2:],
                num_str
            )
            return self._parsear_numero(num_str)
        return None

    def _extraer_ahorro(self, texto: str) -> Optional[float]:
        match = self.PATRON_AHORRO.search(texto)
        if not match:
            return None
        return self._parsear_numero(match.group(1))

    def _extraer_precio(self, texto: str) -> Optional[float]:
        # Ignorar si el texto empieza con prefijo de ahorro o precio anterior
        if re.match(r"^\s*(?:ahorr[ao]s?|antes|antos|precio\s+anterior)", texto,
                    re.IGNORECASE):
            return None
        # Ignorar condiciones de compra ("En compras desde $500", "válido en compras mayores a $238")
        if re.search(
            r"(?:^|\b)(?:en\s+compras?|en\s+toda|v[aá][\"'o]?\w*\s+en|"
            r"compras?\s+mayores?\s+a)",
            texto, re.IGNORECASE
        ):
            return None
        # Precio con $ OCR corrupto (s/8 + dígitos): fresko y similares
        m_ocr = self.PATRON_PRECIO_OCR_CORRUPTO.match(texto)
        if m_ocr:
            try:
                return float(f"{m_ocr.group(1)}.{m_ocr.group(2)}")
            except ValueError:
                pass
        # Corrige "O"/"o" leida como cero dentro de un precio (ej. "$4OO" -> "$400").
        # Sin esto, PATRON_PRECIO solo captura los digitos antes de la "O" ("4") y el
        # resto se pierde en silencio -- bug confirmado en costco ($400 -> 4.0). Solo
        # se aplica si el bloque ya contiene "$", para no tocar texto no relacionado.
        if "$" in texto:
            texto = re.sub(r"(?<=\d)[Oo]+", lambda m: "0" * len(m.group()), texto)
        match = self.PATRON_PRECIO.search(texto)
        if not match:
            return None
        return self._parsear_numero(match.group(1))

    def _extraer_precio_sin_simbolo(
        self, texto: str, bbox: dict, bloques_pagina: Optional[list[dict]],
        factor_escala: float = 1.0
    ) -> Optional[float]:
        """
        Recupera precios cuyo "$" el OCR perdio o leyo mal (ver PATRON_DIGITO_ESPURIO /
        PATRON_BARE_DIGITOS_3 / PATRON_BARE_DIGITOS_4). Solo se activa si hay contexto
        de precio confirmado cerca del bloque -- un bloque numerico aislado (SKU,
        pagina, cantidad) no cuenta.
        """
        if not bbox or not bloques_pagina:
            return None
        if self.PATRON_ANIO_PLAUSIBLE.match(texto):
            return None

        # Regla A-miles: digito espurio + remanente con coma de miles (ej. "58,999" ->
        # $8,999). Verificado contra la imagen real -- ver comentario en la constante.
        # Va ANTES que la Regla C para que gane esta interpretacion cuando el string
        # empieza con un digito espurio valido.
        m = self.PATRON_DIGITO_ESPURIO_MILES.match(texto)
        if m:
            return self._parsear_numero(m.group(1))

        # Regla C: numero suelto con coma de miles que NO empieza con digito espurio
        # -- sin ambiguedad posible, se lee completo. No exige contexto cercano.
        m = self.PATRON_BARE_MILES.match(texto)
        if m:
            return self._parsear_numero(m.group(1))

        # Regla A2: digito espurio + numero que ya trae su propio punto decimal
        # (ej. "824.95k6" -> $24.95). El decimal explicito ya es una senal tan fuerte
        # como el digito espurio mismo -- no se exige contexto cercano.
        m = self.PATRON_DIGITO_ESPURIO_DECIMAL.match(texto)
        if m:
            return self._parsear_numero(m.group(1))

        # Regla B-4 vs Regla A: ambigueedad real y documentada para texto de 4
        # digitos puros SIN sufijo -- "6990" puede ser un precio real con
        # centavos (69.90, Regla B-4, validada con 92/93 casos del dataset
        # manual) o un "$" mal leido + precio entero (249, Regla A, validada
        # con 6 casos confirmados en jul-2026: 299/266/249/169/229/599,
        # NINGUNO termina en 0). Antes, Regla A se evaluaba primero con un
        # gate mas debil y, si fallaba, mataba la funcion entera sin darle
        # oportunidad a Regla B-4 -- bug encontrado el 19-ago-2026 midiendo
        # contra el dataset manual: precios reales terminados en ".90" (69.90,
        # 59.90, 64.90, 89.90...) se estaban descartando por esto. Fix: para
        # texto sin sufijo se intenta primero Regla B-4 (mejor validada); solo
        # si su gate falla, se intenta Regla A como alternativa. Si el texto
        # SI trae sufijo (letras/c-u pegado) el comportamiento no cambia --
        # Regla B-4 esta anclada estricta sin sufijo, nunca lo matchea. Ver
        # sources/nlp/04_cobertura_bare_digits_2_5.md.
        m_b4 = self.PATRON_BARE_DIGITOS_4.match(texto)
        if m_b4:
            if (
                self._hay_contexto_precio(bbox, bloques_pagina, requerir_fuerte=True, factor_escala=factor_escala)
                or self._hay_producto_cerca(bbox, bloques_pagina, factor_escala=factor_escala)
            ):
                return self._parsear_numero(f"{m_b4.group(1)}.{m_b4.group(2)}")
            # Gate de B-4 fallo -- probar Regla A como alternativa antes de descartar.

        # Regla A: digito espurio + precio entero sin centavos (ej. "8249" -> $249,
        # "5199c/u" -> $199 c/u). Si el sufijo pegado es "c/u"/"c.u." -- una senal de
        # contexto fuerte igual de valida que si viniera en un bloque separado -- no
        # se exige contexto externo. Sin ese sufijo, contexto amplio (fuerte o de
        # unidad) porque el digito espurio ya es una senal fuerte por si solo.
        m = self.PATRON_DIGITO_ESPURIO.match(texto)
        if m:
            sufijo_fuerte = bool(re.search(r"c/u|c\.u\.", texto, re.IGNORECASE))
            if not sufijo_fuerte and not self._hay_contexto_precio(bbox, bloques_pagina, requerir_fuerte=False, factor_escala=factor_escala):
                return None
            return self._parsear_numero(m.group(1))

        # Regla B-5: 5 digitos puros -- ultimos 2 son centavos (ej. "15490" ->
        # $154.90). Empezo con gate AND (contexto fuerte Y producto cerca) por
        # el riesgo de SKU ya documentado en PATRON_BARE_DIGITOS_4 -- pero
        # medido (19-ago-2026), el AND dejaba pasar casi nada: 0/62 casos
        # reales del dataset manual tenian contexto fuerte (igual que B-2/B-4,
        # un precio de grid normal no trae "antes/oferta" cerca). El riesgo de
        # SKU documentado era sobre 6 digitos ("541583"/"559944"), nunca se
        # probo 5 por separado. Gate: mismo OR que B-2/B-4, validado con
        # evaluar_nlp.py (precios_mal_clasificados + revision manual de
        # muestra). Ver sources/nlp/04_cobertura_bare_digits_2_5.md.
        m = self.PATRON_BARE_DIGITOS_5.match(texto)
        if m:
            if not (
                self._hay_contexto_precio(bbox, bloques_pagina, requerir_fuerte=True, factor_escala=factor_escala)
                or self._hay_producto_cerca(bbox, bloques_pagina, factor_escala=factor_escala)
            ):
                return None
            return self._parsear_numero(f"{m.group(1)}.{m.group(2)}")

        # Regla B-3: 3 digitos puros (ej. "999" -> $9.99). Exige contexto FUERTE
        # unicamente -- SIN relajar con "producto cerca" (ver comentario arriba:
        # a 3 digitos, un bloque bare-digit casi siempre es una lectura truncada,
        # no un precio completo, y "producto cerca" no distingue eso).
        m = self.PATRON_BARE_DIGITOS_3.match(texto)
        if m:
            if not self._hay_contexto_precio(bbox, bloques_pagina, requerir_fuerte=True, factor_escala=factor_escala):
                return None
            return self._parsear_numero(f"{m.group(1)}.{m.group(2)}")

        # Regla B-2: 2 digitos puros -- precio entero SIN centavos (ej. "15" ->
        # $15). Se penso inicialmente exigir solo contexto fuerte (como B-3),
        # pero medido contra el dataset manual (19-ago-2026) el 96% de los
        # casos reales tenian "producto cerca" y NO contexto fuerte (a
        # diferencia de precios promocionales, un precio de grid normal junto
        # a su producto no trae palabras como "antes/oferta") -- igual que ya
        # se valido para B-4. Gate: mismo OR que B-4. Ver
        # sources/nlp/04_cobertura_bare_digits_2_5.md.
        # "00" explicitamente excluido: un precio de $0 nunca es real -- es el
        # remanente de centavos de un precio fusionado en 2 bloques (ej.
        # "199"+"00") que ya se cubre aparte via _detectar_precios_fusionados.
        # Sin este guard, "00" colaba como 173 precios falsos de $0.00 en todo
        # el corpus (encontrado 19-ago-2026 al revisar valores extremos).
        m = self.PATRON_BARE_DIGITOS_2.match(texto)
        if m and m.group(1) != "00":
            if not (
                self._hay_contexto_precio(bbox, bloques_pagina, requerir_fuerte=True, factor_escala=factor_escala)
                or self._hay_producto_cerca(bbox, bloques_pagina, factor_escala=factor_escala)
            ):
                return None
            return self._parsear_numero(m.group(1))

        return None

    def _hay_contexto_precio(
        self, bbox: dict, bloques_pagina: list[dict], requerir_fuerte: bool,
        factor_escala: float = 1.0
    ) -> bool:
        """
        True si hay un bloque de contexto de precio cerca del bbox y NINGUN bloque de
        exclusion (ej. "puntos" de lealtad) igual de cerca -- la exclusion tiene
        prioridad para evitar falsos positivos como "150 puntos".

        Si requerir_fuerte=True, solo cuenta el contexto "fuerte" (antes/de oferta/
        c-u/etc); el contexto de unidad (kg/ml/g) por si solo no basta porque tambien
        describe cantidades de producto sin relacion con el precio.
        """
        distancia_max = self.DISTANCIA_MAX_CONTEXTO_PRECIO * factor_escala
        hay_contexto = False
        for otro in bloques_pagina:
            otro_bbox = otro.get("bbox")
            if not otro_bbox or otro_bbox is bbox:
                continue
            if self._distancia_bbox(bbox, otro_bbox) > distancia_max:
                continue
            texto_otro = otro.get("texto", "")
            if self.PATRON_EXCLUSION_CONTEXTO_PRECIO.search(texto_otro):
                return False
            if self.PATRON_CONTEXTO_PRECIO_FUERTE.search(texto_otro):
                hay_contexto = True
            elif not requerir_fuerte and self.PATRON_CONTEXTO_UNIDAD.search(texto_otro):
                hay_contexto = True
        return hay_contexto

    def _hay_producto_cerca(self, bbox: dict, bloques_pagina: list[dict],
                            factor_escala: float = 1.0) -> bool:
        """
        True si hay un bloque vecino (dentro de DISTANCIA_MAX_CONTEXTO_PRECIO) que
        el catalogo o la heuristica reconocen como PRODUCTO/ATRIBUTO, y NINGUN
        bloque de exclusion (ej. "puntos" de lealtad) igual de cerca.

        Senal nueva (07-ago-2026) para la Regla B-4 (ver PATRON_BARE_DIGITOS_4):
        en estos folletos el precio va pegado al nombre del producto que etiqueta,
        asi que un precio "normal" (sin palabra de oferta cerca) casi siempre tiene
        un producto al lado. Validado contra el dataset manual: cubre 230/236
        (97%) de los precios recuperables reales.
        """
        distancia_max = self.DISTANCIA_MAX_CONTEXTO_PRECIO * factor_escala
        for otro in bloques_pagina:
            otro_bbox = otro.get("bbox")
            if not otro_bbox or otro_bbox is bbox:
                continue
            if self._distancia_bbox(bbox, otro_bbox) > distancia_max:
                continue
            texto_otro = otro.get("texto", "")
            if self.PATRON_EXCLUSION_CONTEXTO_PRECIO.search(texto_otro):
                return False
            texto_limpio = self._limpiar_texto(texto_otro)
            en_catalogo, _, _ = buscar_categoria(texto_limpio)
            if en_catalogo or self._es_probable_producto(texto_limpio):
                return True
        return False

    def _detectar_precios_fusionados(
        self, bloques_pagina: list[dict], factor_escala: float = 1.0
    ) -> list[tuple[dict, dict, float]]:
        """
        Detecta precios repartidos en 2 bloques OCR adyacentes -- precio entero
        grande + centavos en superindice chico, cada uno como su propio bloque
        (ej. "99" + "90" en vez de "9990"). Confirmado empiricamente 07-ago-2026
        contra alsuper/416306/pagina_002.webp: el bloque de centavos aparece justo
        a la derecha del entero, con menor altura de bbox (superindice) y alineado
        hacia la mitad superior del entero.

        Se corre como pre-paso ANTES del loop normal de clasificacion (ver
        procesar_pagina) porque un entero de 1-2 digitos ("99") nunca llegaria a
        _extraer_precio_sin_simbolo por si solo -- _es_descarte lo descarta de
        entrada por longitud (<=2 caracteres), igual que al bloque de centavos.

        Restringido a enteros de 1-2 digitos a proposito: un entero de 3 digitos
        ya tiene su propio camino via Regla B-3/B-4 en el loop normal -- no se
        toca ese camino para no arriesgar una fusion incorrecta con un bloque
        vecino no relacionado.

        Solo fusiona cuando hay EXACTAMENTE UN candidato a centavos valido para
        un entero dado -- ambiguedad (mas de un candidato) no se fusiona, para no
        arriesgar un emparejamiento incorrecto en paginas densas.

        Retorna una lista de (bloque_entero, bloque_centavos, valor_fusionado).
        """
        # Calibrados a ANCHO_REFERENCIA_UMBRALES, igual que DISTANCIA_MAX_CONTEXTO_PRECIO.
        GAP_HORIZONTAL_MIN = -30 * factor_escala
        GAP_HORIZONTAL_MAX = 60 * factor_escala

        candidatos_enteros = [
            b for b in bloques_pagina
            if b.get("bbox") and re.match(r"^\d{1,2}$", b.get("texto", ""))
        ]
        candidatos_centavos = [
            b for b in bloques_pagina
            if b.get("bbox") and re.match(r"^\d{2}$", b.get("texto", ""))
        ]

        fusionados = []
        for entero in candidatos_enteros:
            bbox_e = entero["bbox"]
            emparejados = []
            for centavos in candidatos_centavos:
                if centavos is entero:
                    continue
                bbox_c = centavos["bbox"]
                gap = bbox_c["x"] - (bbox_e["x"] + bbox_e["ancho"])
                if not (GAP_HORIZONTAL_MIN <= gap <= GAP_HORIZONTAL_MAX):
                    continue
                if bbox_c["alto"] >= bbox_e["alto"]:
                    continue  # el centavo debe ser visualmente mas chico (superindice)
                if bbox_c["y"] > bbox_e["y"] + bbox_e["alto"] * 0.5:
                    continue  # alineado hacia la mitad superior del entero
                emparejados.append(centavos)

            if len(emparejados) == 1:
                centavos = emparejados[0]
                valor = self._parsear_numero(f"{entero['texto']}.{centavos['texto']}")
                if valor is not None:
                    fusionados.append((entero, centavos, valor))

        return fusionados

    @staticmethod
    def _distancia_bbox(bbox_a: dict, bbox_b: dict) -> float:
        """Distancia euclidiana entre los centros de dos bbox {x,y,ancho,alto}."""
        xa = bbox_a["x"] + bbox_a["ancho"] / 2
        ya = bbox_a["y"] + bbox_a["alto"] / 2
        xb = bbox_b["x"] + bbox_b["ancho"] / 2
        yb = bbox_b["y"] + bbox_b["alto"] / 2
        return math.hypot(xa - xb, ya - yb)

    def _parsear_numero(self, numero_str: str) -> Optional[float]:
        """
        Convierte string numérico a float manejando separadores de miles/decimales.

        Reglas:
          $2,295  → 2295.0  (coma de miles: 3 dígitos tras separador)
          $10.999 → 10999.0 (punto de miles: 3 dígitos tras separador)
          $18.50  → 18.5    (punto decimal: 1-2 dígitos tras separador)
          $1,390  → 1390.0
        """
        try:
            numero_str = numero_str.strip()
            # Quitar letras sufijo (c, e, u, etc.) que hayan quedado
            numero_str = re.sub(r"[a-zA-Z]+$", "", numero_str).strip()
            # Separador de miles: coma o punto seguido de EXACTAMENTE 3 dígitos
            # — reemplazar por placeholder vacío (eliminar separador de miles)
            numero_str = re.sub(r"[,\.](\d{3})(?!\d)", r"\1", numero_str)
            # El separador que quede ahora (si hay) es decimal → normalizar a punto
            numero_str = numero_str.replace(",", ".")
            return float(numero_str)
        except (ValueError, IndexError):
            return None

    def _es_promo_fuerte(self, texto: str) -> bool:
        return any(patron.search(texto) for patron in self.PATRONES_PROMO_FUERTE)

    def _es_promo_debil(self, texto: str) -> bool:
        return any(patron.search(texto) for patron in self.PATRONES_PROMO_DEBIL)

    def _es_promo(self, texto: str) -> bool:
        return self._es_promo_fuerte(texto) or self._es_promo_debil(texto)

    def _pagina_tiene_precio(self, bloques_pagina: list[dict],
                             factor_escala: float = 1.0) -> bool:
        """
        Escaneo liviano previo a la clasificacion: True si algun bloque de la
        pagina contiene un precio real (con o sin simbolo). Se usa para exigir
        contexto de precio antes de aceptar una PROMO (ver _clasificar, paso 3)
        -- evita insertar promos huerfanas de paginas puramente publicitarias
        sin ningun producto con precio (ej. banners de portada).
        """
        for bloque in bloques_pagina:
            confianza = bloque.get("confianza", 0)
            if confianza < self.confianza_minima:
                continue
            texto = self._limpiar_texto(bloque.get("texto", ""))
            if not texto:
                continue
            if self._extraer_precio(texto) is not None:
                return True
            if self._extraer_precio_sin_simbolo(texto, bloque.get("bbox", {}), bloques_pagina, factor_escala) is not None:
                return True
        return False

    def _es_probable_producto(self, texto: str) -> bool:
        if len(texto) < 4:
            return False
        texto_norm = texto.lstrip("'\"'")
        # El OCR suele pegar puntuacion al final de la palabra ("Suavitel?",
        # "Rosita*", "Blancatel\"", "HUGGiES:") que rompe el .isalpha() de abajo
        # y hace que la palabra completa desaparezca del heuristico -- se
        # despoja por palabra antes de evaluarla (no afecta texto_norm, que es
        # lo que se guarda). Confirmado 07-ago-2026 via evaluar_nlp.py
        # fallos_producto (ocr_encontrado=True, nlp_clasificado=False).
        palabras = [p.strip("'\"?!;:,.*_()[]") for p in texto_norm.split()]
        palabras = [p for p in palabras
                    if len(p) >= 3 and
                    p.replace("é","e").replace("á","a").replace("ó","o")
                     .replace("í","i").replace("ú","u").replace("ñ","n").isalpha()]
        if not palabras:
            return False
        if self.KEYWORDS_PRODUCTO.search(texto):
            return True
        if texto_norm.isupper() and 4 <= len(texto_norm) <= 60:
            return True
        # Palabra unica de 4+ caracteres (antes exigia 5+): confirmado
        # 07-ago-2026 contra fragmentos reales de nombres largos que el OCR
        # corta en bloques independientes (ej. "Ciel"/"Amor"/"Ropa"/"Tela"/
        # "Saba" de "Agua Ciel", "Suavizante Amor Suavitel", "Shampoo...Vel
        # Rosita", "Tela Multiusos", "Toalla Femenina Saba") -- ver
        # evaluar_nlp.py fallos_producto con ocr_encontrado=True.
        if len(palabras) == 1 and len(palabras[0]) >= 4:
            return True
        if 4 <= len(texto_norm) <= 80 and len(palabras) >= 2:
            return True
        return False

    # --------------- Utilidades ---------------

    def imprimir_resultado(self, resultado: ResultadoPagina):
        print(f"\n{'═'*65}")
        print(f"  {resultado.imagen}")
        print(f"{'═'*65}")

        if resultado.productos:
            print(f"\n  🏷️  PRODUCTOS ({len(resultado.productos)}):")
            for e in resultado.productos:
                cat = f" [{e.categoria}]" if e.categoria else ""
                print(f"      {e.texto_norm[:50]:<50} [{e.confianza:.0%}]{cat}")

        if resultado.precios:
            print(f"\n  💰 PRECIOS ({len(resultado.precios)}):")
            for e in resultado.precios:
                print(f"      ${e.valor:>10,.2f}  ←  '{e.texto_norm}'")

        if resultado.precios_anteriores:
            print(f"\n  📉 PRECIOS ANTERIORES ({len(resultado.precios_anteriores)}):")
            for e in resultado.precios_anteriores:
                print(f"      ${e.valor:>10,.2f}  ←  '{e.texto_norm}'")

        if resultado.ahorros:
            print(f"\n  💸 AHORROS ({len(resultado.ahorros)}):")
            for e in resultado.ahorros:
                print(f"      ${e.valor:>10,.2f}  ←  '{e.texto_norm}'")

        if resultado.promos:
            print(f"\n  🎯 PROMOCIONES ({len(resultado.promos)}):")
            for e in resultado.promos:
                print(f"      {e.texto_norm[:55]}")

        if resultado.eventos_promo:
            print(f"\n  📅 EVENTOS PROMO ({len(resultado.eventos_promo)}):")
            for e in resultado.eventos_promo:
                print(f"      {e.texto_norm[:55]}")

        if resultado.atributos:
            print(f"\n  🔧 ATRIBUTOS ({len(resultado.atributos)}):")
            for e in resultado.atributos:
                print(f"      {e.texto_norm[:55]:<55} [{e.confianza:.0%}]")

        print(f"\n  🗑️  Descartes: {len(resultado.descartes)} bloques filtrados")
        print(f"{'─'*65}\n")