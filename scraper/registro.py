# registro.py
import json
import logging
from pathlib import Path
from datetime import datetime

"""
Registro de folletos ya procesados para evitar reprocesar.
Guarda un JSON con los folleto_id descargados por fuente.

Uso:
    registro = Registro()
    if not registro.ya_procesado("tiendeo", "401741"):
        # descargar y procesar
        registro.marcar_procesado("tiendeo", "401741", metadata)
"""

logger = logging.getLogger(__name__)

RUTA_REGISTRO = Path("data/folletos_procesados.json")


class Registro:
    """
    Registro persistente de folletos ya descargados.
    Evita reprocesar el mismo folleto si el scraper se corre varias veces.
    """

    def __init__(self, ruta: Path = None):
        self.ruta = ruta or RUTA_REGISTRO
        self._datos = self._cargar()

    def _cargar(self) -> dict:
        """Carga el registro desde disco. Si no existe, lo crea vacío."""
        if self.ruta.exists():
            try:
                with open(self.ruta, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"[Registro] Error cargando registro: {e}. Iniciando vacío.")
        return {}

    def _guardar(self):
        """Persiste el registro en disco."""
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(self._datos, f, ensure_ascii=False, indent=2)

    def ya_procesado(self, fuente: str, folleto_id: str) -> bool:
        """
        Verifica si un folleto ya fue procesado anteriormente.

        Args:
            fuente:     'tiendeo' o 'ofertomat'
            folleto_id: ID único del folleto

        Returns:
            True si ya fue procesado, False si es nuevo.
        """
        clave = f"{fuente}:{folleto_id}"
        return clave in self._datos

    def marcar_procesado(self, fuente: str, folleto_id: str, metadata: dict = None):
        """
        Registra un folleto como procesado.

        Args:
            fuente:     'tiendeo' o 'ofertomat'
            folleto_id: ID único del folleto
            metadata:   Dict opcional con info adicional (tienda, título, fechas)
        """
        clave = f"{fuente}:{folleto_id}"
        self._datos[clave] = {
            "fuente":        fuente,
            "folleto_id":    folleto_id,
            "procesado_at":  datetime.now().isoformat(),
            **(metadata or {}),
        }
        self._guardar()
        logger.debug(f"[Registro] Marcado como procesado: {clave}")

    def total_procesados(self, fuente: str = None) -> int:
        """Retorna el total de folletos procesados, opcionalmente por fuente."""
        if fuente:
            return sum(1 for k in self._datos if k.startswith(f"{fuente}:"))
        return len(self._datos)

    def listar(self, fuente: str = None) -> list[dict]:
        """Lista todos los folletos procesados, opcionalmente filtrado por fuente."""
        registros = list(self._datos.values())
        if fuente:
            registros = [r for r in registros if r.get("fuente") == fuente]
        return registros