"""
Evaluador de registros finales contra el ground truth.

    python -m evaluador correr [--split dev|holdout|todo] [--nlp disco|memoria] [--tienda T]
    python -m evaluador comparar runs/A.json runs/B.json
    python -m evaluador verificar
    python -m evaluador sellar --motivo "..."        (decision humana)
    python -m evaluador splits --generar             (una sola vez; no regenera)
    python -m evaluador validacion muestra|concordancia --respuestas DIR
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def _con_semilla_fija() -> int | None:
    # Normalizador._extraer_marca desempata marcas del mismo largo segun el orden de un set:
    # sin semilla fija dos corridas iguales podrian diferir
    if os.environ.get("PYTHONHASHSEED") != "0":
        return subprocess.call([sys.executable, "-m", "evaluador", *sys.argv[1:]],
                               env={**os.environ, "PYTHONHASHSEED": "0"})
    return None


def cmd_correr(args) -> int:
    from . import integridad, reporte, splits
    from .comparar import comparar_pagina
    from .gt import cargar_gt
    from .metricas import agregar_por_tienda
    from .pipeline import FuentePipeline, version_vision

    paginas = splits.filtrar(cargar_gt(), args.split, splits.cargar())
    if args.tienda:
        paginas = [p for p in paginas if p.tienda == args.tienda]
    fuente = FuentePipeline(nlp=args.nlp)
    resultados = [comparar_pagina(fuente.pagina(pg)) for pg in paginas]

    metricas = agregar_por_tienda(resultados)
    estado = integridad.verificar()
    meta = {"fecha": datetime.now().isoformat(timespec="seconds"), "split": args.split, "nlp": args.nlp,
            "tienda": args.tienda, "paginas": len(paginas), "version_vision": version_vision(),
            "codigo": reporte.version_codigo()}
    reporte.imprimir_resumen(metricas, estado, meta)
    if not args.sin_guardar:
        ruta = reporte.guardar_corrida(meta, metricas, estado, None if args.split == "holdout" else resultados)
        print(f"\nCorrida guardada: {ruta}")
    return 0 if estado["valida"] else 2


def cmd_comparar(args) -> int:
    from .metricas import comparar_corridas
    from .reporte import imprimir_comparacion
    base, nueva = (json.load(open(r, encoding="utf-8")) for r in (args.base, args.nueva))
    for nombre, corrida in (("base", base), ("nueva", nueva)):
        if not corrida["integridad"]["valida"]:
            print(f"!! La corrida {nombre} NO es valida: {corrida['integridad']['problemas']}")
    if base["meta"]["split"] != nueva["meta"]["split"]:
        print(f"!! Splits distintos: {base['meta']['split']} vs {nueva['meta']['split']}")
    comp = comparar_corridas(base["metricas"], nueva["metricas"])
    imprimir_comparacion(comp)
    return 1 if any(r["bloquea"] for r in comp["regresiones"]) else 0


def cmd_verificar(_args) -> int:
    from .integridad import verificar
    estado = verificar()
    print("Integridad OK (sellado " + str(estado.get("sellado_at")) + ")" if estado["valida"]
          else "NO VALIDA:\n  " + "\n  ".join(estado["problemas"]))
    return 0 if estado["valida"] else 2


def cmd_sellar(args) -> int:
    from .integridad import sellar
    m = sellar(args.motivo)
    print(f"Sellado {m['sellado_at']}: {len(m['gt'])} archivos de GT, splits y {len(m['reglas'])} archivos de reglas")
    return 0


def cmd_splits(args) -> int:
    from . import splits
    from .gt import cargar_gt
    if splits.RUTA_SPLITS.exists():
        print(f"{splits.RUTA_SPLITS} ya existe y no se regenera (la particion esta congelada).")
        return 1
    particion = splits.generar(cargar_gt())
    json.dump(particion, open(splits.RUTA_SPLITS, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"dev: {len(particion['dev'])} folletos | holdout: {len(particion['holdout'])} folletos -> {splits.RUTA_SPLITS}")
    return 0


def cmd_validacion(args) -> int:
    from . import validacion
    from .gt import cargar_gt
    if args.accion == "muestra":
        print(f"Muestra guardada: {validacion.guardar_muestra()}")
        return 0
    # concordancia: respuestas exportadas como <dir>/<id>.json (un archivo por caso)
    muestra = json.load(open(validacion.RAIZ_VALIDACION / "muestra_v1.json", encoding="utf-8"))
    respuestas = {}
    for archivo in Path(args.respuestas).rglob("*.json"):
        doc = json.load(open(archivo, encoding="utf-8"))
        respuestas[archivo.stem] = doc.get("data", doc)
    sin_precio = {p.clave for p in cargar_gt() if not any(a.precio is not None for a in p.articulos)}
    r = validacion.concordancia(muestra, respuestas, sin_precio)
    tasa = "-" if r["concordancia"] is None else f"{r['concordancia'] * 100:.1f}%"
    print(f"Calificados: {r['evaluados']} (+{r['dudosos']} dudosos, {len(r['excluidos'])} sin precio en GT) | acuerdos: {r['acuerdos']} | concordancia: {tasa}")
    for d in r["desacuerdos"]:
        print(f"  {d['id']} {d['pagina']}: dashboard={d['producto']!r} ${d['precio']} | juez={'ok' if d['juez'] else 'mal'} "
              f"humano={'ok' if d['humano'] else 'mal'} | sim={d['detalle_juez'].get('similitud')} nota={d['respuesta'].get('nota', '')!r}")
    salida = validacion.RAIZ_VALIDACION / "concordancia_v1.json"
    json.dump(r, open(salida, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"Detalle: {salida}")
    return 0


def main() -> int:
    reejecucion = _con_semilla_fija()
    if reejecucion is not None:
        return reejecucion
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.path.insert(0, str(Path.cwd()))

    p = argparse.ArgumentParser(prog="python -m evaluador", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("correr", help="mide los registros finales contra el GT")
    c.add_argument("--split", choices=("dev", "holdout", "todo"), default="dev")
    c.add_argument("--nlp", choices=("disco", "memoria"), default="disco",
                   help="disco = nlp_resultado.json cargado; memoria = regenerar con el codigo actual sin escribir")
    c.add_argument("--tienda")
    c.add_argument("--sin-guardar", action="store_true")
    k = sub.add_parser("comparar", help="deltas y regresiones por tienda entre dos corridas")
    k.add_argument("base", type=Path)
    k.add_argument("nueva", type=Path)
    sub.add_parser("verificar", help="GT, splits y reglas contra manifest.json")
    s = sub.add_parser("sellar", help="sella GT, splits y reglas (decision humana)")
    s.add_argument("--motivo", required=True)
    g = sub.add_parser("splits", help="genera splits.json una sola vez")
    g.add_argument("--generar", action="store_true", required=True)
    v = sub.add_parser("validacion", help="fase 3: muestra para calificar y concordancia juez-persona")
    v.add_argument("accion", choices=("muestra", "concordancia"))
    v.add_argument("--respuestas", help="carpeta con las respuestas exportadas (concordancia)")

    args = p.parse_args()
    return {"correr": cmd_correr, "comparar": cmd_comparar, "verificar": cmd_verificar,
            "sellar": cmd_sellar, "splits": cmd_splits, "validacion": cmd_validacion}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
