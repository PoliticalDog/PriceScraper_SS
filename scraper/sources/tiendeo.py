"""
tiendeo.py
Adaptador específico para Tiendeo.com.mx

Estrategia para obtener TODAS las páginas del folleto:
  - Tiendeo usa Shopfully como visor con lazy loading
  - Solo carga ~5 páginas visibles al abrir el folleto
  - Solución: abrir el folleto en bloques usando ?flyerPage=N
    para forzar que el visor cargue páginas distintas en cada apertura
  - Se acumulan todas las URLs únicas capturadas por intercepción de red
"""

import re
import logging
from bs4 import BeautifulSoup
from ..metodos_scraper import BaseScraper

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


class TiendeoScraper(BaseScraper):

    FUENTE   = "tiendeo"
    BASE_URL = "https://www.tiendeo.mx"

    # ─── Listado de folletos ───────────────────────────────────────────────────

    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        async def _extraer():
            await self._navegar(categoria_url)
            await self._scroll_hasta_abajo(pasos=12) #6 para pruebas
            html = await self.page.content()
            return self._parsear_tarjetas(html)

        folletos = await self.reintentar(_extraer)
        logger.info(f"[Tiendeo] {len(folletos)} folletos encontrados")
        return folletos

    def _parsear_tarjetas(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        folletos = []

        for tarjeta in soup.select("a[href*='/Catalogos/']"):
            try:
                f = self._extraer_datos_tarjeta(tarjeta)
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

    def _extraer_datos_tarjeta(self, tarjeta) -> dict | None:
        href = tarjeta.get("href", "")
        match_id = re.search(r"/Catalogos/(\d+)", href)
        if not match_id:
            return None

        folleto_id = match_id.group(1)
        url_folleto = f"{self.BASE_URL}{href}" if href.startswith("/") else href

        # Solo usar la URL base del folleto sin parámetros extras
        url_folleto = f"{self.BASE_URL}/Catalogos/{folleto_id}"

        tienda = ""
        h4 = tarjeta.select_one("h4")
        if h4:
            tienda = h4.get_text(strip=True)

        titulo = ""
        h3 = tarjeta.select_one("h3")
        if h3:
            titulo = h3.get_text(strip=True)

        fecha_inicio, fecha_fin = self._extraer_fechas(tarjeta)
        url_preview = self._extraer_url_imagen(tarjeta, folleto_id)

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

    def _extraer_fechas(self, tarjeta) -> tuple[str | None, str | None]:
        img = tarjeta.select_one("img")
        if not img:
            return None, None
        alt = img.get("alt", "")
        patron = r"(\d{4}-\d{2}-\d{2})T[\d:.Z]+\s*-\s*(\d{4}-\d{2}-\d{2})T"
        match = re.search(patron, alt)
        if match:
            return match.group(1), match.group(2)
        return None, None

    def _extraer_url_imagen(self, tarjeta, folleto_id: str) -> str:
        for img in tarjeta.select("img"):
            src = img.get("src", "")
            if "volantini" in src or "publications" in src:
                if "small_" in src:
                    return src.replace("small_", "big_").replace("_webp.webp", "_webp_desktop.webp")
                return src
        return f"https://es-mx-media.shopfully.cloud/images/volantini/big_{folleto_id}_webp_desktop.webp"

    # ─── Páginas internas del folleto — bloques con flyerPage ────────────────

    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        """
        Captura TODAS las páginas del folleto abriendo el visor en bloques.

        El visor de Shopfully tiene lazy loading — solo carga ~5 páginas
        visibles al abrir. Para capturar todas, abrimos el folleto varias
        veces usando ?flyerPage=N para forzar que cargue bloques distintos:

          Bloque 1: ?flyerPage=1  → captura páginas 1-5
          Bloque 2: ?flyerPage=6  → captura páginas 6-10
          Bloque 3: ?flyerPage=11 → captura páginas 11-15
          ...

        Se detiene cuando un bloque no aporta URLs nuevas (fin del folleto).
        """
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

    async def _capturar_bloque(self, url_con_pagina: str) -> list[str]:
        """
        Abre el folleto en una URL específica con flyerPage=N
        e intercepta las peticiones de red para capturar las URLs
        de imágenes que el visor carga para ese bloque de páginas.
        """
        urls_capturadas: list[str] = []

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

        async def _extraer():
            self.page.on("request", _on_request)
            await self._navegar(url_con_pagina, esperar="networkidle")
            await self.page.wait_for_timeout(2500)
            await self._scroll_visor()
            await self.page.wait_for_timeout(1500)
            self.page.remove_listener("request", _on_request)

            if not urls_capturadas:
                # Fallback al DOM si el listener no capturó nada
                return await self._extraer_desde_dom()

            return urls_capturadas

        try:
            return await self.reintentar(_extraer, intentos=2)
        except Exception as e:
            logger.warning(f"[Tiendeo] Error en bloque {url_con_pagina}: {e}")
            return []

    async def _scroll_visor(self):
        """Scroll dentro del visor para activar carga de páginas adyacentes."""
        try:
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

    async def _extraer_desde_dom(self) -> list[str]:
        """Fallback: extrae URLs de imágenes directamente del DOM."""
        html = await self.page.content()
        soup = BeautifulSoup(html, "html.parser")
        urls = set()

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

        patron_url = r'https://[^"\']+(?:publications/page_assets|level_2)[^"\']+\.(?:webp|jpg|png)'
        for match in re.finditer(patron_url, html):
            urls.add(match.group(0))

        return list(urls)

    def _ordenar_paginas(self, urls: list[str]) -> list[str]:
        """Ordena las URLs por número de página extraído del patrón del CDN."""
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

    # ─── Métodos de conveniencia ──────────────────────────────────────────────

    async def scrapear_categoria(self, nombre_categoria: str) -> list[dict]:
        if nombre_categoria not in CATEGORIAS:
            raise ValueError(
                f"Categoría '{nombre_categoria}' no válida. "
                f"Opciones: {list(CATEGORIAS.keys())}"
            )
        return await self.obtener_folletos(CATEGORIAS[nombre_categoria])

    async def scrapear_tienda(self, slug_tienda: str) -> list[dict]:
        """
        Scraping de una tienda específica por su slug.

        Args:
            slug_tienda: Key del dict TIENDAS.
                         Ej: "walmart", "bodega-aurrera", "costco"
        """
        if slug_tienda not in TIENDAS:
            raise ValueError(
                f"Tienda '{slug_tienda}' no disponible. "
                f"Opciones: {list(TIENDAS.keys())}"
            )
        return await self.obtener_folletos(TIENDAS[slug_tienda])