#metodos_scraper.py

import asyncio
import random
import logging
from abc import ABC, abstractmethod
from playwright.async_api import async_playwright, Browser, Page

# logers
logger = logging.getLogger(__name__)

# rotación de agentes anti-bot
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]

# Clase abstracta para avrias fuentes
# Contiene la lógica compartida: navegador, reintentos, delays, logging.
class BaseScraper(ABC):
    # headless por defecto para evitar abrir ventanas, pero se puede configurar para debug
    def __init__(self, headless: bool = True, delay_min: float = 1.5, delay_max: float = 3.5):
        # Configuración del scraper, delay aleatorio para simular comportamiento humano y activar o desactivar ventana del navegador.
        self.headless = headless
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.browser: Browser | None = None
        self.page: Page | None = None

    # Scrapeo navegador
    async def iniciar(self):
        # Abre el navegador con configuración anti-detección.
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",  # oculta que es bot
            ]
        )
        self.page = await self.browser.new_page(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="es-MX",
        )
        # Ocultar webdriver flag (técnica anti-bot estándar)
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info(f"[{self.__class__.__name__}] Navegador iniciado.")

    # Cerrar
    async def cerrar(self):
        """Cierra el navegador limpiamente."""
        if self.browser:
            await self.browser.close()
        if hasattr(self, '_playwright'):
            await self._playwright.stop()
        logger.info(f"[{self.__class__.__name__}] Navegador cerrado.")

    # ─── Utilidades compartidas ────────────────────────────────────────────────
    
    async def _delay_aleatorio(self):
        # Espera un tiempo aleatorio para simular comportamiento humano
        espera = random.uniform(self.delay_min, self.delay_max)
        logger.debug(f"Esperando {espera:.1f}s...")
        await asyncio.sleep(espera)

    async def _navegar(self, url: str, esperar: str = "networkidle"):
        """
        Navega a una URL con manejo de errores.

        Args:
            url: URL de destino.
            esperar: Estrategia de espera:
                     'networkidle' → espera a que no haya peticiones de red (más seguro)
                     'domcontentloaded' → espera solo el HTML base (más rápido)
        """
        try:
            logger.info(f"Navegando a: {url}")
            await self.page.goto(url, wait_until=esperar, timeout=30_000)
            await self._delay_aleatorio()
        except Exception as e:
            logger.error(f"Error navegando a {url}: {e}")
            raise

    async def reintentar(self, funcion, intentos: int = 3, espera: float = 5.0):
        """
        Ejecuta una función async con reintentos automáticos.

        Args:
            funcion: Coroutine a ejecutar.
            intentos: Número máximo de intentos.
            espera: Segundos entre cada reintento.

        Returns:
            El resultado de la función si tiene éxito.

        Raises:
            Exception: Si se agotan todos los intentos.
        """
        ultimo_error = None
        for intento in range(1, intentos + 1):
            try:
                return await funcion()
            except Exception as e:
                ultimo_error = e
                logger.warning(f"Intento {intento}/{intentos} fallido: {e}")
                if intento < intentos:
                    await asyncio.sleep(espera)
        raise ultimo_error

    async def _scroll_hasta_abajo(self, pasos: int = 5):
        # aplica el scroll gradual hacia abajo para activar lazy loading de las paginas
        for i in range(pasos):
            await self.page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/pasos})")
            await asyncio.sleep(0.8)

    # ─── Métodos abstractos que cada adaptador debe implementar ───────────────

    @abstractmethod
    # Extrae la lista de folletos disponibles en una categoría.
    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        """
        regresa:
            Lista de dicts con keys: tienda, titulo, url_folleto,
            fecha_inicio, fecha_fin, url_imagen_preview, fuente
        """
        pass

    @abstractmethod
    # Dado el URL de un folleto individual, retorna las URLs de todas sus páginas como imágenes.
    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:
        """
        regresa:
            Lista de URLs de imágenes ordenadas por página.
        """
        pass

    # ─── Context manager para uso con 'async with' ────────────────────────────

    async def __aenter__(self):
        await self.iniciar()
        return self

    async def __aexit__(self, *args):
        await self.cerrar()