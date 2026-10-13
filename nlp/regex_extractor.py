# Toma los bloques de texto del OCR y los clasifica en categorías:
#       PRECIO, PRECIO_ANTERIOR, AHORRO, PROMO, EVENTO_PROMO, PRODUCTO, ATRIBUTO, DESCARTE

import re
import math
import logging
from dataclasses import dataclass, field
from typing import Optional
from .catalogo_productos import buscar_categoria

"""
    Flujo de clasificación (orden de prioridad):
      1. Limpiar texto OCR
      2. ¿Es descarte?          --> DESCARTE
      3. ¿Es precio anterior?   --> PRECIO_ANTERIOR
      4. ¿Es ahorro?            --> AHORRO
      5. ¿Es evento promo?      --> EVENTO_PROMO
      6. ¿Es precio?            --> PRECIO
      7. ¿Es promoción?         --> PROMO
      8. ¿En catálogo?          --> PRODUCTO o ATRIBUTO
      9. ¿Heurística producto?  --> PRODUCTO
     10. Ninguno                --> DESCARTE
"""

# Resumen de las reglas mas relevantes
"""
1. DESCARTE (se evalúa primero, "elimina ruido antes de intentar clasificar")
- Bloques de 1-2 caracteres (excepto "2 dígitos puros", que podrían ser un precio sin centavos)
- Solo símbolos, URLs (www., .com/.mx/.org)
- Texto de vigencia/vencimiento y pie de página legal ("sujeto a...", "términos y condiciones")
- Nombres de tienda sueltos (Walmart, Soriana, Chedraui, Costco, etc.)
- Metadata de tallas y specs técnicas sueltas (GB, MHz, watts, pulgadas)
- Estados y abreviaturas geográficas de México
- Bancos/financiero (BBVA, Banamex, "meses sin intereses", "tarjetas participantes", montos "$X MN")
- Slogans de campaña genéricos ("consiente", "renueva", "aprovecha", "celebra"...)
- Condiciones de "meses sin intereses" (listas de categorías separadas por coma)
- Slogans propios de tienda ("en tienda y en línea", "sólo en tienda", "híper", "cashback", "precios bajos todos los días")
- Palabras sueltas típicas de folleto en mayúsculas ("desde", "oferta", "descuento", "vigente"...)
- Logos de marca de envase (ej. variantes OCR de "Golden Hills")
- Ruido OCR puro (consonantes sin vocales)
- Calendario de campaña (día de la semana + fecha, ej. "Sábado 30 de Mayo")
- "También en App/tienda/línea"
- Restricciones de compra ("máximo N kg por cliente", "aplican restricciones")
- Frases de marketing completas y específicas (no palabras sueltas genéricas, para no perder cobertura de producto)
- Regla genérica de respaldo: más del 40% de caracteres raros en el texto

1b. Condiciones de compra (antes de intentar precio): "en compras...", "compras mayores a $X" → DESCARTE

2. PRECIO_ANTERIOR
- Prefijos "antes:", "antos;" (typo de OCR), "precio anterior", como palabra completa ("desinfectantes 35pz" no cuenta)
- Patrón "DE $X A" (Soriana) → el primer monto es el anterior; no aplica a rangos con unidad ("de 180 gr a 220 gr")
- Tolera el "$" leído como * # s S ' { + y los centavos en superíndice pegados o ilegibles
- Devuelve todas las lecturas posibles del monto ("candidatos"); load elige la coherente con el precio actual

3. AHORRO
- Palabra "ahorra/ahorras" seguida de un monto (tolera "$" leído como "5" por el OCR)

4. PROMO
- Fuerte (no requiere que haya un precio real en la página): mecánicas tipo "NxM" (3x2), "$X por cada $Y", "mitad de precio", "compra uno y llévate", paquetes repetidos "1x$Y 3x$Z"
- Débil (sólo cuenta si la página ya tiene un precio real, para no capturar banners sueltos): "%", "off/descuento", "te regalamos/lleva/paga/gratis", "hasta X%"

5. EVENTO_PROMO (metadata de campaña, no mecánica de precio)
- Campañas mexicanas conocidas: Julio Regalado, Hot Sale, Buen Fin, Cyber Monday, Black Friday, Navidad, Día de las Madres/Niño/Reyes, Regreso a Clases, Semana Santa, Día de Muertos
- Etiquetas de oferta genéricas: "precio bajo/especial", "oferta especial/de temporada", "liquidación", "descuento exclusivo"

6. PRECIO (con símbolo $)
- "$" + número (miles/decimales), con prefijos "desde"/"a sólo" y sufijos "c/u"/"MXN"/"pesos"
- Caso especial: "$" leído corrupto por el OCR como "s"/"8"/"S" pegado a dígitos

7. PRECIO sin símbolo (fallback — sólo si hay contexto de precio cerca)
- Dígito espurio inicial (5/6/8/s/S confundido con "$") + resto del número, con o sin coma de miles/decimal
- Números sueltos con coma de miles (no ambiguo, no exige contexto)
- Números "pelones" de 2 a 5 dígitos, cada longitud con su propio nivel de exigencia de contexto (calibrado empíricamente contra el dataset manual — ver sources/nlp/04_cobertura_bare_digits_2_5.md)
- Contexto "fuerte" que valida estos casos: "a sólo", "de oferta", "antes", "ahorra(s)", "cada uno/a", "paquete", "c/u"
- Contexto de unidad (kg, ml, g, pza) — solo refuerza, nunca basta solo
- Exclusión: la palabra "puntos" (de lealtad) cerca anula cualquier contexto de precio
- Nunca interpreta un año (2020-2029) como precio

8. Precios fusionados en 2 bloques (pre-paso especial, antes de todo lo demás)
- Un entero de 1-2 dígitos + un bloque más chico de 2 dígitos justo a su derecha (superíndice) → se arman como un solo precio decimal

9. PRODUCTO / ATRIBUTO por catálogo
- Consulta catalogo_productos.buscar_categoria() — catálogo externo de nombres/categorías conocidas (vive en otro archivo, no en este módulo)

10. PRODUCTO por heurística (si no está en catálogo)
- Palabras clave de producto (lámpara, aceite, detergente, leche, kg, ml, pza, etc.)
- Texto todo en MAYÚSCULAS (4-60 caracteres)
- Palabra única de 4+ letras
- Frase de 2+ palabras (4-80 caracteres)

"""
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
    # PRECIO_ANTERIOR: lecturas posibles del monto, la primera = valor. Load elige la
    # que sea coherente con el precio actual emparejado (ver _candidatos_precio_anterior)
    candidatos: list[float] = field(default_factory=list)

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

# clase prnicpal que verifica entidades
# VERBOSE --> permite comentarios y saltos de linea en el patron
# IGNORECASE --> ignora mayusculas/minusculas
class RegexExtractor:
    
    # -------------------------- PRECIO ANTERIOR --------------------------
    # "Antes: $699" / "Antos; $3495" / "precio anterior $1,200" / "'Antes:$2495"
    # El OCR lee el "$" como * # s S ' { + (los 5/8 sin simbolo se resuelven en
    # _candidatos_precio_anterior). \b evita "desinfectANTES 35pz", "endulzANTES".
    PATRON_PRECIO_ANTERIOR = re.compile(
        r"""
        \b(?:ant[eo]s|precio\s+anterior)\b\s*[;:,.]?\s*
        (?P<simbolo>[\$*\#sS'{+]{0,2})\s*
        (?P<numero>\d[\d,\.]*\d|\d)
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # -------------------------- AHORRO --------------------------
    # "Ahorras $32.90" / "Ahorra $49.90" / "Ahorras 5755.00" (OCR $ --> 5)
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

    # -------------------------- PRECIO --------------------------
    # ya tiene igual prefijos DESDE/A sólo/desde:/a solo: y sufijo C/U
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
    # s9989 --> $99.89 | 82990 --> $29.90 | s15790 --> $157.90
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

    # "DE $22,990⁰⁰ A" (Soriana): el primer precio es el anterior, el actual va en otro bloque.
    # Se detecta ANTES del PATRON_PRECIO normal para no extraer solo el primer número.
    # Los centavos en superindice llegan pegados ("22,99000") o como basura (@ * " oo u).
    # El "A" no puede ir seguido de unidad: "de 180 gr a 220 gr" no es precio.
    PATRON_DE_A = re.compile(
        r"""
        ^DE\s*
        (?P<simbolo>[\$*\#sS'{+t]{0,2})\s*
        (?P<numero>\d[\d,\.]*\d)        # 2+ digitos: "de 2 a 3X" no es precio
        [@*"'°oOuU]*                    # superindice ilegible
        \s*[,.;:]?\s*
        A\b(?!\s*\d)
        """,
        re.VERBOSE | re.IGNORECASE
    )

    # -------------------------- PRECIO SIN SIMBOLO ("$" perdido o mal leido por el OCR) -----------------------------------------
    
    # Rescatar "$"" confundido 5, 6, 8, s o S.
    PATRON_DIGITO_ESPURIO = re.compile(r"^[568sS](\d{3})(?:c/u|c\.u\.|[a-zA-Z]{1,4})?$")

    # Regla A-cu: digito espurio + entero + sufijo "c/u" que el OCR lee "clu"/"cIu"/"c1u",
    # pegado o con un espacio ("5949clu" -> $949, "555 clu" -> $55, "519clu" -> $19).
    # Confirmado 11-oct-2026 en Walmart dev (413647/413251): 17/17 bloques con el monto del GT,
    # ninguno con otro monto. El sufijo es contexto fuerte por si solo (igual que "c/u" bien
    # leido en la Regla A), por eso no exige contexto externo. NO acepta 4 digitos tras el
    # espurio: "5995c/u" podria ser $59.95 c/u sin "$" y no hay evidencia de precios enteros
    # >= $1,000 con c/u.
    PATRON_DIGITO_ESPURIO_CU = re.compile(r"^[568sS](\d{2,3})\s?(?:c/u|c\.u\.?|c[lI1]u)$")

    # Desempate por la resta "Antes $A" - "Ahorra $B" (Walmart pone Ahora / Antes / Ahorra en
    # la misma casilla). Un bloque "5454" se lee como $54.54 (Regla B-4) o como "$" mal leido
    # + $454 (Regla A); si la casilla dice "Antes $699" y "Ahorra $245", el precio es 454.
    # Confirmado 11-oct-2026 en Walmart dev 413647: 28/28 bloques con antes y ahorro cerca
    # cuadran con la resta y con el GT. Solo se acepta la lectura que cuadra EXACTA con la resta,
    # asi que no cambia nada donde no hay par antes/ahorro.
    PATRON_DIGITO_ESPURIO_ENTERO = re.compile(r"^[568sS](\d{2,4})$")


    # Rescatar precio / kg --> "824.95k6" -> $24.95/kg "kg" con "k6")
    PATRON_DIGITO_ESPURIO_DECIMAL = re.compile(r"^[568sS](\d{1,3}[.,]\d{2})[a-zA-Z0-9]{0,4}$")

    # Rescata miles con $  al inicio (ej. "58,999" -> $8,999, "53,999" -> $3,999)
    #(ej. "58,999" -> $8,999, "53,999" -> $3,999 -- verificado contra la imagen real: el "5" inicial
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
    # GAP_HORIZONTAL_MIN/MAX de _detectar_precios_fusionados. Es el ancho con el que
    # se calibraron esos valores (default historico), NO tiene que coincidir con
    # preprocessor.ANCHO_OBJETIVO_DEFAULT (1800px desde oct-2026): factor_escala ajusta
    # los umbrales al ancho real de cada pagina. No cambiar sin recalibrar.
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
        # Bonificacion "$10 por cada $50" con el "$" leido s/5/8/{ (12-oct-2026): el patron de
        # arriba exige "$" literal y el bloque caia en PATRON_PRECIO, que se quedaba con el
        # monto de compra (la_comer "s25 por cada $100" -> $100, "510 porcada $50" -> $50,
        # "8250 Por CADA"; HEB "Por cada $1OO de compra" -> $100). El monto es la condicion o
        # el monedero de la promocion, nunca el precio de un producto. "cada uno/a" (contexto
        # fuerte de precio, "$15 cada uno") no entra: exige "por cada" + monto o fin de bloque.
        re.compile(r"(?:^|(?<=\s))[\$sS58{]?\s*\d{1,4}\s*por\s*cada\b(?!\s+un[oa]\b)", re.IGNORECASE),
        re.compile(r"\bpor\s*cada\s*[\$sS]\s*[\dOoIil]{2,}", re.IGNORECASE),
    ]

    PATRONES_PROMO_DEBIL = [
        re.compile(r"\d+\s*%\s*(?:off|desc(?:uento)?|de\s+desc)?", re.IGNORECASE),
        re.compile(r"\b(?:te\s+regalamos|lleva|paga|gratis|bonificaci[oó]n)\b", re.IGNORECASE),
        re.compile(r"precio\s+(?:ya\s+)?con\s+(?:la\s+)?promo", re.IGNORECASE),
        re.compile(r"\b(?:hasta|descuento\s+de)\s+\d+\s*%", re.IGNORECASE),
    ]

    # Compatibilidad: union de ambos grupos, usada donde no importa la distincion
    PATRONES_PROMO = PATRONES_PROMO_FUERTE + PATRONES_PROMO_DEBIL

    # -------------------------- EVENTOS PROMOCIONALES --------------------------
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

# -------------------------- DESCARTE --------------------------
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

        # -- Estados y geografía de México --------------------------------------
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

        # -- Financiero / bancario -----------------------------------------------
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

        # -- Slogans y frases de campaña cross-tienda ---------------------------
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

        # -- Condiciones MSI: lista de categorias separadas por coma ------------
        # "En Electrónica, Cómputo, Fotografía, Videojuegos..." -- condicion de
        # letra chica de "Meses Sin Intereses", no un nombre de producto.
        re.compile(
            r"^en\s+\w+(?:\s+\w+)*(?:\s*,\s*\w+(?:\s+\w+)*){2,}",
            re.IGNORECASE
        ),

        # -- Slogans específicos de tienda detectados en análisis ---------------
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
            r"s[oó]lqen\s+l[ií]nea|s[oó]lqen\s+linea|"     # ERROR #19: Q-->O por OCR
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

        # -- Palabras sueltas de folleto que pasan isupper() --------------------
        # Bordes [\W_]* (12-oct-2026, mismo cierre que los rotulos de casilla): el OCR pega
        # puntuacion o corchetes a la palabra y el bloque se escapaba como PRODUCTO:
        # waldos "Desde:" (62 bloques fuera del holdout), la_comer "DESDE." / "DESDE ," /
        # "[DESDE ,", merco "'DESCUENTO" (153). "gratis" y "bonificacion" conservan el anclaje
        # exacto: con puntuacion ("GRATIS)", "(GRATIS") hoy son PROMO (PATRONES_PROMO_DEBIL) y
        # deben seguir siendolo.
        re.compile(
            r"^[\W_]*(?:desde|ahora|antes|sale|rebajado|h[ií]per|kilo|kilos|"
            r"oferta|ofertas|promocion|promoci[oó]n|exclusivo|exclusiva|"
            r"descuento|descuentos|ahorro|ahorros|vigente|vigentes|"
            r"temporada|liquidaci[oó]n|especial)[\W_]*$|"
            r"^(?:gratis|bonificaci[oó]n)$",
            re.IGNORECASE
        ),

        # -- Marcas-logo de envase (fresko / alsuper) ---------------------------
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

        # -- Header repetido de folleto (fresko Golden Hills) -----------------
        re.compile(
            r"^(?:un\s+brillo(?:\s+de\s+calidad)?|de\s+calidad|decalidad)$",
            re.IGNORECASE
        ),

        # -- Textos de portada / cierre de folleto ----------------------------
        re.compile(
            r"^(?:como\s+te\s+gusta|exploralo\s+en|s[ií]guenos\s+en|"
            r"libera|el\s+potencial|de\s+tu\s+suv|"
            r"consulte\s+a\s+su\s+m[eé]dico|ver\s+bien\s+es\s+importante)$",
            re.IGNORECASE
        ),

        # -- Slogan "precio bajo" de Bodega Aurrera ------------------------------
        # El OCR nunca lee "precio bodega" limpio en este folleto -- variantes
        # garbled confirmadas: "PREçIQ"/"BGDEGA", "PREçO"/"DEGA", "PREçI".
        re.compile(r"^(?:precio\s*bodega|pre[cç][ií]?[oq]?|bgdega|dega)$", re.IGNORECASE),

        # -- Ruido OCR puro (consonantes sin vocales) ---------------------------
        re.compile(
            r"^(?:[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}\s+){1,3}"
            r"[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}$"
        ),

        # -- Calendario de campana promocional (dia de la semana + fecha) --------
        # Agregado 23-ago-2026: analisis de productos_canonicos vs Postgres real
        # encontro "Martes y Miercoles" (172), "Sabado 30 de Mayo"/"Viernes 29 de
        # Mayo"/etc. (34 c/u, un bloque repetido por pagina de un calendario de
        # ofertas por dia) clasificados como PRODUCTO. Estructural: dia(s) de la
        # semana solos o seguidos de "N de <mes>".
        re.compile(
            r"^(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)"
            r"(?:\s+y\s+(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo))?"
            r"(?:\s+\d{1,2}\s*\w{0,3}\s*de\s+\w+)?\.?$",
            re.IGNORECASE
        ),

        # -- "Tambien en la App/tienda/linea" ------------------------------------
        # Agregado 23-ago-2026: "Tambien En: App"/"Appc"/"Appi" (264 combinado)
        # no matcheaba los patrones existentes de "en tienda"/"en linea" (linea
        # 454) porque empieza con "tambien", no con "en".
        re.compile(r"^tambi[eé]n\s*en\b.{0,15}$", re.IGNORECASE),

        # -- Limite de compra / restricciones de promocion ----------------------
        # Agregado 23-ago-2026: "Maximo 10 Kg. Por Cliente" (90), "Aplican
        # Restricciones" (51). Distinto del pie de pagina legal generico (linea
        # 348) porque esos exigen "sujeto a"/"terminos y condiciones" -- este es
        # el patron especifico "Maximo N ... por cliente".
        re.compile(
            r"^m[aá]ximo\s+\d+.{0,20}por\s+cliente\.?$|"
            r"^aplican\s+restricciones?[;:.]?$",
            re.IGNORECASE
        ),

        # -- Slogans (frases de marketing completas, no palabras sueltas) --------
        # Agregado 23-ago-2026, RESTRINGIDO tras medir regresion contra
        # evaluar_nlp.py: la primera version de este cambio tambien incluia
        # palabras genericas sueltas ("mimarca", "variedad", "compra",
        # "congelado", "super", "producto", "pieza"/"kilo"/"gramos" solos) que
        # bajaron PROD global de 75.2%->73.8% -- resulto que el OCR frecuentemente
        # separa esas palabras del resto de un producto real en su propio bloque
        # ("Frijol pinto Mimarca 900 gramos" -> 3 bloques OCR: "Frijol pinto" +
        # "Mimarca" + "900 gramos"), y la evaluacion cuenta cobertura de tokens
        # en CUALQUIER bloque PRODUCTO de la pagina -- descartar el bloque
        # "Mimarca" o "900 gramos" aislado bajaba la cobertura del producto
        # real aunque el resto se siguiera detectando bien. Se dejaron SOLO las
        # frases de varias palabras que son estructuralmente slogans de
        # marketing (nunca aparecen como fragmento de un nombre de producto).
        re.compile(
            # "te regala" (con variantes OCR) vive ahora en el patron de lealtad, mas abajo
            r"^(?:del\s+ahorro|"
            r"combina\s+como\s+quieras|los\s+m[aá]s\s+baratos\s+del\s+mercado|"
            r"hasta\s+ac?otar\s+existencias|im[aá]genes\s+ilustrativas|"
            r"al\s+precio\s+m[aá]s\s+bajo\s+siempre)\.?$",
            re.IGNORECASE
        ),

        # -- Rotulos de casilla de precio (bloque que es SOLO el rotulo) --------
        # Agregado 11-oct-2026 (evaluador dev, base 20261011_205930): el OCR separa el
        # rotulo de su precio y _es_probable_producto lo aceptaba como PRODUCTO; luego la
        # asociacion por cercania lo prefiere al nombre real (que suele ir debajo) y el
        # normalizador lo vuelve un producto inventado. En dev: Walmart "todos los dias"
        # (de "Precio bajo todos los dias", 30 bloques), Chedraui "Apartalo con" (23),
        # S-Mart/Soriana Mercado "a solo:"/"asolo:"/"solo:" (16), HEB "AHORRA (MAS)"/
        # "COMPRA" (32), S-Mart "De oferta:" (9), Bodega Aurrera "Aurrera"/"Aurrerao"
        # (marca de tienda sola, 19), "cada una", "Llevate", "Demo", "Ahara" (OCR de Ahora).
        # Anclado a todo el bloque y SIN digitos: un bloque con precio ("a solo $49",
        # "Ahorra $20") nunca entra aqui, asi que no cambia ninguna regla de precio
        # (_hay_contexto_precio y _hay_producto_cerca leen los bloques crudos, no esto).
        # Variantes OCR (11-oct-2026, dashboard de produccion tras c1a84b2): Chedraui
        # "Apärtalo con", "Apartalorcon", "Apartalo Cön/Ccn/cod/coi", "Apjrtalo con",
        # "Aprrtaloicon", "Apartallo con"; Walmart "todos los dlas/diss", "todoslosdlas",
        # "stodos los días" (cola de "bajos") y "todos los días_" (el "_" no es \W).
        # Sigue sin admitir digitos ni texto despues del rotulo: "TODOS LOS DESODORANTES",
        # "Todos los dips", "Apartado", "Aparta tus juguetes" o "Gabapertina" no entran.
        # Unica excepcion a "sin digitos": Chedraui "Apártalo con | $629.90" debajo de
        # "$6,299" (folleto 428354 pag 14) es el ANTICIPO de apartado (10%), no el precio
        # del producto; con el monto pegado al rotulo ("Apartalo Con$1,49950",
        # "Apártalo Conls83950", "Apartalo con829950") el bloque entero se descarta en vez
        # de leerse como precio. Solo para este rotulo: "a solo $149" sigue siendo PRECIO.
        re.compile(
            r"^\W*(?:"
            r"ap[a-zà-öø-ÿ]{0,2}rt[a-zà-öø-ÿ]{0,2}l{1,2}[aáoóöò]?[\s|]*[ri]?\s*c[oóöòceu][nudihr]?"
            r"(?:[\s|\]\[!l]*[s$]?[\s|\]l]*\d[\d,.\s]*)?|"
            r"(?:precios?\s*bajos?\s*)?s?todos\s*los\s*d(?:[iíìl1][aáàs]|l?[aá])s|precio\s*bajo|"
            r"[0a]?\s*s[oó]lo|as[ií]\s*lo|"
            r"d[ea]\s+of[ec]r?t[ae]r?|"
            r"ahorr[ao]s?(?:\s+m[aá]s)?|ahara|"
            # "cada" solo (Soriana "CADA", HEB "cada": 120 bloques) y "Llévate" con "y" pegada
            # o cola OCR ("YLLÉVATE", "'Llevatel", "Llevate más", "LLÉVATELA"), 12-oct-2026
            r"compra|cada(?:\s+un[oa])?|y?\s*ll[eé]vate(?:l|la|lo)?(?:\s+m[aá]s)?|demo|"
            r"aurrer[aá][a-z_@]?"
            r")[\W_]*$",
            re.IGNORECASE
        ),

        # -- Rotulos de promocion/condicion/financiamiento/lealtad/servicio/vigencia ------
        # Agregado 12-oct-2026 (BI: 1,662 registros del dashboard de produccion, 5.8%, con una
        # promo como nombre de producto, todos heuristicos; ver docs/bi/consultas/
        # promos_como_producto*.sql). El OCR parte la frase ("Meses sin intereses",
        # "Te regala 300 puntos", "SÚPER PRECIAZO", "Llévate GRATIS 1 Pieza Adicional") en
        # bloques sueltos; los descartes de arriba exigen la frase completa y exacta, asi que
        # cada pedazo pasaba _es_probable_producto y la asociacion por cercania lo tomaba como
        # nombre. Fuera del holdout (bloques PRODUCTO): merco "SÚPER" 1,815 y "PRECIAZO" ~1,400
        # (con corchetes y mayusculas mezcladas), Soriana "Puntos"/"Puhtos"/"300 puntos" ~800,
        # "Intereses"/"Intcrcscs"/"Interescs" ~450, "Meses sln"/"Heses sin" ~150, "Teregala"
        # ~130, casa_ley "Adicional(es)" ~250, chedraui "Envío" 119 y "(no incluye producto de
        # ambientación)" ~80, merco "ELIGES"/"[COMPRANDO", alsuper "A ESCOGER", waldos
        # "Exclusivo en waldos com mx", heb "12 al 18 de Junio de 2026"...
        # Mismo criterio que los rotulos de casilla: anclado al bloque COMPLETO y sin texto
        # adicional, asi que un nombre real que contiene la palabra no entra: "Súper Value"
        # (marca de S-Mart), "Hasta 35 horas de batería", "Incluye 2 juegos Astro Bot",
        # "Crema Facial Protección", "Ellmina puntos de presión", "Talla: 0 - 6 meses".
        # Digitos solo donde el numero es parte del rotulo: plazo ("12 MESES"), puntos de
        # lealtad ("'300 puntos") y fechas de vigencia ("Del 03 al 21 de junio 2026").
        # No toca reglas de precio: _hay_contexto_precio y _hay_producto_cerca leen los
        # bloques crudos con _es_probable_producto, no con este descarte.
        re.compile(
            r"^[\W_]*(?:"
            # financiamiento: fragmentos de "meses sin intereses" y plazos
            r"(?:(?:\d{1,2}\s*)?(?:m[eéc]s(?:[eéc]s)?|hes[eé]s)\s*(?:s[iíl1][nhm]|de)?\s*)?"
            r"(?:s[iíl1]n\s*)?i{1,2}nt[eéc]r[eéc]s[eéco]s|"
            r"(?:\d{1,2}\s*)?(?:m[eéc]s(?:[eéc]s)?|hes[eé]s)(?:\s*(?:s[iíl1][nhm]|de))?|"
            r"(?:en\s+\d{1,2}\s+)?quincenas?|quincenal|(?:en\s+)?un\s+s[oó]lo\s+pago|"
            # lealtad: puntos, "te regala", bonificacion, monedero, ticket
            r"(?:\d{1,4}\s*)?p[uú][nh]tos?|"
            r"todas\s+tus\s+compras\s+te\s+dan\s+puntos\w?|"
            r"[t7g][eoc]\s*regal[aà][lr]?|"
            # ("de bonificación" no entra: es PROMO por PATRONES_PROMO_DEBIL y debe seguir siendolo)
            r"(?:te\s*)?bonificamos\s*(?:en\s*tu|t)?|"
            r"(?:o\s*|(?:en\s*)?tu\s*)?monedero(?:\s+electr[oóá]nico)?|"
            r"t[il1]cke?ts?(?:\s+d[eø]\s+compra)?|"
            # precio generico de casilla
            r"(?:s[uú]per\s*)?p{1,2}r?[a-z]?[eé]?c[iíl1]?a[z2]os?|s[uú]per|"
            r"hasta|multi\s*ahorro|promos?(?:\s+ahorro)?|"
            r"\d?prec[iíì]?[oóò]s?(?:\s+re[gq]ular)?|"
            # condicion de compra
            r"adicional(?:es|e|s|os|ea)?|eliges|comprando|(?:a\s*)?escoge[rb]|"
            r"exclusiv[oa]s?\s*(?:(?:en|con)\s*(?:l[ií]nea|t?[if]ienda|"
            r"\w*\W?\s*co[mr]n?\W?\s*[mr]x(?:\s*y\s*app)?)?)?|"
            r"(?:no\s*)?incluyen?s?(?:\s*productos?(?:\s*de\s*ambientaci[oó]n)?|\s*rin(?:es)?)?|"
            # colas sin digitos ni "$": "Aplica ... Mínimo de compra $5,000.00" (chedraui) es un
            # monto minimo de compra y hoy es PRECIO; queda fuera a proposito (regla de precio)
            r"de\s*compra(?:\s+(?:en|a)\b[^\d$]*)?|"
            r"(?:\d?precio\s+|s[oó]lo\s+|no\s+)?apl[ií]ca(?:n|r[aá])?(?:\s+[^\d\s$][^\d$]*)?|"
            r"(?:aplica\s+en\s+el\s+de\s+)?(?:menor\s+)?pr[eéc]cio\s+qu[eéc]\s+[eéc]l\s*"
            r"(?:producto\s+)?de\s+compra|"
            # servicio
            # ("Envío gratis" no entra: es PROMO por "gratis")
            r"(?:incluye\s+|\d\s*a[ñn]o\s+de\s+|a[ñn]o\s+de\s+)?env[ií]os?|"
            r"(?:haz\s+tu\s+)?recargas?(?:\s+tiempo\s+aire)?|"
            r"(?:al\s+extender\s+)?(?:tu\s+)?garant[ií]a(?:\s+extendida)?|"
            r"(?:\d{1,2}\s+)?(?:meses\s+de\s+|seguro\s+de\s+)?protecci[oó]n(?:\s+para\s+ni[ñh]o)?|"
            r"(?:\d{1,2}\s+meses\s+de\s+)?suscripci[oó]n(?:\s+online)?|"
            # vigencia "Del 03 al 21 de junio 2026" (el patron de arriba exige "del N de")
            r"(?:del?\s*)?\d{1,2}\s+al\s+\d{1,2}\s+de\s+"
            r"(?:ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic)[a-z]*"
            r"(?:\s+(?:de|del)?\s*\d{4})?"
            r")[\W_]*$",
            re.IGNORECASE
        ),

        # -- Mensualidad "N MSI | $X" (bloque que es SOLO el rotulo y su monto) -----------
        # Agregado 12-oct-2026 (evaluador dev, base 20261012_093114_1838425): en la etiqueta
        # de la casilla de Chedraui, bajo el precio grande, van "9 MSI | $777.22" y
        # "12 MSI | $582.92": el monto es la MENSUALIDAD (precio/N), no el precio. Fuera del
        # holdout, ~480 bloques asi se leian como PRECIO, todos Chedraui y todos con la forma
        # rotulo + monto: "9MSI|$1,44433)", "(12MsI/$70750", "I2MSI | 51,58292", "MSI | $34944",
        # "9 MSI /81,221"" (el N se lee 9/12/15/I2/l2/J2/i2/(g, o se pierde). El rotulo solo
        # ("9 MSI", "(12MSI") tambien entra: hoy "9 MSI" pasaba como PRODUCTO.
        # Anclado al inicio: un precio real ANTES de "MSI" ("$5,999 o 12 MSI de $499.92")
        # no entra y conserva el $5,999. Despues del rotulo no admite palabras (2+ letras
        # seguidas, salvo el conector "de"): "MSI aplican pagando con Paypal", "+6 MSI con",
        # "MSI GF63" (marca de laptops) no entran; tampoco una letra pegada al rotulo
        # ("mslo", Soriana Mercado 430263). El monto en un bloque aparte, a la
        # derecha del rotulo, lo cubre _detectar_montos_de_rotulo.
        # Sin N delante (QA 12-oct-2026) la tolerancia OCR abriria la puerta a modelos y
        # promos ("M51 $4,999" = Galaxy M51, "M5i $2,499", "MSl 2x$50"): ahi se exige "MS"
        # en mayusculas literal + I/l/1 (no seguido de letra o digito) y, si hay monto, el
        # separador "|", "/" o "[" de la etiqueta. Fuera del holdout los unicos casos sin N
        # son "MSI | $34944" y "MSI| $53322" y ambos siguen entrando.
        re.compile(
            r"^\W*(?:"
            r"(?:\d{1,2}|[iIlJ][2589]|[iIl1][5S]|(?-i:[gI]))\s*"
            r"M\W?[sS5]\W?[iIl1|]{1,2}(?![a-zà-öø-ÿ])"
            r"|(?-i:MS[Il1])(?![\wà-öø-ÿ])\s*(?:[|/\[]|$)"
            r")(?:\s*de\b)?"
            r"(?!.*[a-zà-öø-ÿ]{2}).*$",
            re.IGNORECASE
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
        # 'o' minúscula entre coma de miles y dígitos: $16,o00 --> $16,000
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

# -------------------------------------- Método principal --------------------------------------

    # Procesa una sola pagina de OCR (diccionario con "imagen" y "bloques") y devuelve un objeto ResultadoPagina
    def procesar_pagina(self, datos_pagina: dict) -> ResultadoPagina:
        resultado = ResultadoPagina(imagen=datos_pagina["imagen"])
        bloques_pagina = datos_pagina["bloques"]  # contexto espacial para precios sin simbolo

        # Ajuste de escala: la distancia de contexto y los umbrales de fusion de precios
        ancho_pagina = datos_pagina.get("ancho_pagina") or self.ANCHO_REFERENCIA_UMBRALES
        factor_escala = ancho_pagina / self.ANCHO_REFERENCIA_UMBRALES

        hay_precio_en_pagina = self._pagina_tiene_precio(bloques_pagina, factor_escala)

        # Pre-paso: anticipo de apartado en su propio bloque, a la derecha del rotulo
        # "Apartalo con" (ver _detectar_anticipos_apartado). Se descarta entero.
        anticipos = self._detectar_anticipos_apartado(bloques_pagina, factor_escala)
        # Igual para la mensualidad: "9MSI" en un bloque y "$77722" a su derecha
        anticipos |= self._detectar_montos_de_rotulo(bloques_pagina, factor_escala,
                                                     self.PATRON_ROTULO_MSI)
        # Y los puntos, el plazo o la mensualidad junto a "puntos"/"meses sin intereses"
        anticipos |= self._detectar_cantidades_de_rotulo(bloques_pagina, factor_escala)

        # Pre-paso: precios repartidos en 2 bloques adyacentes (entero + centavos,
        # ver _detectar_precios_fusionados). Va ANTES del loop normal porque un
        # entero de 1-2 digitos nunca llegaria a clasificarse por si solo.
        bloques_consumidos = set()
        for bloque_entero, bloque_centavos, valor in self._detectar_precios_fusionados(bloques_pagina, factor_escala):
            if id(bloque_entero) in anticipos or id(bloque_centavos) in anticipos:
                continue
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

            if id(bloque) in anticipos:
                resultado.descartes.append(EntidadExtraida("DESCARTE", texto_raw, texto_limpio,
                                                           confianza=confianza, bbox=bbox))
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

# -------------------------- Procesamiento de JSON OCR --------------------------
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
        candidatos_ant = self._extraer_precio_anterior(texto)
        if candidatos_ant:
            return EntidadExtraida("PRECIO_ANTERIOR", texto_raw, texto,
                                   valor=candidatos_ant[0], confianza=confianza, bbox=bbox,
                                   candidatos=candidatos_ant)

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

        # 4b. Precio grande con el "$" leido 8/5/S que cuadra con la mensualidad o el anticipo
        # de su casilla (ver PATRON_PRECIO_ESPURIO_CUOTAS). Va antes del paso 5 porque
        # PATRON_PRECIO_OCR_CORRUPTO lee "S7995" como $79.95.
        precio_cuotas = self._precio_por_cuotas(texto, bbox, bloques_pagina, factor_escala)
        if precio_cuotas is not None:
            return EntidadExtraida("PRECIO", texto_raw, texto,
                                   valor=precio_cuotas, confianza=confianza, bbox=bbox)

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

        # 6. Catálogo --> PRODUCTO o ATRIBUTO
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

    def _extraer_precio_anterior(self, texto: str) -> list[float]:
        """Lecturas posibles del precio anterior, de la más a la menos probable ([] si no es)."""
        # Patrón estándar: "Antes: $X", "Antos; $X", "precio anterior $X"
        match = self.PATRON_PRECIO_ANTERIOR.search(texto)
        if match:
            candidatos = self._candidatos_precio_anterior(match.group("simbolo"), match.group("numero"))
            # El "Antes" va tachado (Chedraui) y la raya deforma el 1 inicial:
            # $10,995 --> "19,995", $1,395 --> "3,395", $1,845 --> "4,845". Va al final:
            # load solo la usa si la lectura literal no da un descuento creible
            numero = match.group("numero")
            if numero[0] in "3479":
                candidatos += [c for c in self._candidatos_precio_anterior("$", "1" + numero[1:])
                               if c not in candidatos]
            return candidatos
        match = self.PATRON_DE_A.match(texto)
        if match:
            # Soriana imprime los centavos siempre en superindice
            return self._candidatos_precio_anterior(match.group("simbolo"), match.group("numero"),
                                                    centavos_primero=True)
        return []

    # Montos que _parsear_numero lee sin ambigüedad: "2995", "1,955", "29.95", "12,990.00"
    _NUMERO_BIEN_FORMADO = re.compile(r"\d+|\d{1,3}(?:[,\.]\d{3})*(?:[,\.]\d{1,2})?")

    def _candidatos_precio_anterior(self, simbolo: str, numero: str,
                                    centavos_primero: bool = False) -> list[float]:
        """
        El OCR rompe el monto de formas que no se distinguen solo con el texto:
          "$10⁹⁰"     --> "81090"     ("$" leído como 8 + centavos pegados) = 10.90
          "$22,990⁰⁰" --> "522,99000"                                     = 22990.00
          "$5,490.00" --> "5,4900"    (coma de miles + centavos pegados)    = 5490.00
          "$29.95"    --> "529.95"                                        = 29.95
        Devuelve todas las lecturas razonables; load se queda con la que da un descuento
        creíble contra el precio actual (load.emparejar_precios_anteriores).
        """
        variantes = [numero]
        # Sin símbolo visible, un 5/8 inicial suele ser el "$" mal leído
        if not simbolo and numero[0] in "58" and len(re.sub(r"\D", "", numero)) >= 3:
            variantes.append(numero[1:].lstrip(",."))

        candidatos = []
        for v in variantes:
            digitos = re.sub(r"\D", "", v)
            tal_cual = self._parsear_numero(v) if self._NUMERO_BIEN_FORMADO.fullmatch(v) else None
            m = re.fullmatch(r"(\d{1,3}),(\d{3})(\d{1,2})", v)
            miles_y_centavos = float(f"{m[1]}{m[2]}.{m[3]}") if m else None
            # Centavos en superindice pegados: solo sin separadores; "$4,999" ya es
            # un monto bien escrito y partirlo en 49.99 solo sirve para cuadrar
            # contra un precio actual mal leido
            centavos = float(f"{digitos[:-2]}.{digitos[-2:]}") if len(digitos) >= 3 and v.isdigit() else None
            candidatos += ([miles_y_centavos, centavos, tal_cual] if centavos_primero
                           else [tal_cual, miles_y_centavos, centavos])

        unicos = []
        for c in candidatos:
            if c and c not in unicos:
                unicos.append(c)
        return unicos

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

        # Regla A-cu: "c/u" ilegible pegado al entero (ver constante)
        # Excepto 3 digitos terminados en "00": "6900 clu" es $69⁰⁰ c/u con los centavos en
        # superindice (Soriana Mercado 425730), no "$" mal leido + $900. Ningun caso de Walmart
        # que sustenta la regla termina en "00". Ese bloque sigue por las demas reglas.
        m = self.PATRON_DIGITO_ESPURIO_CU.match(texto)
        if m and not (len(m.group(1)) == 3 and m.group(1).endswith("00")):
            return self._parsear_numero(m.group(1))

        # Desempate B-4 / Regla A con la resta antes - ahorro de la casilla (ver constante).
        # Va antes de B-4 porque B-4 se queda con "5454" en cuanto hay un producto cerca.
        # Aqui SI se aceptan enteros terminados en "00": la lectura tiene que cuadrar exacta con
        # A - B de la misma casilla, y que un $69⁰⁰ coincida por azar con una resta de 900 es
        # mucho menos probable que el c/u suelto de la Regla A-cu.
        m = self.PATRON_DIGITO_ESPURIO_ENTERO.match(texto)
        if m:
            entero = float(m.group(1))
            if any(abs(entero - r) < 0.01
                   for r in self._restas_antes_ahorro(bbox, bloques_pagina, factor_escala)):
                return entero

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

    def _restas_antes_ahorro(self, bbox: dict, bloques_pagina: list[dict],
                             factor_escala: float = 1.0) -> set[float]:
        """
        Precios actuales que implica la casilla: A - B por cada "Antes $A" (con sus lecturas
        posibles) y cada "Ahorra $B" a menos de DISTANCIA_MAX_CONTEXTO_PRECIO del bbox.
        Vacio si falta alguno de los dos.
        """
        distancia_max = self.DISTANCIA_MAX_CONTEXTO_PRECIO * factor_escala
        antes, ahorros = [], []
        for otro in bloques_pagina:
            otro_bbox = otro.get("bbox")
            if not otro_bbox or otro_bbox is bbox:
                continue
            if self._distancia_bbox(bbox, otro_bbox) > distancia_max:
                continue
            texto_otro = self._limpiar_texto(otro.get("texto", ""))
            candidatos = self._extraer_precio_anterior(texto_otro)
            if candidatos:
                antes += candidatos
                continue
            ahorro = self._extraer_ahorro(texto_otro)
            if ahorro:
                ahorros.append(ahorro)
        return {round(a - b, 2) for a in antes for b in ahorros if a > b}

    # -- Precio grande confirmado por la mensualidad / el anticipo de la casilla --------------
    # Agregado 12-oct-2026 (evaluador dev, base 20261012_102745_7fad080). En la casilla de
    # Chedraui, bajo el precio grande, la etiqueta trae "9 MSI | $X" / "12 MSI | $Y" (precio/N)
    # y "Apartalo con $Z" (10% del precio, o $50 fijo). Cuando el OCR lee el "$" del precio
    # grande como 8/5/S, las reglas de arriba no saben si "82995c/u" es $2,995 o $29.95 c/u
    # (por eso la Regla A-cu no acepta 4 digitos) y leen "S7995" como $79.95. Aqui se elige
    # la lectura que cuadra con N x mensualidad o 10 x anticipo de la misma casilla.
    # Confirmado en chedraui 428354 p4 ("82995c/u": anticipo $299.50 y 9 x $332.78 -> $2,995),
    # p8 ("S7995": $799.50, 9 x $888.33, 12 x $666.25 -> $7,995) y 416057 p5/p8
    # ("85,990c/u" -> $5,990; "511,890c/" -> $11,890). Es el analogo de la resta
    # Antes - Ahorra de Walmart (_restas_antes_ahorro), con la misma distancia de casilla.
    # NO cubre a proposito el anticipo de $50: es el minimo fijo (juguetes de $429 o $929
    # en 428354 p15 lo traen igual), no el 10%, asi que no confirma nada.
    PATRON_PRECIO_ESPURIO_CUOTAS = re.compile(
        r"^(?P<espurio>[568sS])(?P<num>\d{1,3},\d{3}|\d{3,5})"
        r"\s?(?:c/u|c\.u\.?|c[lI1]u|cu|c/|u)?[\W_]?$"
    )
    # Rotulo de cuota con o sin monto pegado. N de la mensualidad con las variantes OCR del
    # patron de PATRONES_DESCARTE ("I2MSI" = 12, "l5" = 15, "(g" = 9); el anticipo es N = 10.
    PATRON_CUOTA_MSI = re.compile(
        r"^\W*(?P<n>\d{1,2}|[iIlJ][2589]|[iIl1][5S]|(?-i:g))\s*"
        r"M\W?[sS5]\W?[iIl1|]{1,2}(?![a-zà-öø-ÿ])(?P<monto>.*)$",
        re.IGNORECASE
    )
    PATRON_CUOTA_APARTADO = re.compile(
        r"^\W*ap[a-zà-öø-ÿ]{0,2}rt[a-zà-öø-ÿ]{0,2}l{1,2}[aáoóöò]?[\s|]*[ri]?\s*"
        r"c[oóöòceu][nudihr]?(?P<monto>.*)$",
        re.IGNORECASE
    )
    # Monto de la cuota: "$1,48950", "|$355", "858292" ("$" leido 8), "s99083", "1,655"
    PATRON_MONTO_CUOTA = re.compile(r"^[\W_lI]*?(?P<simbolo>[$sS]?)(?P<num>\d[\d,.]*)[\W_]*$")
    MESES_MSI = {3, 6, 9, 12, 15, 18, 24}
    ANTICIPO_MINIMO = 50.0

    def _lecturas_monto_cuota(self, texto: str) -> set[float]:
        """Lecturas posibles del monto: con centavos pegados, entero, y sin un "$" leido 8/5."""
        m = self.PATRON_MONTO_CUOTA.match(texto.strip())
        if not m:
            return set()
        num = m.group("num")
        digitos = re.sub(r"\D", "", num)
        variantes = [digitos]
        if not m.group("simbolo") and digitos[:1] in ("5", "8") and len(digitos) >= 4:
            variantes.append(digitos[1:])
        lecturas = set()
        for d in variantes:
            lecturas.add(int(d) / 100)
            if len(d) <= 3 or re.fullmatch(r"\d{1,2},\d{3}", num):
                lecturas.add(float(int(d)))
        return {v for v in lecturas if v > 0}

    def _cuotas_de_pagina(self, bloques_pagina: list[dict],
                          factor_escala: float) -> list[tuple[dict, int, str]]:
        """(bloque del rotulo, N, texto del monto) de cada mensualidad/anticipo de la pagina."""
        cuotas = []
        for b in bloques_pagina:
            if not b.get("bbox"):
                continue
            texto = self._limpiar_texto(b.get("texto", ""))
            m = self.PATRON_CUOTA_MSI.match(texto) or self.PATRON_CUOTA_APARTADO.match(texto)
            n = self._meses_de_rotulo(texto) if m else None
            if n and re.search(r"\d", m.group("monto")):
                cuotas.append((b, n, m.group("monto")))
        for patron in (self.PATRON_ROTULO_MSI, self.PATRON_ROTULO_APARTADO):
            for rotulo, monto in self._pares_rotulo_monto(bloques_pagina, factor_escala, patron):
                n = self._meses_de_rotulo(self._limpiar_texto(rotulo["texto"]))
                if n:
                    cuotas.append((rotulo, n, monto.get("texto", "")))
        return cuotas

    def _meses_de_rotulo(self, texto: str) -> Optional[int]:
        """N del rotulo de mensualidad (None si no se lee o no es un plazo usual); 10 si es anticipo."""
        m = self.PATRON_CUOTA_MSI.match(texto)
        if not m:
            return 10 if self.PATRON_CUOTA_APARTADO.match(texto) else None
        n_txt = m.group("n").translate(str.maketrans("iIlJSg", "111159"))
        return int(n_txt) if n_txt.isdigit() and int(n_txt) in self.MESES_MSI else None

    def _precio_por_cuotas(self, texto: str, bbox: dict, bloques_pagina: Optional[list[dict]],
                           factor_escala: float = 1.0) -> Optional[float]:
        """
        Lectura del precio grande "<$ leido 8/5/S><digitos>" que cuadra con N x mensualidad
        o 10 x anticipo de rotulos a menos de DISTANCIA_MAX_CONTEXTO_PRECIO, debajo del
        borde superior del precio y con traslape horizontal con el (la etiqueta de la casilla
        de al lado no cuenta). Tolerancia N x 1 centavo (la cuota se redondea al centavo).
        Gana la lectura con mas rotulos a favor; empate o ninguna -> None (siguen las reglas
        de siempre). Riesgo conocido, sin casos en el corpus (12-oct-2026): un precio sin
        rotulos legibles propios cuya casilla de abajo, alineada, trae una cuota que cuadra
        con el precio sin su primer digito. Exigir 2 rotulos a favor lo evitaria, pero
        perderia 32 de las 58 correcciones de produccion.
        """
        if not bbox or not bloques_pagina:
            return None
        m = self.PATRON_PRECIO_ESPURIO_CUOTAS.match(texto)
        if not m:
            return None
        num = m.group("num")
        resto = re.sub(r"\D", "", num)
        lecturas = {float(int(resto))}
        if "," not in num:
            lecturas.add(int(resto) / 100)
        if m.group("espurio").isdigit():  # o el 8/5/6 si es parte del precio
            completo = m.group("espurio") + resto
            lecturas |= {float(int(completo)), int(completo) / 100}

        distancia_max = self.DISTANCIA_MAX_CONTEXTO_PRECIO * factor_escala
        votos = {}
        for rotulo, n, texto_monto in self._cuotas_de_pagina(bloques_pagina, factor_escala):
            rb = rotulo["bbox"]
            if rb["y"] < bbox["y"] or self._distancia_bbox(bbox, rb) > distancia_max:
                continue
            if rb["x"] >= bbox["x"] + bbox["ancho"] or rb["x"] + rb["ancho"] <= bbox["x"]:
                continue  # sin traslape horizontal: es la etiqueta de la casilla de al lado
            implicitos = [n * v for v in self._lecturas_monto_cuota(texto_monto)
                          if not (n == 10 and v == self.ANTICIPO_MINIMO)]
            for lectura in {l for l in lecturas
                            if any(abs(l - p) <= n * 0.01 for p in implicitos)}:
                votos[lectura] = votos.get(lectura, 0) + 1
        if not votos:
            return None
        orden = sorted(votos.items(), key=lambda kv: -kv[1])
        if len(orden) > 1 and orden[0][1] == orden[1][1]:
            return None
        return orden[0][0]

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

    # Rotulo "Apartalo con" solo (sin monto pegado), con las mismas variantes OCR que el
    # patron de rotulos de casilla de PATRONES_DESCARTE.
    PATRON_ROTULO_APARTADO = re.compile(
        r"^\W*ap[a-zà-öø-ÿ]{0,2}rt[a-zà-öø-ÿ]{0,2}l{1,2}[aáoóöò]?[\s|]*[ri]?\s*"
        r"c[oóöòceu][nudihr]?[\W_]*$",
        re.IGNORECASE
    )
    # Separacion horizontal (px a ANCHO_REFERENCIA_UMBRALES) entre el borde derecho del
    # rotulo y el bloque del monto. Los valores estan a 1500 px de referencia: en Chedraui
    # (1200 px, factor 0.8) equivalen a -12..24 px, y lo medido fue -5..15 px.
    GAP_ANTICIPO_MIN = -15
    GAP_ANTICIPO_MAX = 30
    # El monto del anticipo es una linea de la etiqueta negra (alto <= ~2.2x el rotulo);
    # el precio grande de la casilla mide >= 3x el rotulo y ademas queda lejos.
    ALTO_MAX_ANTICIPO_VS_ROTULO = 2.5

    # Rotulo de mensualidad solo ("9MSI", "(12MsI|", "I2MSI", "9 MSI"), sin monto pegado.
    # Mismas variantes OCR que el patron "N MSI | $X" de PATRONES_DESCARTE.
    PATRON_ROTULO_MSI = re.compile(
        r"^\W*(?:(?:\d{1,2}|[iIlJ][2589]|[iIl1][5S]|(?-i:[gI]))\s*M\W?[sS5]\W?[iIl1]{1,2}"
        r"|(?-i:MS[Il1]))[\W_]*$",
        re.IGNORECASE
    )

    # -- Cantidad de un rotulo de lealtad o de meses sin intereses en un bloque aparte -------
    # Agregado 12-oct-2026 (evaluador dev, base 20261012_222448_2f616c3; BI: en produccion 109
    # de 325 registros "msi" tenian de valor un plazo 12/18/24 y 156 de 485 "puntos" eran
    # plazos o puntos). El OCR lee el rotulo y su cantidad en bloques separados, el rotulo ya
    # es DESCARTE (2f616c3) y la cantidad pasaba como PRECIO por B-2/B-4/C y se asociaba a
    # otro nombre vecino. Casos confirmados en imagen:
    #   - Soriana Hiper 416269 p2-p3: "CON | 50 | PUNTOS" en una linea bajo el precio por kilo
    #     -> "$50" con "Zanahoria"/"Ataulfo". El 50 son puntos.
    #   - Soriana Hiper 422326 p8/p14/p15 (insignia morada vertical): "Te regala | 436 |
    #     puntos | 18 | Meses sin | intereses | $193.89" -> "18" (plazo) y "819389"/"833317"
    #     (mensualidad leida sin "$") como precios.
    #   - Chedraui 416057 p7 / 428354 p7: "12" grande a la izquierda de "meses sin"/"intereses";
    #     Costco 424471 p2 "12 | Meses"; Waldos 421714 p1 "12" sobre "MESES DE".
    # Geometria: misma tolerancia que el anticipo (GAP_ANTICIPO_MIN/MAX), en la misma linea
    # (centros alineados) o apilado (traslape horizontal >= mitad del mas angosto).
    # Que se acepta (lo demas no cambia):
    #   - "puntos": cantidad SIN "$" a la izquierda o arriba, alto <= 2.5x el rotulo. El precio
    #     por kilo de Soriana que queda justo encima de "CON 50 PUNTOS" mide 4.5x y no entra.
    #   - "meses"/"intereses", a la izquierda o arriba: solo un entero que es un plazo usual
    #     (MESES_MSI), sin limite de alto (el plazo se imprime grande: 86-92 px contra 33-55).
    #     Un precio real arriba de la leyenda "Meses sin intereses" (Walmart, Chedraui) no es
    #     un plazo y no cambia; "$12" con simbolo tampoco.
    #   - "meses"/"intereses", a la derecha o abajo: la mensualidad (cualquier monto), con alto
    #     <= 2.5x el rotulo, como el anticipo, y solo si hay un plazo suelto a menos de
    #     DISTANCIA_MAX_CONTEXTO_PRECIO del rotulo (el "18" de la insignia): sin plazo, un precio
    #     que va justo debajo de una leyenda "Meses sin intereses" no se toca.
    # NO cubre a proposito: los puntos de la insignia cuando el OCR no lee "puntos" (Soriana
    # "1,873" sobre el "18"), ni el "$25" gigante de HEB "Ahorra $25 / Por cada $100 de compra"
    # (rotulo 4x mas chico que el monto: es la geometria del precio grande).
    PATRON_ROTULO_PUNTOS = re.compile(r"^[\W_]*p[uú][nh]?[tl1][o0][s5][\W_]*$", re.IGNORECASE)
    PATRON_ROTULO_PLAZO = re.compile(
        r"^[\W_]*(?:"
        r"(?:[mh][eéc]s(?:[eéc]s)?\s*(?:s[iíl1][nhm]|de)?\s*)?(?:s[iíl1]n\s*)?i{1,2}nt[eéc]r[eéc]s[eéco]s?"
        r"|[mh][eéc]s[eéc]s\s*(?:s[iíl1][nhm]|de)?"
        r")[\W_]*$",
        re.IGNORECASE
    )
    PATRON_ENTERO_PLAZO = re.compile(r"^[\W_]*(\d{1,2})[\W_]*$")
    ALTO_MAX_CANTIDAD_VS_ROTULO = 2.5

    def _detectar_cantidades_de_rotulo(self, bloques_pagina: list[dict],
                                       factor_escala: float = 1.0) -> set[int]:
        """ids de los bloques que son puntos, plazo o mensualidad de un rotulo vecino (ver arriba)."""
        gap_min = self.GAP_ANTICIPO_MIN * factor_escala
        gap_max = self.GAP_ANTICIPO_MAX * factor_escala
        rotulos = []
        for b in bloques_pagina:
            if not b.get("bbox"):
                continue
            texto = self._limpiar_texto(b.get("texto", ""))
            if self.PATRON_ROTULO_PUNTOS.match(texto):
                rotulos.append((b, "puntos"))
            elif self.PATRON_ROTULO_PLAZO.match(texto):
                rotulos.append((b, "plazo"))
        if not rotulos:
            return set()

        # Solo cuenta el bloque MAS pegado al rotulo por cada lado, sea cual sea su texto: en la
        # etiqueta "A SOLO $549 / con 50 / puntos" de Soriana (412336 p38) el precio tambien
        # queda arriba de "puntos" a 22 px, pero el "50" esta en medio a -3 px.
        cantidades = set()
        for rotulo, tipo in rotulos:
            rb = rotulo["bbox"]
            vecino = {}
            for otro in bloques_pagina:
                ob = otro.get("bbox")
                if otro is rotulo or not ob:
                    continue
                lado_gap = self._lado_respecto_a(ob, rb, gap_min, gap_max)
                if lado_gap and (lado_gap[0] not in vecino or lado_gap[1] < vecino[lado_gap[0]][0]):
                    vecino[lado_gap[0]] = (lado_gap[1], otro)
            for lado, (_, otro) in vecino.items():
                ob = otro["bbox"]
                texto = self._limpiar_texto(otro.get("texto", ""))
                if not self.PATRON_MONTO_CUOTA.match(texto):
                    continue
                chico = ob["alto"] <= rb["alto"] * self.ALTO_MAX_CANTIDAD_VS_ROTULO
                antes = lado in ("izquierda", "arriba")
                if tipo == "puntos":
                    ok = antes and chico and "$" not in texto
                elif antes:
                    ok = self._es_plazo(texto)
                else:
                    ok = chico and self._hay_plazo_cerca(rotulo, bloques_pagina, factor_escala)
                if ok:
                    cantidades.add(id(otro))
        return cantidades

    def _es_plazo(self, texto: str) -> bool:
        m = self.PATRON_ENTERO_PLAZO.match(texto)
        return bool(m) and int(m.group(1)) in self.MESES_MSI

    def _hay_plazo_cerca(self, rotulo: dict, bloques_pagina: list[dict],
                         factor_escala: float) -> bool:
        """True si un plazo suelto ("18", "12") esta a menos de DISTANCIA_MAX_CONTEXTO_PRECIO
        del rotulo: confirma que el monto de al lado/abajo es la mensualidad de ESE plazo. Sin
        plazo, un "$949" bajo una leyenda "Meses sin intereses" no se toca."""
        distancia_max = self.DISTANCIA_MAX_CONTEXTO_PRECIO * factor_escala
        return any(
            b is not rotulo and b.get("bbox")
            and self._distancia_bbox(rotulo["bbox"], b["bbox"]) <= distancia_max
            and self._es_plazo(self._limpiar_texto(b.get("texto", "")))
            for b in bloques_pagina
        )

    @staticmethod
    def _lado_respecto_a(ob: dict, rb: dict, gap_min: float,
                         gap_max: float) -> Optional[tuple[str, float]]:
        """(lado, separacion) del bloque ob respecto al rotulo rb si estan pegados
        (misma linea o apilados); None si no."""
        cy_o, cy_r = ob["y"] + ob["alto"] / 2, rb["y"] + rb["alto"] / 2
        if abs(cy_o - cy_r) <= max(ob["alto"], rb["alto"]) / 2:
            gap = rb["x"] - (ob["x"] + ob["ancho"])
            if gap_min <= gap <= gap_max:
                return "izquierda", gap
            gap = ob["x"] - (rb["x"] + rb["ancho"])
            if gap_min <= gap <= gap_max:
                return "derecha", gap
        traslape = min(ob["x"] + ob["ancho"], rb["x"] + rb["ancho"]) - max(ob["x"], rb["x"])
        if traslape >= min(ob["ancho"], rb["ancho"]) / 2:
            gap = rb["y"] - (ob["y"] + ob["alto"])
            if gap_min <= gap <= gap_max:
                return "arriba", gap
            gap = ob["y"] - (rb["y"] + rb["alto"])
            if gap_min <= gap <= gap_max:
                return "abajo", gap
        return None

    def _detectar_anticipos_apartado(self, bloques_pagina: list[dict],
                                     factor_escala: float = 1.0) -> set[int]:
        return self._detectar_montos_de_rotulo(bloques_pagina, factor_escala,
                                               self.PATRON_ROTULO_APARTADO)

    def _detectar_montos_de_rotulo(self, bloques_pagina: list[dict], factor_escala: float,
                                   patron_rotulo: re.Pattern) -> set[int]:
        """
        Mensualidad (12-oct-2026): con patron_rotulo=PATRON_ROTULO_MSI la misma geometria
        detecta "9MSI" + "$77722" / "(12MSI" + "858292" en bloques separados (Chedraui,
        etiqueta de la casilla): ~190 rotulos fuera del holdout, con el monto a 4..15 px,
        alto 20-32 contra 16-28 del rotulo. El monto es la mensualidad, no el precio.

        Anticipo de apartado (descripcion original):
        ids de los bloques que son el ANTICIPO de apartado de Chedraui leido aparte del
        rotulo: "Apartalo con" en un bloque y "$59990" / "838650" / "$50" / "850" en el
        bloque inmediato a su derecha, en la misma linea. Ese monto es el 10% del precio
        (o $50 fijo) impreso en la etiqueta negra bajo el precio grande -- verificado en
        imagenes de 428354 p13-p15 y 428353 p7 --, no el precio del producto.

        Complementa el caso con el monto pegado al rotulo (PATRONES_DESCARTE, 05ca950).
        Medido 12-oct-2026 en todos los folletos fuera del holdout: los 97 rotulos solos
        con un vecino a la derecha son de Chedraui, el vecino esta a -5..15 px, con el
        centro vertical alineado y alto 26-31 px (44 uno) contra 16-24 del rotulo.
        El precio real de la casilla (alto >= 64, >= 78 px a la derecha o arriba) no entra.
        Exige el rotulo, asi que un "$50" sin "Apartalo con" al lado no cambia, y solo
        toma el bloque MAS cercano por rotulo.
        """
        return {id(monto) for _, monto in
                self._pares_rotulo_monto(bloques_pagina, factor_escala, patron_rotulo)}

    def _pares_rotulo_monto(self, bloques_pagina: list[dict], factor_escala: float,
                            patron_rotulo: re.Pattern) -> list[tuple[dict, dict]]:
        """(rotulo, bloque del monto) con la geometria de _detectar_montos_de_rotulo."""
        gap_min = self.GAP_ANTICIPO_MIN * factor_escala
        gap_max = self.GAP_ANTICIPO_MAX * factor_escala
        pares = []
        for rotulo in bloques_pagina:
            rb = rotulo.get("bbox")
            if not rb or not patron_rotulo.match(
                    self._limpiar_texto(rotulo.get("texto", ""))):
                continue
            cy_rotulo = rb["y"] + rb["alto"] / 2
            mejor = None
            for otro in bloques_pagina:
                ob = otro.get("bbox")
                if otro is rotulo or not ob:
                    continue
                if not re.search(r"\d", otro.get("texto", "")):
                    continue
                gap = ob["x"] - (rb["x"] + rb["ancho"])
                if not (gap_min <= gap <= gap_max):
                    continue
                if abs(ob["y"] + ob["alto"] / 2 - cy_rotulo) > max(rb["alto"], ob["alto"]) / 2:
                    continue
                if ob["alto"] > rb["alto"] * self.ALTO_MAX_ANTICIPO_VS_ROTULO:
                    continue
                if mejor is None or gap < mejor[0]:
                    mejor = (gap, otro)
            if mejor:
                pares.append((rotulo, mejor[1]))
        return pares

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
          $2,295  --> 2295.0  (coma de miles: 3 dígitos tras separador)
          $10.999 --> 10999.0 (punto de miles: 3 dígitos tras separador)
          $18.50  --> 18.5    (punto decimal: 1-2 dígitos tras separador)
          $1,390  --> 1390.0
        """
        try:
            numero_str = numero_str.strip()
            # Quitar letras sufijo (c, e, u, etc.) que hayan quedado
            numero_str = re.sub(r"[a-zA-Z]+$", "", numero_str).strip()
            # Separador de miles: coma o punto seguido de EXACTAMENTE 3 dígitos
            # — reemplazar por placeholder vacío (eliminar separador de miles)
            numero_str = re.sub(r"[,\.](\d{3})(?!\d)", r"\1", numero_str)
            # El separador que quede ahora (si hay) es decimal --> normalizar a punto
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
        print(f"\n{'='*65}")
        print(f"  {resultado.imagen}")
        print(f"{'='*65}")

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
        print(f"{'-'*65}\n")