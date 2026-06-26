# Motor de OCR - EasyOCR y Tesseract como motores independientes
# Se obtienen resultados de OCR con texto, confianza, bbox y motor utilizado

import logging
import numpy as np
import cv2
from dataclasses import dataclass
from pathlib import Path

# inicialización del logger para este módulo
logger = logging.getLogger(__name__)

# Lista de motores OCR disponibles
MOTORES_DISPONIBLES = ["easyocr", "tesseract"]

# Resultado de OCR con texto, confianza, bbox y motor utilizado
@dataclass
class ResultadoOCR:
    # bloque de texto detectado por el OCR
    texto:     str    # texto detectado
    confianza: float  # Score de confianza (0.0 a 1.0)
    bbox:      list   # [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] en píxeles
    motor:     str    # motor usado

    # Convierte el bbox a formato simple {x, y, ancho, alto} para JSON
    @property
    def bbox_simple(self) -> dict:
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        return {
            "x":     min(xs),
            "y":     min(ys),
            "ancho": max(xs) - min(xs),
            "alto":  max(ys) - min(ys),
        }

    # resultado OCR
    def __str__(self):
        return f"[{self.confianza:.0%}] '{self.texto}' ({self.motor})"

# Motor de OCR con EasyOCR y Tesseract como opciones independientes
class OCREngine: # resultados = ocr.extraer_texto(imagen_np, motor="")

    # Inicialización con idiomas
    def __init__(
        self,
        idiomas:  list[str] = None,
        usar_gpu: bool= False,
    ):
        self.idiomas  = idiomas or ["es", "en"]
        self.usar_gpu = usar_gpu

        self._reader    = None   # instancia de EasyOCR.Reader (inicialización lazy) 
        self._tesseract = False  # instancia de Tesseract verificada (lazy)

    # ------------------ Método principal ------------------ 
    # Extraer texto OCR con motor seleccionado y ordenar resultados por posición
    def extraer_texto(
        self,
        imagen: np.ndarray,
        motor:  str = "easyocr",
    ) -> list[ResultadoOCR]:
        
        # Verificar motor solicitado, easyocr es el default
        if motor not in MOTORES_DISPONIBLES:
            logger.warning(f"[OCR] Motor '{motor}' no válido, usando 'easyocr'.")
            motor = "easyocr"
        # usar easyocr
        if motor == "easyocr":
            self._iniciar_easyocr()
            resultados = self._extraer_easyocr(imagen)
        # usar tesseract
        else:
            resultados = self._extraer_tesseract(imagen)
        # Log de resultados y confianza promedio
        if resultados:
            conf_prom = sum(r.confianza for r in resultados) / len(resultados)
            logger.info(
                f"[OCR] {motor.upper()}: {len(resultados)} bloques, "
                f"confianza promedio: {conf_prom:.0%}"
            )
        else:
            logger.warning(f"[OCR] {motor.upper()} no encontró texto.")

        return self._ordenar_resultados(resultados) # ordenar por posición (arriba-abajo, izquierda-derecha)

    # Extraer texto directamente desde un archivo de imagen sin preprocesar
    def extraer_texto_desde_archivo(
        self,
        ruta:  Path,
        motor: str = "easyocr",
    ) -> list[ResultadoOCR]:
        
        # Cargar imagen con OpenCV (BGR) y convertir a RGB para OCR
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            raise ValueError(f"No se pudo cargar: {ruta}")
        # Convertir de BGR a RGB
        imagen = cv2.cvtColor(imagen, cv2.COLOR_BGR2RGB)
        return self.extraer_texto(imagen, motor=motor) # extraer texto desde imagen numpy (RGB) con motor seleccionado

    
    # ---------------------- Inicialización lazy de motores ---------------------- 
    # cargar easyocr, solo cuando se seleeciona
    def _iniciar_easyocr(self):
        if self._reader is None:
            logger.info("[OCR] Iniciando EasyOCR ...")
            # importar biblioetca
            import easyocr
            self._reader = easyocr.Reader(
                self.idiomas,
                gpu=self.usar_gpu,
                verbose=False,
            )
            logger.info("[OCR] EasyOCR listo.")

    # verificar disponibilidad de Tesseract
    def _verificar_tesseract(self) -> bool:
        if self._tesseract:
            return True
        try:
            # importar biblioteca y verificar versión
            import pytesseract
            pytesseract.get_tesseract_version()
            self._tesseract = True
            return True
        except Exception:
            logger.warning("[OCR] 🛑 Tesseract no disponible.")
            return False

    
    # ---------------- Motores individuales ----------------
    # Extraer texto con EasyOCR, filtrando por confianza y limpiando texto
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
        
    # Extraer texto con Tesseract, filtrando por confianza y limpiando texto
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

    
    # --------------- Utilidades ---------------
    # Ordenar resultados por posición: primero por Y (arriba-abajo) con tolerancia de 20px, luego por X (izquierda-derecha)
    def _ordenar_resultados(
        self, resultados: list[ResultadoOCR]
    ) -> list[ResultadoOCR]:
        # Ordenar por Y (arriba-abajo) con tolerancia de 20px, luego por X (izquierda-derecha)
        def _clave(r: ResultadoOCR) -> tuple:
            y_min = min(p[1] for p in r.bbox)
            x_min = min(p[0] for p in r.bbox)
            return (y_min // 20, x_min)
        return sorted(resultados, key=_clave)
    
    # Imprimir resultados en consola con formato legible
    def imprimir_resultados(self, resultados: list[ResultadoOCR]):
        print(f"\n{'─'*62}")
        print(f"  {'TEXTO':<35} {'CONF':>6}  {'MOTOR'}")
        print(f"{'─'*62}")
        for r in resultados:
            print(f"  {r.texto:<35} {r.confianza:>5.0%}  {r.motor}")
        print(f"{'─'*62}")
        print(f"  Total: {len(resultados)} bloques\n")