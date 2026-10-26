"""Utilidades de SOLO LECTURA (no es prueba) de los experimentos de centavos del 25-oct-2026
(soriana con centavos pegados x100 y centavos sueltos "90"/"99").

cargar_base(): RegexExtractor de la base de los experimentos (HEAD 798a35f), copiado antes de editar en
tests/_herramienta_centavos_base_regex.txt. cargar_base(ruta) carga otra copia.
"""
import importlib.util
import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
logging.disable(logging.INFO)

BASE_TXT = Path(__file__).resolve().parent / "_herramienta_centavos_base_regex.txt"


def cargar_base(ruta=None, nombre="nlp.regex_extractor_base_centavos"):
    ruta = Path(ruta) if ruta else BASE_TXT
    fuente = ruta.read_text(encoding="utf-8")
    spec = importlib.util.spec_from_loader(nombre, loader=None)
    modulo = importlib.util.module_from_spec(spec)
    modulo.__package__ = "nlp"
    sys.modules[nombre] = modulo
    exec(compile(fuente, str(ruta), "exec"), modulo.__dict__)
    return modulo
