# Guarda un registro de folletos ya procesados para evitar reprocesar en futuras ejecuciones del scrapeer

import json
import logging
from pathlib import Path
from datetime import datetime

from .downloader import ruta_folleto

# inicia el logger para este módulo
logger = logging.getLogger(__name__)

# Ruta por defecto para el registro de folletos procesados
RUTA_REGISTRO = Path("data/registro_folletos_scrapeados.json")

# Registro de folletos procesados
class Registro:

    # Inicializa el registro, cargando datos existentes o creando uno nuevo
    def __init__(self, ruta: Path = None):
        self.ruta = ruta or RUTA_REGISTRO
        self._datos = self._cargar()
    
    # Carga el registro desde disco. Si no existe, lo crea vacío
    def _cargar(self) -> dict:
        
        if self.ruta.exists():
            try:
                with open(self.ruta, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[Registro] Error cargando registro: {e}. Iniciando vacío.")
        return {}

    # Guarda el registro actualizado en disco
    def _guardar(self):
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self._datos, f, ensure_ascii=False, indent=2)

    # Verifica si un folleto ya fue procesado anteriormente.
    # Si el registro esta procesado pero la carpeta del folleto no existe o esta vacia, se re-procesa
    def ya_procesado(self, fuente: str, folleto_id: str, tienda: str = "") -> bool:
        """
            fuente:         'tiendeo' o 'ofertomat'
            folleto_id:     ID único del folleto
            tienda:         Nombre de la tienda
        """
        clave = f"{fuente}:{folleto_id}"
        if clave not in self._datos:
            return False

        # Determinar qué tienda usar para construir la ruta esperada
        tienda_chequeo = tienda or self._datos[clave].get("tienda", "")
        carpeta = ruta_folleto(fuente, tienda_chequeo, folleto_id)

        if not carpeta.exists() or not any(carpeta.iterdir()):
            logger.info(
                f"[Registro] {clave} marcado como procesado pero "
                f"la carpeta '{carpeta}' no existe o está vacía --> re-procesar"
            )
            return False

        return True

    # Marca un folleto como procesado, guardando información relevante en el registro
    def marcar_procesado(self, fuente: str, folleto_id: str, metadata: dict = None):
        # metadata --> Dict opcional con info adicional (tienda, título, fechas)

        clave = f"{fuente}:{folleto_id}"
        self._datos[clave] = {
            "fuente":        fuente,
            "folleto_id":    folleto_id,
            "procesado_at":  datetime.now().isoformat(),
            **(metadata or {}),
        }
        self._guardar()
        logger.debug(f"[Registro] Marcado como procesado: {clave}")

    # Retorna el total de folletos procesados, opcionalmente filtrado por fuente
    def total_procesados(self, fuente: str = None) -> int:
        # Si se especifica una fuente, cuenta solo los folletos de esa fuente. De lo contrario, cuenta todos
        if fuente:
            return sum(1 for k in self._datos if k.startswith(f"{fuente}:"))
        return len(self._datos)
    
    # Lista todos los folletos procesados, opcionalmente filtrado por fuente
    def listar(self, fuente: str = None) -> list[dict]:
        registros = list(self._datos.values())
        if fuente:
            registros = [r for r in registros if r.get("fuente") == fuente]
        return registros