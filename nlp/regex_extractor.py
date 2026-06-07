# Modulo para extraer y clasificar entidades de texto OCR usando expresiones regulares.
# Toma los bloques de texto del OCR y los clasifica en categorías:
# PRECIO, PRECIO_ANTERIOR, AHORRO, PROMO, EVENTO_PROMO, PRODUCTO, ATRIBUTO, DESCARTE
#
# v3 — Cambios respecto a v2:
#   - PRECIO_ANTERIOR: detecta "Antes: $X", "Antos; $X", "precio anterior $X"
#   - AHORRO: detecta "Ahorras $X", "Ahorra $X", "Ahorras 5X" (OCR $ → 5)
#   - EVENTO_PROMO: detecta campañas como "Julio Regalado", "Hot Sale", "Precio Bajo"
#   - PATRON_PRECIO ampliado: prefijos DESDE/A sólo/desde:/a solo: + sufijo C/U
#   - Corrección OCR: 'o' entre dígitos con coma → '0' ($16,o00 → $16,000)
#   - PATRONES_DESCARTE ampliados: slogans cross-tienda, palabras sueltas de folleto
#   - Marcas-logo de envase descartadas (Golden Hills, etc.)

import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from .catalogo_productos import buscar_categoria

logger = logging.getLogger(__name__)


# --------------- Modelos de datos ---------------

@dataclass
class EntidadExtraida:
    tipo:       str                     # PRECIO | PRECIO_ANTERIOR | AHORRO | PROMO |
                                        # EVENTO_PROMO | PRODUCTO | ATRIBUTO | DESCARTE
    texto_raw:  str
    texto_norm: str
    valor:      Optional[float] = None  # Valor numérico (precios, ahorros)
    confianza:  float = 0.0
    bbox:       dict = field(default_factory=dict)
    categoria:  str = ""                # Categoría del catálogo (PRODUCTO/ATRIBUTO)

    def __str__(self):
        val = f" → ${self.valor:,.2f}" if self.valor else ""
        return f"[{self.tipo}] '{self.texto_norm}'{val}"


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

    @property
    def total_entidades(self):
        return (len(self.productos) + len(self.precios) + len(self.precios_anteriores) +
                len(self.ahorros) + len(self.promos) + len(self.eventos_promo) +
                len(self.atributos))

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

    # --------------- PROMOCIONES ---------------
    PATRONES_PROMO = [
        re.compile(r"\d+\s*[xX×]\s*(?:\$\s*)?\d+", re.IGNORECASE),
        re.compile(r"\d+\s*%\s*(?:off|desc(?:uento)?|de\s+desc)?", re.IGNORECASE),
        re.compile(r"\$\s*\d+\s*por\s*cada\s*\$\s*\d+", re.IGNORECASE),
        re.compile(r"\b(?:te\s+regalamos|lleva|paga|gratis|bonificaci[oó]n)\b", re.IGNORECASE),
        re.compile(r"precio\s+(?:ya\s+)?con\s+(?:la\s+)?promo", re.IGNORECASE),
        re.compile(r"\b(?:hasta|descuento\s+de)\s+\d+\s*%", re.IGNORECASE),
        # "compra uno y llévate el segundo a mitad de precio"
        re.compile(r"mitad\s+de\s+precio", re.IGNORECASE),
        re.compile(r"segunda?\s+a\s+mitad", re.IGNORECASE),
        re.compile(r"compra\s+(?:uno|una)\s+y\s+ll[eé]vate", re.IGNORECASE),
    ]

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
        # 1-2 caracteres
        re.compile(r"^.{1,2}$"),
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

        # ── Slogans y frases de campaña cross-tienda ───────────────────────────
        re.compile(
            r"^(?:i¡)?(?:consiente|encuentra|renueva|aprovecha|celebra|"
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

        # ── Slogans específicos de tienda detectados en análisis ───────────────
        re.compile(
            r"^(?:"
            r"en\s+tienda\s*y\s+en\s+l[ií]nea|s[oó]lo\s+en\s+tienda|"
            r"en\s+tienda\s*\+\s*en\s*l[ií]nea|en\s+tienda\s+y\s+en\s*l[ií]nea|"
            r"en\s*tienda[y\s]+en\s+l[ií]nea|"
            r"en\s+tienda|en\s+linea|en\s+l[ií]nea|"       # solos sin contexto
            r"enlinea|enl[ií]nea|"                          # fusiones OCR costco
            r"s[oó]loenlinea|s[oó]loen\s+tienda|s[oó]loen\s+l[ií]nea|"
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

        for bloque in datos_pagina["bloques"]:
            texto_raw = bloque["texto"]
            confianza = bloque["confianza"]
            bbox      = bloque.get("bbox", {})

            if confianza < self.confianza_minima:
                continue

            texto_limpio = self._limpiar_texto(texto_raw)
            if not texto_limpio:
                continue

            entidad = self._clasificar(texto_limpio, texto_raw, confianza, bbox)

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

    def _clasificar(self, texto, texto_raw, confianza, bbox) -> EntidadExtraida:

        # 1. Descarte rápido
        if self._es_descarte(texto):
            return EntidadExtraida("DESCARTE", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 2. Precio anterior ("Antes: $X")
        valor_ant = self._extraer_precio_anterior(texto)
        if valor_ant is not None:
            return EntidadExtraida("PRECIO_ANTERIOR", texto_raw, texto,
                                   valor=valor_ant, confianza=confianza, bbox=bbox)

        # 3. Ahorro ("Ahorras $X")
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

        # 6. Promoción (2x1, 30% OFF, compra uno y llévate…)
        if self._es_promo(texto):
            return EntidadExtraida("PROMO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 7. Catálogo → PRODUCTO o ATRIBUTO
        en_catalogo, categoria, es_atributo = buscar_categoria(texto)
        if en_catalogo:
            tipo = "ATRIBUTO" if es_atributo else "PRODUCTO"
            return EntidadExtraida(tipo, texto_raw, texto,
                                   confianza=confianza, bbox=bbox, categoria=categoria)

        # 8. Heurística de producto
        if self._es_probable_producto(texto):
            return EntidadExtraida("PRODUCTO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 9. Por defecto
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
        match = self.PATRON_PRECIO_ANTERIOR.search(texto)
        if not match:
            return None
        return self._parsear_numero(match.group(1))

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
        # Ignorar condiciones de compra ("En compras desde $500")
        if re.match(r"^\s*(?:en\s+compras?|en\s+toda|válido\s+en)", texto,
                    re.IGNORECASE):
            return None
        # Precio con $ OCR corrupto (s/8 + dígitos): fresko y similares
        m_ocr = self.PATRON_PRECIO_OCR_CORRUPTO.match(texto)
        if m_ocr:
            try:
                return float(f"{m_ocr.group(1)}.{m_ocr.group(2)}")
            except ValueError:
                pass
        match = self.PATRON_PRECIO.search(texto)
        if not match:
            return None
        return self._parsear_numero(match.group(1))

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

    def _es_promo(self, texto: str) -> bool:
        for patron in self.PATRONES_PROMO:
            if patron.search(texto):
                return True
        return False

    def _es_probable_producto(self, texto: str) -> bool:
        if len(texto) < 4:
            return False
        texto_norm = texto.lstrip("'\"'")
        palabras = [p for p in texto_norm.split()
                    if len(p) >= 3 and
                    p.replace("é","e").replace("á","a").replace("ó","o")
                     .replace("í","i").replace("ú","u").replace("ñ","n").isalpha()]
        if not palabras:
            return False
        if self.KEYWORDS_PRODUCTO.search(texto):
            return True
        if texto_norm.isupper() and 4 <= len(texto_norm) <= 60:
            return True
        if len(palabras) == 1 and len(palabras[0]) >= 5:
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