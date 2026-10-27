# Orquestador del pipeline completo: scraper -> vision (OCR) -> NLP -> carga a la BD.
#
#   python orquestador.py                              las 4 etapas, todas las tiendas de Tiendeo
#   python orquestador.py --tiendas heb chedraui       scraper solo de esas tiendas (slugs de TIENDAS)
#   python orquestador.py --etapas vision nlp load     sin descargar (procesa lo que ya este en data/raw)
#   python orquestador.py --gpu --respaldo             OCR en GPU y pg_dump antes de cargar
#
# Cada etapa solo procesa lo nuevo: el scraper salta los folletos del registro, el OCR los que ya tienen
# ocr_resultado.json, el NLP los que tienen nlp_resultado.json y la carga los folletos ya cargados. Por eso se puede
# correr cuantas veces se quiera, y lo que falle se reintenta solo en la siguiente corrida.
# Si una etapa falla en algunos folletos, las siguientes siguen con lo que si salio y el resumen final lo reporta
# (decision de la persona, 26-oct-2026). Sale con codigo 1 si hubo errores, para que la tarea programada lo note.
#
# Solo scrapea Tiendeo: Ofertomat esta deshabilitado por lo complejo de su scrapeo (el modulo se conserva). El OCR, el
# NLP y la carga recorren las dos fuentes porque los folletos de Ofertomat ya descargados siguen en data/.
# No es una recarga: para reprocesar todo despues de cambiar nlp/ o load/ se usa recargar_bd.py.
# Para programarlo cada semana en Windows: orquestador_semanal.bat (ver su encabezado).

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

REPO = Path(__file__).resolve().parent
os.chdir(REPO)                       # rutas relativas (data/, logs/) aunque la tarea programada arranque en otra carpeta
sys.path.insert(0, str(REPO))

ETAPAS = ("scraper", "vision", "nlp", "load")
RESUMEN = Path("logs/orquestador_ultima_corrida.json")


def configurar_logs():
    """Un solo log por corrida (logs/orquestador.log + consola). Se configura ANTES de importar los modulos del
    pipeline: sus basicConfig ya no aplican y todo queda junto; el NLP ademas sigue en logs/nlp.log."""
    Path("logs").mkdir(exist_ok=True)
    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    archivo = RotatingFileHandler("logs/orquestador.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    consola = logging.StreamHandler()
    for h in (archivo, consola):
        h.setFormatter(formato)
    logging.basicConfig(level=logging.INFO, handlers=[consola, archivo], force=True)


logger = logging.getLogger("orquestador")


# -------------------------------------------------- Etapas --------------------------------------------------
# Cada etapa recibe las opciones y devuelve un dict con al menos "procesados" y "errores".

def etapa_scraper(op) -> dict:
    from probar_scraper import TIENDAS, scrapear_tiendeo, scrapear_tiendeo_todas_tiendas
    from scraper.registro import Registro

    registro = Registro()
    antes = registro.total_procesados("tiendeo")

    async def correr():
        if op.tiendas:
            for slug in op.tiendas:
                await scrapear_tiendeo(registro, slug_tienda=slug)
        else:
            await scrapear_tiendeo_todas_tiendas(registro)

    asyncio.run(correr())
    nuevos = registro.total_procesados("tiendeo") - antes
    # Los errores de folletos sueltos los registra el scraper en el log y no se cuentan aqui: el folleto no queda en
    # el registro y se reintenta en la siguiente corrida
    return {"procesados": nuevos, "errores": 0, "detalle": f"{nuevos} folletos nuevos de Tiendeo"}


def _importar_catchup():
    """catchup_tiendeo manda el NLP a logs/nlp.log sin pasar por el root; en el orquestador ese log tambien va al de
    la corrida (y a la consola una sola vez)."""
    import catchup_tiendeo
    import probar_nlp
    log_nlp = logging.getLogger("nlp")
    log_nlp.handlers = [probar_nlp.file_handler]
    log_nlp.propagate = True
    return catchup_tiendeo


def _juntar(resultados: list[dict]) -> dict:
    return {k: sum(r.get(k, 0) for r in resultados) for k in ("pendientes", "procesados", "errores")}


def etapa_vision(op) -> dict:
    catchup_tiendeo = _importar_catchup()
    from load.load import FUENTES
    r = _juntar([catchup_tiendeo.catchup_vision(f, usar_gpu=op.gpu) for f in FUENTES])
    r["detalle"] = f"OCR de {r['procesados']} de {r['pendientes']} folletos pendientes"
    return r


def etapa_nlp(op) -> dict:
    catchup_tiendeo = _importar_catchup()
    from load.load import FUENTES
    r = _juntar([catchup_tiendeo.catchup_nlp(f) for f in FUENTES])
    r["detalle"] = f"NLP de {r['procesados']} de {r['pendientes']} folletos pendientes"
    return r


def etapa_load(op) -> dict:
    import recargar_bd
    from load.load import Loader
    if op.respaldo:
        recargar_bd.respaldo(Path(op.respaldos))
    loader = Loader()
    try:
        totales = loader.cargar_batch(forzar=False)      # solo folletos nuevos o que cambiaron; no borra nada
    finally:
        loader.conn.close()
    recargar_bd.verificar("orquestador")                  # conteos de solo lectura, en data/recargas/
    return {
        "procesados": totales.get("procesados", 0),
        "errores": totales.get("errores", 0) + totales.get("paginas_con_error", 0),
        "detalle": (f"{totales.get('procesados', 0)} folletos cargados, {totales.get('omitidos', 0)} ya estaban, "
                    f"{totales.get('extracciones_total', 0)} extracciones; errores: {totales.get('errores_por_categoria') or 'ninguno'}"),
    }


FUNCIONES = {"scraper": etapa_scraper, "vision": etapa_vision, "nlp": etapa_nlp, "load": etapa_load}


def correr_etapas(etapas: list[str], op, funciones: dict = FUNCIONES) -> list[dict]:
    """Corre las etapas en el orden del pipeline. Una etapa que truena entera se reporta y las siguientes siguen
    (procesan lo que ya este en disco)."""
    resultados = []
    for nombre in [e for e in ETAPAS if e in etapas]:
        logger.info("=" * 20 + f" Etapa: {nombre} " + "=" * 20)
        inicio = time.monotonic()
        try:
            r = dict(funciones[nombre](op))
            r["ok"] = r.get("errores", 0) == 0
        except Exception as e:
            logger.exception(f"[orquestador] La etapa {nombre} fallo completa: {e}")
            r = {"procesados": 0, "errores": 1, "ok": False, "detalle": f"fallo completa: {e}"}
        r["etapa"] = nombre
        r["segundos"] = round(time.monotonic() - inicio, 1)
        resultados.append(r)
    return resultados


def imprimir_resumen(resultados: list[dict]):
    logger.info("=" * 20 + " Resumen " + "=" * 20)
    for r in resultados:
        estado = "OK " if r["ok"] else "CON ERRORES"
        logger.info(f"  {r['etapa']:8s} {estado:12s} {r['segundos']:>8.1f}s  {r.get('detalle', '')}")


def parsear(argv=None):
    ap = argparse.ArgumentParser(description="Pipeline completo: scraper -> OCR -> NLP -> carga (solo lo nuevo)")
    ap.add_argument("--etapas", nargs="+", choices=ETAPAS, default=list(ETAPAS), help="por defecto, las cuatro")
    ap.add_argument("--tiendas", nargs="+", metavar="SLUG", help="scraper solo de estas tiendas de Tiendeo")
    ap.add_argument("--gpu", action="store_true", help="EasyOCR en GPU (requiere torch con CUDA)")
    ap.add_argument("--respaldo", action="store_true", help="pg_dump de la BD antes de cargar")
    ap.add_argument("--respaldos", default=str(REPO.parent), help="carpeta de los respaldos (fuera del repo)")
    return ap.parse_args(argv)


def validar(op):
    """Errores de uso que conviene detectar antes de pasar horas descargando."""
    if op.tiendas:
        from probar_scraper import TIENDAS
        malas = [t for t in op.tiendas if t not in TIENDAS]
        if malas:
            sys.exit(f"Tiendas que no existen en Tiendeo: {malas}. Opciones: {', '.join(TIENDAS)}")
    if op.gpu and "vision" in op.etapas:
        import torch
        if not torch.cuda.is_available():
            sys.exit("--gpu pedido pero torch.cuda.is_available() es False (instala torch con CUDA o quita --gpu)")


def main(argv=None) -> int:
    configurar_logs()
    op = parsear(argv)
    validar(op)
    logger.info(f"[orquestador] Inicio {datetime.now():%Y-%m-%d %H:%M} | etapas: {' -> '.join(op.etapas)} | "
                f"tiendas: {', '.join(op.tiendas) if op.tiendas else 'todas'} | GPU: {op.gpu} | respaldo: {op.respaldo}")
    resultados = correr_etapas(op.etapas, op)
    imprimir_resumen(resultados)
    RESUMEN.write_text(json.dumps({"fecha": datetime.now().isoformat(timespec="seconds"), "etapas": resultados},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r["ok"] for r in resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
