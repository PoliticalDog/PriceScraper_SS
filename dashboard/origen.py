# Procedencia por registro (docs/bi/metricas.md, seccion "Procedencia por registro", 13-oct-2026).
# Logica pura, sin BD: armado seguro de rutas a data/raw y data/processed, lectura del fragmento de una pagina en
# ocr_resultado.json / nlp_resultado.json, caja (bbox) a porcentajes y combinacion de procedencia por id.
#
# Seguridad: ninguna ruta viene del usuario. Las vistas reciben solo un id entero; fuente, tienda, folleto y archivo
# salen de la BD y aun asi se validan aqui (regex + lista de fuentes + la ruta resuelta debe quedar dentro de la base).
#
# Coordenadas: extracciones.bbox_* esta en el espacio de la imagen PROCESADA (escalada por vision/preprocessor.py a
# un ancho que varia por pagina: 1800, 1500, 1350, 1200). La imagen procesada conserva la proporcion de la cruda,
# asi que la caja en % de la procesada vale para ambas. Nunca asumir 1800.

import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional

FUENTES_PERMITIDAS = frozenset({"tiendeo", "ofertomat"})
EXTENSIONES_IMAGEN = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
RE_ARCHIVO_IMAGEN = re.compile(r"^pagina_\d{3}\.(webp|jpg|jpeg|png)$")
RE_FOLLETO_ID = re.compile(r"^[A-Za-z0-9_-]+$")
# slug de tienda: hay uno con apostrofo ("sam's_club"); sin punto, sin separadores
RE_TIENDA_SLUG = re.compile(r"^[A-Za-z0-9_'-]+$")
ARCHIVOS_JSON = {"ocr": "ocr_resultado.json", "nlp": "nlp_resultado.json"}
VERSIONES_IMAGEN = ("proc", "raw")

# Los JSON mas grandes pesan ~1 MB (13-oct-2026); 25 MB deja margen sin permitir cargar algo desproporcionado.
MAX_BYTES_JSON = 25 * 1024 * 1024
MAX_ARCHIVOS_CACHE = 16
# Bloque "coincide" con una caja si son iguales o si se superponen al menos esta fraccion del area del menor.
SUPERPOSICION_MINIMA = 0.5


class RutaInvalida(ValueError):
    """Algun componente de la ruta no pasa la validacion."""


def _validar_componentes(fuente: str, tienda_slug: str, folleto_id_fuente: str) -> None:
    if fuente not in FUENTES_PERMITIDAS:
        raise RutaInvalida(f"fuente no permitida: {fuente!r}")
    if not isinstance(tienda_slug, str) or not RE_TIENDA_SLUG.fullmatch(tienda_slug):
        raise RutaInvalida(f"slug de tienda invalido: {tienda_slug!r}")
    if not isinstance(folleto_id_fuente, str) or not RE_FOLLETO_ID.fullmatch(folleto_id_fuente):
        raise RutaInvalida(f"folleto_id_fuente invalido: {folleto_id_fuente!r}")


def _dentro_de(base: Path, ruta: Path) -> Path:
    base_r = Path(base).resolve()
    ruta_r = ruta.resolve()
    if not ruta_r.is_relative_to(base_r):
        raise RutaInvalida("la ruta sale de la carpeta base")
    return ruta_r


def ruta_imagen(base: Path, fuente: str, tienda_slug: str, folleto_id_fuente: str, archivo_imagen: str) -> Path:
    """Ruta absoluta y validada a la imagen de una pagina. Lanza RutaInvalida si algo no cuadra.
    No comprueba que el archivo exista (eso lo decide la vista: 404)."""
    _validar_componentes(fuente, tienda_slug, folleto_id_fuente)
    if not isinstance(archivo_imagen, str) or not RE_ARCHIVO_IMAGEN.fullmatch(archivo_imagen):
        raise RutaInvalida(f"archivo_imagen invalido: {archivo_imagen!r}")
    if Path(archivo_imagen).suffix.lower() not in EXTENSIONES_IMAGEN:
        raise RutaInvalida("extension no permitida")
    return _dentro_de(base, Path(base) / fuente / tienda_slug / folleto_id_fuente / archivo_imagen)


def ruta_json(base: Path, fuente: str, tienda_slug: str, folleto_id_fuente: str, tipo: str) -> Path:
    """Ruta validada a ocr_resultado.json o nlp_resultado.json (nombre fijo, nunca del usuario)."""
    if tipo not in ARCHIVOS_JSON:
        raise RutaInvalida(f"tipo de JSON no permitido: {tipo!r}")
    _validar_componentes(fuente, tienda_slug, folleto_id_fuente)
    return _dentro_de(base, Path(base) / fuente / tienda_slug / folleto_id_fuente / ARCHIVOS_JSON[tipo])


def tipo_contenido(ruta: Path) -> str:
    tipo = EXTENSIONES_IMAGEN.get(ruta.suffix.lower())
    if tipo is None:
        raise RutaInvalida("extension no permitida")
    return tipo


# -- Lectura del JSON con cache por mtime ----------------------------------------------------------------

_cache: "OrderedDict[str, tuple[int, int, dict]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cargar_json(ruta: Path) -> dict:
    """Devuelve {"estado": "ok", "datos": ...} o {"estado": "ausente"|"muy_grande"|"corrupto"}.
    Cachea por (mtime_ns, tamano): si el archivo cambia (recarga del pipeline) se vuelve a leer."""
    try:
        st = ruta.stat()
    except (FileNotFoundError, NotADirectoryError):
        return {"estado": "ausente"}
    if not ruta.is_file():
        return {"estado": "ausente"}
    if st.st_size > MAX_BYTES_JSON:
        return {"estado": "muy_grande", "bytes": st.st_size}
    clave = str(ruta)
    with _cache_lock:
        en_cache = _cache.get(clave)
        if en_cache and en_cache[0] == st.st_mtime_ns and en_cache[1] == st.st_size:
            _cache.move_to_end(clave)
            return {"estado": "ok", "datos": en_cache[2]}
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"estado": "corrupto"}
    if not isinstance(datos, dict):
        return {"estado": "corrupto"}
    with _cache_lock:
        _cache[clave] = (st.st_mtime_ns, st.st_size, datos)
        _cache.move_to_end(clave)
        while len(_cache) > MAX_ARCHIVOS_CACHE:
            _cache.popitem(last=False)
    return {"estado": "ok", "datos": datos}


def fragmento_pagina(ruta: Path, archivo_imagen: str) -> dict:
    """Solo el elemento de `paginas` cuyo `pagina` == archivo_imagen (no el archivo completo).
    Estados: ok | ausente | corrupto | muy_grande | sin_pagina."""
    leido = _cargar_json(ruta)
    if leido["estado"] != "ok":
        return leido
    paginas = leido["datos"].get("paginas")
    if not isinstance(paginas, list):
        return {"estado": "corrupto"}
    for elem in paginas:
        if isinstance(elem, dict) and elem.get("pagina") == archivo_imagen:
            return {"estado": "ok", "pagina": elem}
    return {"estado": "sin_pagina"}


# -- Cajas -----------------------------------------------------------------------------------------------

def _caja(b) -> Optional[tuple[float, float, float, float]]:
    """Normaliza una caja a (x, y, ancho, alto). Acepta dict del JSON ({x,y,ancho,alto}) o dict de la BD
    ({bbox_x,...}). None si falta algo o el tamano no es positivo."""
    if not isinstance(b, dict):
        return None
    try:
        if "bbox_x" in b:
            x, y, w, h = b["bbox_x"], b["bbox_y"], b["bbox_ancho"], b["bbox_alto"]
        else:
            x, y, w, h = b["x"], b["y"], b["ancho"], b["alto"]
        x, y, w, h = float(x), float(y), float(w), float(h)
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, w, h


def caja_pct(bbox, ancho_imagen, alto_imagen) -> Optional[dict]:
    """Caja en % del tamano de la imagen procesada (left/top/width/height, 0-100, recortada a la imagen)."""
    c = _caja(bbox)
    if c is None or not ancho_imagen or not alto_imagen or ancho_imagen <= 0 or alto_imagen <= 0:
        return None
    x, y, w, h = c
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(float(ancho_imagen), x + w), min(float(alto_imagen), y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return {
        "left": round(100.0 * x0 / ancho_imagen, 3),
        "top": round(100.0 * y0 / alto_imagen, 3),
        "width": round(100.0 * (x1 - x0) / ancho_imagen, 3),
        "height": round(100.0 * (y1 - y0) / alto_imagen, 3),
    }


def coincide(bloque_bbox, caja) -> bool:
    """True si el bloque del JSON es la misma caja o se superpone >= SUPERPOSICION_MINIMA del area del menor
    (la caja de PRODUCTO puede ser la union de varios bloques)."""
    a, b = _caja(bloque_bbox), _caja(caja)
    if a is None or b is None:
        return False
    if a == b:
        return True
    ix = max(0.0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    menor = min(a[2] * a[3], b[2] * b[3])
    return menor > 0 and (ix * iy) / menor >= SUPERPOSICION_MINIMA


def marcar_bloques(pagina: dict, cajas: dict) -> dict:
    """Para cada lista de bloques del fragmento (OCR: "bloques"; NLP: "productos", "precios", ...) devuelve los
    indices que coinciden con cada caja nombrada. cajas = {"precio": {...}, "producto": {...}}.
    Resultado: {"bloques": {"precio": [3], "producto": [2, 4]}, "precios": {...}}"""
    marcas = {}
    if not isinstance(pagina, dict):
        return marcas
    for lista, elems in pagina.items():
        if not isinstance(elems, list):
            continue
        por_caja = {}
        for nombre, caja in cajas.items():
            idx = [i for i, e in enumerate(elems) if isinstance(e, dict) and coincide(e.get("bbox"), caja)]
            if idx:
                por_caja[nombre] = idx
        if por_caja:
            marcas[lista] = por_caja
    return marcas


# -- Combinacion de procedencia ----------------------------------------------------------------------------

CAMPOS_PROCEDENCIA = (
    "pagina_id", "numero_pagina", "folleto_id", "folleto_id_fuente", "folleto_titulo", "url_origen",
)


def combinar_procedencia(filas: list[dict], procedencia: dict, clave: str = "id") -> list[dict]:
    """Agrega a cada fila los CAMPOS_PROCEDENCIA desde procedencia[{id}] (id = extracciones.id, PK: 1 a 1).
    No agrega ni quita filas; si un id no tiene procedencia, los campos quedan en None."""
    for f in filas:
        p = procedencia.get(f.get(clave)) or {}
        for campo in CAMPOS_PROCEDENCIA:
            f[campo] = p.get(campo)
    return filas


def dimensiones_imagen(ruta: Path) -> Optional[tuple[int, int]]:
    """(ancho, alto) leyendo solo la cabecera de la imagen. None si no existe o no se puede leer."""
    try:
        from PIL import Image
        with Image.open(ruta) as im:
            return im.size
    except Exception:  # archivo ausente, truncado o formato desconocido: el visor muestra la pagina sin cajas
        return None


def url_origen_segura(url: Optional[str]) -> Optional[str]:
    """Solo http(s); cualquier otra cosa (javascript:, vacio) se descarta para no generar enlaces peligrosos."""
    # \S+ y fullmatch: sin espacios ni saltos de linea (un "\n" al final pasaba con "$")
    if isinstance(url, str) and re.fullmatch(r"https?://\S+", url.strip(), re.IGNORECASE):
        return url.strip()
    return None
