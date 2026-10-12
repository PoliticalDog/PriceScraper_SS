"""
Detalle por caso de una corrida y comparacion caso por caso entre dos corridas.

Los agregados (precision, recall) solo dan netos: un cambio que gana 30 articulos y pierde 28
se ve como +2. Aqui cada articulo del GT y cada registro del dashboard tiene un estado
("ok" o el codigo de error del juez), y comparar dos corridas lista quien cambio de estado.

- Articulo: clave "tienda/folleto/pagina#id" (id del GT, estable entre corridas).
- Registro: clave "tienda/folleto/pagina|precio|x,y" (monto y esquina del bloque de precio):
  estable mientras no cambie el OCR; si cambia, el registro aparece como desaparecido y nuevo.
"""
from collections import Counter, defaultdict

from .comparar import ResultadoPagina

OK = "ok"


def _clave_articulo(a) -> str:
    return f"{a.tienda}/{a.folleto}/{a.pagina}#{a.id}"


def _clave_registro(r) -> str:
    b = r.bbox_precio or {}
    return f"{r.pagina}|{r.precio}|{b.get('x')},{b.get('y')}"


def detalle(resultados: list[ResultadoPagina]) -> dict:
    """Estado de cada articulo (con precio) y de cada registro del dashboard en las paginas evaluables."""
    articulos, registros = {}, {}
    for res in resultados:
        if not res.evaluable:
            continue
        tienda = res.pagina.gt.tienda
        for p in res.pares:
            estado = OK if p.completo_ok else p.error
            articulos[_clave_articulo(p.articulo)] = {
                "tienda": tienda, "estado": estado, "producto_gt": p.articulo.producto, "precio_gt": p.articulo.precio,
                "producto": p.registro.producto, "precio": p.registro.precio, "similitud": round(p.similitud, 2)}
            registros[_clave_registro(p.registro)] = {
                "tienda": tienda, "estado": estado, "producto": p.registro.producto,
                "producto_texto": p.registro.producto_texto, "precio": p.registro.precio,
                "articulo": _clave_articulo(p.articulo)}
        for a, codigo in res.articulos_perdidos:
            articulos[_clave_articulo(a)] = {
                "tienda": tienda, "estado": codigo, "producto_gt": a.producto, "precio_gt": a.precio,
                "producto": None, "precio": None, "similitud": None}
        for r, codigo in res.registros_sobrantes:
            registros[_clave_registro(r)] = {
                "tienda": tienda, "estado": codigo, "producto": r.producto, "producto_texto": r.producto_texto,
                "precio": r.precio, "articulo": None}
    return {"articulos": articulos, "registros": registros}


def _cambios(base: dict, nueva: dict, ausente: str) -> list[dict]:
    """Casos cuyo estado difiere; `ausente` es el estado de una clave que solo existe en una corrida."""
    cambios = []
    for clave in sorted(set(base) | set(nueva)):
        b, n = base.get(clave), nueva.get(clave)
        eb, en = (b or {}).get("estado", ausente), (n or {}).get("estado", ausente)
        if eb != en:
            cambios.append({"clave": clave, "tienda": (n or b)["tienda"], "antes": eb, "despues": en,
                            "base": b, "nueva": n})
    return cambios


def comparar_casos(base: dict, nueva: dict) -> dict:
    """
    Articulos ganados (error -> ok) y perdidos (ok -> error), registros que dejaron de estar bien
    o pasaron a estarlo, y la matriz de transiciones de codigo, por tienda.
    """
    arts = _cambios(base["articulos"], nueva["articulos"], ausente="fuera")
    regs = _cambios(base["registros"], nueva["registros"], ausente="no_existe")

    por_tienda = defaultdict(Counter)
    for c in arts:
        if c["despues"] == OK:
            por_tienda[c["tienda"]]["articulos_ganados"] += 1
        elif c["antes"] == OK:
            por_tienda[c["tienda"]]["articulos_perdidos"] += 1
        else:
            por_tienda[c["tienda"]]["articulos_cambio_error"] += 1
    for c in regs:
        if c["despues"] == OK:
            por_tienda[c["tienda"]]["registros_ganados"] += 1
        elif c["antes"] == OK:
            por_tienda[c["tienda"]]["registros_perdidos"] += 1
        elif c["antes"] == "no_existe":
            por_tienda[c["tienda"]]["registros_nuevos_mal"] += 1

    return {
        "por_tienda": {t: dict(v) for t, v in sorted(por_tienda.items())},
        "transiciones_articulo": Counter(f"{c['antes']} -> {c['despues']}" for c in arts).most_common(),
        "articulos": arts,
        "registros": regs,
    }
