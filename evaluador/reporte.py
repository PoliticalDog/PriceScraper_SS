"""JSON por corrida (data/processed/_eval/runs/) y resumen legible."""
import json
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .comparar import ResultadoPagina

RAIZ_RUNS = Path("data/processed/_eval/runs")
EJEMPLOS_POR_CODIGO = 10


def version_codigo() -> dict:
    def git(*args):
        try:
            return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return None
    return {"commit": git("rev-parse", "--short", "HEAD"),
            "cambios_sin_commit": bool(git("status", "--porcelain", "--untracked-files=no"))}


def _registro(r) -> dict:
    return {"pagina": r.pagina, "precio": r.precio, "precio_texto": r.precio_texto, "producto": r.producto,
            "producto_texto": r.producto_texto, "precio_anterior": r.precio_anterior,
            "bbox_precio": r.bbox_precio, "bbox_producto": r.bbox_producto}


def _articulo(a) -> dict:
    return {"pagina": f"{a.tienda}/{a.folleto}/{a.pagina}", "id": a.id, "producto": a.producto,
            "precio": a.precio, "precio_anterior": a.precio_anterior}


def ejemplos_error(resultados: list[ResultadoPagina]) -> dict:
    """Hasta EJEMPLOS_POR_CODIGO casos por (codigo, tienda), con bbox para recortar la imagen."""
    ej = defaultdict(lambda: defaultdict(list))

    def agregar(codigo, tienda, caso):
        if len(ej[codigo][tienda]) < EJEMPLOS_POR_CODIGO:
            ej[codigo][tienda].append(caso)

    for res in resultados:
        tienda = res.pagina.gt.tienda
        for p in res.pares:
            if p.error:
                agregar(p.error, tienda, {"registro": _registro(p.registro), "esperado": _articulo(p.articulo),
                                          "similitud_producto": round(p.similitud, 2)})
        for r, codigo in res.registros_sobrantes:
            agregar(codigo, tienda, {"registro": _registro(r), "esperado": None})
        for a, codigo in res.articulos_perdidos:
            agregar(codigo, tienda, {"registro": None, "esperado": _articulo(a)})
    return {c: dict(t) for c, t in ej.items()}


def guardar_corrida(meta: dict, metricas: dict, integridad: dict, resultados: list[ResultadoPagina] | None) -> Path:
    v = meta["codigo"]
    nombre = f"{datetime.now():%Y%m%d_%H%M%S}_{v['commit'] or 'sin-git'}{'-sucio' if v['cambios_sin_commit'] else ''}_{meta['split']}.json"
    RAIZ_RUNS.mkdir(parents=True, exist_ok=True)
    ruta = RAIZ_RUNS / nombre
    contenido = {"meta": meta, "integridad": integridad, "metricas": metricas}
    if resultados is not None:  # holdout: solo agregados, nunca registros ni ejemplos
        contenido["ejemplos_error"] = ejemplos_error(resultados)
    json.dump(contenido, open(ruta, "w", encoding="utf-8"), indent=2, ensure_ascii=False, default=str)
    return ruta


def _pct(v) -> str:
    return "  -  " if v is None else f"{v * 100:5.1f}"


def imprimir_resumen(metricas: dict, integridad: dict, meta: dict) -> None:
    print(f"\nEvaluador de registros | split={meta['split']} | nlp={meta['nlp']} | "
          f"commit={meta['codigo']['commit']}{' (con cambios sin commit)' if meta['codigo']['cambios_sin_commit'] else ''}")
    if not integridad["valida"]:
        print("!! CORRIDA NO VALIDA: " + "; ".join(integridad["problemas"]))
    g = metricas["global"]
    ic = g["precision_ic95"]
    print(f"\nPRECISION (principal): {_pct(g['precision'])}%  IC95 [{_pct(ic[0]) if ic else '-'}, {_pct(ic[1]) if ic else '-'}]"
          f" | recall {_pct(g['recall'])}% | F1 {_pct(g['f1'])}%")
    print(f"Basica (precio+producto, sin 'antes'): precision {_pct(g['precision_basica'])}% | recall {_pct(g['recall_basico'])}%")
    print(f"Precio anterior: precision {_pct(g['precision_antes'])}% | recall {_pct(g['recall_antes'])}%"
          f" | categoria {_pct(g['exactitud_categoria'])}%")
    c = g["conteos"]
    print(f"Registros en dashboard: {c['registros_dashboard']} | articulos GT con precio: {c['articulos_con_precio']}"
          f" | completos correctos: {c['completos_ok']} | precios sin producto: {c['registros_sin_producto']}")

    print(f"\n{'tienda':<16} {'regs':>5} {'arts':>5} {'prec%':>6} {'IC95':>13} {'rec%':>6} {'F1%':>6}  error principal")
    for t, m in metricas["tiendas"].items():
        c, ic = m["conteos"], m["precision_ic95"]
        errores = {**m["errores_registro"]}
        for k, v in m["errores_articulo"].items():
            errores[k] = max(errores.get(k, 0), v)
        top = max(errores.items(), key=lambda kv: kv[1]) if any(errores.values()) else ("-", 0)
        ic_txt = f"[{ic[0] * 100:4.0f},{ic[1] * 100:4.0f}]" if ic else "      -"
        chica = " *" if c["articulos_con_precio"] < 20 else ""
        print(f"{t:<16} {c['registros_dashboard']:>5} {c['articulos_con_precio']:>5} {_pct(m['precision']):>6} {ic_txt:>13}"
              f" {_pct(m['recall']):>6} {_pct(m['f1']):>6}  {top[0]} ({top[1]}){chica}")
    print("  * menos de 20 articulos: se reporta con conteos, no bloquea aceptacion")

    print("\nErrores de REGISTRO (lo que el dashboard muestra mal):  " +
          ", ".join(f"{k}={v}" for k, v in g["errores_registro"].items()))
    print("Errores de ARTICULO (lo que se pierde, por primera etapa): " +
          ", ".join(f"{k}={v}" for k, v in g["errores_articulo"].items()))


def imprimir_comparacion(comp: dict) -> None:
    print(f"\n{'ambito':<16} {'precision base->nueva (delta)':>34} {'recall base->nueva (delta)':>32}")
    for f in comp["filas"]:
        def celda(m):
            d = m["delta_pts"]
            return f"{_pct(m['base'])}->{_pct(m['nueva'])} ({'-' if d is None else f'{d:+.1f}'})"
        print(f"{f['ambito']:<16} {celda(f['precision']):>34} {celda(f['recall']):>32}")
    if comp["regresiones"]:
        print("\nREGRESIONES (> 2 pts):")
        for r in comp["regresiones"]:
            print(f"  {r['ambito']} {r['metrica']}: {r['delta_pts']:+.1f} pts (n={r['n']}, z={r['z']})"
                  f"{' SIGNIFICATIVA' if r['significativa'] else ''}{'' if r['bloquea'] else ' [muestra chica, no bloquea]'}")
    else:
        print("\nSin regresiones mayores a 2 pts.")
