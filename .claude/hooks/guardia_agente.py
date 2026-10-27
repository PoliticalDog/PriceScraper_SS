"""
Guardia de los subagentes (PreToolUse). Solo corre mientras un agente de .claude/agents/ esta activo:
la sesion principal no la usa.

    python .claude/hooks/guardia_agente.py <rol>      rol = producto | vision | qa | bi

Lee el evento del hook por stdin. Sale con 2 (bloquea y le explica el motivo al agente) o con 0.
Si este archivo no existe, python tambien sale con 2: la guardia falla cerrada.

Lo que ningun agente puede hacer:
- tocar el ground truth, los splits, las reglas del evaluador ni esta misma configuracion;
- hacer commits, push o cambiar el arbol de git;
- recargar la BD o reescribir los JSON de produccion (OCR, NLP);
- sellar el evaluador o regenerar splits.
Los especialistas (producto, vision) ademas no ven el holdout: solo QA lo corre.
BI (bi-specialist) lee la BD unicamente con .claude/skills/consulta-analitica/consulta.py (rol pricescraper_ro,
sesion READ ONLY); no usa la conexion de escritura (DATABASE_URL, psycopg, db_builder, manage.py shell).

Es una heuristica sobre comandos de shell, no un sandbox. El respaldo es evaluador/manifest.json
(cualquier cambio a GT/splits/reglas deja la corrida NO VALIDA) y la revision humana del diff.
"""
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Rutas donde cada rol puede editar con Edit/Write (relativas a la raiz del repo)
EDITABLE = {
    "producto": ("nlp/", "load/load.py", "tests/"),
    # load.py: TIENDAS_ROI_HIBRIDO y la asociacion por ROI. OCR (preprocessor, ocr_engine): se mide en CPU con
    # `python -m evaluador ocr`; los JSON de produccion solo se rehacen en la GPU cuando la persona lo lanza
    "vision": ("vision/region_detector.py", "vision/preprocessor.py", "vision/ocr_engine.py", "load/load.py", "tests/"),
    "qa": (),
    # Dashboard Django y el catalogo de metricas. vistas.sql/schema.sql quedan protegidos: se proponen, no se editan
    "bi": ("dashboard/", "docs/bi/", "tests/"),
}
# Unica puerta a la BD para leer (BI y QA): valida que sea SELECT y usa el rol de solo lectura
CONSULTA_RO = re.compile(r"\.claude[/\\]skills[/\\]consulta-analitica[/\\]consulta\.py\b")
# Dentro de lo editable, igual protegido
# nlp/evaluador_calidad.py (26-oct-2026): el evaluador importa de ahi TOLERANCIA_PRECIO y tokens_significativos, pero no
# esta en el sello y el especialista de producto edita nlp/: sin esto podia cambiar al juez sin invalidar la corrida
PROTEGIDO = ("evaluador/", "data/", ".claude/", "tests/test_evaluador.py", "tests/conftest.py",
             "load/schema.sql", "load/vistas.sql", "nlp/evaluador_calidad.py")
# Fragmentos que, mencionados en un comando de shell que escribe, delatan una ruta protegida
FRAGMENTOS_PROTEGIDOS = ("evaluador/", "evaluador\\", "evaluador_calidad", "_revision_manual", ".claude", "splits.json", "manifest.json",
                         "test_evaluador", "conftest", "schema.sql", "vistas.sql", "data/processed", "data\\processed")
MARCAS_ESCRITURA = re.compile(
    r"(>|\btee\b|\bsed\s+-i|\brm\b|\bmv\b|\bcp\b|\btruncate\b|\bunlink\b|\bmkdir\b|\btouch\b|\bchmod\b"
    r"|\.write|write_text|write_bytes|json\.dump\b|open\([^)]*['\"][wax]|shutil\.|os\.remove|os\.rename|\.unlink\("
    r"|Set-Content|Add-Content|Out-File|Remove-Item|Move-Item|Copy-Item|New-Item)", re.I)

PROHIBIDOS = [
    (r"\bgit\s+(commit|push|reset|checkout|restore|stash|clean|rebase|merge|add|rm|mv|tag|branch\s+-[dD]|switch|cherry-pick|revert|am|apply)\b",
     "Los agentes no cambian el arbol de git ni hacen commits/push: eso lo aprueba la persona."),
    # recargar_bd (26-oct-2026): respalda, reprocesa el NLP, recarga y limpia la BD; lo corre la persona
    (r"\bload[/\\.]load\b|\bload\.py\b|probar_load|db_builder|recargar_bd|\bpsql\b|pg_restore|pg_dump|createdb|dropdb"
     r"|manage\.py\s+(migrate|flush|loaddata|sqlflush|dbshell)",
     "Los agentes no tocan la BD (ni recarga ni consultas directas): usa el evaluador, que construye los registros en memoria."),
    (r"\b(DROP|TRUNCATE|ALTER)\s+(TABLE|VIEW|SCHEMA|DATABASE)\b|\bDELETE\s+FROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\w+\s+SET\b",
     "SQL de escritura prohibido para los agentes."),
    # orquestador (27-oct-2026): descarga, hace OCR/NLP de produccion y carga a la BD; lo corre la persona
    (r"probar_nlp|probar_vision|probar_scraper|catchup_tiendeo|orquestador|scraper[/\\.]",
     "Esos scripts reescriben datos de produccion (JSON de OCR/NLP o descargas). Evalua con: python -m evaluador correr --nlp memoria"),
    (r"\bevaluador\s+(sellar|splits|validacion)\b",
     "Sellar el evaluador, regenerar splits o la validacion humana son decisiones de la persona."),
]
SOLO_QA = [
    (r"--split[\s=]+(holdout|todo)\b",
     "El holdout es solo para QA. Los especialistas miden en dev (el default)."),
]
SOLO_VISION_QA = [
    (r"\bevaluador\s+ocr\b",
     "El OCR experimental es del especialista de vision (o de QA para verificarlo)."),
]
SOLO_BI = [
    (r"psycopg|get_connection|get_cursor|DATABASE_URL(?!_RO)|manage\.py\s+(shell|dbshell)|from\s+dashboard\.models|django\.setup",
     "BI lee la BD solo con .claude/skills/consulta-analitica/consulta.py (rol de solo lectura)."),
    (r"--split[\s=]+(holdout|todo)\b|\bevaluador\s+(correr|ocr)\b",
     "BI lee las corridas guardadas del evaluador (data/processed/_eval/runs); no corre el evaluador."),
]


def _relativa(ruta: str) -> str | None:
    p = Path(ruta)
    if not p.is_absolute():
        p = RAIZ / p
    try:
        return p.resolve().relative_to(RAIZ).as_posix()
    except ValueError:
        return None  # fuera del repo


def revisar_edicion(rol: str, ruta: str) -> str | None:
    rel = _relativa(ruta)
    if rel is None:
        return f"{ruta} esta fuera del repositorio."
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in PROTEGIDO):
        return f"{rel} esta protegido: GT, splits, reglas del evaluador, datos o configuracion de agentes."
    if not any(rel == p or rel.startswith(p) for p in EDITABLE.get(rol, ())):
        permitido = ", ".join(EDITABLE.get(rol, ())) or "nada"
        return f"El rol {rol} solo edita: {permitido}. {rel} queda fuera de su alcance; propon el cambio en tu reporte."
    return None


def revisar_comando(rol: str, comando: str) -> str | None:
    reglas = PROHIBIDOS + ([] if rol == "qa" else SOLO_QA) + ([] if rol in ("vision", "qa") else SOLO_VISION_QA)
    if rol == "bi":
        reglas = reglas + SOLO_BI
    for patron, motivo in reglas:
        if re.search(patron, comando, re.I):
            return motivo
    if CONSULTA_RO.search(comando) and rol not in ("bi", "qa"):
        return "Los especialistas no consultan la BD: miden con el evaluador. La consulta directa es de BI y QA."
    if CONSULTA_RO.search(comando):
        # El SQL puede traer ">" o mencionar tablas: consulta.py valida que sea solo lectura. Se exige que el
        # comando sea solo esa llamada (sin encadenar otra cosa ni redirigir la salida)
        if re.search(r"[;&|`]|\$\(|>\s*[\w./\\]", re.sub(r"\"[^\"]*\"|'[^']*'", "", comando)):
            return "Llama a consulta.py sola: sin encadenar comandos ni redirigir la salida."
        return None
    if any(f.lower() in comando.lower() for f in FRAGMENTOS_PROTEGIDOS) and MARCAS_ESCRITURA.search(comando):
        return "El comando parece escribir sobre una ruta protegida (evaluador, GT, splits, datos o .claude). Para leer usa Read/Grep."
    return None


def revisar(rol: str, evento: dict) -> str | None:
    herramienta = evento.get("tool_name", "")
    entrada = evento.get("tool_input") or {}
    if rol not in EDITABLE:
        return f"Rol desconocido {rol!r} en la guardia."
    if herramienta in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return revisar_edicion(rol, entrada.get("file_path") or entrada.get("notebook_path") or "")
    if herramienta in ("Bash", "PowerShell"):
        return revisar_comando(rol, entrada.get("command", ""))
    return None


def main() -> int:
    rol = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        evento = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("Guardia: evento ilegible, se bloquea por precaucion.", file=sys.stderr)
        return 2
    motivo = revisar(rol, evento)
    if motivo:
        print(f"Bloqueado por la guardia de agentes: {motivo}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
