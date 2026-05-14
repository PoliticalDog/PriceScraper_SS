"""
ofertomat.py  — v2
Adaptador para Ofertomat.mx — versión corregida.

Cambios respecto a v1:
  1. _navegar usa domcontentloaded (fix timeout)
  2. _parsear_tarjetas filtra logos, redes sociales y basura
  3. folleto_id extrae el número al FINAL de la URL (ej: 127756)
  4. Páginas se construyen directamente desde el CDN de Leaflets
     → no necesita iframe ni intercepción de red
  5. El navegador se reutiliza dentro de cada sesión (fix Page crashed)

CDN descubierto:
  Portada:  na.leafletscdn.com/mx/data/1/{id}/0.jpg
  Páginas:  na.leafletscdn.com/mx/data/1/{id}/{num_pagina}.jpg
"""

import re
import logging
from bs4 import BeautifulSoup
from ..metodos_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Tiendas disponibles con sus slugs
TIENDAS = {
    "walmart":          "https://www.ofertomat.mx/walmart/",
    "bodega-aurrera":   "https://www.ofertomat.mx/bodega-aurrera/",
    "soriana":          "https://www.ofertomat.mx/soriana/",
    "chedraui":         "https://www.ofertomat.mx/chedraui/",
    "la-comer":         "https://www.ofertomat.mx/la-comer/",
    "costco":           "https://www.ofertomat.mx/costco/",
    "heb":              "https://www.ofertomat.mx/h-e-b/",
    "sams-club":        "https://www.ofertomat.mx/sams-club/",
    "oxxo":             "https://www.ofertomat.mx/oxxo/",
    "s-mart":           "https://www.ofertomat.mx/s-mart/",
    "walmart-express":  "https://www.ofertomat.mx/walmart-express/",
    "alsuper":          "https://www.ofertomat.mx/alsuper/",
    "7-eleven":         "https://www.ofertomat.mx/7-eleven/",
    "calimax":          "https://www.ofertomat.mx/calimax/",
    "casa-ley":         "https://www.ofertomat.mx/casa-ley/",
}

URL_SUPERMERCADOS = "https://www.ofertomat.mx/supermercados/"

# CDN base de Leaflets para Ofertomat
CDN_BASE = "https://na.leafletscdn.com/mx/data/1"

# Palabras que indican que una tarjeta NO es un folleto real
PALABRAS_BASURA = {
    "logo", "facebook", "youtube", "instagram", "twitter",
    "offers", "←", "→", "iniciar", "registrarse", "busca",
    "confirmar", "ubicación", "guardado",
}


class OfertomatScraper(BaseScraper):

    FUENTE   = "ofertomat"
    BASE_URL = "https://www.ofertomat.mx"
    _tienda_actual = ""  # slug de la tienda que se está scrapeando

    # ── Override de _navegar para Ofertomat ───────────────────────────────────
    async def _navegar(self, url: str, esperar: str = "domcontentloaded"):
        """
        Ofertomat tiene requests continuas de geolocalización/analytics
        que impiden que networkidle se alcance. Usamos domcontentloaded
        y esperamos 3 segundos manualmente.
        """
        try:
            logger.info(f"Navegando a: {url}")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await self.page.wait_for_timeout(3000)
            await self._delay_aleatorio()
        except Exception as e:
            logger.error(f"Error navegando a {url}: {e}")
            raise

    # ── Listado de folletos ───────────────────────────────────────────────────

    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        # Guardar el slug de la tienda actual para filtrar tarjetas
        # Ej: 'https://www.ofertomat.mx/walmart/' → 'walmart'
        partes = [p for p in categoria_url.replace(self.BASE_URL, "").split("/") if p]
        self._tienda_actual = partes[0] if partes else ""

        async def _extraer():
            await self._navegar(categoria_url)
            await self._scroll_hasta_abajo(pasos=4)
            html = await self.page.content()
            return self._parsear_tarjetas(html)

        folletos = await self.reintentar(_extraer)
        logger.info(f"[Ofertomat] {len(folletos)} folletos encontrados en {categoria_url}")
        return folletos

    def _parsear_tarjetas(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        folletos = []

        # Extraer tienda base de la URL de categoría que se está scrapeando
        # para filtrar solo folletos de esa tienda
        tienda_base = self._tienda_actual

        for a in soup.select("a[href]"):
            href = a.get("href", "")

            # Debe contener un ID numérico de 5+ dígitos al final
            if not re.search(r"-(\d{5,})\/?$", href):
                continue

            # Si estamos scrapeando una tienda específica, filtrar por su slug
            if tienda_base and tienda_base != "supermercados":
                if not href.startswith(f"/{tienda_base}/"):
                    continue

            # Descartar links de navegación, redes sociales y logos
            texto = a.get_text(strip=True).lower()
            if any(b in texto for b in PALABRAS_BASURA):
                continue

            try:
                f = self._extraer_datos_tarjeta(a)
                if f:
                    folletos.append(f)
            except Exception as e:
                logger.warning(f"[Ofertomat] Error en tarjeta: {e}")

        # Deduplicar por folleto_id
        vistos, unicos = set(), []
        for f in folletos:
            if f["folleto_id"] not in vistos:
                vistos.add(f["folleto_id"])
                unicos.append(f)

        return unicos

    def _extraer_datos_tarjeta(self, tarjeta) -> dict | None:
        href = tarjeta.get("href", "")

        # Extraer ID numérico del final de la URL
        # Ej: /walmart/walmart-folleto-desde-15-04-2026-127756/ → 127756
        match_id = re.search(r"-(\d{5,})\/?$", href)
        if not match_id:
            return None
        folleto_id = match_id.group(1)

        # URL completa
        url_folleto = (f"{self.BASE_URL}{href}"
                      if href.startswith("/") else href)

        # Nombre de la tienda — extraer del primer segmento del href
        # Ej: /walmart/walmart-folleto-... → "walmart"
        segmentos = [s for s in href.split("/") if s]
        tienda_slug = segmentos[0] if segmentos else ""
        tienda = tienda_slug.replace("-", " ").title()

        # Título — del texto del enlace o del alt de imagen
        titulo = ""
        img = tarjeta.select_one("img")
        if img:
            alt = img.get("alt", "").strip()
            if alt and len(alt) > 3:
                titulo = alt

        if not titulo:
            titulo = tarjeta.get_text(strip=True)
            if len(titulo) > 80:
                titulo = titulo[:80]

        # Limpiar título — quitar el nombre de la tienda duplicado
        if titulo.lower().startswith(tienda_slug.lower()):
            titulo = titulo[len(tienda_slug):].strip(" -")

        # Fechas — extraer de la URL (patrón: desde-DD-MM-YYYY o desde-DDMMYYYY)
        fecha_inicio, fecha_fin = self._extraer_fechas_url(href)

        # URL de imagen preview — extraída de la imagen de la tarjeta
        url_preview = self._extraer_url_preview(tarjeta, folleto_id)

        if not tienda or not folleto_id:
            return None

        return {
            "fuente":       self.FUENTE,
            "folleto_id":   folleto_id,
            "tienda":       tienda,
            "titulo":       titulo or f"Folleto {tienda}",
            "url_folleto":  url_folleto,
            "url_preview":  url_preview,
            "fecha_inicio": fecha_inicio,
            "fecha_fin":    None,  # Ofertomat no expone fecha_fin en URL
        }

    def _extraer_fechas_url(self, href: str) -> tuple[str | None, str | None]:
        """
        Extrae fecha de inicio desde la URL del folleto.
        Patrones encontrados:
          desde-miercoles-15-04-2026  → 2026-04-15
          desde-domingo-03052026      → 2026-05-03
        """
        # Patrón con guiones: desde-{dia_semana}-DD-MM-YYYY
        m = re.search(r"desde-\w+-(\d{2})-(\d{2})-(\d{4})", href)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", None

        # Patrón sin guiones: desde-{dia_semana}-DDMMYYYY
        m = re.search(r"desde-\w+-(\d{2})(\d{2})(\d{4})", href)
        if m:
            return f"{m.group(3)}-{m.group(2)}-{m.group(1)}", None

        return None, None

    # ── Páginas del folleto — CDN directo ────────────────────────────────────

    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        """
        Obtiene páginas del folleto navegando a la página del folleto
        y extrayendo las URLs de imágenes desde el HTML.

        Ofertomat usa un CDN con tokens de seguridad (thumbor) que
        no se pueden construir manualmente. Las URLs reales están
        en los meta tags og:image y en los elementos img del HTML.
        """
        async def _extraer():
            await self._navegar(url_folleto)
            html = await self.page.content()
            return self._extraer_paginas_html(html, url_folleto)

        paginas = await self.reintentar(_extraer)
        logger.info(f"[Ofertomat] {len(paginas)} páginas en {url_folleto}")
        return paginas

    def _extraer_paginas_html(self, html: str, url_folleto: str) -> list[str]:
        """
        Extrae URLs de imágenes del HTML de la página del folleto.
        Busca en: meta og:image, elementos img con src del CDN leafletscdn.
        """
        soup = BeautifulSoup(html, "html.parser")
        urls = set()

        # 1. Buscar en meta og:image (portada — página 0)
        og_image = soup.find("meta", {"property": "og:image"})
        if og_image:
            src = og_image.get("content", "")
            if "leafletscdn" in src:
                urls.add(src)

        # 2. Buscar todas las imágenes del CDN en el DOM
        for img in soup.select("img[src]"):
            src = img.get("src", "")
            if "leafletscdn" in src and "/data/" in src:
                urls.add(src)

        # 3. Buscar en atributos data-src (lazy loading)
        for img in soup.select("img[data-src]"):
            src = img.get("data-src", "")
            if "leafletscdn" in src and "/data/" in src:
                urls.add(src)

        # 4. Buscar en el HTML completo con regex
        patron = r'https://na\.leafletscdn\.com/[^"\' ]+/(?:mx/)?data/[^"\' ]+\.(?:jpg|webp|png)(?:\?[^"\' ]*)?'
        for match in re.finditer(patron, html):
            url = match.group(0)
            if "/data/" in url:
                urls.add(url)

        if not urls:
            logger.warning(f"[Ofertomat] Sin imágenes en HTML de {url_folleto}")
            return []

        # Ordenar por número de página extraído de la URL
        return self._ordenar_paginas(list(urls))

    def _extraer_url_preview(self, tarjeta, folleto_id: str) -> str:
        """Extrae la URL de imagen de portada de la tarjeta del folleto."""
        for img in tarjeta.select("img"):
            src = img.get("src", "") or img.get("data-src", "")
            if src and "leafletscdn" in src:
                return src
        # Fallback vacío — se obtendrá al navegar al folleto
        return ""

    # ── Métodos de conveniencia ───────────────────────────────────────────────

    async def scrapear_supermercados(self) -> list[dict]:
        return await self.obtener_folletos(URL_SUPERMERCADOS)

    async def scrapear_tienda(self, slug_tienda: str) -> list[dict]:
        if slug_tienda not in TIENDAS:
            raise ValueError(
                f"Tienda '{slug_tienda}' no disponible. "
                f"Opciones: {list(TIENDAS.keys())}"
            )
        return await self.obtener_folletos(TIENDAS[slug_tienda])