# Recarga completa de la BD despues de un cambio en nlp/ o load/ (procedimiento de las recargas de oct-2026).
#
#   python recargar_bd.py verificar <etiqueta>   solo lectura: conteos de la BD (antes / despues)
#   python recargar_bd.py respaldo               pg_dump de la BD + tar.gz de los nlp_resultado.json
#   python recargar_bd.py nlp                    reprocesa el NLP de los folletos de produccion (forzar=True)
#   python recargar_bd.py load                   recarga forzada: Loader().cargar_batch(forzar=True)
#   python recargar_bd.py todo                   verificar antes -> respaldo -> nlp -> load -> verificar despues
#
# El reproceso NLP hace falta cuando cambia nlp/: load lee nlp_resultado.json, no el codigo del NLP. Si solo cambia
# load/, basta con el paso load. Los respaldos van a la carpeta padre del repo (--respaldos) y NUNCA a git.
# La recarga reemplaza los datos de cada folleto: corre siempre el respaldo antes y compara las dos verificaciones.

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
os.chdir(REPO)                       # probar_nlp y load usan rutas relativas a data/processed
sys.path.insert(0, str(REPO))

DIR_VERIFICACIONES = Path("data/recargas")
CATALOGO = ("exacto", "fuzzy", "fuzzy_bajo")
CONSULTAS = {
    "precio_filas": "SELECT count(*) AS n FROM extracciones WHERE tipo = 'PRECIO'",
    "dashboard_registros": "SELECT count(*) AS n FROM v_precios_actuales",
    "precio_con_metodo_norm": "SELECT count(*) AS n FROM extracciones WHERE tipo = 'PRECIO' AND metodo_norm IS NOT NULL",
    # = _SQL_CONFIABILIDAD del dashboard sin filtros ("% catalogo")
    "catalogo": f"""
        SELECT count(*) AS registros,
               count(*) FILTER (WHERE COALESCE(e.metodo_norm, p.metodo_norm) IN {CATALOGO}) AS catalogo
        FROM extracciones e JOIN extracciones p ON p.id = e.producto_extraccion_id
        WHERE e.tipo = 'PRECIO' AND e.valor IS NOT NULL AND e.texto_norm IS NOT NULL""",
    "comparativa": "SELECT count(*) AS grupos, COALESCE(sum(num_registros), 0) AS registros FROM v_comparativa_precios",
    "sin_categoria": """SELECT count(*) AS n FROM extracciones WHERE tipo = 'PRECIO' AND valor IS NOT NULL
                        AND texto_norm IS NOT NULL AND COALESCE(BTRIM(categoria_nlp), '') = ''""",
    "folletos": "SELECT count(*) AS n FROM folletos",
    "eventos": "SELECT count(*) AS n FROM eventos_promo",
    "extracciones": "SELECT count(*) AS n FROM extracciones",
    "precios_mil_o_mas": """SELECT t.slug, count(*) AS n FROM extracciones e JOIN tiendas t ON t.id = e.tienda_id
                            WHERE e.tipo = 'PRECIO' AND e.valor >= 1000 GROUP BY t.slug ORDER BY t.slug""",
}


def herramienta_pg(nombre: str) -> str:
    """pg_dump / pg_restore: del PATH, de PG_BIN o de la instalacion mas reciente en Program Files."""
    encontrada = shutil.which(nombre)
    if encontrada:
        return encontrada
    candidatos = []
    if os.environ.get("PG_BIN"):
        candidatos.append(Path(os.environ["PG_BIN"]) / f"{nombre}.exe")
    candidatos += sorted(Path(r"C:\Program Files\PostgreSQL").glob(f"*/bin/{nombre}.exe"), reverse=True)
    for c in candidatos:
        if c.exists():
            return str(c)
    sys.exit(f"[recarga] No encuentro {nombre}: agregalo al PATH o define PG_BIN con la carpeta bin de PostgreSQL")


def verificar(etiqueta: str):
    from load.db_builder import get_connection
    salida = {"etiqueta": etiqueta, "momento": datetime.now().isoformat(timespec="seconds")}
    with get_connection() as conn, conn.cursor() as cur:
        for nombre, sql in CONSULTAS.items():
            cur.execute(sql)
            filas = cur.fetchall()
            salida[nombre] = filas if nombre == "precios_mil_o_mas" else filas[0]
    c = salida["catalogo"]
    salida["pct_catalogo"] = round(100.0 * c["catalogo"] / c["registros"], 1) if c["registros"] else None
    DIR_VERIFICACIONES.mkdir(parents=True, exist_ok=True)
    ruta = DIR_VERIFICACIONES / f"verificacion_{datetime.now():%Y%m%d_%H%M}_{etiqueta}.json"
    ruta.write_text(json.dumps(salida, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for k, v in salida.items():
        if k != "precios_mil_o_mas":
            print(f"{k:24s} {v}")
    print(f"{'precios_mil_o_mas':24s} {sum(f['n'] for f in salida['precios_mil_o_mas'])}")
    print(f"[recarga] verificacion guardada en {ruta}")


def respaldo(destino: Path):
    from load.db_builder import _cargar_url
    from load.load import rutas_nlp
    sello = datetime.now().strftime("%Y%m%d_%H%M")
    dump = destino / f"respaldo_antes_reproceso_nlp_{sello}.dump"
    # la URL va por argumento a pg_dump, nunca a la consola
    subprocess.run([herramienta_pg("pg_dump"), "-Fc", "-d", _cargar_url(), "-f", str(dump)], check=True)
    lista = subprocess.run([herramienta_pg("pg_restore"), "-l", str(dump)], check=True,
                           capture_output=True, text=True).stdout
    entradas = sum(1 for linea in lista.splitlines() if linea and not linea.startswith(";"))
    print(f"[recarga] dump: {dump} ({dump.stat().st_size:,} bytes, {entradas} objetos, legible con pg_restore)")

    rutas = rutas_nlp(Path("data/processed"))
    tar = destino / f"respaldo_nlp_resultado_{sello}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        for r in rutas:
            t.add(r, arcname=str(r))
    print(f"[recarga] nlp: {tar} ({len(rutas)} nlp_resultado.json, {tar.stat().st_size:,} bytes)")


def nlp():
    from nlp.regex_extractor import RegexExtractor
    from probar_nlp import carpetas_con_ocr, procesar_carpeta
    extractor = RegexExtractor(confianza_minima=0.15)
    carpetas = carpetas_con_ocr()
    errores = 0
    for i, carpeta in enumerate(carpetas, 1):
        try:
            if procesar_carpeta(carpeta, extractor, forzar=True) is None:
                errores += 1
        except Exception as e:            # sigue con el resto; se reporta al final
            print(f"[recarga] ERROR {carpeta}: {e}")
            errores += 1
        if i % 50 == 0:
            print(f"[recarga] nlp {i}/{len(carpetas)}", flush=True)
    print(f"[recarga] nlp: {len(carpetas)} folletos, {errores} errores")
    return errores


def load():
    from load.load import Loader
    totales = Loader().cargar_batch(forzar=True)
    print("[recarga] load:", {k: v for k, v in totales.items() if k != "corrida_at"})
    return totales.get("errores", 0)


def main():
    ap = argparse.ArgumentParser(description="Recarga completa de la BD (ver el encabezado del archivo)")
    ap.add_argument("paso", choices=["verificar", "respaldo", "nlp", "load", "todo"])
    ap.add_argument("etiqueta", nargs="?", default="manual", help="para verificar: antes / despues / ...")
    ap.add_argument("--respaldos", default=str(REPO.parent), help="carpeta de los respaldos (fuera del repo)")
    ap.add_argument("--si", action="store_true", help="no pedir confirmacion en 'todo'")
    a = ap.parse_args()
    destino = Path(a.respaldos)

    if a.paso == "verificar":
        verificar(a.etiqueta)
    elif a.paso == "respaldo":
        respaldo(destino)
    elif a.paso == "nlp":
        nlp()
    elif a.paso == "load":
        load()
    else:
        if not a.si and input("Se reprocesa el NLP y se REEMPLAZAN los datos de la BD. ¿Continuar? (s/n): ").strip().lower() != "s":
            return
        verificar("antes")
        respaldo(destino)
        if nlp():
            sys.exit("[recarga] hubo errores en el NLP: revisa antes de cargar (la BD no se toco)")
        load()
        verificar("despues")
        print("[recarga] compara las dos verificaciones de data/recargas/ antes de dar la recarga por buena")


if __name__ == "__main__":
    main()
