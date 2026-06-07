# Modulo para extraer y clasificar entidades de texto OCR usando expresiones regulares.
# Toma los bloques de texto del OCR y los clasifica en 4 categorías: PRECIO, PROMO, PRODUCTO, DESCARTE

import re
import logging
from dataclasses import dataclass, field
from typing import Optional
from .catalogo_productos import buscar_categoria

# inicializar logger para este módulo
logger = logging.getLogger(__name__)


# --------------- Modelos de datos ---------------

# Entidad clasificada extraída del texto OCR
@dataclass
class EntidadExtraida:

    tipo:       str                     # PRECIO | PROMO | PRODUCTO | DESCARTE
    texto_raw:  str                     # Texto original del OCR
    texto_norm: str                     # Texto normalizado/limpio
    valor:      Optional[float] = None  # Valor numérico si aplica (precios)
    confianza:  float = 0.0             # Confianza del OCR heredada
    bbox:       dict = field(default_factory=dict)
    categoria:  str = ""                # Categoría del catálogo (solo PRODUCTO)

    # Representación legible para debugging
    def __str__(self):
        val = f" → ${self.valor:,.2f}" if self.valor else ""
        return f"[{self.tipo}] '{self.texto_norm}'{val}"

# Resultado agrupado por página del folleto
@dataclass
class ResultadoPagina:
    imagen:     str
    productos:  list[EntidadExtraida] = field(default_factory=list)
    precios:    list[EntidadExtraida] = field(default_factory=list)
    promos:     list[EntidadExtraida] = field(default_factory=list)
    atributos:  list[EntidadExtraida] = field(default_factory=list)  # v2: características técnicas
    descartes:  list[EntidadExtraida] = field(default_factory=list)

    # Contar el total de entidades útiles
    @property
    def total_entidades(self):
        return len(self.productos) + len(self.precios) + len(self.promos) + len(self.atributos)

    # Resumen legible para logging
    def resumen(self) -> str:
        return (f"Página: {self.imagen} | "
                f"Productos: {len(self.productos)} | "
                f"Precios: {len(self.precios)} | "
                f"Promos: {len(self.promos)} | "
                f"Atributos: {len(self.atributos)} | "
                f"Descartes: {len(self.descartes)}")


# --------------- Extractor principal ---------------

# La clase RegexExtractor aplica las reglas de clasificación a cada bloque de texto OCR
class RegexExtractor:
    """
    Fluojo de clasificación:
      1. Limpiar texto OCR (corregir errores comunes del OCR)
      2. Intentar clasificar como PRECIO
      3. Intentar clasificar como PROMO
      4. Si pasa filtros mínimos --> PRODUCTO
      5. Si no --> DESCARTE
    """

    # --------------- Patrones de PRECIO ---------------
    # Captura: $18.50 / $1,568.00 / $2,498 / $10,999 / $10.999 / Antes:$699 / $359c
    #
    # Mejoras v2:
    #   - Acepta punto como separador de miles ($10.999 -> 10999)
    #   - Acepta sufijos OCR pegados ($359c, $999e, $249u) — se ignoran
    #   - Acepta prefijo "Antes:" para precios anteriores
    #   - Captura números de 4-6 dígitos sin separador ($10999)
    PATRON_PRECIO = re.compile(
        r"""
        (?:antes\s*:?\s*|precio\s+anterior\s*:?\s*)?  # prefijo opcional
        (?:^\$|(?<!\w)\$)               # $ al inicio o precedido de no-palabra
        \s*
        (
            \d{4,6}                     # PRIMERO: 4-6 dígitos sin separador ($10999)
            |
            \d{1,3}(?:[,\.]\d{3})*      # número con separadores de miles
            (?:[,\.]\d{1,2})?           # centavos opcionales
        )
        [a-zA-Z/_]*                     # sufijos OCR: c, e, u, / etc. (se ignoran)
        (?:\s*(?:MXN|pesos?))?          # moneda opcional
        """,
        re.VERBOSE | re.IGNORECASE)

    # --------------- Patrones de PROMOCIÓN ---------------
    PATRONES_PROMO = [
        # 2x$35 / 3x$100 / 2x1
        re.compile(r"\d+\s*[xX×]\s*(?:\$\s*)?\d+", re.IGNORECASE),
        # 30% OFF / 20% descuento / 50% de descuento
        re.compile(r"\d+\s*%\s*(?:off|desc(?:uento)?|de\s+desc)?", re.IGNORECASE),
        # $30 por cada $100 / $20 por cada $200
        re.compile(r"\$\s*\d+\s*por\s*cada\s*\$\s*\d+", re.IGNORECASE),
        # TE REGALAMOS / LLEVA X PAGA Y / GRATIS
        re.compile(r"\b(?:te\s+regalamos|lleva|paga|gratis|bonificaci[oó]n)\b",
                   re.IGNORECASE),
        # Precio ya con la promoción / Precio con descuento
        re.compile(r"precio\s+(?:ya\s+)?con\s+(?:la\s+)?promo", re.IGNORECASE),
        # HASTA X% / DESCUENTO DE X%
        re.compile(r"\b(?:hasta|descuento\s+de)\s+\d+\s*%", re.IGNORECASE),
    ]

    # --------------- Patrones de DESCARTE ---------------
    PATRONES_DESCARTE = [
        # Solo 1-2 caracteres
        re.compile(r"^.{1,2}$"),
        # Solo caracteres especiales o símbolos
        re.compile(r"^[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\$]+$"),
        # URLs y dominios web
        re.compile(r"(?:www\.|\.com|\.mx|\.org)", re.IGNORECASE),
        # Fechas de vigencia (importante para el pipeline pero no son productos)
        re.compile(r"vigencia|vencimiento|v[aá]lido|del\s+\d+\s+de", re.IGNORECASE),
        # Texto de pie de página
        re.compile(r"hasta\s+agotar|sujeto\s+a|en\s+tiendas\s+que", re.IGNORECASE),
        # Fragmentos con demasiados caracteres especiales (ruido OCR)
        re.compile(r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑ\s\$\.,\-%]{3,}"),
        # Nombres de marcas/logos en pie de página
        re.compile(r"^(?:lacomer|fresko|walmart|soriana|chedraui)(?:\.com(?:\.mx)?)?$",
                   re.IGNORECASE),
        # Metadata de tallas suelta — no es nombre de producto
        re.compile(r"^tallas?:\s*[A-Za-z0-9]{2,}", re.IGNORECASE),
        # Especificaciones técnicas sueltas sin contexto de producto
        re.compile(r"^\d+\s*(?:gb|mb|ghz|mhz|watts?|w\b|mpx|pulgadas)", re.IGNORECASE),

        # ── v2: Estados y geografía de México ────────────────────────────────
        # Los folletos listan estados de cobertura — no son nombres de producto.
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
            r"uevo|hapas|couma|estado\s+de\s+m[eé]xico|"
            r"tamaulpas|teaxcala|zagaiecas|uer[eé]taro|ca\s+puebua|"
            r"tamau[a-z]*pas|tlax[a-z]*la|zacat[a-z]*cas|quer[a-z]*taro"
            r")$",
            re.IGNORECASE
        ),
        # Abreviaturas de estados en mayúsculas
        re.compile(
            r"^(?:CDMX|DF|NL|BC|BCS|AGS|CHIS|CHIH|COAH|COL|DGO|GTO|GRO|"
            r"HGO|JAL|MEX|MICH|MOR|NAY|OAX|PUE|QRO|QROO|SLP|SIN|SON|"
            r"TAB|TAMPS|TLAX|VER|YUC|ZAC)$"
        ),

        # ── v2: Información financiera / bancaria ─────────────────────────────
        # Bancos, tarjetas y MSI no son productos ni atributos.
        # Nombres exactos de bancos/wallets
        re.compile(
            r"^(?:bbva|banamex|banorte|santander|hsbc|citibanamex|"
            r"scotiabank|inbursa|banbajio|afirme|invex|american\s+express|"
            r"amex|sam['\"]?s\s+club|walmart\s+invex|bradescard|"
            r"clip|mercado\s+pago|oxxo\s+pay|codi)$",
            re.IGNORECASE
        ),
        # Variantes OCR de bancos — el texto contiene el nombre del banco
        # aunque con errores de reconocimiento (Inbursa Bodcgo, Amcrican Express)
        re.compile(
            r"\b(?:inbursa|amcrican|american)\b",
            re.IGNORECASE
        ),
        # Walmart + INVEX juntos (línea de financiamiento en folletos)
        re.compile(
            r"\bwalmart\b.{0,30}\binvex\b",
            re.IGNORECASE
        ),
        # Frases financieras de folleto (exactas o al inicio del bloque)
        re.compile(
            r"^(?:pagando\s+con|meses\s+sin(?:\s+intereses)?|"
            r"tarjetas?\s+de\s+cr[eé]dito|tarjetas?\s+participantes|"
            r"con\s+tu\s+tarjeta|a\s+\d+\s+meses|sin\s+intereses|"
            r"en\s+toda\s+la\s+tienda|en\s+tiendas\s+participantes)$",
            re.IGNORECASE
        ),
        # Líneas que listan múltiples bancos juntos (Banamex, Banorte, HSBC...)
        re.compile(
            r"\b(?:banamex|banorte|santander|hsbc|inbursa|bradescard)\b"
            r".{0,50}"
            r"\b(?:banamex|banorte|santander|hsbc|inbursa|bradescard|"
            r"walmart|invex|liverpool|coppel)\b",
            re.IGNORECASE
        ),

        # ── v2: Slogans y encabezados de sección ─────────────────────────────
        # Frases publicitarias del folleto — no son nombres de producto.
        re.compile(
            r"^[i¡](?:consiente|encuentra|renueva|aprovecha|celebra|"
            r"descubre|cuida|disfruta)\b",
            re.IGNORECASE
        ),
        re.compile(
            r"\b(?:sin\s+gastar\s+de\s+m[aá]s|lo\s+que\s+necesita|"
            r"lo\s+que\s+le\s+gustar[ií]a|espacio\s+de\s+mam[aá]|"
            r"consiente\s+a\s+mam[aá]|renueva\s+el\s+espacio)\b",
            re.IGNORECASE
        ),
        # Continuaciones de slogans que no empiezan con i/¡
        re.compile(
            r"^(?:hasta\s+[Ii]o\s+que|hasta\s+lo\s+que)\b.{0,30}[!;]?$",
            re.IGNORECASE
        ),

        # ── v2: Ruido OCR — bloques solo de consonantes cortas sin contexto ──
        # Solo filtra bloques de 1-3 palabras donde NINGUNA tiene vocal.
        # Ejemplos válidos: "VB GBROM", "DBGBRON"
        # NO filtra: "Slmply Baslco" (tiene vocales en otras palabras del bloque)
        re.compile(
            r"^(?:[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}\s+){1,3}"
            r"[b-df-hj-np-tv-zB-DF-HJ-NP-TV-Z]{2,6}$"
        ),
    ]

    # --------------- Palabras clave de productos ---------------
    # Si el texto contiene estas palabras, probablemente es un producto
    KEYWORDS_PRODUCTO = re.compile(
        r"\b(?:lampara|l[aá]mpara|gabinete|carro|carrito|pintura|sellador|"
        r"impermeabilizante|escalera|taburete|herramienta|caja|silla|mesa|"
        r"organizador|leche|aceite|detergente|jab[oó]n|papel|carne|pollo|"
        r"refresco|cerveza|yogurt|queso|mantequilla|harina|az[uú]car|sal|"
        r"shampoo|crema|desodorante|pa[ñn]al|botella|lata|bolsa|paquete|"
        r"litro|[Ll]t\.?|[Kk][Gg]\.?|[Gg]r?\.?|[Mm][Ll]\.?|pieza|pza)\b",
        re.IGNORECASE
    )

    # --------------- Correcciones comunes de OCR ---------------
    # corecciones caracteres para mejorar la calidad del texto antes de clasificar 
    CORRECCIONES_OCR = [
        (re.compile(r"@"),           "o"),          # @ → o (confusión muy común)
        (re.compile(r"(?<!\w)0(?=\d{2,})"), "o"),   # 0 al inicio de palabra → o
        (re.compile(r"\$\s+"),       "$"),          # $ separado del número
        (re.compile(r"(\d),(\d{3})(?!\d)"), r"\1,\2"),  # normalizar miles
        (re.compile(r"(\d)\.(\d{3})(?!\d)"), r"\1,\2"), # punto de miles → coma
        (re.compile(r"\s{2,}"),      " "),          # espacios múltiples
        (re.compile(r"[|¡!]{2,}"),   ""),           # signos repetidos (ruido)
    ]

    # --------------- Umbral mínimo de confianza OCR para considerar un bloque ---------------
    CONFIANZA_MINIMA = 0.15

    # Constructor de confianza
    def __init__(self, confianza_minima: float = None):
        self.confianza_minima = confianza_minima or self.CONFIANZA_MINIMA

    # --------------- Método principal ---------------

    # Procesa una página completa del folleto (OCR) y clasifica cada bloque
    def procesar_pagina(self, datos_pagina: dict) -> ResultadoPagina:
        # datos_pagina: Dict con keys 'imagen' y 'bloques' (output del OCREngine).
        
        # Cada bloque tiene 'texto', 'confianza', y opcionalmente 'bbox' (coordenadas).
        resultado = ResultadoPagina(imagen=datos_pagina["imagen"])

        for bloque in datos_pagina["bloques"]:
            texto_raw  = bloque["texto"]
            confianza  = bloque["confianza"]
            bbox       = bloque.get("bbox", {})

            # Filtrar bloques con confianza muy baja
            if confianza < self.confianza_minima:
                continue

            # Limpiar texto
            texto_limpio = self._limpiar_texto(texto_raw)

            if not texto_limpio:
                continue

            # Clasificar
            entidad = self._clasificar(texto_limpio, texto_raw, confianza, bbox)

            # Agregar al grupo correspondiente
            if entidad.tipo == "PRECIO":
                resultado.precios.append(entidad)
            elif entidad.tipo == "PROMO":
                resultado.promos.append(entidad)
            elif entidad.tipo == "PRODUCTO":
                resultado.productos.append(entidad)
            elif entidad.tipo == "ATRIBUTO":
                resultado.atributos.append(entidad)
            else:
                resultado.descartes.append(entidad)

        # ResultadoPagina con entidades clasificadas
        return resultado

    def procesar_json_ocr(self, datos_ocr: list[dict]) -> list[ResultadoPagina]:
        """
        Procesa el JSON completo generado por el OCREngine.

        Args:
            datos_ocr: Lista de dicts con resultados por página.

        Returns:
            Lista de ResultadoPagina, uno por imagen procesada.
        """
        resultados = []
        for pagina in datos_ocr:
            r = self.procesar_pagina(pagina)
            resultados.append(r)
            logger.info(r.resumen())
        return resultados

    # --------------- Clasificador ---------------

    def _clasificar(
        self,
        texto: str,
        texto_raw: str,
        confianza: float,
        bbox: dict
    ) -> EntidadExtraida:
        """Aplica las reglas de clasificación en orden de prioridad."""

        # 1. ¿Es descarte? (verificar primero para filtrar ruido rápido)
        if self._es_descarte(texto):
            return EntidadExtraida("DESCARTE", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 2. ¿Es precio?
        precio_valor = self._extraer_precio(texto)
        if precio_valor is not None:
            return EntidadExtraida("PRECIO", texto_raw, texto,
                                   valor=precio_valor,
                                   confianza=confianza, bbox=bbox)

        # 3. ¿Es promoción?
        if self._es_promo(texto):
            return EntidadExtraida("PROMO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 4. ¿Está en el catálogo? — puede ser PRODUCTO o ATRIBUTO técnico
        en_catalogo, categoria, es_atributo = buscar_categoria(texto)
        if en_catalogo:
            tipo = "ATRIBUTO" if es_atributo else "PRODUCTO"
            return EntidadExtraida(tipo, texto_raw, texto,
                                   confianza=confianza, bbox=bbox,
                                   categoria=categoria)

        # 5. ¿Tiene indicios de ser producto por heurísticas?
        if self._es_probable_producto(texto):
            return EntidadExtraida("PRODUCTO", texto_raw, texto,
                                   confianza=confianza, bbox=bbox)

        # 6. Por defecto → descarte
        return EntidadExtraida("DESCARTE", texto_raw, texto,
                               confianza=confianza, bbox=bbox)

    # --------------- Reglas individuales ---------------

    def _limpiar_texto(self, texto: str) -> str:
        """Aplica correcciones comunes de errores de OCR."""
        texto = texto.strip()
        for patron, reemplazo in self.CORRECCIONES_OCR:
            texto = patron.sub(reemplazo, texto)
        return texto.strip()

    def _es_descarte(self, texto: str) -> bool:
        """Retorna True si el texto es claramente ruido o irrelevante."""
        for patron in self.PATRONES_DESCARTE:
            if patron.search(texto):
                return True
        # Descartar si tiene más del 40% de caracteres no alfanuméricos
        chars_raros = sum(1 for c in texto
                         if not c.isalnum() and c not in " $.,-%áéíóúÁÉÍÓÚñÑ")
        if len(texto) > 3 and chars_raros / len(texto) > 0.4:
            return True
        return False

    def _extraer_precio(self, texto: str) -> Optional[float]:
        """
        Intenta extraer un valor numérico de precio del texto.
        Retorna float si lo encuentra, None si no.

        Maneja separadores ambiguos:
          $10,999 → 10999.0  (coma de miles, no decimales)
          $10.999 → 10999.0  (punto de miles — común en OCR)
          $18.50  → 18.5     (punto decimal real)
          $1,390  → 1390.0
        """
        match = self.PATRON_PRECIO.search(texto)
        if not match:
            return None
        try:
            numero_str = match.group(1)
            # Detectar si el separador es de miles o decimal
            # Regla: si hay 3 dígitos después del separador → es de miles
            import re as _re
            # Quitar separadores de miles (coma o punto seguido de exactamente 3 dígitos)
            numero_str = _re.sub(r"[,\.](\d{3})(?!\d)", r"", numero_str)
            # El separador que quede (si hay) es decimal
            numero_str = numero_str.replace(",", ".")
            return float(numero_str)
        except (ValueError, IndexError):
            return None

    def _es_promo(self, texto: str) -> bool:
        """Retorna True si el texto contiene un patrón de promoción."""
        for patron in self.PATRONES_PROMO:
            if patron.search(texto):
                return True
        return False

    def _es_probable_producto(self, texto: str) -> bool:
        """
        Heurísticas para detectar nombres de productos.
        Un texto es probable producto si:
          - Tiene al menos 4 caracteres
          - Contiene al menos una palabra de 3+ letras
          - Contiene una keyword de producto, O
          - Está en mayúsculas (como suelen aparecer en folletos), O
          - Tiene entre 3 y 60 caracteres y no es puro número, O
          - Es una sola palabra larga con inicial mayúscula (nombre de producto/marca)
        """
        if len(texto) < 4:
            return False

        # Quitar apóstrofos/comillas al inicio para comparar
        texto_norm = texto.lstrip("'\"'")

        # Verificar que tiene contenido alfabético real
        palabras = [p for p in texto_norm.split() if len(p) >= 3 and p.replace("é","e").replace("á","a").replace("ó","o").replace("í","i").replace("ú","u").replace("ñ","n").isalpha()]
        if not palabras:
            return False

        # Keyword explícita de producto
        if self.KEYWORDS_PRODUCTO.search(texto):
            return True

        # Texto en MAYÚSCULAS (marcas y productos en folletos suelen estar así)
        if texto_norm.isupper() and 4 <= len(texto_norm) <= 60:
            return True

        # Una sola palabra de 5+ letras con inicial mayúscula → nombre de producto o marca
        # Captura: Licuadora, Balerinas, Camison, Exprimidor, Galaxy, Koblenz, mabe...
        if len(palabras) == 1 and len(palabras[0]) >= 5:
            return True

        # Texto mixto de longitud razonable con 2+ palabras reales
        if 4 <= len(texto_norm) <= 80 and len(palabras) >= 2:
            return True

        return False

    # --------------- Utilidades ---------------

    def imprimir_resultado(self, resultado: ResultadoPagina):
        """Imprime el resultado clasificado de forma legible."""
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

        if resultado.promos:
            print(f"\n  🎯 PROMOCIONES ({len(resultado.promos)}):")
            for e in resultado.promos:
                print(f"      {e.texto_norm[:55]}")

        if resultado.atributos:
            print(f"\n  🔧 ATRIBUTOS ({len(resultado.atributos)}):")
            for e in resultado.atributos:
                print(f"      {e.texto_norm[:55]:<55} [{e.confianza:.0%}]")

        print(f"\n  🗑️  Descartes: {len(resultado.descartes)} bloques filtrados")
        print(f"{'─'*65}\n")