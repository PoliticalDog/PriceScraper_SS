# Guarda cada página como imagen en data/raw/{fuente}/{tienda}/{folleto_id}/pagina_{n}.webp

import asyncio
import aiohttp
import logging
import re
import unicodedata
from pathlib import Path

#inicia loger
logger = logging.getLogger(__name__)

# Directorio raíz donde se guardan las imágenes crudas
DATA_RAW = Path(__file__).parent.parent / "data" / "raw"

# Elimina acentos, convierte a minúsculas y reemplaza espacios con guión bajo par ano rtomper los paths
def normalizar_nombre(nombre: str) -> str:
    texto_normalizado = unicodedata.normalize("NFKD", nombre) # nfkd separa acento y la letra
    sin_acentos = "".join(c for c in texto_normalizado if not unicodedata.combining(c)) # elimina los caracteres de acento
    limpio = sin_acentos.lower().strip()
    return re.sub(r"\s+", "_", limpio) # patron, remplazo, texto


# Construye la ruta esperada de un folleto: data/raw/{fuente}/{tienda_slug}/{folleto_id}/
def ruta_folleto(fuente: str, tienda: str, folleto_id: str) -> Path:
    if not tienda or not tienda.strip():
        tienda_slug = "desconocidos"
    else:
        tienda_slug = normalizar_nombre(tienda).replace("/", "-")
    return DATA_RAW / fuente / tienda_slug / folleto_id

# Clase downloader que descarga las imagenmes de forma asincrona
class Downloader: 
    # Headers para simular navegador real al descargar del CDN
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
        "Referer":    "https://www.tiendeo.mx/",
        "Accept":     "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    # Referer correcto por fuente — cada CDN espera el dominio del sitio que lo sirve
    REFERERS = {
        "tiendeo":   "https://www.tiendeo.mx/",
        "ofertomat": "https://www.ofertomat.mx/",
    }

    # max_concurrentes: Máximo de descargas simultáneas (para veitar bloqueos)
    def __init__(self, max_concurrentes: int = 3, timeout: int = 30):
        self.max_concurrentes = max_concurrentes
        self.timeout = timeout

    # Headers con el Referer correcto para la fuente (fallback al de Tiendeo)
    def _headers_para(self, fuente: str) -> dict:
        return {**self.HEADERS, "Referer": self.REFERERS.get(fuente, self.HEADERS["Referer"])}

    # Construye la ruta de destino para un folleto y crea el directorio si no existe
    def _ruta_folleto(self, fuente: str, tienda: str, folleto_id: str) -> Path:
        
        # Estructura: data/raw/{fuente}/{tienda_slug}/{folleto_id}/
        # Si la tienda está vacía → carpeta desconocidos para revisión manual
        ruta = ruta_folleto(fuente, tienda, folleto_id)
        ruta.mkdir(parents=True, exist_ok=True)
        return ruta

    # Descarga todas las páginas de un folleto.
    async def descargar_paginas(
        self,
        urls_paginas: list[str],    # Lista de URLs de las páginas del folleto.
        fuente: str,                # tiendeo o ofertomat
        tienda: str,                # Nombre de la tienda (para organizar carpetas)
        folleto_id: str,            # ID único del folleto (para organizar carpetas)
    ) -> list[Path]:
        
        # Lista de rutas locales de las imágenes descargadas.
        ruta_destino = self._ruta_folleto(fuente, tienda, folleto_id)
        semaforo = asyncio.Semaphore(self.max_concurrentes)

        async with aiohttp.ClientSession(headers=self._headers_para(fuente)) as session:
            tareas = [
                self._descargar_una(session, semaforo, url, ruta_destino, num_pagina=i + 1)
                for i, url in enumerate(urls_paginas)
            ]
            resultados = await asyncio.gather(*tareas, return_exceptions=True)

        # Filtrar errores y retornar solo las descargas exitosas
        rutas_exitosas = [r for r in resultados if isinstance(r, Path)]
        errores = len(resultados) - len(rutas_exitosas)

        # logeo errores al descragar
        if errores:
            logger.warning(f"[Downloader] {errores} páginas fallaron en folleto {folleto_id}")

        logger.info(f"[Downloader] {len(rutas_exitosas)}/{len(urls_paginas)} páginas descargadas → {ruta_destino}")
        return sorted(rutas_exitosas)

    # Descarga una sola página respetando el semáforo de concurrencia.
    async def _descargar_una(
        self,
        session: aiohttp.ClientSession,
        semaforo: asyncio.Semaphore,
        url: str,
        ruta_destino: Path,
        num_pagina: int,
    ) -> Path:
        
        # Determinar extensión del archivo
        extension = "webp" if "webp" in url else "jpg"
        ruta_archivo = ruta_destino / f"pagina_{num_pagina:03d}.{extension}"

        # Si el archivo ya existe, no lo vuelve a descargar
        if ruta_archivo.exists():
            logger.debug(f"Ya existe: {ruta_archivo.name}, saltando.")
            return ruta_archivo
        
        # Descargar la página respetando el semáforo para limitar concurrencia
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
    
    # Descarga solo la imagen de portada (preview) de un folleto
    async def descargar_preview(
        self,
        url_preview: str,
        fuente: str,
        tienda: str,
        folleto_id: str,
    ) -> Path | None:
        
        ruta_destino = self._ruta_folleto(fuente, tienda, folleto_id)
        ruta_archivo = ruta_destino / "preview.webp"

        if ruta_archivo.exists():
            return ruta_archivo

        try:
            async with aiohttp.ClientSession(headers=self._headers_para(fuente)) as session:
                async with session.get(url_preview, timeout=aiohttp.ClientTimeout(total=15)) as r:
                    r.raise_for_status()
                    ruta_archivo.write_bytes(await r.read())
            logger.info(f"[Downloader] Preview guardada: {ruta_archivo}")
            return ruta_archivo
        except Exception as e:
            logger.error(f"Error descargando preview de folleto {folleto_id}: {e}")
            return None