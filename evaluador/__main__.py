"""
Evaluador de registros finales contra el ground truth.

    python -m evaluador correr [--split dev|holdout|todo] [--nlp disco|memoria] [--tienda T]
    python -m evaluador comparar runs/A.json runs/B.json [--casos [--tienda T] [--max N]]
    python -m evaluador catalogo [--tienda T] [--nlp memoria|disco]   (diseno por tienda, solo dev)
    python -m evaluador verificar
    python -m evaluador sellar --motivo "..."        (decision humana)
    python -m evaluador splits --generar             (una sola vez; no regenera)
    python -m evaluador validacion muestra|concordancia --respuestas DIR
    python -m evaluador ocr --nombre N [--tienda T] [--max-paginas K]   (OCR experimental en CPU, dev)
    python -m evaluador correr --ocr-exp N [--tienda T]
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
    if args.ocr_exp:
        from .ocr_experimental import paginas_disponibles
        if args.split != "dev":
            print("El OCR experimental solo existe para dev.")
            return 1
        disponibles = paginas_disponibles(args.ocr_exp)
        paginas = [p for p in paginas if p.clave in disponibles]
        args.nlp = "memoria"
    fuente = FuentePipeline(nlp=args.nlp, ocr_exp=args.ocr_exp)
    resultados = [comparar_pagina(fuente.pagina(pg)) for pg in paginas]

    metricas = agregar_por_tienda(resultados)
    estado = integridad.verificar()
    meta = {"fecha": datetime.now().isoformat(timespec="seconds"), "split": args.split, "nlp": args.nlp,
            "ocr_exp": args.ocr_exp,
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
    if (base["meta"]["paginas"], base["meta"].get("tienda")) != (nueva["meta"]["paginas"], nueva["meta"].get("tienda")):
        print(f"!! Conjuntos de paginas distintos: {base['meta']['paginas']} vs {nueva['meta']['paginas']} paginas "
              "(con OCR experimental, base y cambio deben cubrir las mismas paginas)")
    comp = comparar_corridas(base["metricas"], nueva["metricas"])
    imprimir_comparacion(comp)
    if "detalle" in base and "detalle" in nueva:
        from .casos import comparar_casos
        from .reporte import imprimir_casos
        imprimir_casos(comparar_casos(base["detalle"], nueva["detalle"]), args.casos, args.tienda, args.max)
    else:
        print("\n(sin detalle por caso: alguna corrida es anterior a casos.py o de holdout)")
    return 1 if any(r["bloquea"] for r in comp["regresiones"]) else 0


def cmd_catalogo(args) -> int:
    from . import catalogo, reporte, splits
    from .gt import cargar_gt
    from .pipeline import FuentePipeline

    paginas = splits.filtrar(cargar_gt(), "dev", splits.cargar())  # nunca holdout
    if args.tienda:
        paginas = [p for p in paginas if p.tienda == args.tienda]
    cat = catalogo.construir(paginas, FuentePipeline(nlp=args.nlp))
    tiendas = catalogo.resumen(cat)
    catalogo.imprimir(tiendas)
    meta = {"fecha": datetime.now().isoformat(timespec="seconds"), "split": "dev", "nlp": args.nlp,
            "tienda": args.tienda, "codigo": reporte.version_codigo()}
    print(f"\nCatalogo guardado: {catalogo.guardar(cat, tiendas, meta)}")
    return 0


def cmd_ocr(args) -> int:
    from .ocr_experimental import correr_ocr
    ruta = correr_ocr(args.nombre, args.tienda, args.max_paginas, args.perfil, args.resolucion, args.forzar)
    print(f"OCR experimental listo: {ruta}")
    print(f"Midelo con: python -m evaluador correr --ocr-exp {args.nombre}"
          + (f" --tienda {args.tienda}" if args.tienda else ""))
    return 0


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
    c.add_argument("--ocr-exp", help="usa el OCR experimental <nombre> (solo dev, solo sus paginas, NLP en memoria)")
    o = sub.add_parser("ocr", help="OCR experimental en CPU sobre paginas de dev, sin tocar produccion")
    o.add_argument("--nombre", required=True)
    o.add_argument("--tienda")
    o.add_argument("--max-paginas", type=int)
    o.add_argument("--perfil", help="fuerza un perfil de preprocessor (default: el de cada tienda)")
    o.add_argument("--resolucion", type=int, help="fuerza un ancho objetivo (default: el de cada tienda)")
    o.add_argument("--forzar", action="store_true", help="rehace las paginas aunque ya existan")
    k = sub.add_parser("comparar", help="deltas y regresiones por tienda entre dos corridas")
    k.add_argument("base", type=Path)
    k.add_argument("nueva", type=Path)
    k.add_argument("--casos", action="store_true", help="lista cada articulo ganado o perdido y cada registro que empeora")
    k.add_argument("--tienda", help="con --casos, solo esa tienda")
    k.add_argument("--max", type=int, default=40, help="con --casos, maximo de casos por lista (default 40)")
    d = sub.add_parser("catalogo", help="diseno por tienda en dev: donde queda el nombre respecto al precio")
    d.add_argument("--nlp", choices=("disco", "memoria"), default="memoria")
    d.add_argument("--tienda")
    sub.add_parser("verificar", help="GT, splits y reglas contra manifest.json")
    s = sub.add_parser("sellar", help="sella GT, splits y reglas (decision humana)")
    s.add_argument("--motivo", required=True)
    g = sub.add_parser("splits", help="genera splits.json una sola vez")
    g.add_argument("--generar", action="store_true", required=True)
    v = sub.add_parser("validacion", help="fase 3: muestra para calificar y concordancia juez-persona")
    v.add_argument("accion", choices=("muestra", "concordancia"))
    v.add_argument("--respuestas", help="carpeta con las respuestas exportadas (concordancia)")

    args = p.parse_args()
    return {"correr": cmd_correr, "comparar": cmd_comparar, "verificar": cmd_verificar, "ocr": cmd_ocr,
            "catalogo": cmd_catalogo,
            "sellar": cmd_sellar, "splits": cmd_splits, "validacion": cmd_validacion}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
