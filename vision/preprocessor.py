# preparacion de imagen antes del OCR - 2 motores principales: Color (EasyOCR) y Blanco y negro (Tesseract)
# 2 perfiles (color blanco y negro) y 3 niveles de procesamiento (suave, normal, fuerte) para cada perfil

import cv2
import numpy as np
import logging 
from pathlib import Path

# Perfiles de color - pensadi para EasyOCR (3 perfiles):
"""
    Perfil suave: Escalado a 1800px
    Perfil normal: Escalado, sharpening
    Perfil fuerte:  Escalado, sharpening, clahe
"""

# Perfiles de blanco y negro - pensado para Tesseract (3 perfiles):
"""
    perfil suave: escalado, grises
    perfil normal: escalado, grises, ruido
    perfil fuerte: escalado, grises, ruido, binarizacion
"""

# Configuración de logging
logger = logging.getLogger(__name__)

# Clase principal de preprocesamiento
class Preprocessor:
    
    # Ancho del escalado por default
    ANCHO_OBJETIVO_DEFAULT = 1800  # px valor por defecto (antes 1500, cambiado oct-2026 tras experimento 4 resoluciones)

    # Constructor
    def __init__(self,
        
        # --------------- Parámetros compartidos entre perfiles ---------------
        escalar:        bool       = True,   # siempre se escala
        escala_factor:  float|None = None,   # None --> adaptativo por ancho_objetivo (se ajusta sobre la marcha)
        ancho_objetivo: int        = None,   # None --> usa ANCHO_OBJETIVO_DEFAULT (1800px)
        
        corregir_rot:   bool  = True,       # La verdad no es util aqui, pero se deja porque asi decia el tutorial

        # --------------- Blanco y negro (Tesseract) ---------------
        escala_grises:  bool  = True,
        reducir_ruido:  bool  = True,
        binarizar:      bool  = True,
        
        
        # --------------- COLOR (EasyOCR) ---------------
        sharpening:     bool  = False,  # Realza bordes conservando color
        clahe:          bool  = False,  # Mejora contraste por regiones de 64
    ):
        # Inicializacion de variables
        # Pasos compartidos
        self.escalar_flag  = escalar
        self.escala_factor = escala_factor  # None = adaptativo
        self.ancho_objetivo = ancho_objetivo or self.ANCHO_OBJETIVO_DEFAULT
        self.corregir_rot  = corregir_rot

        # Perfil --> blanco y negro
        self.escala_grises = escala_grises
        self.reducir_ruido = reducir_ruido
        self.binarizar     = binarizar
        
        # Perfil --> color
        self.sharpening    = sharpening
        self.clahe         = clahe

# --------------------- Método principal ---------------------
    # Procesa la imagen según los pasos activos en el orden correcto.
    def procesar(self, ruta_imagen: Path) -> np.ndarray:
        imagen = cv2.imread(str(ruta_imagen))
        if imagen is None:
            raise ValueError(f"No se pudo cargar la imagen: {ruta_imagen}")

        # Log de inicio del procesamiento
        logger.info(f"[Preprocessor] Procesando: {ruta_imagen.name} "
                    f"({imagen.shape[1]}x{imagen.shape[0]}px)")

        # 1. Escalar (siempre primero)
        if self.escalar_flag:
            imagen = self._escalar(imagen)

        # 2. CLAHE - mejora contraste antes del sharpening
        if self.clahe:
            imagen = self._clahe(imagen)

        # 3. Sharpening - realza bordes conservando color
        if self.sharpening:
            imagen = self._sharpening(imagen)

        # 4. Escala de grises
        if self.escala_grises:
            imagen = self._escala_grises(imagen)

        # 5. Reducir ruido gaussiano
        if self.reducir_ruido:
            imagen = self._reducir_ruido(imagen)

        # 6. Corrección de rotación - Hough (no es util para estos folletos, pero se deja por compatibilidad)
        if self.corregir_rot:
            imagen = self._corregir_rotacion(imagen)

        # 7. Binarización adaptativa
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

        # Obtener dimensiones de la imagen
        alto, ancho = imagen.shape[:2] # alto, ancho, canales

        # Determinar medida de escalado 
        if self.escala_factor is None:
            # Escalado adaptativo --> calcular factor según ancho objetivo
            if ancho == self.ancho_objetivo:
                logger.info(f"[Preprocessor] Escalado adaptativo: {ancho}px = objetivo, sin cambio")
                return imagen
            # sino es objetivo, calcula escalado
            factor = self.ancho_objetivo / ancho
            direccion = "AUMENTA" if ancho < self.ancho_objetivo else "REDUCE"
            logger.info(
                f"[Preprocessor] Escalado adaptativo: "
                f"{ancho}px {direccion} {self.ancho_objetivo}px (x{factor:.2f})"
            )
        # Recibio medida fija
        else:
            factor = self.escala_factor

        nuevo_ancho = int(ancho * factor)
        nuevo_alto  = int(alto  * factor)
        # INTER_CUBIC suaviza bordes - alternativa: INTER_LANCZOS4 (más nítido, más lento)
        return cv2.resize(imagen, (nuevo_ancho, nuevo_alto),interpolation=cv2.INTER_CUBIC)

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


    # ---------------------- Perfil Blanco y negro - pensado tesseract ----------------------
    # Convierte a escala de grises si la imagen tiene 3 canales (color)
    def _escala_grises(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        return imagen

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

    # ---------------------- Perfil COLOR - EasyOCR ---------------------- 
    # sharpening - mejora contraste local sin sobreexponer zonas claras
    # CLAHE - Contrast Limited Adaptive Histogram Equalization
   
    # Convierte a LAB, aplica CLAHE en L y vuelve a BGR
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
        Se toma el centro y se multiplica por 5, 
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


# -------- perfiles predefinidos para cada motor de OCR  --------
#  Color - EasyOcr
_PERFILES_COLOR = {
    "color_suave": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo --> ANCHO_OBJETIVO
        # Solo escala - línea base para EasyOCR en color
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=False, clahe=False,
    ),
    "color_normal": Preprocessor(
        escalar=True, escala_factor=None, ancho_objetivo=1800,  # estándar de producción
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

# ----------------- Resolución por tienda -----------------
# Mejor ancho por tienda según el experimento de 4 resoluciones (sources/vision/09_..., criterio:
# promedio de F1 producto y F1 precio) y la comparativa casa_ley 1800 vs 2500 (_v9_B_...).
# Las tiendas que no aparecen aquí usan ANCHO_OBJETIVO_DEFAULT (1800px): o ganaron con 1800
# (bodega_aurrera, heb, s-mart, waldos) o no se han medido todavía.
RESOLUCION_POR_TIENDA = {
    "chedraui": 1200,
    "alsuper":  1350,
    "costco":   1350,
    "merco":    1350,
    "walmart":  1500,
    "casa_ley": 2500,
}

# Devuelve el ancho objetivo de una tienda (None --> default del preprocesador)
def resolucion_para_tienda(tienda: str) -> int | None:
    return RESOLUCION_POR_TIENDA.get(tienda)

# Lista completa de perfiles disponibles (para validación externa)
LISTA_PERFILES = list(PERFILES.keys())