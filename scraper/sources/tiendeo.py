# Tiendeo scraper personalizado

import re
import asyncio
import logging
from bs4 import BeautifulSoup
from ..metodos_scraper import BaseScraper

# inicialización del logger para este módulo
logger = logging.getLogger(__name__)

# categoria
CATEGORIAS = {
    "supermercados":   "https://www.tiendeo.mx/Folletos-Catalogos/hiper-supermercados"
}

# URLs directas por cada cadena Tiendeo
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

# Para romper el loop de bloques
MAX_PAGINAS = 60

# Numero de paginas por bloque (ventana del visor)
PAGINAS_POR_BLOQUE = 5

# Extrae el "publication ID" de una URL de la imagen
# page_assets/{publication_id}/{num_pagina}/page_{n}_level_{lvl}_{hash}.{ext}
PATRON_PUBLICATION_ID = re.compile(r"/page_assets/(\d+)/")

# Extrae el ID de publicación de una URL de imagen
def _publication_id(url: str) -> str | None:
    m = PATRON_PUBLICATION_ID.search(url)
    return m.group(1) if m else None

# clase prinicpal de tiendeo
class TiendeoScraper(BaseScraper):

    FUENTE   = "tiendeo"
    BASE_URL = "https://www.tiendeo.mx"

    # -------------------- Métodos principales de scraping --------------------

    # Obtiene los folletos listados en una categoría o tienda específica.
    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        async def _extraer():
            # carga los metodos estadnar de navegacion y carga
            await self._navegar(categoria_url)
            await self._scroll_hasta_abajo(pasos=12) # Con 12 se logra cargar todos los folletos
            html = await self.page.content()
            return self._parsear_tarjetas(html)

        # Segunda vuelta la extracción de folletos para manejar posibles bloqueos o fallos temporales
        folletos = await self.reintentar(_extraer)
        logger.info(f"[Tiendeo] {len(folletos)} folletos encontrados")
        """
            "tienda": "Soriana",
            "titulo": "Julio Regalado",
            "url_folleto": "...",
        """
        return folletos
    
    # Parsea las tarjetas de folletos en la página de categoría/tienda de html a dict con datos estructurados. 
    # se busca <a> que contiene la informacion del folleto
    def _parsear_tarjetas(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser") # b4 interpreta html y busca eleemntos en html y css
        folletos = []

        # revisa el html y halla las etioquetass <a> y evlua que tenga un id
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
        # ------ extra el id del folleto ------
        href = tarjeta.get("href", "")
        match_id = re.search(r"/Catalogos/(\d+)", href) # expresión regular: busca "/Catalogos/" seguido de dígitos y captura esos dígitos como ID del folleto
        if not match_id:
            return None

        # extrae el codifo id
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

        # La tarjeta "hero" contirne el nombre de lña tienda en un contenedor
        contenedor_busqueda = tarjeta
        if not tienda and not titulo:
            contenedor = tarjeta.find_parent(class_="js-flyer") or tarjeta.parent
            if contenedor:
                contenedor_busqueda = contenedor
                h4 = contenedor.select_one("h4")
                if h4:
                    tienda = h4.get_text(strip=True)
                h3 = contenedor.select_one("h3")
                if h3:
                    titulo = h3.get_text(strip=True)

        # Extraer fechas de inicio y fin del folleto desde el atributo alt de la imagen
        fecha_inicio, fecha_fin = self._extraer_fechas(contenedor_busqueda)
        url_preview = self._extraer_url_imagen(tarjeta, folleto_id)

        # Si no se pudo extraer ni tienda ni título se descarta
        if not tienda and not titulo:
            return None

        # Regresa un dict con los datos estructurados del folleto
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
        # Si no se encontró una imagen válida en la tarjeta, se construye la URL de preview usando el ID del folleto
        return f"https://es-mx-media.shopfully.cloud/images/volantini/big_{folleto_id}_webp_desktop.webp"

    # ------------------ Páginas internas del folleto — bloques con flyerPage ------------------

    # El visor carga las páginas en bloques usando el parámetro flyerPage=N, se navega por bloques
    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        # se captura desde la paghina 1
        todas_urls: set[str] = set()
        pagina_inicio = 1
        publication_id: str | None = None

        # Se itera sobre los bloques de páginas (flyerPage=1, 6, 11, ...)
        while pagina_inicio <= MAX_PAGINAS:
            url_bloque = f"{url_folleto}?flyerPage={pagina_inicio}"
            logger.info(f"[Tiendeo] Capturando bloque desde página {pagina_inicio}...")
            # Abre la URL del bloque de páginas y captura las URLs de las imágenes que el visor carga para ese bloque
            urls_bloque, publication_id = await self._capturar_bloque(url_bloque, publication_id)

            # si no hay mas paginas en el iguiente bloque, cierra
            if not urls_bloque:
                logger.info(f"[Tiendeo] Sin páginas en bloque {pagina_inicio} → fin del folleto")
                break
            
            nuevas = set(urls_bloque) - todas_urls
            # si no hay nuevas pagina se cierra
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

    # abre la URL del bloque de páginas y captura las URLs de las imágenes que el visor carga para ese bloque, usa un listener
    async def _capturar_bloque(self, url_con_pagina: str, publication_id_conocido: str | None = None
    ) -> tuple[list[str], str | None]:
    
        urls_capturadas: list[str] = []
        redirect_detectado = asyncio.Event() # evento para captar el redireccionamiento al finalizar el folleto
        indice_corte = [None]  # indice en urls_capturadas al momento del redirect

        # Cacha las peticiones para capturar SOLO URLs de imágenes
        def _on_request(request):
            url = request.url
            # valida que sea una URL con nivel de imagen
            if (
                "publications/page_assets" in url or
                "page_level" in url or
                "_level_2_" in url or
                "_level_1_" in url
            ):  
                # valida que la url sea de una imagen
                if any(ext in url for ext in [".webp", ".jpg", ".jpeg", ".png"]):
                    urls_capturadas.append(url)
                    logger.debug(f"[Tiendeo] Capturada: ...{url[-55:]}")

        # Detecta si la página navega a otra URL (redirect a otro catálogo)
        def _on_framenavigated(frame): # recibe el frame completo
            if frame == self.page.main_frame:
                # Compara la URL del frame con la URL del bloque actual, para detectar redirecciones a otro folleto
                if frame.url.split("?")[0] != url_con_pagina.split("?")[0]:
                    if not redirect_detectado.is_set():
                        indice_corte[0] = len(urls_capturadas)
                    redirect_detectado.set() # activa el evento de redirect

        # Abre la URL del bloque de páginas y espera a que se carguen las imágenes, mientras el listener captura las URLs
        async def _extraer():
            self.page.on("request", _on_request)    # listener para capturar las peticiones de imágenes
            self.page.on("framenavigated", _on_framenavigated)  # listener para detectar redirecciones
            try:
                await self._navegar(url_con_pagina, esperar="networkidle")

                # Esperar en pasos cortos, abortando si hay redirect
                for _ in range(5):  # 5 veces por 500 ms = 2.5 seg
                    if redirect_detectado.is_set():
                        logger.info(f"[Tiendeo] Redirect detectado en {url_con_pagina} "
                                    f"→ deteniendo captura de este bloque")
                        break
                    await self.page.wait_for_timeout(500)
                else:
                    # sino se redirigio hace mas scroll apra cachar mas imagenes del bloque
                    if not redirect_detectado.is_set():
                        await self._scroll_visor()
                        for _ in range(3):  # 3 x 500ms = 1500ms equivalente al timeout original
                            if redirect_detectado.is_set():
                                logger.info(f"[Tiendeo] Redirect detectado en {url_con_pagina} "
                                            f"→ deteniendo captura de este bloque")
                                break
                            await self.page.wait_for_timeout(500)
            finally:
                # vaciar listeners para evitar capturas cruzadas entre bloques
                self.page.remove_listener("request", _on_request)
                self.page.remove_listener("framenavigated", _on_framenavigated)

            # Si el listener no capturó nada, es posible que el visor haya cargado las páginas sin hacer peticiones nuevas o que haya un bloqueo. 
            # si es el caso se hace un fallback extrayendo URLs directamente del DOM
            if not urls_capturadas:
                if redirect_detectado.is_set():
                    return [], publication_id_conocido
                # Sin publication_id conocido no se puede validar el DOM;
                if publication_id_conocido is not None:
                    # si regres vacio con este falback es que no hay nada nuevo en el bloque
                    return [], publication_id_conocido
                return await self._extraer_desde_dom(), publication_id_conocido

            # Si hubo redirect, descarta los utlimos url capturados
            urls_validas = urls_capturadas
            # si el evento se activo
            if redirect_detectado.is_set() and indice_corte[0] is not None:
                descartadas = urls_capturadas[indice_corte[0]:]
                for url in descartadas:
                    logger.warning(f"[Tiendeo] Descartando página capturada tras "
                                   f"redirect: ...{url[-55:]}")
                urls_validas = urls_capturadas[:indice_corte[0]]

            return self._filtrar_por_publication_id(urls_validas, publication_id_conocido)
        # si no se pudo extraer nada que rompa el bloque
        # se reintenta 2 veces mas
        try:
            return await self.reintentar(_extraer, intentos=2)
        except Exception as e:
            logger.warning(f"[Tiendeo] Error en bloque {url_con_pagina}: {e}")
            return [], publication_id_conocido

   
    # filtra solo urls que sean de la misma publication_id
    def _filtrar_por_publication_id(self, urls: list[str], publication_id_conocido: str | None = None
    ) -> tuple[list[str], str | None]:
        if not urls:
            return urls, publication_id_conocido

        grupos: dict[str, list[str]] = {}
        for url in urls:
            pid = _publication_id(url)
            if pid is None:
                continue
            grupos.setdefault(pid, []).append(url)

        if not grupos:
            return urls, publication_id_conocido  # no se pudo determinar ningún publication_id, no filtrar

        # bajo publication_id se agrupan las URLs
        if publication_id_conocido is not None:
            if publication_id_conocido in grupos:
                for pid, urls_grupo in grupos.items():
                    if pid != publication_id_conocido:
                        for url in urls_grupo:
                            logger.warning(f"[Tiendeo] Descartando página de otro folleto "
                                           f"(publication_id={pid}, correcto={publication_id_conocido}): "
                                           f"...{url[-55:]}")
                return grupos[publication_id_conocido], publication_id_conocido
            else:
                # Ninguna URL de este bloque corresponde al folleto real
                for pid, urls_grupo in grupos.items():
                    for url in urls_grupo:
                        logger.warning(f"[Tiendeo] Descartando página de otro folleto "
                                       f"(publication_id={pid}, correcto={publication_id_conocido}): "
                                       f"...{url[-55:]}")
                return [], publication_id_conocido
            
        # Si no se conoce el publication_id, se asume que el grupo con más páginas es el correcto
        #  En caso de empate, se prefiere el que tenga URLs con "_level_4_"
        def _es_level_4(urls_grupo: list[str]) -> bool:
            return any("_level_4_" in u for u in urls_grupo)

        # Ordenar grupos por: (1) cantidad de páginas desc, (2) preferencia level_4
        id_correcto = max(grupos,key=lambda pid: (len(grupos[pid]), _es_level_4(grupos[pid])))

        if len(grupos) > 1:
            for pid, urls_grupo in grupos.items():
                if pid != id_correcto:
                    for url in urls_grupo:
                        logger.warning(f"[Tiendeo] Descartando página de otro folleto "
                                       f"(publication_id={pid}, correcto={id_correcto}): "
                                       f"...{url[-55:]}")

        return grupos[id_correcto], id_correcto
        
    # Scroll dentro del visor para activar carga de páginas adyacentes.
    async def _scroll_visor(self):
        try:
            # busca un iframe o contenedor del visor y hace scroll hasta el final para activar la carga de páginas adicionales
            # Si no encuentra un visor específico, hace scroll al final de la página
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

    # Ordena las URLs de las páginas del folleto por número de página extraído del patrón del CDN
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

    # Métodos públicos para scrapear por categoría o por tienda, que validan la entrada y llaman a obtener_folletos con la URL correspondiente
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