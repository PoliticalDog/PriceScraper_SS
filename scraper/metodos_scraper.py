# Contiene la preparación del entorno de scraping, manejo de navegador, reintentos y delays.

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

# Definicion de la clase abstracta para ambas fuentes : navegador, reintentos, delays, logging
class BaseScraper(ABC):
    def __init__(self, headless: bool = True, delay_min: float = 1.5, delay_max: float = 3.5):
        # Configuración del scraper, delay aleatorio para simular comportamiento humano y activar o desactivar ventana del navegador.
        self.headless = headless # False muestra la ventana
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.browser: Browser | None = None
        self.page: Page | None = None

    # ----------------- Inicio y cierre del navegador -----------------
    # iniciar navegador
    async def iniciar(self):
        
        # inicia el navegador con un user-agent aleatorio
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",                     # por si se usa docker despues para postgre
                "--disable-dev-shm-usage",          # evita crashes por memoria compartida
                "--disable-gpu",                    # evita crashes de GPU en servidores sin GPU
                "--disable-software-rasterizer",    # reducción de consumo de recursos
                "--disable-blink-features=AutomationControlled",  # oculta que es bot
            ]
        )
        # recibe agente y crea nueva vgentana
        self.page = await self.browser.new_page(
            user_agent=random.choice(USER_AGENTS),
            viewport={"width": 1366, "height": 768},
            locale="es-MX",
        )
        # ouclta el webdriver para evitar detección de bot
        await self.page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        logger.info(f"[{self.__class__.__name__}] Navegador iniciado.")

    # Cerrar
    async def cerrar(self):
        # Cierra el navegador limpiando todo
        if self.browser:
            await self.browser.close()
        if hasattr(self, '_playwright'):
            await self._playwright.stop()
        logger.info(f"[{self.__class__.__name__}] Navegador cerrado.")

    #---------------------- Métodos comunes para navegación, reintentos y delays ----------------------
    
    # Lapsos de tiempo para simular navegacion 
    async def _delay_aleatorio(self):
        espera = random.uniform(self.delay_min, self.delay_max)
        logger.debug(f"Delay {espera:.1f}s...")
        await asyncio.sleep(espera)

    # Navega a una URL con manejo de errores.
    async def _navegar(self, url: str, esperar: str = "networkidle"):

        # url: URL de destino.
        # networkidle --> espera a que no haya peticiones de red (más seguro)
    
        try:
            logger.info(f"Navegando a: {url}")
            await self.page.goto(url, wait_until=esperar, timeout=30_000)
            await self._delay_aleatorio()
        except Exception as e:
            logger.error(f"Error navegando a {url}: {e}")
            raise
    
    # reintento asincrono
    async def reintentar(self, funcion, intentos: int = 3, espera: float = 5.0):
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

    # Cargar toda la página con scroll para activar lazy loading
    async def _scroll_hasta_abajo(self, pasos: int = 5):
        for i in range(pasos):
            await self.page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/pasos})")
            await asyncio.sleep(0.8)

    # ---------------------- Métodos abstractos que cada scraper debe implementar ----------------------

    # Extrae la lista de folletos disponibles en una categoría.
    @abstractmethod
    async def obtener_folletos(self, categoria_url: str) -> list[dict]:
        # regresa: 
            # Lista de dicts con keys: tienda, titulo, url_folleto, 
            # fecha_inicio, fecha_fin, url_imagen_preview, fuente
        pass

    # Dado el URL de un folleto individual, retorna las URLs de todas sus páginas como imágenes.
    @abstractmethod
    async def obtener_paginas_folleto(self, url_folleto: str) -> list[str]:        
        # regresa: Lista de URLs de imágenes ordenadas por página.
        pass

    # -------------------------- Context manager para manejo automático del navegador ----------------------

    async def __aenter__(self):
        await self.iniciar()
        return self

    async def __aexit__(self, *args):
        await self.cerrar()