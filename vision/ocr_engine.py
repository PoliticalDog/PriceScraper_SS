import logging
import numpy as np
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Motor de OCR con EasyOCR como principal y Tesseract como fallback.

"""
    imagen preprocesada
        → EasyOCR (extrae texto + bbox + confianza)
        → si confianza promedio < umbral → Tesseract como fallback
        → lista de ResultadoOCR ordenados por posición
"""

# Representa un bloque de texto detectado por el OCR.
@dataclass
class ResultadoOCR:
    texto:     str      # Texto extraído.
    confianza: float    # Score de confianza del OCR (0.0 a 1.0).
    bbox:      list     # Bounding box [[x1,y1],[x2,y1],[x2,y2],[x1,y2]] en coordenadas de píxeles.
    motor:     str      # Qué motor lo extrajo ('easyocr' o 'tesseract').

    @property
    def bbox_simple(self) -> dict:
        xs = [p[0] for p in self.bbox]
        ys = [p[1] for p in self.bbox]
        # Retorna el bbox como dict con x, y, ancho, alto para guardar en DB.
        return {
            "x":      min(xs),
            "y":      min(ys),
            "ancho":  max(xs) - min(xs),
            "alto":   max(ys) - min(ys),
        }

    def __str__(self):
        return f"[{self.confianza:.0%}] '{self.texto}'"

# EasyOCR principal + Tesseract fallback
class OCREngine:
    """
    EasyOCR es mejor con imágenes de folletos comerciales (fondos de colores, tipografías decorativas)
    Tesseract es mejor con texto impreso limpio sobre fondo blanco  (por eso se usa después del preprocesamiento como fallback)
    """

    # Umbral mínimo de confianza promedio para aceptar resultados de EasyOCR
    # Si el promedio baja de esto, se activa Tesseract como fallback
    UMBRAL_CONFIANZA = 0.4

    def __init__(
        self,
        idiomas: list[str] = None,      # Lista de idiomas para EasyOCR. Default: español + inglés
        usar_gpu: bool = False,         # usar_gpu: bool = true,
        umbral_confianza: float = None, # Confianza mínima para activar fallback a Tesseract --> Default: 40%
    ):
        self.idiomas          = idiomas or ["es", "en"]
        self.usar_gpu         = usar_gpu
        self.umbral_confianza = umbral_confianza or self.UMBRAL_CONFIANZA

        self._reader     = None   # EasyOCR (lazy init — tarda en cargar)
        self._tesseract  = False  # Si Tesseract está disponible

    # ─── Inicialización lazy de motores ───────────────────────────────────────

    def _iniciar_easyocr(self):
        """Inicializa EasyOCR la primera vez que se necesita."""
        if self._reader is None:
            logger.info("[OCR] Iniciando EasyOCR (puede tardar unos segundos)...")
            import easyocr
            self._reader = easyocr.Reader(
                self.idiomas,
                gpu=self.usar_gpu,
                verbose=False,
            )
            logger.info("[OCR] EasyOCR listo.")

    def _verificar_tesseract(self) -> bool:
        """Verifica si Tesseract está instalado y disponible."""
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            self._tesseract = True
            return True
        except Exception:
            logger.warning("[OCR] Tesseract no disponible — solo se usará EasyOCR.")
            return False

    # ─── Método principal ─────────────────────────────────────────────────────

    def extraer_texto(self, imagen: np.ndarray) -> list[ResultadoOCR]:
        """
        Extrae texto de una imagen preprocesada.

        Args:
            imagen: Array NumPy de la imagen (salida del Preprocessor).

        Returns:
            Lista de ResultadoOCR ordenados de arriba a abajo, izquierda a derecha.
        """
        self._iniciar_easyocr()

        # Intentar con EasyOCR primero
        resultados = self._extraer_easyocr(imagen)

        # Calcular confianza promedio
        if resultados:
            confianza_prom = sum(r.confianza for r in resultados) / len(resultados)
            logger.info(f"[OCR] EasyOCR: {len(resultados)} bloques, "
                       f"confianza promedio: {confianza_prom:.0%}")

            # Si la confianza es baja, intentar con Tesseract como fallback
            if confianza_prom < self.umbral_confianza:
                logger.warning(f"[OCR] Confianza baja ({confianza_prom:.0%}), "
                               "activando Tesseract como fallback...")
                resultados_tess = self._extraer_tesseract(imagen)
                if resultados_tess:
                    # Usar Tesseract solo si obtuvo más texto
                    if len(resultados_tess) > len(resultados):
                        logger.info(f"[OCR] Tesseract mejoró: "
                                   f"{len(resultados_tess)} bloques")
                        return resultados_tess
        else:
            logger.warning("[OCR] EasyOCR no encontró texto, intentando Tesseract...")
            resultados = self._extraer_tesseract(imagen)

        return self._ordenar_resultados(resultados)

    def extraer_texto_desde_archivo(self, ruta: Path) -> list[ResultadoOCR]:
        """
        Extrae texto directamente desde un archivo de imagen.
        Útil para pruebas rápidas sin pasar por el Preprocessor.
        """
        import cv2
        imagen = cv2.imread(str(ruta))
        if imagen is None:
            raise ValueError(f"No se pudo cargar: {ruta}")
        return self.extraer_texto(imagen)

    # ─── Motores individuales ─────────────────────────────────────────────────

    def _extraer_easyocr(self, imagen: np.ndarray) -> list[ResultadoOCR]:
        """Extrae texto usando EasyOCR."""
        try:
            # EasyOCR acepta arrays NumPy directamente
            raw = self._reader.readtext(
                imagen,
                detail=1,          # retorna bbox + texto + confianza
                paragraph=False,   # no agrupar en párrafos (queremos bloques individuales)
            )
            resultados = []
            for (bbox, texto, confianza) in raw:
                texto = texto.strip()
                if texto and confianza > 0.1:  # filtrar ruido
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
        """Extrae texto usando Tesseract como fallback."""
        if not self._verificar_tesseract():
            return []
        try:
            import pytesseract

            # Configuración optimizada para folletos en español
            config = "--oem 3 --psm 11 -l spa+eng"

            data = pytesseract.image_to_data(
                imagen,
                config=config,
                output_type=pytesseract.Output.DICT,
            )

            resultados = []
            n = len(data["text"])
            for i in range(n):
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

    # ─── Utilidades ───────────────────────────────────────────────────────────

    def _ordenar_resultados(self, resultados: list[ResultadoOCR]) -> list[ResultadoOCR]:
        """
        Ordena los resultados de arriba a abajo y de izquierda a derecha.
        Importante para que el extractor NLP procese el texto en orden lógico.
        """
        def _clave(r: ResultadoOCR) -> tuple:
            y_min = min(p[1] for p in r.bbox)
            x_min = min(p[0] for p in r.bbox)
            # Agrupar en filas de 20px de tolerancia
            fila = y_min // 20
            return (fila, x_min)

        return sorted(resultados, key=_clave)

    def imprimir_resultados(self, resultados: list[ResultadoOCR]):
        """Imprime los resultados en consola de forma legible. Útil para debug."""
        print(f"\n{'─'*60}")
        print(f"{'TEXTO':<35} {'CONFIANZA':>10}  {'MOTOR'}")
        print(f"{'─'*60}")
        for r in resultados:
            print(f"{r.texto:<35} {r.confianza:>9.0%}  {r.motor}")
        print(f"{'─'*60}")
        print(f"Total: {len(resultados)} bloques de texto\n")