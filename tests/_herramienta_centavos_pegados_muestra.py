"""Herramienta de SOLO LECTURA (no es prueba). Experimento "soriana: centavos pegados x100", 25-oct-2026.

Toma el signo_digitos.json que deja _herramienta_centavos_pegados_formas.py, filtra los textos que cumplen <regex>,
saca una muestra estratificada por tienda (random.Random(semilla), proporcional con minimo `minimo`) y arma mosaicos
de recortes (rojo = el bloque). Solo escribe en <dir_salida>.

    venv/Scripts/python.exe tests/_herramienta_centavos_pegados_muestra.py <signo_digitos.json> <dir_raw> <dir_salida> <regex> <semilla> <n> <minimo>
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _herramienta_digito_signo_muestra import mosaicos  # noqa: E402


def main(ruta_json, dir_raw, dir_salida, patron, semilla, n, minimo):
    filas = [f for f in json.loads(Path(ruta_json).read_text(encoding="utf-8")) if re.match(patron, f["texto"])]
    print("por tienda:", Counter(f["tienda"] for f in filas).most_common())
    por = defaultdict(list)
    for c in sorted(filas, key=lambda c: (c["tienda"], c["folleto"], c["pagina"], c["bbox"]["y"], c["bbox"]["x"])):
        por[c["tienda"]].append(c)
    rng = random.Random(semilla)
    muestra = []
    for t in sorted(por):
        k = max(minimo, round(n * len(por[t]) / max(1, len(filas))))
        muestra += rng.sample(por[t], min(k, len(por[t])))
    for i, c in enumerate(muestra, 1):
        c["id"] = f"G{i:02d}"
        print(f"{c['id']} {c['tienda']}/{c['folleto']}/{c['pagina']} {c['texto']!r} -> {c['valor']}")
    out = Path(dir_salida)
    out.mkdir(parents=True, exist_ok=True)
    (out / "muestra.json").write_text(json.dumps(muestra, ensure_ascii=False, indent=1), encoding="utf-8")
    mosaicos(muestra, dir_raw, out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]), int(sys.argv[6]), int(sys.argv[7]))
