# Metodos de preprocesamiento de imagenes para mejorar el OCR
# Escalado --> grises --> reduccion ruido --> rotacion --> binarizacion --> OCR

"""
    Escalado --> INTER_CUBIC
    Reducir ruido --> gaussiano
    Rotación --> Hough
    Binarización --> adaptativa (gaussiana)
"""
import cv2
import numpy as np
import logging
from pathlib import Path

# Configuración de logging
logger = logging.getLogger(__name__)

# Función para determinar si es necesario escalar la imagen
class Preprocessor:
    def __init__(
        self,
        escala_grises: bool = True,
        reducir_ruido:  bool = True,
        binarizar:      bool = True,
        corregir_rot:   bool = True,
        escalar:        bool = True,
        escala_factor:  float = 2.0,
    ):
        self.escala_grises = escala_grises
        self.reducir_ruido = reducir_ruido
        self.binarizar     = binarizar
        self.corregir_rot  = corregir_rot
        self.escalar_flag  = escalar        
        self.escala_factor = escala_factor

    # Procesa la imagen según las opciones configuradas
    def procesar(self, ruta_imagen: Path) -> np.ndarray:
        
        # cargar imagen
        imagen = cv2.imread(str(ruta_imagen))
        if imagen is None:
            raise ValueError(f"No se pudo cargar la imagen: {ruta_imagen}")

        logger.info(f"[Preprocessor] Procesando: {ruta_imagen.name} ({imagen.shape[1]}x{imagen.shape[0]}px)")

        # 1. Escalar
        if self.escalar_flag:
            imagen = self._escalar(imagen)

        # 2. Convertir a escala de grises
        if self.escala_grises:
            imagen = self._escala_grises(imagen)

        # 3. Reducir ruido (Suave, para no destruir bordes de letras)
        if self.reducir_ruido:
            imagen = self._reducir_ruido(imagen)

        # 4. Corrección de rotación 
        if self.corregir_rot:
            imagen = self._corregir_rotacion(imagen)

        # 5. Binarización adaptativa
        if self.binarizar:
            imagen = self._binarizar(imagen)

        logger.info(f"[Preprocessor] Listo → {imagen.shape[1]}x{imagen.shape[0]}px")
        return imagen
    
    # Procesa la imagen y la guarda en la ruta especificada
    def procesar_y_guardar(self, ruta_imagen: Path, ruta_salida: Path) -> Path:
        # Asegurar que el directorio de salida exista
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        imagen_procesada = self.procesar(ruta_imagen)
        # Guardar la imagen procesada
        cv2.imwrite(str(ruta_salida), imagen_procesada)
        logger.info(f"[Preprocessor] Guardada en: {ruta_salida}")
        return ruta_salida

    # Escala la imagen según el factor configurado
    def _escalar(self, imagen: np.ndarray) -> np.ndarray:
        alto, ancho = imagen.shape[:2]
        nuevo_ancho = int(ancho * self.escala_factor)
        nuevo_alto  = int(alto  * self.escala_factor)
        # NOTA PARA MI PROBAR: INTER_LANCZOS4 
        return cv2.resize(imagen, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_CUBIC) # inter_cubic suaviza bordes
        #return cv2.resize(imagen, (nuevo_ancho, nuevo_alto), interpolation=cv2.INTER_LANCZOS4)
    
    # Convierte la imagen a escala de grises si no lo está
    def _escala_grises(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        return imagen

    # Aplica un filtro Gaussiano ligero para reducir el ruido sin perder detalles finos
    def _reducir_ruido(self, imagen: np.ndarray) -> np.ndarray:
        # Cambiado a filtro Gaussiano ligero: es más rápido y no destruye fuentes tipográficas finas
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        
        # Nota 2: Probar Bilateral Filter
        return cv2.GaussianBlur(imagen, (3, 3), 0)
        #return cv2.bilateralFilter(imagen, d=9, sigmaColor=75, sigmaSpace=75)
    
    # Binariza la imagen utilizando un método adaptativo
    def _binarizar(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        return cv2.adaptiveThreshold(
            imagen,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11,   # vecindad
            C=2             # penalización para evitar que el fondo quede completamente blanco 
        )
    
    # Corrige la rotación de la imagen utilizando la Transformada de Hough para detectar líneas y calcular el ángulo de inclinación
    def _corregir_rotacion(self, imagen: np.ndarray) -> np.ndarray:
        try:
            # Asegurar que esté en grises para Canny
            img_gris = self._escala_grises(imagen)
            bordes = cv2.Canny(img_gris, 50, 150, apertureSize=3) 
            lineas = cv2.HoughLines(bordes, 1, np.pi / 180, threshold=100)

            # Si no se detectan líneas se asume que la imagen no está rotada
            if lineas is None or len(lineas) == 0:
                return imagen

            # Analizar los ángulos de las líneas detectadas para determinar la rotación predominante
            angulos = []
            for linea in lineas[:20]:
                rho, theta = linea[0]
                angulo = np.degrees(theta) - 90
                if -45 < angulo < 45:
                    angulos.append(angulo)

            # Si no se detectan ángulos válidos la imagen no está rotada
            if not angulos:
                return imagen

            angulo_promedio = np.median(angulos)

            # Si el ángulo es muy pequeño, no es necesario corregir la rotación
            if abs(angulo_promedio) < 1.0:
                return imagen

            logger.debug(f"Corrigiendo rotación: {angulo_promedio:.2f}°")

            alto, ancho = imagen.shape[:2]
            centro = (ancho // 2, alto // 2)
            matriz_rot = cv2.getRotationMatrix2D(centro, angulo_promedio, 1.0)
            
            # Usamos BORDER_CONSTANT con fondo blanco (255) para que los bordes nuevos no ensucien el OCR
            imagen_rotada = cv2.warpAffine(
                imagen, matriz_rot, (ancho, alto),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=255 
            )
            return imagen_rotada

        except Exception as e:
            logger.warning(f"Error en corrección de rotación: {e}, saltando paso.")
            return imagen
        
    # Guarda una imagen que muestra la comparación entre la original y la procesada
    def guardar_comparacion(self, ruta_original: Path, ruta_salida: Path) -> Path:
        original  = cv2.imread(str(ruta_original))
        procesada = self.procesar(ruta_original)

        # Si la imagen procesada es en escala de grises --> convertirla a BGR para mostrarla junto a la original
        if len(procesada.shape) == 2:
            procesada_bgr = cv2.cvtColor(procesada, cv2.COLOR_GRAY2BGR)
        else:
            procesada_bgr = procesada

        # Redimensionar ambas imágenes al mismo alto para que se vean bien juntas
        alto_objetivo = min(original.shape[0], procesada_bgr.shape[0])
        escala_orig = alto_objetivo / original.shape[0]
        escala_proc = alto_objetivo / procesada_bgr.shape[0]

        orig_resized = cv2.resize(original, (int(original.shape[1] * escala_orig), alto_objetivo))
        proc_resized = cv2.resize(procesada_bgr, (int(procesada_bgr.shape[1] * escala_proc), alto_objetivo))

        # Agregar etiquetas a cada imagen
        cv2.putText(orig_resized, "ORIGINAL", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(proc_resized, "PROCESADA", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        # Combinar ambas imágenes horizontalmente
        comparacion = np.hstack([orig_resized, proc_resized])
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ruta_salida), comparacion)
        logger.info(f"[Preprocessor] Comparación guardada: {ruta_salida}")
        return ruta_salida

# Función para obtener un preprocesador según un perfil predefinido
def obtener_preprocesador(nombre: str) -> Preprocessor:
    perfiles = {
        "suave":  Preprocessor(escalar=True, escala_factor=1.5, escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False),
        "normal": Preprocessor(escalar=True, escala_factor=1.5, escala_grises=True,  reducir_ruido=True,  binarizar=False, corregir_rot=True),
        "fuerte": Preprocessor(escalar=True, escala_factor=1.5, escala_grises=True,  reducir_ruido=True,  binarizar=True,  corregir_rot=True)
    }
    return perfiles.get(nombre, perfiles["suave"])

LISTA_PERFILES = ["suave", "normal", "fuerte"]