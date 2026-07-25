"""
ofertomat.py
Adaptador para Ofertomat.mx.

Notas de diseño:
  1. _navegar usa domcontentloaded por defecto (Ofertomat tiene requests
     continuas de geolocalización/analytics que impiden llegar a networkidle),
     con recreacion de pagina si crashea.
  2. _parsear_tarjetas filtra logos, redes sociales y basura.
  3. folleto_id se extrae del numero al FINAL de la URL (ej: 127756).
  4. El visor carga las imagenes de las paginas de forma perezosa: solo pide
     la imagen de la pagina actual. Por eso obtener_paginas_folleto navega
     secuencialmente ?page=2, ?page=3, ... (ademas de la url base = pagina 1),
     escuchando pasivamente (page.on("request")) la request al CDN que
     dispara cada navegacion, hasta que una pagina no dispare ninguna
     request nueva para ese folleto_id (fin del folleto -- esa ultima
     "pagina" no tiene imagen propia, o el visor muestra miniaturas de
     folletos recomendados en su lugar).
  5. Las imagenes solo se sirven a traves del proxy thumbor con una URL
     firmada (hash) que cambia por request -- no se puede adivinar/construir
     la URL de una pagina sin que el visor la pida primero (confirmado: la
     ruta directa al CDN sin thumbor siempre 404, y thumbor no acepta modo
     "unsafe"). Por eso no hay atajo de solo-HTTP como Tiendeo tiene con el
     fallback de DOM/regex -- hay que navegar con el browser si o si.
  6. obtener_paginas_folleto usa page.on("request") (escucha pasiva), NO
     page.route() (interceptor activo) -- confirmado con pruebas reales que
     activar page.route(), aunque no bloquee nada, rompe la carga perezosa
     del visor (deja de pedir la imagen de las paginas siguientes a la
     primera). Por eso este metodo no bloquea recursos pesados (fonts,
     analytics, etc.) como sí se podía hacer antes con page.route().

CDN descubierto (URL real, vía thumbor, firma omitida):
  Portada:  na.leafletscdn.com/thumbor/<hash>/.../mx/data/{N}/{id}/0.jpg
  Páginas:  na.leafletscdn.com/thumbor/<hash>/.../mx/data/{N}/{id}/{num}.jpg
  (el segmento data/{N} varia por folleto, no es fijo)
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
    "arteli":           "https://www.ofertomat.mx/arteli/",
}

# Tiendas de interes en Ofertomat: no tienen equivalente en Tiendeo, asi que
# son las unicas que debe tocar el rastreo masivo ("todas las tiendas") para
# no duplicar informacion de supermercados que Tiendeo ya cubre.
# Excluidas (ya cubiertas en Tiendeo): walmart, bodega-aurrera,
# soriana (-> soriana-hiper/soriana-mercado en Tiendeo), chedraui, la-comer,
# costco, heb, sams-club, oxxo, s-mart, alsuper, casa-ley.
TIENDAS_UNICAS = ("arteli", "calimax", "7-eleven", "walmart-express")

# Una pagina real de folleto termina en /{numero}.jpg|webp|png — distingue
# paginas de otros assets del mismo CDN (logo.png, banners, etc.)
_ES_PAGINA_CDN = re.compile(r"/(\d+)\.(?:jpg|webp|png)(?:\?|$)")

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
            await self.page.goto(url, wait_until=esperar, timeout=45_000)
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

    # ── Páginas del folleto — navegación secuencial + intercepción de red ────

    MAX_PAGINAS = 30

    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        """
        Obtiene las páginas reales del folleto navegando secuencialmente
        ?page=2, ?page=3, ... (la url base = página 1) y escuchando la
        request al CDN que cada navegación dispara -- el visor solo pide la
        imagen de la página actual (lazy), no hay atajo por HTTP puro (ver
        docstring del módulo: las URLs del CDN están firmadas por thumbor).

        IMPORTANTE: se usa page.on("request") (escucha pasiva) y NO
        page.route() (interceptor activo). Se confirmó con pruebas reales
        que activar page.route() -- incluso sin bloquear ningún recurso --
        rompe el mecanismo de carga perezosa del visor: a partir de la
        segunda navegación deja de pedirse la imagen de la página nueva
        (solo se re-pide el logo). Con on("request") pasivo el visor se
        comporta igual que en un navegador normal y sí pide cada página.
        Como consecuencia ya no se bloquean recursos (fonts/media/ads) en
        este método -- el trade-off de cargar un poco más pesado es
        preferible a que el scraping no funcione.

        Se detiene en la primera página que no dispare ninguna request nueva
        para este folleto_id: ahí termina el folleto (esa "página" no tiene
        imagen propia, o el visor muestra miniaturas de folletos recomendados
        en su lugar -- por eso el filtro exige que la URL sea del folleto_id
        que estamos scrapeando, no de leafletscdn en general).
        """
        match_id = re.search(r"-(\d{5,})\/?$", url_folleto)
        folleto_id = match_id.group(1) if match_id else None
        if not folleto_id:
            logger.warning(f"[Ofertomat] No se pudo extraer folleto_id de {url_folleto}")
            return []

        patron_pagina_propia = re.compile(rf"/{folleto_id}/\d+\.(?:jpg|webp|png)(?:\?|$)")
        urls_capturadas: set[str] = set()

        def _on_request(request):
            url = request.url
            # Solo capturar páginas del folleto que estamos scrapeando --
            # descarta logo.png y, sobre todo, las miniaturas de folletos
            # recomendados de la pantalla final (llevan otro folleto_id).
            if "leafletscdn" in url and patron_pagina_propia.search(url):
                urls_capturadas.add(url)

        async def _navegar_pagina(url_pagina: str) -> bool:
            antes = len(urls_capturadas)
            # commit = minimo posible, no esperar JS pesado. Pasa por
            # _navegar (no page.goto directo) para heredar la recreación
            # de página si el renderer crashea a mitad de la navegación.
            await self._navegar(url_pagina, esperar="commit")
            # Esperar a que el visor pida la imagen de esta página
            for _ in range(8):
                if len(urls_capturadas) > antes:
                    break
                await asyncio.sleep(0.5)
            return len(urls_capturadas) > antes

        self.page.on("request", _on_request)
        try:
            for num_pagina in range(1, self.MAX_PAGINAS + 1):
                url_pagina = (url_folleto if num_pagina == 1
                              else f"{url_folleto}?page={num_pagina}")
                try:
                    hubo_nueva = await self.reintentar(
                        lambda u=url_pagina: _navegar_pagina(u), intentos=2
                    )
                except Exception as e:
                    logger.warning(f"[Ofertomat] Error en página {num_pagina} de {url_folleto}: {e}")
                    break

                if not hubo_nueva:
                    logger.debug(f"[Ofertomat] Fin del folleto en página {num_pagina} (sin imagen nueva)")
                    break
        finally:
            self.page.remove_listener("request", _on_request)

        paginas = self._ordenar_paginas(list(urls_capturadas))
        logger.info(f"[Ofertomat] {len(paginas)} páginas en {url_folleto}")
        return paginas

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
            m = _ES_PAGINA_CDN.search(url)
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

    async def scrapear_tienda(self, slug_tienda: str) -> list[dict]:
        if slug_tienda not in TIENDAS:
            raise ValueError(
                f"Tienda '{slug_tienda}' no disponible. "
                f"Opciones: {list(TIENDAS.keys())}"
            )
        return await self.obtener_folletos(TIENDAS[slug_tienda])