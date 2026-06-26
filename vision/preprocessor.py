# Metodos de los 3 perfiles de preprocesamiento de imagenes para mejorar el OCR
# 2 categorías principales: Color (EasyOCR) y Blanco y negro (Tesseract)

import cv2
import numpy as np
import logging 
from pathlib import Path

# Perfiles de preprocesamiento:
"""
     Color - EasyOCR (3 perfiles):
        Preserva color -->  se usa usa canales RGB para segmentar texto del fondo
        Sharpening --> realza bordes de letras sin quitar color
        CLAHE --> mejora contraste local en zonas oscuras sin afectar zonas claras

    Blanco y Negro - Tesseract (3 perfiles):
        Escala de grises --> Tesseract opera mejor en un solo canal
        Gaussiano --> reduce ruido antes de binarizar
        Rotación --> Hough (útil para documentos escaneados)
        Binarización adaptativa --> máximo contraste texto/fondo
"""

# Configuración de logging
logger = logging.getLogger(__name__)

# Clase preporcesar
class Preprocessor:
    
    # Ancho del escalado por default
    ANCHO_OBJETIVO_DEFAULT = 1500  # valor por defecto

    def __init__(
        self,
        
        # --------------- Parámetros compartidos entre perfiles ---------------
        escalar:        bool       = True,
        escala_factor:  float|None = None,   # None --> adaptativo por ancho_objetivo
        ancho_objetivo: int        = None,   # None -->ñ usa ANCHO_OBJETIVO_DEFAULT (1500px)
        
        # --------------- Blanco y negro (Tesseract) ---------------
        escala_grises:  bool  = True,
        reducir_ruido:  bool  = True,
        binarizar:      bool  = True,
        corregir_rot:   bool  = True,
        
        # --------------- COLOR (EasyOCR) ---------------
        sharpening:     bool  = False,  # Realza bordes conservando color
        clahe:          bool  = False,  # Mejora contraste local por canal
    ):
        # Inicializacion de variables
        # Pasos compartidos
        self.escalar_flag  = escalar
        self.escala_factor = escala_factor  # None = adaptativo
        self.ancho_objetivo = ancho_objetivo or self.ANCHO_OBJETIVO_DEFAULT
        # Perfil --> blanco y negro
        self.escala_grises = escala_grises
        self.reducir_ruido = reducir_ruido
        self.binarizar     = binarizar
        self.corregir_rot  = corregir_rot
        # Perfil --> color
        self.sharpening    = sharpening
        self.clahe         = clahe

    # --------------------- Método principal ---------------------
    # Procesa la imagen según los pasos activos en el orden correcto.
    def procesar(self, ruta_imagen: Path) -> np.ndarray:
        imagen = cv2.imread(str(ruta_imagen))
        if imagen is None:
            raise ValueError(f"No se pudo cargar la imagen: {ruta_imagen}")

        logger.info(f"[Preprocessor] Procesando: {ruta_imagen.name} "
                    f"({imagen.shape[1]}x{imagen.shape[0]}px)")

        # 1. Escalar (siempre primero)
        if self.escalar_flag:
            imagen = self._escalar(imagen)

        # 2. CLAHE - mejora contraste antes del sharpening (v2 color)
        if self.clahe:
            imagen = self._clahe(imagen)

        # 3. Sharpening - realza bordes conservando color (v2 color)
        if self.sharpening:
            imagen = self._sharpening(imagen)


        # 4. Escala de grises (v1 / v2 bn)
        if self.escala_grises:
            imagen = self._escala_grises(imagen)

        # 5. Reducir ruido gaussiano (v1 / v2 bn)
        if self.reducir_ruido:
            imagen = self._reducir_ruido(imagen)

        # 6. Corrección de rotación - Hough (v1 / v2 bn)
        if self.corregir_rot:
            imagen = self._corregir_rotacion(imagen)

        # 7. Binarización adaptativa (v1 / v2 bn fuerte)
        if self.binarizar:
            imagen = self._binarizar(imagen)

        # Log final con resolución de la imagen procesada
        logger.info(f"[Preprocessor] Listo --> {imagen.shape[1]}x{imagen.shape[0]}px")
        return imagen

    # Guarda la imagen procesada en la ruta de salida especificada
    def procesar_y_guardar(self, ruta_imagen: Path, ruta_salida: Path) -> Path:
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        imagen_procesada = self.procesar(ruta_imagen)
        cv2.imwrite(str(ruta_salida), imagen_procesada)
        logger.info(f"[Preprocessor] Guardada en: {ruta_salida}")
        return ruta_salida

    # -------------------- Pasos compartidos --------------------
    # escalado adaptativo o fijo, según el perfil
    def _escalar(self, imagen: np.ndarray) -> np.ndarray:
        
        alto, ancho = imagen.shape[:2] # alto, ancho, canales

        # Si la imagen ya es más ancha que el objetivo, no SE escala 
        if self.escala_factor is None:
            # Escalado adaptativo --> calcular factor según ancho objetivo
            if ancho == self.ancho_objetivo:
                logger.info(f"[Preprocessor] Escalado adaptativo: {ancho}px = objetivo, sin cambio")
                return imagen
            factor = self.ancho_objetivo / ancho
            direccion = "↑" if ancho < self.ancho_objetivo else "↓"
            logger.info(
                f"[Preprocessor] Escalado adaptativo: "
                f"{ancho}px {direccion} {self.ancho_objetivo}px (x{factor:.2f})"
            )
        else:
            # Modo fijo v1
            factor = self.escala_factor

        nuevo_ancho = int(ancho * factor)
        nuevo_alto  = int(alto  * factor)
        # INTER_CUBIC suaviza bordes - alternativa: INTER_LANCZOS4 (más nítido, más lento)
        return cv2.resize(imagen, (nuevo_ancho, nuevo_alto),
                          interpolation=cv2.INTER_CUBIC)

    # Convierte a escala de grises si la imagen tiene 3 canales (color)
    def _escala_grises(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        return imagen

    # ---------------------- Perfil Blanco y negro - Tesseracy ----------------------
    # elimina ruido con gauss, no destruye tipografías finas
    def _reducir_ruido(self, imagen: np.ndarray) -> np.ndarray:
        # si la imagen es de 3 canales (color), se convierte a escala de grises
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        return cv2.GaussianBlur(imagen, (3, 3), 0)

    # Binarización adaptativa gaussiana
    def _binarizar(self, imagen: np.ndarray) -> np.ndarray:
        
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        return cv2.adaptiveThreshold(
            imagen,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11, #vecindad
            C=2 # penalización para evitar fondo completamente blanco
        )

    # tecnica de rotacion Hough (inecesaria en pruebas)
    def _corregir_rotacion(self, imagen: np.ndarray) -> np.ndarray:
        
        try:
            img_gris = self._escala_grises(imagen)
            bordes   = cv2.Canny(img_gris, 50, 150, apertureSize=3)
            lineas   = cv2.HoughLines(bordes, 1, np.pi / 180, threshold=100)

            if lineas is None or len(lineas) == 0:
                return imagen

            angulos = []
            for linea in lineas[:20]:
                rho, theta = linea[0]
                angulo = np.degrees(theta) - 90
                if -45 < angulo < 45:
                    angulos.append(angulo)

            if not angulos:
                return imagen

            angulo_promedio = np.median(angulos)
            if abs(angulo_promedio) < 1.0:
                return imagen

            logger.debug(f"Corrigiendo rotación: {angulo_promedio:.2f}°")
            alto, ancho   = imagen.shape[:2]
            centro        = (ancho // 2, alto // 2)
            matriz_rot    = cv2.getRotationMatrix2D(centro, angulo_promedio, 1.0)
            return cv2.warpAffine(
                imagen, matriz_rot, (ancho, alto),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=255
            )
        except Exception as e:
            logger.warning(f"Error en corrección de rotación: {e}, saltando paso.")
            return imagen

    # --------------------------------- v2 COLOR - optimizado para EasyOCR ---------------------- 
    # mejora contraste local sin sobreexponer zonas claras
    # Contrast Limited Adaptive Histogram Equalization
    def _clahe(self, imagen: np.ndarray) -> np.ndarray:
    
        # Si eesta en grises se aplica directo
        if len(imagen.shape) == 2:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(imagen)

        # Color BGR --> LAB --> CLAHE en L --> BGR
        lab   = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB) # luminodsidad, componente verde-rojo, componente azul-amarillo
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)) # 8x8 = 64 cuadricula
        l_eq  = clahe.apply(l)
        lab_eq = cv2.merge([l_eq, a, b])
        return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    # Realza bordes de letras sin quitar color
    def _sharpening(self, imagen: np.ndarray) -> np.ndarray:
        # Resalta bordes y el fondo blanco queda igual, usa el kernel de sharpening
        """
        Explicacion breve, se toma el centro y se multiplica por 5, 
        se resta el valor de los 4 puntos cardenales y se le resta al producto, de esta forma si los 4 puntos cardnales son cargados
        queda igual pero si los 4 puntos cardenales son blancos, el centro se resalta y se ve mas nítido
        """
        kernel = np.array([
            [ 0, -1,  0],
            [-1,  5, -1],
            [ 0, -1,  0]
        ], dtype=np.float32)
        return cv2.filter2D(imagen, -1, kernel)


    # ---------------- Comparación visual original vs procesada ----------------
    # Imagen comparativa, original - tratada 
    def guardar_comparacion(self, ruta_original: Path, ruta_salida: Path) -> Path:
        original  = cv2.imread(str(ruta_original))
        procesada = self.procesar(ruta_original)

        # si la imagen procesada es de 1 canal (grises), convertir a BGR para concatenar
        if len(procesada.shape) == 2:
            procesada_bgr = cv2.cvtColor(procesada, cv2.COLOR_GRAY2BGR)
        else:
            procesada_bgr = procesada

        # rediomensionar ambas imágenes al mismo alto para concatenar horizontalmente
        alto_objetivo = min(original.shape[0], procesada_bgr.shape[0])
        escala_orig   = alto_objetivo / original.shape[0]
        escala_proc   = alto_objetivo / procesada_bgr.shape[0]

        # Redimensionar imágenes manteniendo la relación de aspecto
        orig_resized = cv2.resize(
            original, (int(original.shape[1] * escala_orig), alto_objetivo))
        proc_resized = cv2.resize(
            procesada_bgr, (int(procesada_bgr.shape[1] * escala_proc), alto_objetivo))

        # etiquetas
        cv2.putText(orig_resized, "ORIGINAL",  (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(proc_resized, "PROCESADA", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        comparacion = np.hstack([orig_resized, proc_resized])
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ruta_salida), comparacion)
        logger.info(f"[Preprocessor] Comparación guardada: {ruta_salida}")
        return ruta_salida



# ----------------- COMPARATIVAS ENTRE PERFILES -----------------

"""
PERFIL BASE V1
_PERFILES_V1 = {
    "suave":  Preprocessor(
        escalar=True, escala_factor=1.5,
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
    ),
    "normal": Preprocessor(
        escalar=True, escala_factor=1.5,
        escala_grises=True, reducir_ruido=True, binarizar=False, corregir_rot=True,
    ),
    "fuerte": Preprocessor(
        escalar=True, escala_factor=1.5,
        escala_grises=True, reducir_ruido=True, binarizar=True, corregir_rot=True,
    ),
}
"""

#  Color - EasyOcr
_PERFILES_COLOR = {
    "color_suave": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Solo escala - línea base para EasyOCR en color
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=False, clahe=False,
    ),
    "color_normal": Preprocessor(
        escalar=True, escala_factor=None, ancho_objetivo=1500,  # estándar de producción
        # Escala + sharpening: realza bordes de texto sin quitar color
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=True, clahe=False,
    ),
    "color_fuerte": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Escala + CLAHE + sharpening: para páginas con bajo contraste o zonas oscuras
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=True, clahe=True,
    ),
}

#  Blanco Y Negro - TESSERACT 
_PERFILES_BN = {
    "bn_suave": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Escala + grises: mínimo procesamiento B/N
        escala_grises=True, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=False, clahe=False,
    ),
    "bn_normal": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Escala + grises + gaussiano + rotación
        escala_grises=True, reducir_ruido=True, binarizar=False, corregir_rot=True,
        sharpening=False, clahe=False,
    ),
    "bn_fuerte": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Pipeline completo: escala + grises + gaussiano + rotación + binarización adaptativa
        escala_grises=True, reducir_ruido=True, binarizar=True, corregir_rot=True,
        sharpening=False, clahe=False,
    ),
}

# Catálogo unificado
PERFILES = {**_PERFILES_COLOR, **_PERFILES_BN} # desempaquetar diccionarios y unirlos en uno solo

# Agrupaciones para el menú
#PERFILES_V1    = list(_PERFILES_V1.keys())     # ["suave", "normal", "fuerte"]
PERFILES_COLOR = list(_PERFILES_COLOR.keys())  # ["color_suave", "color_normal", "color_fuerte"]
PERFILES_BN    = list(_PERFILES_BN.keys())     # ["bn_suave", "bn_normal", "bn_fuerte"]


# ----------------- Función para obtener preprocesador por nombre -----------------
def obtener_preprocesador(nombre: str, ancho_objetivo: int = None) -> Preprocessor:
    # Devuelve una instancia de Preprocessor según el nombre del perfil y el ancho objetivo opcional
    if nombre not in PERFILES:
        logger.warning(f"[Preprocessor] Perfil '{nombre}' no encontrado, usando 'color_suave'.")
        nombre = "color_suave"

    p = PERFILES[nombre]

    # Si se pide una resolución diferente al default, crear nueva instancia
    if ancho_objetivo and ancho_objetivo != p.ancho_objetivo:
        import copy
        p_custom = copy.copy(p)
        p_custom.ancho_objetivo = ancho_objetivo
        return p_custom

    return p


# Lista completa de perfiles disponibles (para validación externa)
LISTA_PERFILES = list(PERFILES.keys())