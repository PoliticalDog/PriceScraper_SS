# Convierte el texto OCR crudo de productos en nombres canónicos comparables
# entre tiendas y semanas. Necesario para que el BI pueda rastrear un mismo
# producto a lo largo del tiempo sin duplicados por variantes OCR.

import re
import unicodedata
import logging
from dataclasses import dataclass, field
from typing import Optional
from rapidfuzz import process, fuzz

from .catalogo_productos import buscar_categoria, CATALOGO

logger = logging.getLogger(__name__)

# Mapeo nombre-para-mostrar -> slug de categoria, derivado directamente de
# catalogo_productos.CATALOGO (clave del dict) en vez de slugificar el
# nombre para mostrar -- evita que un mismo departamento termine con dos
# slugs distintos en productos_canonicos.categoria segun si el producto
# matcheo por CATALOGO_CANONICO (slug corto, ej. "alimentos") o por este
# fallback (antes generaba "alimentos_y_bebidas" a partir de "Alimentos y
# Bebidas" -- bug encontrado 23-ago-2026 comparando conteos reales en
# Postgres: "alimentos" 24895 filas vs "alimentos_y_bebidas" 1667 filas,
# la MISMA categoria fragmentada en dos).
# "Frutas y Verduras" se fusiona deliberadamente con "alimentos": el
# catalogo canonico ya trata produce como parte de alimentos (Platano,
# Manzana, Naranja... usan categoria="alimentos"), no se crea un slug
# "frutas_verduras" aparte para no fragmentar la taxonomia otra vez.
_NOMBRE_A_SLUG: dict[str, str] = {datos["nombre"]: clave for clave, datos in CATALOGO.items()}
_NOMBRE_A_SLUG["Frutas y Verduras"] = "alimentos"

# Catálogo de productos canónicos

CATALOGO_CANONICO: dict[str, dict] = {

    # ---------------------------- Lácteos ----------------------------
    "Leche entera":            {"categoria": "alimentos", "marca": None,  "aliases": ["leche entra", "leche ent", "leche 1l", "leche 1lt"]},
    "Leche light":             {"categoria": "alimentos", "marca": None,  "aliases": ["leche lite", "leche descremada"]},
    "Leche deslactosada":      {"categoria": "alimentos", "marca": None,  "aliases": ["leche sin lactosa", "leche deslac"]},
    "Yogurt":                  {"categoria": "alimentos", "marca": None,  "aliases": ["yoghurt", "yogur"]},
    "Queso Oaxaca":            {"categoria": "alimentos", "marca": None,  "aliases": ["qeso oaxaca", "q. oaxaca"]},
    "Queso fresco":            {"categoria": "alimentos", "marca": None,  "aliases": ["queso frcos", "qso fresco"]},
    "Crema":                   {"categoria": "alimentos", "marca": None,  "aliases": ["crema acida", "crema ácida"]},
    "Mantequilla":             {"categoria": "alimentos", "marca": None,  "aliases": ["manequilla", "mantequlla"]},

    # ---------------------------- Carnes y embutidos ----------------------------
    "Salchicha":               {"categoria": "alimentos", "marca": None,  "aliases": ["salchica", "salchcha", "salcihca"]},
    "Jamón":                   {"categoria": "alimentos", "marca": None,  "aliases": ["jamon", "hamon", "jámon"]},
    "Chorizo":                 {"categoria": "alimentos", "marca": None,  "aliases": ["choriso", "chorizoo"]},
    "Pollo entero":            {"categoria": "alimentos", "marca": None,  "aliases": ["pollo entro", "polo entero"]},
    "Pechuga de pollo":        {"categoria": "alimentos", "marca": None,  "aliases": ["pechuga pollo", "pechuga"]},
    "Carne molida":            {"categoria": "alimentos", "marca": None,  "aliases": ["carne molda", "carne mol"]},
    "Bistec de res":           {"categoria": "alimentos", "marca": None,  "aliases": ["bistec res", "bisteck"]},
    "Atún en agua":            {"categoria": "alimentos", "marca": None,  "aliases": ["atun en agua", "atun agua", "atún"]},

    # ---------------------------- Despensa básica ----------------------------
    "Arroz":                   {"categoria": "alimentos", "marca": None,  "aliases": ["arros", "arrros"]},
    "Frijol negro":            {"categoria": "alimentos", "marca": None,  "aliases": ["frijol ngro", "frijoles negros"]},
    "Frijol pinto":            {"categoria": "alimentos", "marca": None,  "aliases": ["frijoles pintos"]},
    "Lenteja":                 {"categoria": "alimentos", "marca": None,  "aliases": ["lentejas", "lentej"]},
    "Azúcar":                  {"categoria": "alimentos", "marca": None,  "aliases": ["azucar", "azcar", "azúccar"]},
    "Sal":                     {"categoria": "alimentos", "marca": None,  "aliases": ["sal de mesa"]},
    "Harina de trigo":         {"categoria": "alimentos", "marca": None,  "aliases": ["harina trigo", "harina"]},
    "Aceite vegetal":          {"categoria": "alimentos", "marca": None,  "aliases": ["aceite vegtal", "aceite vegetal 800ml"]},
    "Aceite de oliva":         {"categoria": "alimentos", "marca": None,  "aliases": ["aceite oliva", "aceite de olva"]},
    "Aceite de coco":          {"categoria": "alimentos", "marca": None,  "aliases": ["aceite coco", "aceite de ccoo"]},
    "Aceite de canola":        {"categoria": "alimentos", "marca": None,  "aliases": ["aceite canola"]},
    "Aceite de soya":          {"categoria": "alimentos", "marca": None,  "aliases": ["aceite soya"]},
    "Aceite de maíz":          {"categoria": "alimentos", "marca": None,  "aliases": ["aceite maiz", "aceite de maiz"]},
    "Aceite de aguacate":      {"categoria": "alimentos", "marca": None,  "aliases": ["aceite aguacate"]},
    "Pasta para sopa":         {"categoria": "alimentos", "marca": None,  "aliases": ["pasta sopa", "sopa pasta", "pasta para sopas"]},
    "Tortillas de maíz":       {"categoria": "alimentos", "marca": None,  "aliases": ["tortillas", "tortillas maiz", "tortias"]},
    "Pan de caja":             {"categoria": "alimentos", "marca": None,  "aliases": ["pan caja", "pan de caj"]},
    "Galletas":                {"categoria": "alimentos", "marca": None,  "aliases": ["galleta", "galetas"]},
    "Cereal":                  {"categoria": "alimentos", "marca": None,  "aliases": ["cereal mañanero", "cereales"]},
    "Avena":                   {"categoria": "alimentos", "marca": None,  "aliases": ["hojuelas de avena"]},

    # ---------------------------- Frutas y verduras ----------------------------
    "Plátano":                 {"categoria": "alimentos", "marca": None,  "aliases": ["platano", "pltano", "platano macho", "plátanos"]},
    "Manzana":                 {"categoria": "alimentos", "marca": None,  "aliases": ["manznas", "manzana roja"]},
    "Naranja":                 {"categoria": "alimentos", "marca": None,  "aliases": ["naranjas", "naranja valencia"]},
    "Aguacate":                {"categoria": "alimentos", "marca": None,  "aliases": ["aguacte", "aguacates", "palta"]},
    "Tomate":                  {"categoria": "alimentos", "marca": None,  "aliases": ["jitomate", "tomates", "jitomates", "tomate rojo"]},
    "Cebolla":                 {"categoria": "alimentos", "marca": None,  "aliases": ["cebolca", "cebollas", "ceblla"]},
    "Papa":                    {"categoria": "alimentos", "marca": None,  "aliases": ["papas", "patata"]},
    "Chía":                    {"categoria": "alimentos", "marca": None,  "aliases": ["chia", "semilla de chia", "semilla de chía"]},
    "Quinoa":                  {"categoria": "alimentos", "marca": None,  "aliases": ["quinua", "quinua real"]},
    # Agregados 23-ago-2026 -- top frutas/verduras reales mas frecuentes en
    # el bucket heuristico (analisis de productos_canonicos vs Postgres real,
    # ver sources/nlp/). "Granel"/unidades de venta se excluyeron a proposito
    # (no son nombre de producto, ver plan de integracion).
    "Melón":                   {"categoria": "alimentos", "marca": None,  "aliases": ["melon", "melon chino", "melones"]},
    "Papaya":                  {"categoria": "alimentos", "marca": None,  "aliases": ["papaya maradol"]},
    "Lechuga":                 {"categoria": "alimentos", "marca": None,  "aliases": ["lechuga romana", "lechugas"]},
    "Sandía":                  {"categoria": "alimentos", "marca": None,  "aliases": ["sandia", "sandias"]},
    "Elote":                   {"categoria": "alimentos", "marca": None,  "aliases": ["elotes", "elote dorado"]},
    "Chile serrano":           {"categoria": "alimentos", "marca": None,  "aliases": ["chile serano", "chiles serranos"]},
    "Chile jalapeño":          {"categoria": "alimentos", "marca": None,  "aliases": ["chile jalapeno", "chiles jalapenos"]},
    "Brócoli":                 {"categoria": "alimentos", "marca": None,  "aliases": ["brocoli", "brocolis"]},
    "Zanahoria":               {"categoria": "alimentos", "marca": None,  "aliases": ["zanahorias"]},

    # ---------------------------- Bebidas ----------------------------
    "Refresco":                {"categoria": "alimentos", "marca": None,  "aliases": ["refrcos", "refresco 2l", "refresco 600ml"]},
    "Agua natural":            {"categoria": "alimentos", "marca": None,  "aliases": ["agua purificada", "agua 1.5l", "agua garrafon"]},
    "Jugo":                    {"categoria": "alimentos", "marca": None,  "aliases": ["jugo de naranja", "jugo 1l"]},
    "Cerveza":                 {"categoria": "alimentos", "marca": None,  "aliases": ["cerzeva", "cerbeza", "cervesa"]},
    "Vino tinto":              {"categoria": "alimentos", "marca": None,  "aliases": ["vino tnto", "vino"]},
    "Café":                    {"categoria": "alimentos", "marca": None,  "aliases": ["cafe", "cafe soluble", "café molido"]},
    "Vinagre":                 {"categoria": "alimentos", "marca": None,  "aliases": ["vinagre blanco", "vinagre de manzana"]},

    # ---------------------------- Condimentos ----------------------------
    "Mayonesa":                {"categoria": "alimentos", "marca": None,  "aliases": ["maonesa", "mayonesa de aguacate"]},
    "Salsa":                   {"categoria": "alimentos", "marca": None,  "aliases": ["salsa picante", "salsas", "salsa verde"]},
    "Ketchup":                 {"categoria": "alimentos", "marca": None,  "aliases": ["catsup", "ketxup"]},
    "Aderezos":                {"categoria": "alimentos", "marca": None,  "aliases": ["aderezo", "aderezo cesar", "aderezo italiano"]},

    # ---------------------------- Limpieza ----------------------------
    "Detergente":              {"categoria": "limpieza", "marca": None,   "aliases": ["detergnte", "detrjente", "detergente líquido", "detergente en polvo"]},
    "Suavizante de telas":     {"categoria": "limpieza", "marca": None,   "aliases": ["suavizante", "suavizante ropa", "suavizante telas"]},
    "Cloro":                   {"categoria": "limpieza", "marca": None,   "aliases": ["cloro regular", "blanqueador"]},
    "Papel higiénico":         {"categoria": "limpieza", "marca": None,   "aliases": ["papel higienico", "papel sanitario", "papel hig"]},
    "Papel de cocina":         {"categoria": "limpieza", "marca": None,   "aliases": ["papel cocina", "toalla de cocina", "rollo de cocina"]},
    "Esponja":                 {"categoria": "limpieza", "marca": None,   "aliases": ["esponjas", "esponja fibra"]},
    "Bolsas de basura":        {"categoria": "limpieza", "marca": None,   "aliases": ["bolsa basura", "bolsas basura"]},

    # ---------------------------- Cuidado personal ----------------------------
    "Shampoo":                 {"categoria": "cuidado_personal", "marca": None, "aliases": ["xampoo", "shampo", "champú"]},
    "Acondicionador":          {"categoria": "cuidado_personal", "marca": None, "aliases": ["acondicionadr", "rinse"]},
    "Desodorante":             {"categoria": "cuidado_personal", "marca": None, "aliases": ["desodrant", "antitranspirante", "desodorante roll-on"]},
    "Pasta dental":            {"categoria": "cuidado_personal", "marca": None, "aliases": ["pasta de dientes", "crema dental", "pasta dentl"]},
    "Rastrillo":               {"categoria": "cuidado_personal", "marca": None, "aliases": ["rastrillos", "rastrillos desechables", "rastrilo"]},
    "Pañales":                 {"categoria": "cuidado_personal", "marca": None, "aliases": ["pañal", "panales", "pañales desechables"]},
    "Toallitas húmedas":       {"categoria": "cuidado_personal", "marca": None, "aliases": ["toallitas", "toallitas humedas", "toallitas bebe"]},
    "Tinte para cabello":      {"categoria": "cuidado_personal", "marca": None, "aliases": ["tinte", "tinte cabello", "coloración"]},

    # ---------------------------- Electrodomésticos ----------------------------
    "Refrigerador":            {"categoria": "linea_blanca",  "marca": None, "aliases": ["refri", "refrigeradr", "refrigerador duplex", "refirgerador"]},
    "Lavadora":                {"categoria": "linea_blanca",  "marca": None, "aliases": ["labadera", "lavdora", "lavadora automatica"]},
    "Estufa":                  {"categoria": "linea_blanca",  "marca": None, "aliases": ["estfa", "cocina integral"]},
    "Secadora":                {"categoria": "linea_blanca",  "marca": None, "aliases": ["secadora de ropa", "secadora de gas"]},
    "Microondas":              {"categoria": "linea_blanca",  "marca": None, "aliases": ["horno microondas", "microonda"]},
    "Licuadora":               {"categoria": "pequenos_electrodomesticos", "marca": None, "aliases": ["licuadra", "licuaora"]},
    "Cafetera":                {"categoria": "pequenos_electrodomesticos", "marca": None, "aliases": ["caftera", "cafetera electrica"]},
    "Ventilador":              {"categoria": "linea_blanca",  "marca": None, "aliases": ["ventiladr", "abanico electrico"]},
    "Aire acondicionado":      {"categoria": "linea_blanca",  "marca": None, "aliases": ["aire acon", "minisplit", "a/a"]},

    # ---------------------------- Tecnología ----------------------------
    "Smart TV":                {"categoria": "electronica",   "marca": None, "aliases": ["smartv", "smart tv 4k", "television smart", "smart television"]},
    "Laptop":                  {"categoria": "electronica",   "marca": None, "aliases": ["lapto", "notebook", "computadora portatil"]},
    "Smartphone":              {"categoria": "electronica",   "marca": None, "aliases": ["celular", "telefono inteligente", "smartphoe"]},
    "Bocina Bluetooth":        {"categoria": "electronica",   "marca": None, "aliases": ["bocina bt", "altavoz bluetooth", "bocina inalambrica"]},
    "Audifonos":               {"categoria": "electronica",   "marca": None, "aliases": ["audífonos", "audifonos inalambricos", "headphones"]},

    # ---------------------------- Mascotas ----------------------------
    "Croquetas para perro":    {"categoria": "mascotas",      "marca": None, "aliases": ["croquetas perro", "alimento perro", "comida perro"]},
    "Croquetas para gato":     {"categoria": "mascotas",      "marca": None, "aliases": ["croquetas gato", "alimento gato", "comida gato"]},

    # ---------------------------- Ropa ----------------------------
    "Playera":                 {"categoria": "ropa",          "marca": None, "aliases": ["camiseta", "playra", "polera"]},
    "Pantalón":                {"categoria": "ropa",          "marca": None, "aliases": ["pantalon", "jeans", "pantalon de mezclilla"]},
    "Vestido":                 {"categoria": "ropa",          "marca": None, "aliases": ["vestdo", "vestidos"]},
    "Pijama":                  {"categoria": "ropa",          "marca": None, "aliases": ["pijamas", "piyama"]},
    "Tenis":                   {"categoria": "ropa",          "marca": None, "aliases": ["tnis", "zapatillas deportivas"]},

    # ---------------------------- Videojuegos ----------------------------
    # Agregados 23-ago-2026 -- categoria nueva, no tenia ninguna entrada
    # canonica pese a que catalogo_productos.py ya reconoce el departamento.
    # Cuidado: "game" (keyword de catalogo_productos.py) matchea como
    # substring dentro de "Gamesa" -- ruido de origen ajeno a este catalogo,
    # ver plan de integracion.
    "FIFA":                    {"categoria": "videojuegos",   "marca": None, "aliases": ["fifao", "fifac", "fifa worldcup"]},
    "Spider-Man":              {"categoria": "videojuegos",   "marca": None, "aliases": ["spiderman", "spider man"]},
    "Mario Kart":              {"categoria": "videojuegos",   "marca": None, "aliases": ["mario kart world"]},
    "PS5":                     {"categoria": "videojuegos",   "marca": None, "aliases": ["ps5 digital slim", "playstation 5"]},
}

# ---------------------------- Marcas conocidas que se filtran del nombre canónico ----------------------------
# Si el producto contiene estas palabras, se extrae como campo `marca`
MARCAS_CONOCIDAS = {
    # Alimentos
    "bimbo", "marinela", "barcel", "sabritas", "gamesa", "maseca", "herdez",
    "la costeña", "san marcos", "clemente jacques", "del monte", "la sierra",
    "lala", "alpura", "sigma", "fud", "san rafael", "kelloggs", "kellog",
    "nestle", "nestlé", "knorr", "maggi", "heinz", "campbell", "maruchan",
    "quaker", "great value",
    # Bebidas
    "coca cola", "pepsi", "jumex", "ciel", "bonafont", "epura", "electropura",
    "modelo", "corona", "victoria", "tecate", "xx", "sol", "heineken",
    # Limpieza
    "ariel", "tide", "downy", "fabuloso", "pinol", "ajax", "roma", "ace",
    "cloralex", "salvo", "vanish",
    # Cuidado personal
    "pantene", "head shoulders", "dove", "axe", "old spice", "colgate",
    "oral b", "gillette", "venus", "always", "kotex", "huggies", "pampers",
    # Marca privada Fresko/La Comer
    "golden hills",
    # Tecnología
    "samsung", "lg", "mabe", "acros", "whirlpool", "oster", "hamilton beach",
    "black decker", "apple", "motorola", "xiaomi", "atvio", "hisense",
    # Ropa
    "simply basico", "simply básico", "george", "op brand",
}



# ---------------------------- Resultado del normalizador ----------------------------

@dataclass
class ResultadoNorm:
    texto_raw:       str
    nombre_canonico: str
    confianza_norm:  float          # 0.0 – 1.0
    metodo:          str            # exacto | fuzzy | heuristico | sin_match
    categoria:       str = ""
    marca:           Optional[str] = None
    descartado:      bool = False   # True si el texto no es un producto válido

    def __str__(self):
        if self.descartado:
            return f"[DESCARTE] '{self.texto_raw}'"
        marca_str = f" [{self.marca}]" if self.marca else ""
        return (f"[{self.metodo.upper()} {self.confianza_norm:.0%}] "
                f"'{self.texto_raw}' → '{self.nombre_canonico}'{marca_str}")



# ---------------------------- Normalizador principal ----------------------------

class Normalizador:
    """
    Normaliza texto OCR de productos en nombres canónicos comparables.

    Umbral de confianza fuzzy:
        >= UMBRAL_ALTO  → match directo, alta confianza (fuzzy)
        >= UMBRAL_BAJO  → match aceptable (fuzzy con advertencia)
        <  UMBRAL_BAJO  → sin match (heurístico o sin_match)

    Args:
        umbral_alto: Confianza mínima para match directo (default: 0.80)
        umbral_bajo: Confianza mínima para match aceptable (default: 0.60)
    """

    UMBRAL_ALTO = 0.80
    UMBRAL_BAJO = 0.60

    # Guarda de longitud para el match fuzzy -- ver comentario en normalizar().
    # 0.2 discrimina bien entre descripciones largas de producto que matchean
    # legitimamente un nombre canonico corto (ratio ~0.3-0.45, ej. "Aceite de
    # coco organico extra virgen 450ml" -> "aceite de coco") y textos largos
    # sin relacion que matchean por contener de casualidad un alias/token
    # corto (ratio ~0.08-0.09, ej. un listado de departamentos que contiene
    # la palabra "celular" -> alias de "Smartphone").
    RATIO_LONGITUD_MINIMO = 0.2

    # Correcciones OCR específicas antes del fuzzy
    CORRECCIONES_OCR = [
        (re.compile(r"\bpltano\b",  re.I), "plátano"),
        (re.compile(r"\bcebolca\b", re.I), "cebolla"),
        (re.compile(r"\bcerzeva\b", re.I), "cerveza"),
        (re.compile(r"\bcerbeza\b", re.I), "cerveza"),
        (re.compile(r"\bjamon\b",   re.I), "jamón"),
        (re.compile(r"\brefri\b(?!\w)", re.I), "refrigerador"),
        (re.compile(r"\bxampoo\b",  re.I), "shampoo"),
        (re.compile(r"\bmaonesa\b", re.I), "mayonesa"),
        (re.compile(r"\blabadera\b",re.I), "lavadora"),
        (re.compile(r"\blapto\b",   re.I), "laptop"),
        (re.compile(r"\bchiia\b",   re.I), "chía"),
        # Unidades de medida normalizadas
        (re.compile(r"\b(\d+)\s*kgs?\b", re.I),   r"\1 kg"),
        (re.compile(r"\b(\d+)\s*kilos?\b", re.I),  r"\1 kg"),
        (re.compile(r"\b(\d+)\s*lts?\b", re.I),    r"\1 l"),
        (re.compile(r"\b(\d+)\s*litros?\b", re.I), r"\1 l"),
        (re.compile(r"\b(\d+)\s*mls?\b", re.I),    r"\1 ml"),
        (re.compile(r"\b(\d+)\s*grs?\b", re.I),    r"\1 g"),
        (re.compile(r"\b(\d+)\s*grms?\b", re.I),   r"\1 g"),
        (re.compile(r"\bpzs?\b", re.I),             "pza"),
    ]

    # Patrones que indican que el texto NO es un producto real
    PATRONES_BASURA = [
        re.compile(r"^\d+$"),                               # solo números
        re.compile(r"^[a-záéíóú]{1,3}$", re.I),            # muy corto
        re.compile(r"del\s+videojuego", re.I),              # fragmento de descripción
        re.compile(r"en\s+(?:tienda|línea|linea)", re.I),   # canal de venta
        re.compile(r"visita\s+tu\s+tienda", re.I),
        re.compile(r"en\s+mancuernas", re.I),               # "En mancuernas" (fragmento)
        re.compile(r"en\s+línea\s+de", re.I),               # "En línea de pintura"
        re.compile(r"noincluye", re.I),
        re.compile(r"precio\s+(?:bajo|especial)", re.I),
        re.compile(r"^\d+\s*(?:pz|pcs|pack|kit)s?$", re.I),# "12 pzs" solo
    ]

    def __init__(
        self,
        umbral_alto: float = UMBRAL_ALTO,
        umbral_bajo: float = UMBRAL_BAJO,
    ):
        self.umbral_alto = umbral_alto
        self.umbral_bajo = umbral_bajo

        # Construir índice de búsqueda fuzzy con todos los nombres y aliases
        self._indice: list[tuple[str, str]] = []  # (texto_busqueda, nombre_canonico)
        for nombre, datos in CATALOGO_CANONICO.items():
            self._indice.append((self._normalizar_base(nombre), nombre))
            for alias in datos.get("aliases", []):
                self._indice.append((self._normalizar_base(alias), nombre))

        self._textos_busqueda = [t for t, _ in self._indice]
        logger.info(f"[Norm] Catálogo cargado: {len(CATALOGO_CANONICO)} productos, "
                    f"{len(self._indice)} entradas de búsqueda")

    # ---------------------------- API pública ----------------------------

    def normalizar(self, texto: str) -> ResultadoNorm:
        """
        Normaliza un texto de producto.

        Returns:
            ResultadoNorm con nombre canónico, confianza y método.
        """
        if not texto or not texto.strip():
            return ResultadoNorm(
                texto_raw=texto, nombre_canonico="",
                confianza_norm=0.0, metodo="sin_match", descartado=True
            )

        texto_raw = texto.strip()

        # 1. Filtro de basura
        if self._es_basura(texto_raw):
            return ResultadoNorm(
                texto_raw=texto_raw, nombre_canonico="",
                confianza_norm=0.0, metodo="sin_match", descartado=True
            )

        # 2. Extraer marca si está presente
        marca = self._extraer_marca(texto_raw)

        # 3. Limpiar texto para búsqueda
        texto_limpio = self._limpiar(texto_raw)

        # 4. Match exacto en catálogo (después de normalizar)
        texto_norm_base = self._normalizar_base(texto_limpio)
        for texto_idx, nombre_canonico in self._indice:
            if texto_norm_base == texto_idx:
                datos = CATALOGO_CANONICO[nombre_canonico]
                return ResultadoNorm(
                    texto_raw=texto_raw,
                    nombre_canonico=nombre_canonico,
                    confianza_norm=1.0,
                    metodo="exacto",
                    categoria=datos["categoria"],
                    marca=marca or datos.get("marca"),
                )

        # 5. Fuzzy matching
        resultado_fuzzy = process.extractOne(
            texto_norm_base,
            self._textos_busqueda,
            scorer=fuzz.token_set_ratio,
            score_cutoff=self.umbral_bajo * 100,
        )

        if resultado_fuzzy:
            match_texto, score, idx = resultado_fuzzy
            # Guarda de longitud: token_set_ratio puede dar score 100 cuando
            # el alias/nombre entero (a menudo corto: "a/a", "celular") queda
            # contenido como token dentro de un texto mucho mas largo y sin
            # relacion real -- confirmado 22-ago-2026 probando contra
            # Postgres real: "'Sujato,a disponibllidad" matcheaba "Aire
            # acondicionado" (via alias "a/a") y un listado de departamentos
            # ("...Telefonia Celular; Linea Blanca...") matcheaba
            # "Smartphone" (via alias "celular"), ambos con confianza 1.0.
            # Un texto de producto real mas largo que su nombre canonico
            # (ej. "Aceite de coco organico extra virgen 450ml" -> "aceite de
            # coco", ratio ~0.33) nunca es TAN desproporcionado como estos
            # falsos positivos (ratio ~0.08-0.09) -- la proporcion de
            # longitud discrimina bien entre ambos casos sin penalizar
            # descripciones largas legitimas.
            largo_corto = min(len(match_texto), len(texto_norm_base))
            largo_largo = max(len(match_texto), len(texto_norm_base))
            ratio_longitud = largo_corto / largo_largo if largo_largo else 0.0

            if ratio_longitud >= self.RATIO_LONGITUD_MINIMO:
                confianza = score / 100.0
                nombre_canonico = self._indice[idx][1]
                datos = CATALOGO_CANONICO[nombre_canonico]
                metodo = "fuzzy" if confianza >= self.umbral_alto else "fuzzy_bajo"

                return ResultadoNorm(
                    texto_raw=texto_raw,
                    nombre_canonico=nombre_canonico,
                    confianza_norm=round(confianza, 3),
                    metodo=metodo,
                    categoria=datos["categoria"],
                    marca=marca or datos.get("marca"),
                )
            # Si no pasa la guarda de longitud, cae al heuristico (paso 6)
            # en vez de aceptar un match de confianza reportada alta pero
            # espuria.

        # 6. Sin match en el catálogo canónico (~90 productos, sesgado a
        # abarrotes/limpieza/cuidado personal) -- devolver heurístico (texto
        # limpio con capitalización) pero con la categoría amplia del
        # departamento si catalogo_productos.py la reconoce (17 departamentos,
        # cubre electrónica/ropa/muebles/etc. que el catálogo canónico no
        # tiene todavía) en vez de dejarla vacía. Agregado 22-ago-2026: antes
        # de esto, todo producto "heuristico" quedaba sin categoria alguna en
        # productos_canonicos, aunque el texto sí calzara con un departamento
        # conocido (ej. "Licuadora Oster 5 velocidades" -> sin match exacto,
        # pero sí matchea "licuadora" en catalogo_productos.CATALOGO).
        nombre_heuristico = self._capitalizar(texto_limpio)
        en_catalogo, categoria_amplia, _ = buscar_categoria(texto_raw)
        # buscar_categoria devuelve el nombre para mostrar ("Línea Blanca"),
        # no el slug -- se traduce via _NOMBRE_A_SLUG (derivado de
        # catalogo_productos.CATALOGO) para que productos_canonicos.categoria
        # sea consistente sin importar si el producto matcheo por catálogo
        # canónico o por este fallback.
        if en_catalogo:
            categoria_amplia = _NOMBRE_A_SLUG.get(categoria_amplia, categoria_amplia)
        return ResultadoNorm(
            texto_raw=texto_raw,
            nombre_canonico=nombre_heuristico,
            confianza_norm=0.0,
            metodo="heuristico",
            categoria=categoria_amplia,
            marca=marca,
        )

    def normalizar_lista(self, textos: list[str]) -> list[ResultadoNorm]:
        """Normaliza una lista de textos. Más eficiente que llamar normalizar() N veces."""
        return [self.normalizar(t) for t in textos]

    def normalizar_pagina(self, pagina: dict) -> dict:
        """
        Normaliza todos los productos de una página del nlp_resultado.json.

        Args:
            pagina: dict con claves 'productos', 'precios', etc.

        Returns:
            Misma estructura con campo 'norm' añadido a cada producto.
        """
        pagina_norm = dict(pagina)
        productos_norm = []
        for producto in pagina.get("productos", []):
            resultado = self.normalizar(producto["texto"])
            productos_norm.append({
                **producto,
                "norm": {
                    "nombre_canonico": resultado.nombre_canonico,
                    "confianza_norm":  resultado.confianza_norm,
                    "metodo":          resultado.metodo,
                    "categoria":       resultado.categoria,
                    "marca":           resultado.marca,
                    "descartado":      resultado.descartado,
                }
            })
        pagina_norm["productos"] = productos_norm
        return pagina_norm

    def normalizar_folleto(self, nlp_json: dict) -> dict:
        """
        Normaliza todos los productos de un nlp_resultado.json completo.

        Args:
            nlp_json: dict cargado desde nlp_resultado.json

        Returns:
            Mismo dict con campo 'norm' añadido a cada producto de cada página.
        """
        resultado = dict(nlp_json)
        resultado["paginas"] = [
            self.normalizar_pagina(pag)
            for pag in nlp_json.get("paginas", [])
        ]

        # Métricas de normalización
        total = sum(
            len(pag.get("productos", []))
            for pag in resultado["paginas"]
        )
        matcheados = sum(
            1 for pag in resultado["paginas"]
            for p in pag.get("productos", [])
            if p.get("norm", {}).get("metodo") in ("exacto", "fuzzy")
        )
        descartados = sum(
            1 for pag in resultado["paginas"]
            for p in pag.get("productos", [])
            if p.get("norm", {}).get("descartado")
        )

        resultado["resumen_norm"] = {
            "total_productos":     total,
            "matcheados":          matcheados,
            "descartados":         descartados,
            "sin_match":           total - matcheados - descartados,
            "tasa_match":          round(matcheados / total, 3) if total else 0,
        }
        return resultado

    # ---------------------------- Métodos internos ----------------------------

    def _es_basura(self, texto: str) -> bool:
        for patron in self.PATRONES_BASURA:
            if patron.search(texto):
                return True
        return False

    def _extraer_marca(self, texto: str) -> Optional[str]:
        texto_lower = texto.lower()
        for marca in sorted(MARCAS_CONOCIDAS, key=len, reverse=True):
            if marca in texto_lower:
                return marca.title()
        return None

    def _limpiar(self, texto: str) -> str:
        """Limpieza textual: OCR errors, unidades, espacios."""
        for patron, reemplazo in self.CORRECCIONES_OCR:
            texto = patron.sub(reemplazo, texto)
        texto = " ".join(texto.split())
        return texto.strip()

    @staticmethod
    def _normalizar_base(texto: str) -> str:
        """
        Normalización profunda para comparación fuzzy:
        minúsculas + sin acentos + sin caracteres especiales.
        """
        texto = texto.lower().strip()
        # Quitar acentos
        texto = unicodedata.normalize("NFD", texto)
        texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
        # Quitar caracteres no alfanuméricos excepto espacios
        texto = re.sub(r"[^a-z0-9\s]", " ", texto)
        texto = " ".join(texto.split())
        return texto

    @staticmethod
    def _capitalizar(texto: str) -> str:
        """Capitalización de título en español."""
        minusculas = {"de", "del", "la", "las", "el", "los", "y", "en", "con", "sin"}
        palabras = texto.lower().split()
        resultado = []
        for i, p in enumerate(palabras):
            resultado.append(p if (i > 0 and p in minusculas) else p.capitalize())
        return " ".join(resultado)


# ---------------------------- CLI de prueba rápida ----------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    norm = Normalizador()

    casos_prueba = [
        # Errores OCR clásicos
        "PLATANO", "PLTANO", "cebolca", "Slmply Baslco",
        # Productos limpios
        "Aceite de coco orgánico extra virgen 450ml", "Aderezos 250g",
        "Chía 400g", "Vinagre de manzana orgánico 500ml",
        "Pasta para sopa", "Arroz; frijol,",
        # Con marca
        "Ariel Vivid", "Dog Chow", "Pantene shampoo", "Golden Hills Aceite vegetal",
        # Basura que debe descartar
        "del videojuego", "Visita tu tienda", "En línea de pintura vinílica",
        # Sin match esperado
        "Ropa interior microfibra", "Lentes de contacto de uso mensual",
    ]

    print(f"\n{'═'*70}")
    print(f"  Normalizador PriceScraper MX")
    print(f"  Catálogo: {len(CATALOGO_CANONICO)} productos canónicos")
    print(f"{'═'*70}")
    print(f"  {'TEXTO RAW':<38} {'RESULTADO'}")
    print(f"{''*70}")

    for texto in casos_prueba:
        r = norm.normalizar(texto)
        print(f"  {texto:<38} {r}")

    print(f"{''*70}\n")


if __name__ == "__main__":
    main()