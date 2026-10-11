"""
Proteccion del juez: GT, splits y reglas del evaluador quedan sellados en manifest.json.

Cada corrida recalcula las huellas; si algo cambio sin volver a sellar, la corrida se marca
NO VALIDA. Sellar es una decision humana (el usuario o QA con su aprobacion): los agentes de
NLP y vision no deben correr `sellar`, y como manifest.json esta en git, cualquier
resellado aparece en el diff para revision.
"""
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .gt import RAIZ_GT, huella_gt
from .splits import RUTA_SPLITS

RUTA_MANIFIESTO = Path(__file__).parent / "manifest.json"
_DIR = Path(__file__).parent
# Archivos que definen QUE cuenta como correcto. pipeline.py no: llama al codigo que se evalua.
ARCHIVOS_REGLAS = ("gt.py", "comparar.py", "metricas.py", "splits.py", "integridad.py")


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def huellas_actuales(raiz_gt: Path = RAIZ_GT) -> dict:
    return {
        "gt": huella_gt(raiz_gt),
        "splits": _sha(RUTA_SPLITS) if RUTA_SPLITS.exists() else None,
        "reglas": {nombre: _sha(_DIR / nombre) for nombre in ARCHIVOS_REGLAS},
    }


def sellar(motivo: str) -> dict:
    manifiesto = {"sellado_at": datetime.now().isoformat(timespec="seconds"), "motivo": motivo, **huellas_actuales()}
    json.dump(manifiesto, open(RUTA_MANIFIESTO, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    return manifiesto


def verificar() -> dict:
    """{"valida": bool, "problemas": [...]} comparando contra manifest.json."""
    if not RUTA_MANIFIESTO.exists():
        return {"valida": False, "problemas": ["no hay manifest.json: sellar con `python -m evaluador sellar`"]}
    sellado = json.load(open(RUTA_MANIFIESTO, encoding="utf-8"))
    actual = huellas_actuales()
    problemas = []
    for archivo in sorted(set(sellado["gt"]) | set(actual["gt"])):
        if sellado["gt"].get(archivo) != actual["gt"].get(archivo):
            estado = "nuevo" if archivo not in sellado["gt"] else "falta" if archivo not in actual["gt"] else "modificado"
            problemas.append(f"GT {estado}: {archivo}")
    if sellado["splits"] != actual["splits"]:
        problemas.append("splits.json modificado")
    for nombre in ARCHIVOS_REGLAS:
        if sellado["reglas"].get(nombre) != actual["reglas"].get(nombre):
            problemas.append(f"regla modificada: evaluador/{nombre}")
    return {"valida": not problemas, "problemas": problemas, "sellado_at": sellado.get("sellado_at")}
