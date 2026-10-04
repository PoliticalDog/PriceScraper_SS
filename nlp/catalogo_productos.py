# Catalogo de productos por categoría
# buscar_categoria --> es la unica funcion y busca una aparición de keywords en el texto y devuelve la categoría correspondiente

import re

# Catalogo de categorías y sus keywords asociadas para clasificación de productos mas comunes
CATALOGO = {

    # ----------------------- Línea blanca -----------------------
    "linea_blanca": {
        "nombre": "Línea Blanca",
        "keywords": [
            "lavadora", "lavasecadora", "secadora", "refrigerador", "refri",
            "congelador", "estufa", "horno", "lavavajillas",
            "lava trastes", "campana", "extractor", "minisplit", "aire acondicionado",
            "calentador", "boiler", "tanque de gas", "calefactor",
            # ventilador / enfriador --> pequeños electrodomésticos (criterio del ground truth)
            "climatizador", "purificador", "despachador",
            "mabe", "whirlpool", "lg", "samsung appliances", "acros",
            "koblenz estufa", "teka", "bosch lavadora",
        ]
    },

    # ----------------------- Electrónica y tecnología -----------------------------------------------
    "electronica": {
        "nombre": "Electrónica",
        "keywords": [
            "televisor", "television", "smart tv", "pantalla", "monitor",
            "laptop", "computadora", "pc", "tablet", "ipad",
            "celular", "smartphone", "iphone", "samsung galaxy", "motorola",
            "audifonos", "audífonos", "bocina", "bocina bluetooth", "soundbar",
            "proyector", "camara", "cámara", "gopro", "drone",
            "consola", "playstation", "xbox", "nintendo", "switch",
            "impresora", "escaner", "router", "modem",
            "memoria usb", "disco duro", "ssd", "tarjeta sd",
            "cargador", "power bank", "cable hdmi",
            "4k uhd", "oled", "qled", "webos", "android tv",
            "mpx", "pulgadas",
            "tv", "multifuncional", "teclado", "barra de sonido", "subwoofer",
            "roku", "streaming", "eco tank", "ecotank", "tinta continua",
        ]
    },

    # ----------------------- Videojuegos -----------------------
    "videojuegos": {
        "nombre": "Videojuegos",
        "keywords": [
            "videojuego", "video juego", "playstation", "ps5", "ps4",
            "xbox series", "xbox one", "nintendo switch", "game",
            "control inalambrico", "mando", "joystick",
            "fifa", "call of duty", "fortnite", "zelda", "mario",
            "minecraft", "spider-man", "gta",
        ]
    },

    # ----------------------- Pequeños electrodomésticos -----------------------
    "pequenos_electrodomesticos": {
        "nombre": "Pequeños Electrodomésticos",
        "keywords": [
            "licuadora", "batidora", "tostador", "cafetera", "exprimidor",
            "sandwichera", "waflera", "plancha", "freidora", "airfryer",
            "air fryer", "parrilla electrica", "asador", "vaporera",
            "procesador", "minipimer", "juguera", "extractor de jugos",
            "hervidor", "tetera electrica", "arrocera", "olla express",
            "multicocina", "instant pot",
            "oster", "hamilton beach", "black decker", "cuisinart",
            "taurus", "atvio", "daewoo", "t-fal", "tfal",
            "ventilador", "enfriador", "microondas",
        ]
    },

    # ----------------------- Ropa y calzado -----------------------
    "ropa": {
        "nombre": "Ropa y Calzado",
        "keywords": [
            "playera", "camiseta", "camisa", "blusa", "top",
            "pantalon", "pantalón", "jeans", "mezclilla", "short", "bermuda",
            "falda", "vestido", "conjunto", "pijama", "pijamas",
            "sudadera", "chamarra", "chaqueta", "abrigo", "saco",
            "calcetines", "calcetas", "medias",
            "ropa interior", "calzon", "calzón", "brassiere", "bra",
            "tenis", "zapatos", "zapatillas", "botas", "sandalias",
            "huaraches", "pantuflas", "mocasines",
            "talla", "tallas", "ch-eg", "ch-eeg", "s-xl", "s-xxl",
            "simply basic", "george", "op", "faded glory",
            "balerinas", "camisón", "camison",
            "pants", "pants pierna", "pants pierna ancha",
        ]
    },

    # ----------------------- Alimentos y bebidas -----------------------
    "alimentos": {
        "nombre": "Alimentos y Bebidas",
        "keywords": [
            "leche", "yogurt", "queso", "crema", "mantequilla", "margarina",
            "huevo", "carne", "pollo", "res", "cerdo", "pescado", "atun",
            "jamón", "jamon", "salchicha", "chorizo",
            "aceite", "aceite vegetal", "aceite de oliva",
            "arroz", "frijoles", "lentejas", "azucar", "azúcar", "sal", "harina",
            "pasta", "sopa", "cereal", "avena", "granola",
            "galletas", "pan bimbo", "pan de caja", "pan integral", "bimbo", "tortillas", "tostadas",
            "refresco", "agua natural", "jugo", "café", "chocolate",
            "cerveza", "vino", "bebida",
            "mayonesa", "ketchup", "salsa", "vinagre", "mostaza",
            "chocolate", "nescafé", "quesos",
            # (detergente, jabón, shampoo y acondicionador ya viven en limpieza / cuidado personal)
            # despensa
            "frijol", "lenteja", "maiz", "maíz", "maseca", "quaker",
            "cafe", "nescafe", "dolca", "soluble",
            "galleta", "gamesa", "marinela", "oreo",
            "pan", "telera", "pastel", "pizza",
            "mole", "consome", "consomé", "catsup", "aderezo", "mermelada", "miel", "jarabe",
            "manteca", "achiote", "chamoy", "gelatina", "flan", "helado", "bolis",
            "botana", "chips", "totopos", "palomitas", "cacahuate", "dulce", "tamarindo",
            "sabritas", "barcel", "doritos", "ruffles", "tostitos", "papas",
            # lácteos
            "yoghurt", "yoplait", "danonino", "lala", "alpura", "yakult", "lacteo", "lácteo", "carnation",
            # carnes y mariscos
            "bistec", "filete", "costilla", "chuleta", "arrachera", "sirloin", "t bone", "molida",
            "pierna", "tocino", "salchichon", "pechuga", "pavo", "boneless", "cochinita",
            "camaron", "camarón", "mojarra", "tilapia", "basa", "bagre", "salmon", "salmón",
            "surimi", "almeja", "pulpa",
            # bebidas
            "agua purificada", "agua mineral", "agua de manantial", "agua tonica", "agua tónica",
            "coca-cola", "coca cola", "pepsi", "nectar", "néctar", "gatorlyte", "suerox", "electrolit",
            "tequila", "mezcal", "whisky", "vodka", "ginebra", "ron", "licor", "sangrita",
            "clamato", "kermato",
            # marcas de abarrotes
            "herdez", "la costena", "la costeña", "clemente jacques", "isadora",
            # verdura/fruta procesada: más específica que la fresca, gana por longitud
            "pure de tomate", "puré de tomate", "coctel de tomate", "tomates molidos",
            "concentrado de tomate", "grano de elote", "elote dorado", "rajas", "chipotle",
            "jalapeno", "jalapeño", "chile en polvo", "papa congelada", "en tiras",
            "almibar", "almíbar", "postre", "mousse", "tortitas",
        ]
    },

    # ----------------------- Frutas y verduras frescas -----------------------
    "frutas_verduras": {
        "nombre": "Frutas y Verduras",
        "keywords": [
            "melon", "melón", "sandia", "sandía", "papa", "jicama", "jícama",
            "chile", "cebolla", "tomate", "jitomate", "aguacate", "limon", "limón",
            "zanahoria", "elote", "brocoli", "brócoli", "lechuga", "pepino",
            "manzana", "platano", "plátano", "naranja", "granel",
            "fresa", "frambuesa", "arandano", "arándano", "zarzamora", "uva", "uvas",
            "pina", "piña", "mango", "durazno", "cereza", "mandarina", "pera", "tuna",
            "acelga", "espinaca", "calabacita", "calabaza", "chayote", "cilantro",
            "champinones", "champiñones", "tomatillo", "cebollita", "aguacatito",
            "manojo", "fruta", "verdura",
        ]
    },

    # ----------------------- Despensa y limpieza del hogar -----------------------
    "limpieza": {
        "nombre": "Limpieza del Hogar",
        "keywords": [
            "detergente", "suavizante", "cloro", "fabuloso", "pinol", "ajax",
            "ariel", "tide", "downy", "roma", "ace",
            "escoba", "trapeador", "cubeta", "esponja", "jerga",
            "bolsas de basura", "bolsa basura",
            "papel de cocina", "papel higiénico", "papel higienico",
            "servilletas", "pañuelos",
            "insecticida", "raid", "off",
            "lavatrastes", "acido muriatico", "ácido muriático", "aceite de pino",
            "para trastes", "jabon para trastos",
        ]
    },

    # ----------------------- Cuidado personal -----------------------
    "cuidado_personal": {
        "nombre": "Cuidado Personal",
        "keywords": [
            "shampoo", "acondicionador", "tinte", "tinte para cabello",
            "crema", "locion", "loción", "bloqueador", "bronceador",
            "desodorante", "antitranspirante",
            "pasta dental", "cepillo dental", "enjuague bucal",
            "rastrillos", "rastrillo", "crema de afeitar",
            "pañales", "pañal", "toallitas", "toallas sanitarias",
            "tampones", "protectores",
            "perfume", "colonia",
            "crema dental", "crema corporal", "crema de manos", "desodorante",
            "jabon liquido corporal", "jabón líquido corporal", "jabon", "jabón",
        ]
    },

    # ----------------------- Muebles y hogar -----------------------
    "muebles_hogar": {
        "nombre": "Muebles y Hogar",
        "keywords": [
            "silla", "sillon", "sillón", "mesa", "escritorio", "librero",
            "cama", "colchon", "colchón", "almohada", "cobija", "sabanas",
            "cortinas", "tapete", "alfombra",
            "lampara", "lámpara", "foco", "led", "tira led",
            "organizador", "caja", "bote", "canasta", "cajón",
            "estante", "anaquel", "rack",
            "cuadro", "espejo", "reloj de pared",
            "ventilador de techo", "abanico",
            "vasos", "tazon", "tazón",
        ]
    },

    # ----------------------- Herramientas y ferretería -----------------------
    "herramientas": {
        "nombre": "Herramientas",
        "keywords": [
            "taladro", "sierra", "llave", "desarmador", "martillo",
            "pintura", "impermeabilizante", "sellador", "cemento",
            "escalera", "taburete", "andamio",
            "cinta", "cinta canela", "cinta masking",
            "lija", "brocha", "rodillo",
            "extensión", "extension electrica", "multicontacto",
            "foco", "socket",
            "aceite para motor", "aceite de motor", "motor oil", "aceite para transmision",
        ]
    },

    # ----------------------- Juguetes y bebés -----------------------
    "juguetes": {
        "nombre": "Juguetes y Bebés",
        "keywords": [
            "juguete", "muñeca", "carrito", "lego", "bloques",
            "pelota", "bicicleta", "patineta", "triciclo",
            "pañal", "biberón", "biberon", "mamila", "carriola",
            "silla de bebe", "asiento bebe",
        ]
    },

    # ----------------------- Deportes y ejercicio -----------------------
    "deportes": {
        "nombre": "Deportes y Ejercicio",
        "keywords": [
            "bicicleta", "caminadora", "eliptica", "elíptica", "pesa",
            "mancuerna", "colchoneta", "mat yoga", "pelota ejercicio",
            "mochila", "bolsa deportiva", "termo",
            "jersey", "uniforme deportivo",
        ]
    },

    # ----------------------- Mascotas -----------------------
    "mascotas": {
        "nombre": "Mascotas",
        "keywords": [
            "croquetas", "alimento para perro", "alimento para gato",
            "pedigree", "purina", "whiskas", "dog chow",
            "arena para gato", "correa", "collar",
            "shampoo para mascotas", "antipulgas",
        ]
    },

    # ----------------------- Farmacia y salud -----------------------
    "farmacia": {
        "nombre": "Farmacia y Salud",
        "keywords": [
            "vitaminas", "suplemento", "proteina", "proteína",
            "termómetro", "termometro", "tensiómetro", "oximetro",
            "cubrebocas", "guantes", "alcohol", "gel antibacterial",
            "aspirina", "paracetamol", "ibuprofeno",
            "tabletas", "capsulas", "cápsulas",
        ]
    },

    # ----------------------- Óptica -----------------------
    "optica": {
        "nombre": "Óptica",
        "keywords": [
            "lentes", "armazón", "armazon", "gafas", "anteojos",
            "lentes de sol", "lentes de contacto",
        ]
    },

    # ----------------------- Atributos técnicos de producto -----------------------
    # Características que describen un producto y aparecen como bloques independientes
    # en folletos. Se clasifican como ATRIBUTO en lugar de PRODUCTO o DESCARTE.
    "atributos_tecnicos": {
        "nombre": "Atributo Técnico",
        "keywords": [
            # Cocina / línea blanca
            "quemadores", "quemadores sellados", "encendido manual",
            "encendido electrónico", "encendido electronico",
            "convertible a gas natural", "capelo de cristal",
            "termocontrol", "perfect cook", "easyhandle",
            "jaladera", "parrilla", "parrilla electrica",
            # Electrodomésticos pequeños
            "velocidades", "función de descongelado", "funcion de descongelado",
            "niveles de potencia", "menus de coccion", "menús de cocción",
            "cocción automática", "coccion automatica",
            "boton de un toque", "botón de un toque",
            "perilla selectora",
            # Electrónica / tecnología
            "watts", "watt", "pantalla ips", "pantalla lcd",
            "resolución", "resolucion", "frecuencia de actualización",
            "batería de", "bateria de", "mah", "autonomía",
            "ram", "almacenamiento interno", "procesador",
            "cámara principal", "camara principal",
            "lente gran angular", "zoom óptico", "zoom optico",
            # General
            "luces rgb", "multicolores", "recargable",
            "potencia de", "capacidad de",
            "sonido potente", "sonido envolvente",
            # Controles de electrodoméstico
            "boton de un toque", "botón de un toque", "botòn de un toque",
            "perilla selectora", "selector de",
            "panel de control", "display digital",
        ]
    },

}


# ----------------------------------- Función de búsqueda -----------------------------------

# Reglas de coincidencia (oct-2026):
#  - keywords de <=3 letras exigen palabra completa
#  - las demás no pueden empezar a mitad de palabra (evita "pollo" en "Apollo", "game" en
#    "Pegamento"), pero sí pueden ir pegadas a un número ("48mpx"), a un "de" que el OCR
#    pegó ("DEPOLLO") o a una letra basura al inicio del token ("IQUESO")
#  - si coinciden varias categorías gana la keyword MÁS LARGA (más específica), no la primera
#    del catálogo: "camaron" > "cama", "frijol" > "refri", "crema dental" > "crema"
_LETRA = "a-záéíóúñü"
_PATRONES = []
for _clave, _datos in CATALOGO.items():
    for _kw in _datos["keywords"]:
        _k = _kw.lower()
        if len(_k) <= 3:
            _pat = re.compile(r"\b" + re.escape(_k) + r"\b")
        else:
            _pat = re.compile(
                rf"(?:(?<![{_LETRA}])|(?<=de)|(?<=^[{_LETRA}])|(?<=[^{_LETRA}][{_LETRA}]))" + re.escape(_k)
            )
        _PATRONES.append((len(_k), _clave, _datos["nombre"], _pat))
# más largas primero; en empate se respeta el orden del catálogo (sort estable)
_PATRONES.sort(key=lambda x: -x[0])


# Busca similitud de texto con catalogo de categorías y keywords
# (True, nombre_categoria, es_atributo) si hay match (False, "", False) si no hay match
def buscar_categoria(texto: str) -> tuple[bool, str, bool]: # # Retorna (encontrado, nombre_categoria, es_atributo)
    texto_lower = texto.lower()
    for _, clave, nombre, patron in _PATRONES:
        if patron.search(texto_lower):
            return True, nombre, clave == "atributos_tecnicos"
    return False, "", False