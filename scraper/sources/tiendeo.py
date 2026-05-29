# Tiendeo scraper

import re
import logging
from bs4 import BeautifulSoup
from ..metodos_scraper import BaseScraper

# inicialización del logger para este módulo
logger = logging.getLogger(__name__)

CATEGORIAS = {
    "supermercados":   "https://www.tiendeo.mx/Folletos-Catalogos/hiper-supermercados",
    "farmacias":       "https://www.tiendeo.mx/Folletos-Catalogos/farmacias-y-salud",
    "departamentales": "https://www.tiendeo.mx/Folletos-Catalogos/tiendas-departamentales",
    "electronica":     "https://www.tiendeo.mx/Folletos-Catalogos/electronica-y-tecnologia",
    "hogar":           "https://www.tiendeo.mx/Folletos-Catalogos/hogar-muebles",
}

# URLs directas por tienda en Tiendeo
TIENDAS = {
    "bodega-aurrera":   "https://www.tiendeo.mx/ofertas-folletos/bodega-aurrera",
    "walmart":          "https://www.tiendeo.mx/Folletos-Catalogos/walmart",
    "sams-club":        "https://www.tiendeo.mx/Folletos-Catalogos/sams-club",
    "soriana-hiper":    "https://www.tiendeo.mx/Folletos-Catalogos/soriana-hiper",
    "heb":              "https://www.tiendeo.mx/Folletos-Catalogos/heb",
    "chedraui":         "https://www.tiendeo.mx/Folletos-Catalogos/chedraui",
    "s-mart":           "https://www.tiendeo.mx/Folletos-Catalogos/s-mart",
    "oxxo":             "https://www.tiendeo.mx/Folletos-Catalogos/oxxo",
    "casa-ley":         "https://www.tiendeo.mx/Folletos-Catalogos/casa-ley",
    "soriana-mercado":  "https://www.tiendeo.mx/Folletos-Catalogos/soriana-mercado",
    "costco":           "https://www.tiendeo.mx/Folletos-Catalogos/costco",
    "alsuper":          "https://www.tiendeo.mx/Folletos-Catalogos/alsuper",
    "tiendas-3b":       "https://www.tiendeo.mx/ofertas-catalogos/tiendas-3b",
    "waldos":           "https://www.tiendeo.mx/Folletos-Catalogos/waldos",
    "la-comer":         "https://www.tiendeo.mx/ofertas-folletos/la-comer",
    "merco":            "https://www.tiendeo.mx/ofertas-catalogos/merco",
}

# Máximo de páginas esperadas por folleto (para el loop de bloques)
MAX_PAGINAS = 60

# Cuántas páginas captura el visor por apertura (~5 en la práctica)
PAGINAS_POR_BLOQUE = 5

# Tiendeo tiene un sistema de detección de bots que a veces bloquea el acceso
class TiendeoScraper(BaseScraper):

    FUENTE   = "tiendeo"
    BASE_URL = "https://www.tiendeo.mx"

    # ---------------- Métodos principales de scraping ----------------

    # Obtiene los folletos listados en una categoría o tienda específica.
    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        async def _extraer():
            await self._navegar(categoria_url)
            await self._scroll_hasta_abajo(pasos=12) # Con 12 se logra cargar todos los folletos
            html = await self.page.content()
            return self._parsear_tarjetas(html)

        folletos = await self.reintentar(_extraer)
        logger.info(f"[Tiendeo] {len(folletos)} folletos encontrados")
        """
            Regresa:
                {
                    "tienda": "Soriana",
                    "titulo": "Julio Regalado",
                    "url_folleto": "...",
                }     
        """
        return folletos
    
    # Parsea las tarjetas de folletos en la página de categoría/tienda de html a dict con datos estructurados. 
    # Cada tarjeta es un enlace <a> que contiene info del folleto.
    def _parsear_tarjetas(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        folletos = []

        # Cada tarjeta de folleto es un <a> con href que incluye "/Catalogos/ID"
        for tarjeta in soup.select("a[href*='/Catalogos/']"):
            try:
                f = self._extraer_datos_tarjeta(tarjeta) # Extrae datos de la tarjeta a un dict estructurado
                if f:
                    folletos.append(f)
            except Exception as e:
                logger.warning(f"Error parseando tarjeta: {e}")

        # Deduplicar por URL
        vistos, unicos = set(), []
        for f in folletos:
            if f["url_folleto"] not in vistos:
                vistos.add(f["url_folleto"])
                unicos.append(f)
        return unicos

    # Extrae datos de una tarjeta de folleto a un dict con campos estructurados
    def _extraer_datos_tarjeta(self, tarjeta) -> dict | None:
        href = tarjeta.get("href", "")
        match_id = re.search(r"/Catalogos/(\d+)", href) # expresión regular: busca "/Catalogos/" seguido de dígitos y captura esos dígitos como ID del folleto
        if not match_id:
            return None

        folleto_id = match_id.group(1)
        url_folleto = f"{self.BASE_URL}{href}" if href.startswith("/") else href

        # Solo usar la URL base del folleto sin parámetros extras
        url_folleto = f"{self.BASE_URL}/Catalogos/{folleto_id}"

        # Extraer tienda y título de la tarjeta, si están disponibles
        tienda = ""
        h4 = tarjeta.select_one("h4")
        if h4:
            tienda = h4.get_text(strip=True)

        titulo = ""
        h3 = tarjeta.select_one("h3")
        if h3:
            titulo = h3.get_text(strip=True)

        # Extraer fechas de inicio y fin del folleto desde el atributo alt de la imagen, si está disponible
        fecha_inicio, fecha_fin = self._extraer_fechas(tarjeta)
        url_preview = self._extraer_url_imagen(tarjeta, folleto_id)

        # Si no se pudo extraer ni tienda ni título se descarta
        if not tienda and not titulo:
            return None

        return {
            "fuente":       self.FUENTE,
            "folleto_id":   folleto_id,
            "tienda":       tienda,
            "titulo":       titulo,
            "url_folleto":  url_folleto,
            "url_preview":  url_preview,
            "fecha_inicio": fecha_inicio,
            "fecha_fin":    fecha_fin,
        }

    # Extrae las fechas de inicio y fin del folleto a partir de la tarjeta
    def _extraer_fechas(self, tarjeta) -> tuple[str | None, str | None]:
        
        # busca la imagen dentro de la tarjeta y extrae las fechas del atributo alt usando regex
        img = tarjeta.select_one("img")
        if not img:
            return None, None
        alt = img.get("alt", "") # obtiene el alt, contiene las fechas en formato "2024-06-01T... - 2024-06-30T..."
        patron = r"(\d{4}-\d{2}-\d{2})T[\d:.Z]+\s*-\s*(\d{4}-\d{2}-\d{2})T"
        match = re.search(patron, alt)
        if match:
            return match.group(1), match.group(2)
        return None, None

    # Extrae la URL de la imagen del folleto a partir de la tarjeta
    def _extraer_url_imagen(self, tarjeta, folleto_id: str) -> str:
        for img in tarjeta.select("img"):
            src = img.get("src", "")
            # El src puede tener "small_" o "big_" y a veces no tiene ninguno. Queremos la versión de mayor calidad disponible.
            if "volantini" in src or "publications" in src:
                if "small_" in src:
                    return src.replace("small_", "big_").replace("_webp.webp", "_webp_desktop.webp")
                return src
        # Si no se encontró una imagen válida en la tarjeta, construir la URL de preview usando el ID del folleto (fallback)
        return f"https://es-mx-media.shopfully.cloud/images/volantini/big_{folleto_id}_webp_desktop.webp"

    # ------------------ Páginas internas del folleto — bloques con flyerPage ------------------

    # El visor de folletos de Tiendeo carga las páginas en bloques usando el parámetro flyerPage=N.
    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        
        todas_urls: set[str] = set()
        pagina_inicio = 1

        while pagina_inicio <= MAX_PAGINAS:
            url_bloque = f"{url_folleto}?flyerPage={pagina_inicio}"
            logger.info(f"[Tiendeo] Capturando bloque desde página {pagina_inicio}...")

            urls_bloque = await self._capturar_bloque(url_bloque)

            if not urls_bloque:
                logger.info(f"[Tiendeo] Sin páginas en bloque {pagina_inicio} → fin del folleto")
                break

            nuevas = set(urls_bloque) - todas_urls
            if not nuevas:
                logger.info(f"[Tiendeo] Sin páginas nuevas en bloque {pagina_inicio} → fin del folleto")
                break

            todas_urls.update(nuevas)
            logger.info(f"[Tiendeo] +{len(nuevas)} páginas nuevas "
                       f"(total acumulado: {len(todas_urls)})")

            pagina_inicio += PAGINAS_POR_BLOQUE

        paginas = self._ordenar_paginas(list(todas_urls))
        logger.info(f"[Tiendeo] {len(paginas)} páginas totales en {url_folleto}")
        return paginas

    # abre la URL del bloque de páginas y captura las URLs de las imágenes que el visor carga para ese bloque, 
    # usando un listener de peticiones de red. 
    # Si no se capturan URLs por este método, hace un fallback extrayendo URLs directamente del DOM.
    async def _capturar_bloque(self, url_con_pagina: str) -> list[str]:
    
        urls_capturadas: list[str] = []

        # Listener de peticiones para capturar URLs de imágenes que el visor carga al abrir el bloque de páginas
        def _on_request(request):
            url = request.url
            if (
                "publications/page_assets" in url or
                "page_level" in url or
                "_level_2_" in url or
                "_level_1_" in url
            ):
                if any(ext in url for ext in [".webp", ".jpg", ".jpeg", ".png"]):
                    urls_capturadas.append(url)
                    logger.debug(f"[Tiendeo] Capturada: ...{url[-55:]}")

        # El bloque de código que abre la URL del bloque de páginas y espera a que se carguen las imágenes, mientras el listener captura las URLs
        async def _extraer():
            self.page.on("request", _on_request)
            await self._navegar(url_con_pagina, esperar="networkidle")
            await self.page.wait_for_timeout(2500)
            await self._scroll_visor()
            await self.page.wait_for_timeout(1500)
            self.page.remove_listener("request", _on_request)

            # Si el listener no capturó nada, es posible que el visor haya cargado las páginas sin hacer peticiones nuevas o que haya un bloqueo. 
            # En ese caso, hacemos un fallback extrayendo URLs directamente del DOM.
            if not urls_capturadas:
                # Fallback al DOM si el listener no capturó nada
                return await self._extraer_desde_dom()

            return urls_capturadas

        try:
            return await self.reintentar(_extraer, intentos=2)
        except Exception as e:
            logger.warning(f"[Tiendeo] Error en bloque {url_con_pagina}: {e}")
            return []
        
    # Scroll dentro del visor para activar carga de páginas adyacentes.
    async def _scroll_visor(self):
        try:
            # busca un iframe o contenedor del visor y hace scroll hasta el final para activar la carga de páginas adicionales. 
            # Si no encuentra un visor específico, hace scroll al final de la página.
            await self.page.evaluate("""
                () => {
                    const visor = document.querySelector(
                        'iframe, .catalog-viewer, .publication-viewer, [class*="viewer"]'
                    );
                    if (visor) visor.scrollTop = visor.scrollHeight;
                    else window.scrollTo(0, document.body.scrollHeight);
                }
            """)
            await self.page.wait_for_timeout(800)
        except Exception as e:
            logger.debug(f"[Tiendeo] Scroll visor: {e}")

    # Fallback para extraer URLs de imágenes directamente del DOM si el listener de peticiones no capturó nada
    async def _extraer_desde_dom(self) -> list[str]:
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        urls = set()
        
        # Se buscan las imágenes de varias posibilidades de atributos (src, data-src, data-lazy-src) 
        # Y se filtran por patrones que indican que son páginas del folleto.
        for img in soup.select("img"):
            for attr in ["src", "data-src", "data-lazy-src"]:
                src = img.get(attr, "")
                if src and ("publications" in src or "page_assets" in src
                           or "level_2" in src):
                    urls.add(src)

        for img in soup.select("img[srcset]"):
            for parte in img.get("srcset", "").split(","):
                url = parte.strip().split(" ")[0]
                if "publications" in url or "level_2" in url:
                    urls.add(url)

        # Se puede buscar directamente en el HTML con regex para capturar cualquier URL que tenga los patrones esperados, 
        patron_url = r'https://[^"\']+(?:publications/page_assets|level_2)[^"\']+\.(?:webp|jpg|png)'
        for match in re.finditer(patron_url, html):
            urls.add(match.group(0))

        return list(urls)

    # Ordena las URLs de las páginas del folleto por número de página extraído del patrón del CDN.
    def _ordenar_paginas(self, urls: list[str]) -> list[str]:
        def _extraer_numero(url: str) -> int:
            m = re.search(r"/page_assets/\d+/(\d+)/", url)
            if m:
                return int(m.group(1))
            m = re.search(r"page_(\d+)_level", url)
            if m:
                return int(m.group(1))
            return 0

        urls_unicas = list(set(urls))
        nivel_2 = [u for u in urls_unicas if "level_2" in u]
        if nivel_2:
            return sorted(nivel_2, key=_extraer_numero)
        return sorted(urls_unicas, key=_extraer_numero)

    # ----------------- Scrapeo por categoria o tienda -----------------

    # Métodos públicos para scrapear por categoría o por tienda, que validan la entrada y llaman a obtener_folletos con la URL correspondiente.
    async def scrapear_categoria(self, nombre_categoria: str) -> list[dict]:
        if nombre_categoria not in CATEGORIAS:
            raise ValueError(
                f"Categoría '{nombre_categoria}' no válida. "
                f"Opciones: {list(CATEGORIAS.keys())}"
            )
        return await self.obtener_folletos(CATEGORIAS[nombre_categoria])

    # Scraping de una tienda específica por su slug.
    async def scrapear_tienda(self, slug_tienda: str) -> list[dict]:
        # "walmart", "bodega-aurrera", "costco"
        if slug_tienda not in TIENDAS:
            raise ValueError(
                f"Tienda '{slug_tienda}' no disponible. "
                f"Opciones: {list(TIENDAS.keys())}"
            )
        return await self.obtener_folletos(TIENDAS[slug_tienda])