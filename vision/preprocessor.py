import cv2
import numpy as np
import logging
from pathlib import Path

# Flujo 1: imagen original → escala de grises → reducción de ruido
# Flujo 2: binarización adaptativa → corrección de rotación → imagen lista para OCR

logger = logging.getLogger(__name__)

# Metodos de preprocesamiento para mejorar la calidad de la imagen antes del OCR
class Preprocessor:

    # se puede activar o desactivar según el tipo de folleto, ya que cada tienda tiene su propio estilo visual.
    def __init__(
        self,
        escala_grises: bool = True,
        reducir_ruido:  bool = True,
        binarizar:      bool = True,
        corregir_rot:   bool = True,
        escalar:        bool = True,
        escala_factor:  float = 2.0,
    ):
        """
            escala_grises: Convertir a escala de grises.
            reducir_ruido: Aplicar filtro de reducción de ruido.
            binarizar:     Aplicar umbral adaptativo (blanco/negro).
            corregir_rot:  Corregir rotación si la imagen está torcida.
            escalar:       Escalar la imagen para mejorar OCR en imágenes pequeñas.
            escala_factor: Factor de escala (2.0 = doble de tamaño).
        """
        self.escala_grises = escala_grises
        self.reducir_ruido = reducir_ruido
        self.binarizar     = binarizar
        self.corregir_rot  = corregir_rot
        self.escalar       = escalar
        self.escala_factor = escala_factor

    # Pipeline principal, regresa --> Imagen procesada como array NumPy lista para EasyOCR
    def procesar(self, ruta_imagen: Path) -> np.ndarray:
        # Cargar imagen
        imagen = cv2.imread(str(ruta_imagen))
        if imagen is None:
            raise ValueError(f"No se pudo cargar la imagen: {ruta_imagen}")

        logger.info(f"[Preprocessor] Procesando: {ruta_imagen.name} "
                    f"({imagen.shape[1]}x{imagen.shape[0]}px)")

        # Escalar primero para que los demás pasos trabajen con más resolución
        if self.escalar:
            imagen = self._escalar(imagen)

        # Convertir a escala de grises
        if self.escala_grises:
            imagen = self._escala_grises(imagen)

        # Reducir ruido (antes de binarizar para mejores resultados)
        if self.reducir_ruido:
            imagen = self._reducir_ruido(imagen)

        # Binarización adaptativa
        if self.binarizar:
            imagen = self._binarizar(imagen)

        # Corrección de rotación
        if self.corregir_rot:
            imagen = self._corregir_rotacion(imagen)

        logger.info(f"[Preprocessor] Listo → {imagen.shape[1]}x{imagen.shape[0]}px")
        return imagen

    # Procesa la imagen y la guarda en disco (depuracion)
    def procesar_y_guardar(self, ruta_imagen: Path, ruta_salida: Path) -> Path:
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        imagen_procesada = self.procesar(ruta_imagen)
        cv2.imwrite(str(ruta_salida), imagen_procesada)
        logger.info(f"[Preprocessor] Guardada en: {ruta_salida}")
        return ruta_salida

    # ----------------------------- Pasos individuales del pipeline -----------------------------
    # Se escala para tener + DPI y mejora precision OCR en textos finos
    def _escalar(self, imagen: np.ndarray) -> np.ndarray:
        alto, ancho = imagen.shape[:2]
        nuevo_ancho = int(ancho * self.escala_factor)
        nuevo_alto  = int(alto  * self.escala_factor)

        # INTER_CUBIC + lento pero mejor calidad 
        # INTER_LINEAR + rapido pero pierde detalles (probar despues)
        return cv2.resize(imagen, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_CUBIC)

    #Se cambia a escala de grises antes de binarizar
    def _escala_grises(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        return imagen

    # — mayor h = más suavizado
    def _reducir_ruido(self, imagen: np.ndarray) -> np.ndarray:
        """
         fastNlMeansDenoising puede borrar texto fino.
        """
        return cv2.fastNlMeansDenoising(imagen, h=10, templateWindowSize=7, searchWindowSize=21)

    # Umbralizacion adaptativo
    def _binarizar(self, imagen: np.ndarray) -> np.ndarray:
        return cv2.adaptiveThreshold(
            imagen,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11,   # tamaño del bloque local (debe ser impar)
            C=2             # constante que se resta del promedio local
        )
    
    # Detecta líneas de texto y corrige rotación si es necesario
    def _corregir_rotacion(self, imagen: np.ndarray) -> np.ndarray:
        """
        detecta líneas de texto con HoughLines y calcular el ángulo promedio,
        Si el ángulo detectado es mayor a 1° y menor a 45° se corrige.
        """
        try:
            # Detectar bordes
            bordes = cv2.Canny(imagen, 50, 150, apertureSize=3)

            # Detectar líneas con transformada de Hough
            lineas = cv2.HoughLines(bordes, 1, np.pi / 180, threshold=100)

            if lineas is None or len(lineas) == 0:
                return imagen

            # Calcular ángulo promedio de las líneas detectadas
            angulos = []
            for linea in lineas[:20]:  # usar las primeras 20 líneas más fuertes
                rho, theta = linea[0]
                angulo = np.degrees(theta) - 90
                # Solo considerar ángulos pequeños (inclinación leve)
                if -45 < angulo < 45:
                    angulos.append(angulo)

            if not angulos:
                return imagen

            angulo_promedio = np.median(angulos)

            # Solo corregir si la inclinación es significativa (> 1°)
            if abs(angulo_promedio) < 1.0:
                return imagen

            logger.debug(f"Corrigiendo rotación: {angulo_promedio:.2f}°")

            # Aplicar rotación
            alto, ancho = imagen.shape[:2]
            centro = (ancho // 2, alto // 2)
            matriz_rot = cv2.getRotationMatrix2D(centro, angulo_promedio, 1.0)
            imagen_rotada = cv2.warpAffine(
                imagen, matriz_rot, (ancho, alto),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE
            )
            return imagen_rotada

        except Exception as e:
            logger.warning(f"Error en corrección de rotación: {e}, saltando paso.")
            return imagen

    # ----------------------------- Utilidad: comparar original vs procesada -----------------------------
    # Guarda ambas imagenes con etiquetas
    def guardar_comparacion(
        self,
        ruta_original: Path,
        ruta_salida: Path
    ) -> Path:
        original  = cv2.imread(str(ruta_original))
        procesada = self.procesar(ruta_original)

        # Convertir procesada a BGR para poder juntarlas
        if len(procesada.shape) == 2:
            procesada_bgr = cv2.cvtColor(procesada, cv2.COLOR_GRAY2BGR)
        else:
            procesada_bgr = procesada

        # Redimensionar ambas al mismo alto para concatenar
        alto_objetivo = min(original.shape[0], procesada_bgr.shape[0])
        escala_orig = alto_objetivo / original.shape[0]
        escala_proc = alto_objetivo / procesada_bgr.shape[0]

        orig_resized = cv2.resize(original,
            (int(original.shape[1] * escala_orig), alto_objetivo))
        proc_resized = cv2.resize(procesada_bgr,
            (int(procesada_bgr.shape[1] * escala_proc), alto_objetivo))

        # Añadir etiquetas
        cv2.putText(orig_resized, "ORIGINAL",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(proc_resized, "PROCESADA",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        comparacion = np.hstack([orig_resized, proc_resized])

        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ruta_salida), comparacion)
        logger.info(f"[Preprocessor] Comparación guardada: {ruta_salida}")
        return ruta_salida
    
# --------------------- Perfiles para diferentes niveles de preprocesamiento según el tipo de folleto (pruebas) ---------------------
def obtener_preprocesador(nombre: str) -> Preprocessor:
    """Factory para obtener la instancia configurada según el perfil."""
    perfiles = {
        "suave":  Preprocessor(escalar=True, escala_factor=1.5, escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False),
        "normal": Preprocessor(escalar=True, escala_factor=1.5, escala_grises=True,  reducir_ruido=True,  binarizar=False, corregir_rot=True),
        "fuerte": Preprocessor(escalar=True, escala_factor=1.5, escala_grises=True,  reducir_ruido=True,  binarizar=True,  corregir_rot=True)
    }
    return perfiles.get(nombre, perfiles["suave"])

# Exponemos esto para que probar_vision pueda iterar si lo necesita
LISTA_PERFILES = ["suave", "normal", "fuerte"]