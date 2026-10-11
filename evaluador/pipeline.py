"""
Registros del pipeline para una pagina, con el mismo codigo que llena el dashboard:
NLP (disco o regenerado en memoria) -> load.construir_registros_pagina -> Registro.

No escribe nada en data/processed ni en la BD: un agente puede probar un cambio del NLP
con --nlp memoria sin tocar los JSON de produccion.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from load.load import DATA_PROCESSED, candidatas_roi_pagina, construir_registros_pagina, regiones_con_precio
from nlp.normalizador import Normalizador
from nlp.regex_extractor import RegexExtractor
from nlp.salida_json import clasificar_paginas_ocr, resultado_nlp

from .gt import FUENTE_GT, PaginaGT

logger = logging.getLogger(__name__)

RAIZ_CACHE_REGIONES = Path("data/processed/_eval/cache_regiones")
_ARCHIVOS_VISION = (Path("vision/preprocessor.py"), Path("vision/region_detector.py"))


@dataclass
class Registro:
    """Una fila PRECIO tal como load la insertaria (v_precios_actuales la muestra si tiene producto)."""
    pagina: str                  # tienda/folleto/pagina
    idx: int                     # posicion del precio en el NLP de la pagina
    precio: float | None
    precio_texto: str
    bbox_precio: dict
    producto: str | None         # texto_norm = lo que muestra el dashboard
    producto_texto: str | None   # texto OCR del bloque producto
    categoria: str | None
    bbox_producto: dict | None
    precio_anterior: float | None

    @property
    def en_dashboard(self) -> bool:
        # = WHERE valor IS NOT NULL AND texto_norm IS NOT NULL de v_precios_actuales
        return self.precio is not None and self.producto is not None


@dataclass
class PaginaPipeline:
    gt: PaginaGT
    nlp: dict | None             # pagina de nlp_resultado.json
    ocr: dict | None             # pagina de ocr_resultado.json
    registros: list[Registro]
    productos_nlp: list[dict]    # productos del NLP antes del normalizador
    productos_aceptados: list[dict]


def version_vision() -> str:
    h = hashlib.sha256()
    for archivo in _ARCHIVOS_VISION:
        h.update(archivo.read_bytes())
    return h.hexdigest()[:12]


class FuentePipeline:
    """
    nlp="disco":   lee data/processed/<fuente>/<tienda>/<folleto>/nlp_resultado.json (lo cargado en la BD)
    nlp="memoria": regenera el NLP desde ocr_resultado.json con el codigo actual, sin escribirlo
    """

    def __init__(self, nlp: str = "disco", usar_cache_regiones: bool = True):
        if nlp not in ("disco", "memoria"):
            raise ValueError(f"nlp debe ser 'disco' o 'memoria', no {nlp!r}")
        self.modo_nlp = nlp
        self.usar_cache = usar_cache_regiones
        self.normalizador = Normalizador()
        self._extractor = RegexExtractor() if nlp == "memoria" else None
        self._folletos: dict[tuple, tuple[dict, dict]] = {}
        self._version_vision = version_vision()

    def _carpeta(self, tienda: str, folleto: str) -> Path:
        return DATA_PROCESSED / FUENTE_GT / tienda / folleto

    def _folleto(self, tienda: str, folleto: str) -> tuple[dict, dict]:
        """(paginas NLP por nombre, paginas OCR por nombre)."""
        llave = (tienda, folleto)
        if llave not in self._folletos:
            carpeta = self._carpeta(tienda, folleto)
            ruta_ocr = carpeta / "ocr_resultado.json"
            ocr = json.load(open(ruta_ocr, encoding="utf-8")) if ruta_ocr.exists() else {}
            if self.modo_nlp == "memoria":
                nlp = resultado_nlp(ocr, clasificar_paginas_ocr(ocr, self._extractor)) if ocr else {}
                nlp = json.loads(json.dumps(nlp, ensure_ascii=False))  # mismos tipos que leido de disco
            else:
                ruta_nlp = carpeta / "nlp_resultado.json"
                nlp = json.load(open(ruta_nlp, encoding="utf-8")) if ruta_nlp.exists() else {}
            self._folletos[llave] = (
                {p["pagina"]: p for p in nlp.get("paginas", [])},
                {p["pagina"]: p for p in ocr.get("paginas", [])},
            )
        return self._folletos[llave]

    def _candidatas(self, tienda: str, folleto: str, pagina: str) -> list[dict] | None:
        """load.candidatas_roi_pagina con cache en disco (depende solo de la imagen y del codigo de vision)."""
        if not self.usar_cache:
            return candidatas_roi_pagina(FUENTE_GT, tienda, folleto, pagina)
        ruta = RAIZ_CACHE_REGIONES / self._version_vision / tienda / folleto / f"{pagina}.json"
        if ruta.exists():
            return json.load(open(ruta, encoding="utf-8"))["candidatas"]
        candidatas = candidatas_roi_pagina(FUENTE_GT, tienda, folleto, pagina)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        json.dump({"candidatas": candidatas}, open(ruta, "w", encoding="utf-8"), default=float)
        return candidatas

    def _regiones(self, pag_gt: PaginaGT, pag_nlp: dict) -> list[dict] | None:
        # Igual que Loader._detectar_regiones_pagina: cualquier fallo de ROI -> asociacion por cercania
        try:
            candidatas = self._candidatas(pag_gt.tienda, pag_gt.folleto, pag_gt.pagina)
            if candidatas is None:
                return None
            return regiones_con_precio(candidatas, pag_nlp.get("precios", []))
        except Exception as e:
            logger.warning(f"[Eval] ROI fallo en {pag_gt.clave}: {e} -- cercania")
            return None

    def pagina(self, pag_gt: PaginaGT) -> PaginaPipeline:
        paginas_nlp, paginas_ocr = self._folleto(pag_gt.tienda, pag_gt.folleto)
        pag_nlp, pag_ocr = paginas_nlp.get(pag_gt.pagina), paginas_ocr.get(pag_gt.pagina)
        if pag_nlp is None:
            return PaginaPipeline(pag_gt, None, pag_ocr, [], [], [])

        construidos = construir_registros_pagina(pag_nlp, self._regiones(pag_gt, pag_nlp), self.normalizador)
        registros = []
        for idx, r in enumerate(construidos["precios"]):
            precio, prod = r["precio"], r["producto"]
            registros.append(Registro(
                pagina=pag_gt.clave, idx=idx,
                precio=precio.get("valor"), precio_texto=precio.get("texto", ""), bbox_precio=precio.get("bbox", {}),
                producto=prod["_nombre_norm"] if prod else None,
                producto_texto=prod.get("texto") if prod else None,
                categoria=(prod.get("categoria") or None) if prod else None,
                bbox_producto=prod.get("bbox") if prod else None,
                precio_anterior=r["valor_anterior"],
            ))
        return PaginaPipeline(pag_gt, pag_nlp, pag_ocr, registros,
                              pag_nlp.get("productos", []), construidos["productos"])
