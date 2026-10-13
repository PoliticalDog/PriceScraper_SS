# Confiabilidad del dato por tienda: lector de corridas del evaluador y etiqueta de confiabilidad.
#
# Modulo puro (sin BD ni settings de Django) para poder probarlo sin base de datos.
# Metrica documentada en docs/bi/metricas.md ("1. Confiabilidad del dato por tienda").
#
# Los resultados del evaluador NO estan en la BD: viven en data/processed/_eval/runs/*.json (uno por corrida,
# escrito por evaluador/reporte.py). Aqui se elige la "corrida vigente" = la mas reciente por meta.fecha que sea
# split dev, sin cambios sin commit e integridad valida, y se resume por tienda. Cada archivo se parsea una sola
# vez por proceso mientras no cambie su mtime (cache por ruta+mtime+tamano).

import json
import re
import threading
from pathlib import Path
from typing import Optional

RAIZ_RUNS = Path(__file__).resolve().parent.parent / "data" / "processed" / "_eval" / "runs"

# -- Umbrales aprobados (12-oct-2026). Cambiarlos requiere actualizar docs/bi/metricas.md. ----------------------
# Etiqueta de confiabilidad: se calcula SOLO con la precision medida por el evaluador (relativa: hoy ninguna
# tienda supera 40%).
UMBRAL_REGISTROS_MINIMOS = 30       # < 30 registros evaluados -> "Muestra insuficiente" (IC95 > 40 puntos de ancho)
UMBRAL_PRECISION_MEDIA = 0.10       # precision < 0.10 -> "Baja" (menos de 1 de cada 10 registros correcto)
UMBRAL_PRECISION_ACEPTABLE = 0.25   # precision >= 0.25 ...
UMBRAL_IC95_INFERIOR_ACEPTABLE = 0.15  # ... y limite inferior del IC95 >= 0.15 -> "Aceptable"
# Distintivo "Base heuristica": % de registros con producto de catalogo por debajo de este valor.
UMBRAL_PCT_CATALOGO_BASE_HEURISTICA = 20.0

SIN_MEDIR = "Sin medir"
MUESTRA_INSUFICIENTE = "Muestra insuficiente"
BAJA = "Baja"
MEDIA = "Media"
ACEPTABLE = "Aceptable"

# Nombre que escribe evaluador/reporte.py: {AAAAMMDD_HHMMSS}_{commit|sin-git}[-sucio]_{split}.json
_PATRON_NOMBRE = re.compile(r"^\d{8}_\d{6}_(?P<commit>[^_]+?)(?P<sucio>-sucio)?_(?P<split>[a-z]+)\.json$")

_cache: dict = {}
_cache_lock = threading.Lock()


def etiqueta_confiabilidad(precision: Optional[float], ic95_inferior: Optional[float],
                           registros: Optional[int]) -> str:
    """Etiqueta de confiabilidad de una tienda segun la corrida del evaluador.

    Orden: sin medicion -> Sin medir; registros < 30 -> Muestra insuficiente; precision < 0.10 -> Baja;
    precision >= 0.25 con IC95 inferior >= 0.15 -> Aceptable; el resto -> Media (incluye precision >= 0.25
    cuyo IC95 inferior no llega a 0.15: no hay evidencia suficiente para "Aceptable").
    """
    if precision is None or not registros:
        return SIN_MEDIR
    if registros < UMBRAL_REGISTROS_MINIMOS:
        return MUESTRA_INSUFICIENTE
    if precision < UMBRAL_PRECISION_MEDIA:
        return BAJA
    if (precision >= UMBRAL_PRECISION_ACEPTABLE and ic95_inferior is not None
            and ic95_inferior >= UMBRAL_IC95_INFERIOR_ACEPTABLE):
        return ACEPTABLE
    return MEDIA


def es_base_heuristica(pct_catalogo: Optional[float]) -> bool:
    """True si menos del 20% de los registros de la tienda tienen producto de catalogo."""
    return pct_catalogo is not None and pct_catalogo < UMBRAL_PCT_CATALOGO_BASE_HEURISTICA


def _descartable_por_nombre(nombre: str) -> bool:
    """Atajo para no parsear 1.2 MB por archivo: si el nombre sigue la convencion del evaluador y dice
    -sucio o un split distinto de dev, se descarta. Nombres fuera de convencion se parsean y se validan."""
    m = _PATRON_NOMBRE.match(nombre)
    return bool(m) and (m.group("sucio") is not None or m.group("split") != "dev")


def _resumir_corrida(ruta: Path) -> Optional[dict]:
    """Lee un JSON de corrida y devuelve solo lo necesario (meta, integridad, metricas global y por tienda).
    Devuelve None si el archivo no se puede leer o no tiene la estructura esperada."""
    try:
        with open(ruta, encoding="utf-8") as fh:
            datos = json.load(fh)
        meta = datos["meta"]
        metricas = datos["metricas"]
        return {
            "archivo": ruta.name,
            "meta": meta,
            "integridad": datos.get("integridad") or {},
            "global": metricas.get("global") or {},
            "tiendas": metricas.get("tiendas") or {},
        }
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _resumen_cacheado(ruta: Path) -> Optional[dict]:
    try:
        st = ruta.stat()
    except OSError:
        return None
    clave = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        previo = _cache.get(ruta)
        if previo and previo[0] == clave:
            return previo[1]
    resumen = _resumir_corrida(ruta)
    with _cache_lock:
        _cache[ruta] = (clave, resumen)
    return resumen


def es_corrida_valida(resumen: Optional[dict]) -> bool:
    """dev + sin cambios sin commit + integridad valida + meta.fecha presente."""
    if not resumen:
        return False
    meta = resumen.get("meta") or {}
    codigo = meta.get("codigo") or {}
    return (
        meta.get("split") == "dev"
        and codigo.get("cambios_sin_commit") is False
        and (resumen.get("integridad") or {}).get("valida") is True
        and bool(meta.get("fecha"))
    )


def corrida_vigente(raiz: Path = RAIZ_RUNS) -> Optional[dict]:
    """Resumen de la corrida vigente (la mas reciente por meta.fecha entre las validas), o None si no hay."""
    try:
        rutas = [p for p in Path(raiz).glob("*.json") if p.is_file()]
    except OSError:
        return None
    validas = []
    for ruta in rutas:
        if _descartable_por_nombre(ruta.name):
            continue
        resumen = _resumen_cacheado(ruta)
        if es_corrida_valida(resumen):
            validas.append(resumen)
    if not validas:
        return None
    # meta.fecha es ISO (2026-10-12T14:19:17): el orden de texto es cronologico. El nombre desempata.
    return max(validas, key=lambda r: (r["meta"]["fecha"], r["archivo"]))


def _error_dominante(errores: Optional[dict]) -> Optional[str]:
    if not errores:
        return None
    nombre, n = max(errores.items(), key=lambda kv: (kv[1] or 0, kv[0]))
    return nombre if n else None


def metricas_tienda(m: Optional[dict]) -> dict:
    """Metricas del evaluador para una tienda (dict de metricas.tiendas.<slug>) + su etiqueta."""
    m = m or {}
    conteos = m.get("conteos") or {}
    ic95 = m.get("precision_ic95") or [None, None]
    registros = conteos.get("registros_dashboard")
    medida = bool(conteos.get("paginas")) and bool(conteos.get("articulos_con_precio"))
    precision = m.get("precision") if medida else None
    return {
        "precision": precision,
        "precision_ic95_inf": ic95[0] if medida else None,
        "precision_ic95_sup": ic95[1] if medida else None,
        "recall": m.get("recall") if medida else None,
        "registros_evaluados": registros if medida else None,
        "articulos_gt": conteos.get("articulos_con_precio") if medida else None,
        "paginas_evaluadas": conteos.get("paginas") if medida else None,
        "error_dominante": _error_dominante(m.get("errores_registro")) if medida else None,
        "etiqueta": etiqueta_confiabilidad(precision, ic95[0] if medida else None,
                                           registros if medida else None),
    }


def info_corrida(resumen: Optional[dict]) -> Optional[dict]:
    """Metadatos de la corrida para mostrar en el panel (commit, fecha, alcance)."""
    if not resumen:
        return None
    meta = resumen["meta"]
    tiendas = resumen.get("tiendas") or {}
    medidas = [s for s, m in tiendas.items() if (m.get("conteos") or {}).get("articulos_con_precio")]
    g = resumen.get("global") or {}
    return {
        "archivo": resumen["archivo"],
        "fecha": meta.get("fecha"),
        "commit": (meta.get("codigo") or {}).get("commit"),
        "split": meta.get("split"),
        "paginas_evaluadas": (g.get("conteos") or {}).get("paginas"),
        "tiendas_en_split": len(tiendas),
        "tiendas_medidas": len(medidas),
        "precision_global": g.get("precision"),
        "recall_global": g.get("recall"),
    }


def unir_confiabilidad(filas_bd: list[dict], resumen: Optional[dict]) -> list[dict]:
    """Une las filas por tienda de la BD (con tienda_slug y pct_catalogo) con las metricas de la corrida.
    Sin corrida (resumen None) todas las tiendas quedan "Sin medir" y la pagina sigue funcionando."""
    tiendas = (resumen or {}).get("tiendas") or {}
    salida = []
    for fila in filas_bd:
        fila = dict(fila)
        fila.update(metricas_tienda(tiendas.get(fila.get("tienda_slug"))))
        fila["base_heuristica"] = es_base_heuristica(fila.get("pct_catalogo"))
        salida.append(fila)
    return salida
