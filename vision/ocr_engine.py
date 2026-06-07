# Motor de OCR — EasyOCR y Tesseract como motores independientes.
# El motor se elige explícitamente desde el orquestador (probar_vision.py).
# No existe fallback automático — cada motor corre de forma aislada para
# permitir benchmarks limpios y comparaciones justas entre ambos.

"""
    Flujo:
        imagen preprocesada
            --> motor elegido: "easyocr" | "tesseract"
            --> lista de ResultadoOCR ordenados por posición (arriba→abajo, izq→der)

    Historial de cambios:
        v1: EasyOCR principal + Tesseract fallback automático (umbral de confianza)
        v2: Motores independientes, sin fallback — elección explícita por el orquestador
"""

import logging
import numpy as np
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MOTORES_DISPONIBLES = ["easyocr", "tesseract"]


@dataclass
class ResultadoOCR:
    """Representa un bloque de texto detectado por el OCR."""
    texto:     str    # Texto extraído
    confianza: float  # Score de confianza (0.0 a 1.0)
    bbox:      list   # [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] en píxeles
    motor:     str    # Motor que lo extrajo: 'easyocr' o 'tesseract'

    @property
    def bbox_simple(self) -> dict:
        """Convierte el bbox de lista de puntos a dict {x, y, ancho, alto} para JSON."""
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        return {
            "x":     min(xs),
            "y":     min(ys),
            "ancho": max(xs) - min(xs),
            "alto":  max(ys) - min(ys),
        }

    def __str__(self):
        return f"[{self.confianza:.0%}] '{self.texto}' ({self.motor})"


class OCREngine:
    """Motor OCR con EasyOCR y Tesseract como opciones independientes.

    Uso:
        ocr = OCREngine()
        resultados = ocr.extraer_texto(imagen_np, motor="easyocr")
        resultados = ocr.extraer_texto(imagen_np, motor="tesseract")
    """

    def __init__(
        self,
        idiomas:  list[str] = None,
        usar_gpu: bool       = False,
    ):
        self.idiomas  = idiomas or ["es", "en"]
        self.usar_gpu = usar_gpu

        self._reader    = None   # EasyOCR — carga lazy (tarda ~5s la primera vez)
        self._tesseract = False  # Flag de disponibilidad de Tesseract

    # ─────────────────────────────────────────────────────────────────────
    # Método principal
    # ─────────────────────────────────────────────────────────────────────
    def extraer_texto(
        self,
        imagen: np.ndarray,
        motor:  str = "easyocr",
    ) -> list[ResultadoOCR]:
        """Extrae texto de una imagen preprocesada con el motor indicado.

        Args:
            imagen: ndarray BGR (o escala de grises) ya preprocesado.
            motor:  "easyocr" (default) | "tesseract"

        Returns:
            Lista de ResultadoOCR ordenada por posición (arriba→abajo, izq→der).
        """
        if motor not in MOTORES_DISPONIBLES:
            logger.warning(f"[OCR] Motor '{motor}' no válido, usando 'easyocr'.")
            motor = "easyocr"

        if motor == "easyocr":
            self._iniciar_easyocr()
            resultados = self._extraer_easyocr(imagen)
        else:
            resultados = self._extraer_tesseract(imagen)

        if resultados:
            conf_prom = sum(r.confianza for r in resultados) / len(resultados)
            logger.info(
                f"[OCR] {motor.upper()}: {len(resultados)} bloques, "
                f"confianza promedio: {conf_prom:.0%}"
            )
        else:
            logger.warning(f"[OCR] {motor.upper()} no encontró texto.")

        return self._ordenar_resultados(resultados)

    def extraer_texto_desde_archivo(
        self,
        ruta:  Path,
        motor: str = "easyocr",
    ) -> list[ResultadoOCR]:
        """Extrae texto directamente desde un archivo de imagen sin preprocesar."""
        import cv2
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            raise ValueError(f"No se pudo cargar: {ruta}")
        return self.extraer_texto(imagen, motor=motor)

    # ─────────────────────────────────────────────────────────────────────
    # Inicialización lazy de motores
    # ─────────────────────────────────────────────────────────────────────
    def _iniciar_easyocr(self):
        if self._reader is None:
            logger.info("[OCR] Iniciando EasyOCR ...")
            import easyocr
            self._reader = easyocr.Reader(
                self.idiomas,
                gpu=self.usar_gpu,
                verbose=False,
            )
            logger.info("[OCR] EasyOCR listo.")

    def _verificar_tesseract(self) -> bool:
        if self._tesseract:
            return True
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._tesseract = True
            return True
        except Exception:
            logger.warning("[OCR] 🛑 Tesseract no disponible.")
            return False

    # ─────────────────────────────────────────────────────────────────────
    # Motores individuales
    # ─────────────────────────────────────────────────────────────────────
    def _extraer_easyocr(self, imagen: np.ndarray) -> list[ResultadoOCR]:
        try:
            raw = self._reader.readtext(
                imagen,
                detail=1,        # retorna bbox + texto + confianza
                paragraph=False, # bloques individuales (no agrupar párrafos)
            )
            resultados = []
            for (bbox, texto, confianza) in raw:
                texto = texto.strip()
                if texto and confianza > 0.1:  # filtrar ruido extremo
                    resultados.append(ResultadoOCR(
                        texto=texto,
                        confianza=float(confianza),
                        bbox=[[int(p[0]), int(p[1])] for p in bbox],
                        motor="easyocr",
                    ))
            return resultados
        except Exception as e:
            logger.error(f"[OCR] Error en EasyOCR: {e}")
            return []

    def _extraer_tesseract(self, imagen: np.ndarray) -> list[ResultadoOCR]:
        if not self._verificar_tesseract():
            return []
        try:
            import pytesseract
            # oem 3: motor LSTM (más preciso)
            # psm 11: texto disperso sin orden fijo (adecuado para folletos)
            config = "--oem 3 --psm 11 -l spa+eng"
            data   = pytesseract.image_to_data(
                imagen,
                config=config,
                output_type=pytesseract.Output.DICT,
            )
            resultados = []
            for i in range(len(data["text"])):
                texto = data["text"][i].strip()
                conf  = int(data["conf"][i])
                if not texto or conf < 10:
                    continue
                x, y = data["left"][i], data["top"][i]
                w, h = data["width"][i], data["height"][i]
                resultados.append(ResultadoOCR(
                    texto=texto,
                    confianza=conf / 100.0,
                    bbox=[[x, y], [x+w, y], [x+w, y+h], [x, y+h]],
                    motor="tesseract",
                ))
            return resultados
        except Exception as e:
            logger.error(f"[OCR] Error en Tesseract: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────
    # Utilidades
    # ─────────────────────────────────────────────────────────────────────
    def _ordenar_resultados(
        self, resultados: list[ResultadoOCR]
    ) -> list[ResultadoOCR]:
        """Ordena bloques de arriba a abajo y de izquierda a derecha.
        Agrupa en filas con tolerancia de 20px para alinear texto al mismo nivel.
        """
        def _clave(r: ResultadoOCR) -> tuple:
            y_min = min(p[1] for p in r.bbox)
            x_min = min(p[0] for p in r.bbox)
            return (y_min // 20, x_min)
        return sorted(resultados, key=_clave)

    def imprimir_resultados(self, resultados: list[ResultadoOCR]):
        print(f"\n{'─'*62}")
        print(f"  {'TEXTO':<35} {'CONF':>6}  {'MOTOR'}")
        print(f"{'─'*62}")
        for r in resultados:
            print(f"  {r.texto:<35} {r.confianza:>5.0%}  {r.motor}")
        print(f"{'─'*62}")
        print(f"  Total: {len(resultados)} bloques\n")