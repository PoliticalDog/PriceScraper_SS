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
import random
import asyncio
import logging
from bs4 import BeautifulSoup
from ..metodos_scraper import BaseScraper, USER_AGENTS

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
        Si la página crasheó, la recreamos antes de navegar.
        """
        try:
            # Si la página está en estado crashed, recrearla
            if self.page and self.page.is_closed():
                logger.warning("[OfertomatScraper] Página cerrada/crasheada — recreando...")
                self.page = await self.browser.new_page(
                    user_agent=random.choice(USER_AGENTS),
                    viewport={"width": 1366, "height": 768},
                    locale="es-MX",
                )
                await self.page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
                )
            logger.info(f"Navegando a: {url}")
            await self.page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await self.page.wait_for_timeout(3000)
            await self._delay_aleatorio()
        except Exception as e:
            # Si crasheó durante el goto, marcar la página como cerrada
            # para que el siguiente intento la recree
            if "crashed" in str(e).lower() and self.page:
                try:
                    await self.page.close()
                except Exception:
                    pass
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

    # ── Páginas del folleto — intercepción de red ────────────────────────────

    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        """
        Obtiene páginas del folleto interceptando las requests de red al CDN.

        El visor JS de Ofertomat es pesado y crashea el renderer con facilidad.
        Estrategia:
          1. Registrar el interceptor ANTES del goto para no perder requests tempranas
          2. Bloquear agresivamente recursos innecesarios (media, fonts, analytics,
             imágenes que no sean del CDN de folletos)
          3. Usar wait_until="commit" — el mínimo posible para no esperar JS pesado
          4. Esperar hasta 15s a que el visor pida imágenes al CDN
          5. Fallback: construir URLs del CDN directamente con el folleto_id
             (patrón conocido: CDN_BASE/{folleto_id}/0.jpg, 1.jpg, ...)
        """
        # Extraer folleto_id de la URL para el fallback por CDN directo
        match_id = re.search(r"-(\d{5,})\/?$", url_folleto)
        folleto_id_cdn = match_id.group(1) if match_id else None

        async def _extraer():
            urls_capturadas: set[str] = set()

            async def _interceptar(route, request):
                url = request.url
                tipo = request.resource_type

                # Capturar imágenes del CDN de folletos — dejar pasar y registrar
                if "leafletscdn" in url and "/data/" in url:
                    urls_capturadas.add(url)
                    await route.continue_()
                    return

                # Bloquear todo lo que no sea esencial para cargar el visor
                if tipo in ("media", "font"):
                    await route.abort()
                    return

                # Bloquear imágenes que no son del CDN de folletos
                # (logos, banners, avatares — solo agregan peso al renderer)
                if tipo == "image" and "leafletscdn" not in url:
                    await route.abort()
                    return

                # Bloquear analytics y scripts de terceros pesados
                dominios_bloquear = (
                    "googletagmanager", "google-analytics", "doubleclick",
                    "facebook.net", "connect.facebook", "hotjar", "clarity.ms",
                    "adnxs", "moatads", "quantserve", "criteo", "taboola",
                )
                if tipo in ("script", "xhr", "fetch") and any(
                    d in url for d in dominios_bloquear
                ):
                    await route.abort()
                    return

                await route.continue_()

            # Registrar interceptor ANTES del goto para capturar requests tempranas
            await self.page.route("**/*", _interceptar)

            try:
                logger.info(f"Navegando a: {url_folleto}")
                await self.page.goto(
                    url_folleto,
                    wait_until="commit",   # mínimo posible — no esperar JS pesado
                    timeout=30_000,
                )

                # Esperar hasta 15s a que el visor solicite imágenes al CDN
                for _ in range(30):
                    if urls_capturadas:
                        break
                    await asyncio.sleep(0.5)

            except Exception as e:
                if "crashed" in str(e).lower():
                    logger.warning(f"[Ofertomat] Renderer crasheó en {url_folleto} — usando fallback CDN")
                else:
                    raise
            finally:
                try:
                    await self.page.unroute("**/*", _interceptar)
                except Exception:
                    pass

            return self._ordenar_paginas(list(urls_capturadas))

        # Intento 1: interceptación de red
        try:
            paginas = await self.reintentar(_extraer, intentos=2)
        except Exception as e:
            logger.warning(f"[Ofertomat] Intercepción fallida: {e}")
            paginas = []

        # Fallback: construir URLs del CDN directamente si no capturamos nada
        if not paginas and folleto_id_cdn:
            logger.info(f"[Ofertomat] Fallback CDN directo para folleto {folleto_id_cdn}")
            paginas = await self._paginas_por_cdn(folleto_id_cdn)

        logger.info(f"[Ofertomat] {len(paginas)} páginas en {url_folleto}")
        return paginas

    async def _paginas_por_cdn(self, folleto_id: str, max_paginas: int = 60) -> list[str]:
        """
        Construye URLs del CDN directamente sin navegar al visor.

        El CDN de Leaflets tiene un patrón predecible:
          https://na.leafletscdn.com/mx/data/1/{folleto_id}/{num_pagina}.jpg

        Verifica cuántas páginas existen haciendo HEAD requests con aiohttp
        hasta encontrar un 404 (fin del folleto).
        """
        import aiohttp

        base = f"{CDN_BASE}/{folleto_id}"
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": "https://www.ofertomat.mx/",
        }

        paginas_validas = []
        async with aiohttp.ClientSession(headers=headers) as session:
            for num in range(0, max_paginas):
                url = f"{base}/{num}.jpg"
                try:
                    async with session.head(url, timeout=aiohttp.ClientTimeout(total=8)) as r:
                        if r.status == 200:
                            paginas_validas.append(url)
                            logger.debug(f"[Ofertomat CDN] ✓ página {num}")
                        else:
                            # Primer 404 consecutivo indica fin del folleto
                            logger.debug(f"[Ofertomat CDN] Fin en página {num} (status {r.status})")
                            break
                except Exception as e:
                    logger.debug(f"[Ofertomat CDN] Error en página {num}: {e}")
                    break

        logger.info(f"[Ofertomat CDN] {len(paginas_validas)} páginas encontradas para folleto {folleto_id}")
        return paginas_validas

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

    def _ordenar_paginas(self, urls: list[str]) -> list[str]:
        """
        Ordena las URLs de imágenes por número de página.
        Las URLs del CDN tienen el patrón: .../data/1/{folleto_id}/{num_pagina}.jpg
        Se extrae el último número antes de la extensión como clave de orden.
        URLs sin número reconocible van al final.
        """
        def _clave(url: str) -> int:
            # Extrae el número de página del último segmento antes de la extensión
            # Ej: .../131170/3.jpg → 3  |  .../0.jpg → 0
            m = re.search(r"/(\d+)\.(?:jpg|webp|png)(?:\?|$)", url)
            return int(m.group(1)) if m else 9999

        return sorted(urls, key=_clave)

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