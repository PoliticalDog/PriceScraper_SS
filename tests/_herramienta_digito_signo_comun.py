"""Utilidades de SOLO LECTURA (no es prueba) del experimento "digito leido como $" + escala de la pagina, 25-oct-2026.

cargar_base(): RegexExtractor de la base del experimento (HEAD ff7aaed + regla del "$" suelto aprobada por QA),
copiada antes de editar en tests/_herramienta_digito_signo_base_regex.txt.
senales(): senales de escala de la pagina para un bloque "[568sS]dd".
"""
import importlib.util
import logging
import re
import statistics
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
logging.disable(logging.INFO)

BASE_TXT = Path(__file__).resolve().parent / "_herramienta_digito_signo_base_regex.txt"

FORMA = re.compile(r"^[568sS]\d{2}$")
TRES = re.compile(r"^[0-9sS]\d{2}$")
CENTAVOS = re.compile(r"^\W*(\d{2})\W*$")
LETRAS = re.compile(r"[^\W\d_]{3}")


def cargar_base(nombre="nlp.regex_extractor_base"):
    fuente = BASE_TXT.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_loader(nombre, loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "nlp"
    sys.modules[nombre] = modulo
    exec(compile(fuente, str(BASE_TXT), "exec"), modulo.__dict__)
    return modulo


def mediana_texto(bloques):
    altos = sorted(b["bbox"]["alto"] for b in bloques if b.get("bbox") and LETRAS.search(b.get("texto", "")))
    if not altos:
        return None
    m = len(altos) // 2
    return altos[m] if len(altos) % 2 else (altos[m - 1] + altos[m]) / 2


def tipos(resultado):
    out = {}
    for attr in ("productos", "precios", "precios_anteriores", "ahorros", "promos", "eventos_promo",
                 "atributos", "descartes"):
        for e in getattr(resultado, attr):
            b = e.bbox or {}
            out[(b.get("x"), b.get("y"))] = attr
    return out


def centavos_derecha(b, bloques):
    bb = b["bbox"]
    for o in bloques:
        ob = o.get("bbox")
        if not ob or o is b:
            continue
        m = CENTAVOS.match(o.get("texto", ""))
        if (m and -0.2 * bb["alto"] <= ob["x"] - (bb["x"] + bb["ancho"]) <= 0.5 * bb["alto"]
                and abs(ob["y"] - bb["y"]) <= 0.35 * bb["alto"] and ob["alto"] < bb["alto"]):
            return m.group(1)
    return None


def senales(b, bloques, resultado):
    """Senales de escala para el bloque b ("[568sS]dd") de la pagina.

    ref: precios de la pagina con "$" literal (o fusion entero+centavos) segun la base. Para cada uno, el
    numero de digitos del entero. sim: los de alto 0.6-1.6x el bloque (mismo diseno de casilla).
    tres: bloques de 3 caracteres "[0-9sS]dd" de alto 0.6-1.6x (incluido b): cuantos empiezan con 5/6/8/s.
    """
    h = b["bbox"]["alto"]
    ref, ref_sim = [], []
    for e in resultado.precios:
        if "$" not in e.texto_raw and "+" not in e.texto_raw:
            continue
        if e.valor is None or e.valor <= 0:
            continue
        ent = int(e.valor)
        nd = len(str(ent))
        ref.append(nd)
        eb = e.bbox or {}
        if eb.get("alto") and 0.6 * h <= eb["alto"] <= 1.6 * h:
            ref_sim.append(nd)
    tres_tot = tres_esp = 0
    for o in bloques:
        ob = o.get("bbox")
        t = o.get("texto", "").strip()
        if not ob or not TRES.match(t) or not (0.6 * h <= ob["alto"] <= 1.6 * h):
            continue
        tres_tot += 1
        tres_esp += t[0] in "568sS"
    return {
        "ref_n": len(ref), "ref_2": sum(1 for n in ref if n <= 2), "ref_3": sum(1 for n in ref if n >= 3),
        "sim_n": len(ref_sim), "sim_2": sum(1 for n in ref_sim if n <= 2), "sim_3": sum(1 for n in ref_sim if n >= 3),
        "tres_tot": tres_tot, "tres_esp": tres_esp,
        "ref_mediana": statistics.median([10 ** (n - 1) for n in ref]) if ref else None,
    }
