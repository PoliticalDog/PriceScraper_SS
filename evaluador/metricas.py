"""Agregados de una corrida (global y por tienda) y comparacion entre dos corridas."""
import math
from collections import Counter, defaultdict

from .comparar import ERRORES_ARTICULO, ERRORES_REGISTRO, ResultadoPagina

# Reglas de aceptacion (protegidas: ver evaluador/integridad.py)
UMBRAL_REGRESION_PTS = 2.0   # provisional, acordado con el usuario
MUESTRA_MINIMA = 20          # por debajo, la tienda se reporta con conteos y no bloquea
Z_95 = 1.96


def _tasa(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def wilson(aciertos: int, n: int) -> tuple[float, float] | None:
    """Intervalo de confianza 95% de una proporcion (estable con muestras chicas)."""
    if not n:
        return None
    p = aciertos / n
    centro = (p + Z_95 ** 2 / (2 * n)) / (1 + Z_95 ** 2 / n)
    margen = Z_95 * math.sqrt(p * (1 - p) / n + Z_95 ** 2 / (4 * n ** 2)) / (1 + Z_95 ** 2 / n)
    return round(max(0.0, centro - margen), 4), round(min(1.0, centro + margen), 4)


def _f1(p: float | None, r: float | None) -> float | None:
    if p is None or r is None or p + r == 0:
        return None if p is None or r is None else 0.0
    return round(2 * p * r / (p + r), 4)


_CONTEOS = ("paginas", "paginas_sin_precio_gt", "registros_dashboard", "registros_sin_producto",
            "articulos_con_precio", "pares", "completos_ok", "basicos_ok", "pares_precio_ok", "pares_producto_ok",
            "registros_con_antes", "antes_ok", "articulos_con_antes", "categoria_evaluable", "categoria_ok",
            "embudo_ocr", "embudo_precio_nlp")


def agregar(resultados: list[ResultadoPagina]) -> dict:
    # Todas las claves presentes aunque valgan 0 (una tienda puede quedar sin paginas evaluables)
    c = Counter(dict.fromkeys(_CONTEOS, 0))
    err_reg, err_art = Counter(), Counter()
    for res in resultados:
        if not res.evaluable:
            c["paginas_sin_precio_gt"] += 1
            continue
        dashboard = res.registros_dashboard
        articulos = res.articulos_con_precio
        c["paginas"] += 1
        c["registros_dashboard"] += len(dashboard)
        c["registros_sin_producto"] += sum(1 for r in res.pagina.registros if r.precio is not None and r.producto is None)
        c["articulos_con_precio"] += len(articulos)
        c["pares"] += len(res.pares)
        c["completos_ok"] += sum(p.completo_ok for p in res.pares)
        c["basicos_ok"] += sum(p.basico_ok for p in res.pares)
        c["pares_precio_ok"] += sum(p.precio_ok for p in res.pares)
        c["pares_producto_ok"] += sum(p.producto_ok for p in res.pares)
        # Precio anterior: lo que el dashboard muestra con "antes" y lo que el GT tiene
        c["registros_con_antes"] += sum(r.precio_anterior is not None for r in dashboard)
        c["antes_ok"] += sum(p.registro.precio_anterior is not None and p.anterior_ok and p.basico_ok for p in res.pares)
        c["articulos_con_antes"] += sum(a.precio_anterior is not None for a in articulos)
        c["categoria_evaluable"] += sum(p.categoria_ok is not None and p.producto_ok for p in res.pares)
        c["categoria_ok"] += sum(bool(p.categoria_ok) and p.producto_ok for p in res.pares)
        for p in res.pares:
            if p.error:
                err_reg[p.error] += 1
                err_art[p.error] += 1
        for _, codigo in res.registros_sobrantes:
            err_reg[codigo] += 1
        for _, codigo in res.articulos_perdidos:
            err_art[codigo] += 1
        # Embudo: cuantos articulos llegan a cada etapa
        perdidos = Counter(codigo for _, codigo in res.articulos_perdidos)
        c["embudo_ocr"] += len(articulos) - perdidos["ocr_no_leido"]
        c["embudo_precio_nlp"] += len(articulos) - perdidos["ocr_no_leido"] - perdidos["clasificacion"] - perdidos["precio_mal_leido"]

    precision = _tasa(c["completos_ok"], c["registros_dashboard"])
    recall = _tasa(c["completos_ok"], c["articulos_con_precio"])
    return {
        "conteos": dict(c),
        "precision": precision,                       # METRICA PRINCIPAL
        "precision_ic95": wilson(c["completos_ok"], c["registros_dashboard"]),
        "recall": recall,
        "f1": _f1(precision, recall),
        "precision_basica": _tasa(c["basicos_ok"], c["registros_dashboard"]),   # precio + producto, sin "antes"
        "recall_basico": _tasa(c["basicos_ok"], c["articulos_con_precio"]),
        "exactitud_precio_en_pares": _tasa(c["pares_precio_ok"], c["pares"]),
        "exactitud_producto_en_pares": _tasa(c["pares_producto_ok"], c["pares"]),
        "precision_antes": _tasa(c["antes_ok"], c["registros_con_antes"]),
        "recall_antes": _tasa(c["antes_ok"], c["articulos_con_antes"]),
        "exactitud_categoria": _tasa(c["categoria_ok"], c["categoria_evaluable"]),
        "errores_registro": {k: err_reg[k] for k in ERRORES_REGISTRO},
        "errores_articulo": {k: err_art[k] for k in ERRORES_ARTICULO},
    }


def agregar_por_tienda(resultados: list[ResultadoPagina]) -> dict:
    por_tienda = defaultdict(list)
    for res in resultados:
        por_tienda[res.pagina.gt.tienda].append(res)
    return {"global": agregar(resultados), "tiendas": {t: agregar(rs) for t, rs in sorted(por_tienda.items())}}


def _z_dos_proporciones(a1: int, n1: int, a2: int, n2: int) -> float | None:
    if not n1 or not n2:
        return None
    p = (a1 + a2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return None if se == 0 else (a2 / n2 - a1 / n1) / se


# metrica -> (aciertos, denominador) en "conteos"
_METRICAS_COMPARABLES = {
    "precision": ("completos_ok", "registros_dashboard"),
    "recall": ("completos_ok", "articulos_con_precio"),
}


def comparar_corridas(base: dict, nueva: dict) -> dict:
    """
    Deltas por tienda. Una caida es REGRESION si supera UMBRAL_REGRESION_PTS; se marca
    significativa si ademas |z| >= 1.96 y la tienda tiene MUESTRA_MINIMA o mas casos.
    """
    filas, regresiones = [], []
    tiendas = sorted(set(base["tiendas"]) | set(nueva["tiendas"]))
    for ambito, mb, mn in [("global", base["global"], nueva["global"])] + [
            (t, base["tiendas"].get(t), nueva["tiendas"].get(t)) for t in tiendas]:
        if mb is None or mn is None:
            continue
        fila = {"ambito": ambito}
        for metrica, (num, den) in _METRICAS_COMPARABLES.items():
            vb, vn = mb[metrica], mn[metrica]
            delta = None if vb is None or vn is None else round((vn - vb) * 100, 2)
            n = min(mb["conteos"][den], mn["conteos"][den])
            z = _z_dos_proporciones(mb["conteos"][num], mb["conteos"][den], mn["conteos"][num], mn["conteos"][den])
            fila[metrica] = {"base": vb, "nueva": vn, "delta_pts": delta, "n": n}
            if delta is not None and delta < -UMBRAL_REGRESION_PTS:
                significativa = n >= MUESTRA_MINIMA and z is not None and abs(z) >= Z_95
                regresiones.append({"ambito": ambito, "metrica": metrica, "delta_pts": delta, "n": n,
                                    "z": None if z is None else round(z, 2), "significativa": significativa,
                                    "bloquea": n >= MUESTRA_MINIMA})
        fila["f1"] = {"base": mb["f1"], "nueva": mn["f1"]}
        filas.append(fila)
    return {"filas": filas, "regresiones": regresiones}
