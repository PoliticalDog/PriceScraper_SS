# Metodos de preprocesamiento de imagenes para mejorar el OCR
# Escalado --> grises --> reduccion ruido --> rotacion --> binarizacion --> OCR

"""
    [v1 - Legacy] Pipeline original (3 perfiles):
        Escalado --> INTER_CUBIC
        Reducir ruido --> gaussiano
        Rotación --> Hough
        Binarización --> adaptativa (gaussiana)

    [v2 - Color] Pipeline optimizado para EasyOCR (3 perfiles):
        Preserva color --> EasyOCR usa canales RGB para segmentar texto del fondo
        Sharpening --> realza bordes de letras sin quitar color
        CLAHE --> mejora contraste local en zonas oscuras sin afectar zonas claras

    [v2 - B/N] Pipeline optimizado para Tesseract (3 perfiles):
        Escala de grises --> Tesseract opera mejor en un solo canal
        Gaussiano --> reduce ruido antes de binarizar
        Rotación --> Hough (útil para documentos escaneados)
        Binarización adaptativa --> máximo contraste texto/fondo
"""

import cv2
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class Preprocessor:
    # ── Resolución objetivo para escalado adaptativo ──────────────────────
    # Normaliza todas las imágenes al mismo ancho antes del OCR.
    # Garantiza que EasyOCR reciba imágenes comparables sin importar la fuente.
    #
    # Referencia empírica (benchmark en curso):
    #   Bodega Aurrerá: 900px  → factor 1.5x → 1350px  (benchmark v1 base)
    #   Soriana Híper:  560px  → factor 2.4x → 1350px
    #   Resoluciones candidatas: 1200 / 1500 / 1800px
    #
    # Activo cuando escala_factor=None. Con valor explícito usa factor fijo.
    # Configurable vía constructor para benchmarks de resolución.
    ANCHO_OBJETIVO_DEFAULT = 1350  # píxeles — valor por defecto

    def __init__(
        self,
        # ── Parámetros compartidos ──────────────────────────────────────
        escalar:        bool       = True,
        escala_factor:  float|None = None,   # None → adaptativo por ancho_objetivo
        ancho_objetivo: int        = None,   # None → usa ANCHO_OBJETIVO_DEFAULT (1350px)
        # ── v1 legacy ───────────────────────────────────────────────────
        escala_grises:  bool  = True,
        reducir_ruido:  bool  = True,
        binarizar:      bool  = True,
        corregir_rot:   bool  = True,
        # ── v2 COLOR (EasyOCR) ──────────────────────────────────────────
        sharpening:     bool  = False,  # Realza bordes conservando color
        clahe:          bool  = False,  # Mejora contraste local por canal
        # ── v2 B/N (Tesseract) ──────────────────────────────────────────
        # Reutiliza: escala_grises, reducir_ruido, corregir_rot, binarizar
    ):
        self.escalar_flag  = escalar
        self.escala_factor = escala_factor  # None = adaptativo
        self.ancho_objetivo = ancho_objetivo or self.ANCHO_OBJETIVO_DEFAULT
        # v1
        self.escala_grises = escala_grises
        self.reducir_ruido = reducir_ruido
        self.binarizar     = binarizar
        self.corregir_rot  = corregir_rot
        # v2 color
        self.sharpening    = sharpening
        self.clahe         = clahe

    # ─────────────────────────────────────────────────────────────────────
    # Método principal
    # ─────────────────────────────────────────────────────────────────────
    def procesar(self, ruta_imagen: Path) -> np.ndarray:
        imagen = cv2.imread(str(ruta_imagen))
        if imagen is None:
            raise ValueError(f"No se pudo cargar la imagen: {ruta_imagen}")

        logger.info(f"[Preprocessor] Procesando: {ruta_imagen.name} "
                    f"({imagen.shape[1]}x{imagen.shape[0]}px)")

        # 1. Escalar (siempre primero)
        if self.escalar_flag:
            imagen = self._escalar(imagen)

        # 2. CLAHE — mejora contraste antes del sharpening (v2 color)
        if self.clahe:
            imagen = self._clahe(imagen)

        # 3. Sharpening — realza bordes conservando color (v2 color)
        if self.sharpening:
            imagen = self._sharpening(imagen)

        # 4. Escala de grises (v1 / v2 bn)
        if self.escala_grises:
            imagen = self._escala_grises(imagen)

        # 5. Reducir ruido gaussiano (v1 / v2 bn)
        if self.reducir_ruido:
            imagen = self._reducir_ruido(imagen)

        # 6. Corrección de rotación — Hough (v1 / v2 bn)
        if self.corregir_rot:
            imagen = self._corregir_rotacion(imagen)

        # 7. Binarización adaptativa (v1 / v2 bn fuerte)
        if self.binarizar:
            imagen = self._binarizar(imagen)

        logger.info(f"[Preprocessor] Listo → {imagen.shape[1]}x{imagen.shape[0]}px")
        return imagen

    def procesar_y_guardar(self, ruta_imagen: Path, ruta_salida: Path) -> Path:
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        imagen_procesada = self.procesar(ruta_imagen)
        cv2.imwrite(str(ruta_salida), imagen_procesada)
        logger.info(f"[Preprocessor] Guardada en: {ruta_salida}")
        return ruta_salida

    # ─────────────────────────────────────────────────────────────────────
    # Pasos compartidos
    # ─────────────────────────────────────────────────────────────────────
    def _escalar(self, imagen: np.ndarray) -> np.ndarray:
        """Escala la imagen al tamaño óptimo para OCR.

        Modo adaptativo (escala_factor=None):
            Calcula el factor dinámicamente para llevar el ancho a ANCHO_OBJETIVO.
            Si la imagen ya es más grande que el objetivo, no se reduce
            (escalar hacia abajo perjudica la calidad OCR).

        Modo fijo (escala_factor=float):
            Aplica el factor explícito — usado por perfiles v1 legacy.
        """
        alto, ancho = imagen.shape[:2]

        if self.escala_factor is None:
            # Modo adaptativo: normalizar al ancho objetivo en ambas direcciones.
            # - Imagen pequeña (<1350px): escalar arriba  → más detalle para OCR
            # - Imagen grande  (>1350px): escalar abajo   → menos carga, mismo resultado
            # - Imagen exacta  (=1350px): sin cambio
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
            # Modo fijo: usar el factor explícito (perfiles v1 legacy)
            factor = self.escala_factor

        nuevo_ancho = int(ancho * factor)
        nuevo_alto  = int(alto  * factor)
        # INTER_CUBIC suaviza bordes — alternativa: INTER_LANCZOS4 (más nítido, más lento)
        return cv2.resize(imagen, (nuevo_ancho, nuevo_alto),
                          interpolation=cv2.INTER_CUBIC)

    def _escala_grises(self, imagen: np.ndarray) -> np.ndarray:
        if len(imagen.shape) == 3:
            return cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
        return imagen

    # ─────────────────────────────────────────────────────────────────────
    # v1 — Legacy
    # ─────────────────────────────────────────────────────────────────────
    def _reducir_ruido(self, imagen: np.ndarray) -> np.ndarray:
        """Gaussiano ligero: más rápido que bilateral, no destruye tipografías finas.
        Alternativa pendiente de prueba: bilateralFilter(d=9, sigmaColor=75, sigmaSpace=75)
        """
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        return cv2.GaussianBlur(imagen, (3, 3), 0)

    def _binarizar(self, imagen: np.ndarray) -> np.ndarray:
        """Binarización adaptativa gaussiana.
        blockSize=11: vecindad local para calcular umbral
        C=2: penalización para evitar fondo completamente blanco
        """
        if len(imagen.shape) == 3:
            imagen = self._escala_grises(imagen)
        return cv2.adaptiveThreshold(
            imagen,
            maxValue=255,
            adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            thresholdType=cv2.THRESH_BINARY,
            blockSize=11,
            C=2
        )

    def _corregir_rotacion(self, imagen: np.ndarray) -> np.ndarray:
        """Corrección de rotación con Transformada de Hough.
        Útil para documentos escaneados. Los folletos digitales de Tiendeo/Ofertomat
        raramente llegan rotados, pero se conserva para completitud del pipeline.
        """
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

    # ─────────────────────────────────────────────────────────────────────
    # v2 COLOR — optimizado para EasyOCR
    # ─────────────────────────────────────────────────────────────────────
    def _clahe(self, imagen: np.ndarray) -> np.ndarray:
        """CLAHE (Contrast Limited Adaptive Histogram Equalization) por canal.
        Mejora el contraste local en zonas oscuras sin sobreexponer zonas claras.
        Opera en el espacio LAB: solo modifica el canal L (luminosidad),
        preservando los canales A y B (color) intactos.
        clipLimit=2.0: límite de amplificación — valores altos aumentan ruido
        tileGridSize=(8,8): tamaño de la rejilla local
        """
        if len(imagen.shape) == 2:
            # Escala de grises: aplicar directamente
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            return clahe.apply(imagen)

        # Color BGR → LAB → CLAHE en L → BGR
        lab   = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l_eq  = clahe.apply(l)
        lab_eq = cv2.merge([l_eq, a, b])
        return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    def _sharpening(self, imagen: np.ndarray) -> np.ndarray:
        """Unsharp masking: realza los bordes de las letras sin quitar color.
        Funciona en color (BGR) y en escala de grises.
        Kernel: resta una versión suavizada de la imagen a sí misma,
        amplificando las diferencias locales (bordes de texto).
        alpha=1.5: intensidad del realce — valores > 2.0 generan halos
        """
        kernel = np.array([
            [ 0, -1,  0],
            [-1,  5, -1],
            [ 0, -1,  0]
        ], dtype=np.float32)
        return cv2.filter2D(imagen, -1, kernel)

    # ─────────────────────────────────────────────────────────────────────
    # Comparación visual original vs procesada
    # ─────────────────────────────────────────────────────────────────────
    def guardar_comparacion(self, ruta_original: Path, ruta_salida: Path) -> Path:
        original  = cv2.imread(str(ruta_original))
        procesada = self.procesar(ruta_original)

        if len(procesada.shape) == 2:
            procesada_bgr = cv2.cvtColor(procesada, cv2.COLOR_GRAY2BGR)
        else:
            procesada_bgr = procesada

        alto_objetivo = min(original.shape[0], procesada_bgr.shape[0])
        escala_orig   = alto_objetivo / original.shape[0]
        escala_proc   = alto_objetivo / procesada_bgr.shape[0]

        orig_resized = cv2.resize(
            original, (int(original.shape[1] * escala_orig), alto_objetivo))
        proc_resized = cv2.resize(
            procesada_bgr, (int(procesada_bgr.shape[1] * escala_proc), alto_objetivo))

        cv2.putText(orig_resized, "ORIGINAL",  (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.putText(proc_resized, "PROCESADA", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        comparacion = np.hstack([orig_resized, proc_resized])
        ruta_salida.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(ruta_salida), comparacion)
        logger.info(f"[Preprocessor] Comparación guardada: {ruta_salida}")
        return ruta_salida


# ─────────────────────────────────────────────────────────────────────────────
# Catálogo de perfiles
# ─────────────────────────────────────────────────────────────────────────────

# ── v1 Legacy ─────────────────────────────────────────────────────────────────
# Perfiles originales — conservados para trazabilidad de la investigación.
# Benchmarks anteriores usaron estos perfiles con EasyOCR y EasyOCR+Tesseract.
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

# ── v2 COLOR — optimizado para EasyOCR ────────────────────────────────────────
# Preserva los canales de color que EasyOCR usa para separar texto del fondo.
# No convierte a grises ni binariza — ambos pasos dañan folletos coloridos.
_PERFILES_COLOR = {
    "color_suave": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo → ANCHO_OBJETIVO
        # Solo escala — línea base para EasyOCR en color
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
        escalar=True, escala_factor=None,   # adaptativo → ANCHO_OBJETIVO
        # Escala + CLAHE + sharpening: para páginas con bajo contraste o zonas oscuras
        escala_grises=False, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=True, clahe=True,
    ),
}

# ── v2 B/N — optimizado para Tesseract ────────────────────────────────────────
# Tesseract opera mejor con texto negro sobre fondo blanco — pipeline clásico.
# La binarización adaptativa maximiza el contraste texto/fondo para el motor.
_PERFILES_BN = {
    "bn_suave": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo → ANCHO_OBJETIVO
        # Escala + grises: mínimo procesamiento B/N
        escala_grises=True, reducir_ruido=False, binarizar=False, corregir_rot=False,
        sharpening=False, clahe=False,
    ),
    "bn_normal": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo → ANCHO_OBJETIVO
        # Escala + grises + gaussiano + rotación
        escala_grises=True, reducir_ruido=True, binarizar=False, corregir_rot=True,
        sharpening=False, clahe=False,
    ),
    "bn_fuerte": Preprocessor(
        escalar=True, escala_factor=None,   # adaptativo → ANCHO_OBJETIVO
        # Pipeline completo: escala + grises + gaussiano + rotación + binarización adaptativa
        escala_grises=True, reducir_ruido=True, binarizar=True, corregir_rot=True,
        sharpening=False, clahe=False,
    ),
}

# Catálogo unificado
PERFILES = {**_PERFILES_V1, **_PERFILES_COLOR, **_PERFILES_BN}

# Agrupaciones para el menú
PERFILES_V1    = list(_PERFILES_V1.keys())     # ["suave", "normal", "fuerte"]
PERFILES_COLOR = list(_PERFILES_COLOR.keys())  # ["color_suave", "color_normal", "color_fuerte"]
PERFILES_BN    = list(_PERFILES_BN.keys())     # ["bn_suave", "bn_normal", "bn_fuerte"]


def obtener_preprocesador(nombre: str, ancho_objetivo: int = None) -> Preprocessor:
    """Retorna el preprocesador correspondiente al nombre del perfil.

    Args:
        nombre:         Nombre del perfil (color_suave, color_normal, etc.)
        ancho_objetivo: Resolución objetivo en píxeles para escalado adaptativo.
                        None → usa el default del perfil (1350px).
                        Útil para benchmarks de resolución (1200 / 1500 / 1800px).

    Si el nombre no existe, retorna color_suave como default seguro.
    """
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