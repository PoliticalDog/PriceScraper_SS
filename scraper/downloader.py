# downloader.py - Metodos de descraga y almacenamiento de imágenes de folletos

import asyncio
import aiohttp
import logging
from pathlib import Path

"""
Módulo de descarga y almacenamiento de imágenes de folletos.
Guarda cada página como imagen en data/raw/{fuente}/{tienda}/{folleto_id}/pagina_{n}.webp
"""

#inicia loger
logger = logging.getLogger(__name__)

# Directorio raíz donde se guardan las imágenes crudas
DATA_RAW = Path(__file__).parent.parent / "data" / "raw"

# Clase downloader que descarga las imagenmes de forma asincrona
class Downloader:
   
    # Headers para simular navegador real al descargar del CDN
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Referer":    "https://www.tiendeo.mx/",
        "Accept":     "image/webp,image/apng,image/*,*/*;q=0.8",
    }
    
    # max_concurrentes: Máximo de descargas simultáneas (para veitar bloqueos)
    def __init__(self, max_concurrentes: int = 3, timeout: int = 30):
        self.max_concurrentes = max_concurrentes
        self.timeout = timeout

    # Construye la ruta de destino para un folleto y crea el directorio si no existe
    def _ruta_folleto(self, fuente: str, tienda: str, folleto_id: str) -> Path:
        
        # Estructura: data/raw/{fuente}/{tienda_slug}/{folleto_id}/
        # Si la tienda está vacía → carpeta desconocidos para revisión manual
        if not tienda or not tienda.strip():
            tienda_slug = "desconocidos"
        else:
            tienda_slug = tienda.lower().replace(" ", "_").replace("/", "-")
        ruta = DATA_RAW / fuente / tienda_slug / folleto_id
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    # Descarga todas las páginas de un folleto.
    async def descargar_paginas(
        self,
        urls_paginas: list[str],
        fuente: str,
        tienda: str,
        folleto_id: str,
    ) -> list[Path]:
        """
            urls_paginas: Lista de URLs de imágenes (una por página).
            fuente: Nombre de la fuente ('tiendeo' o 'ofertomat').
            tienda: Nombre de la tienda (para organizar carpetas).
            folleto_id: ID único del folleto.
        """
        
        # Lista de rutas locales de las imágenes descargadas.
        ruta_destino = self._ruta_folleto(fuente, tienda, folleto_id)
        semaforo = asyncio.Semaphore(self.max_concurrentes)

        async with aiohttp.ClientSession(headers=self.HEADERS) as session:
            tareas = [
                self._descargar_una(session, semaforo, url, ruta_destino, num_pagina=i + 1)
                for i, url in enumerate(urls_paginas)
            ]
            resultados = await asyncio.gather(*tareas, return_exceptions=True)

        # Filtrar errores y retornar solo las descargas exitosas
        rutas_exitosas = [r for r in resultados if isinstance(r, Path)]
        errores = len(resultados) - len(rutas_exitosas)

        if errores:
            logger.warning(f"[Downloader] {errores} páginas fallaron en folleto {folleto_id}")

        logger.info(f"[Downloader] {len(rutas_exitosas)}/{len(urls_paginas)} páginas descargadas → {ruta_destino}")
        return sorted(rutas_exitosas)

    async def _descargar_una(
        self,
        session: aiohttp.ClientSession,
        semaforo: asyncio.Semaphore,
        url: str,
        ruta_destino: Path,
        num_pagina: int,
    ) -> Path:
        """
        Descarga una imagen individual respetando el semáforo de concurrencia.
        Si el archivo ya existe, no lo vuelve a descargar (idempotente).
        """
        # Determinar extensión del archivo
        extension = "webp" if "webp" in url else "jpg"
        ruta_archivo = ruta_destino / f"pagina_{num_pagina:03d}.{extension}"

        # Skip si ya existe (útil para reinicios del scraper)
        if ruta_archivo.exists():
            logger.debug(f"Ya existe: {ruta_archivo.name}, saltando.")
            return ruta_archivo

        async with semaforo:
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with session.get(url, timeout=timeout) as response:
                    response.raise_for_status()
                    contenido = await response.read()
                    ruta_archivo.write_bytes(contenido)
                    logger.debug(f"Descargada página {num_pagina}: {ruta_archivo.name}")
                    return ruta_archivo
            except Exception as e:
                logger.error(f"Error descargando página {num_pagina} ({url}): {e}")
                raise

    async def descargar_preview(
        self,
        url_preview: str,
        fuente: str,
        tienda: str,
        folleto_id: str,
    ) -> Path | None:
        """
        Descarga solo la imagen de portada (preview) de un folleto.
        Útil para mostrar en el dashboard sin descargar todo el folleto.
        """
        ruta_destino = self._ruta_folleto(fuente, tienda, folleto_id)
        ruta_archivo = ruta_destino / "preview.webp"

        if ruta_archivo.exists():
            return ruta_archivo

        try:
            async with aiohttp.ClientSession(headers=self.HEADERS) as session:
                async with session.get(url_preview, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    r.raise_for_status()
                    ruta_archivo.write_bytes(await r.read())
            logger.info(f"[Downloader] Preview guardada: {ruta_archivo}")
            return ruta_archivo
        except Exception as e:
            logger.error(f"Error descargando preview de folleto {folleto_id}: {e}")
            return None