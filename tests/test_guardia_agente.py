"""Pruebas de la guardia de los subagentes (.claude/hooks/guardia_agente.py)."""
import importlib.util
import json
import subprocess
import sys

import pytest

from conftest import RAIZ

RUTA = RAIZ / ".claude" / "hooks" / "guardia_agente.py"
_spec = importlib.util.spec_from_file_location("guardia_agente", RUTA)
guardia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guardia)


def edita(rol, ruta):
    return guardia.revisar(rol, {"tool_name": "Edit", "tool_input": {"file_path": ruta}})


def corre(rol, comando):
    return guardia.revisar(rol, {"tool_name": "Bash", "tool_input": {"command": comando}})


@pytest.mark.parametrize("ruta", ["evaluador/comparar.py", "evaluador/manifest.json", "evaluador/splits.json",
                                  "data/raw/_revision_manual/tiendeo/x.json", ".claude/hooks/guardia_agente.py",
                                  ".claude/agents/especialista-producto.md", "tests/test_evaluador.py",
                                  "load/schema.sql", str(RAIZ / "evaluador" / "metricas.py")])
def test_rutas_protegidas_para_todos(ruta):
    for rol in ("producto", "vision", "qa", "bi"):
        assert edita(rol, ruta)


def test_alcance_por_rol():
    assert edita("producto", "nlp/normalizador.py") is None
    assert edita("producto", "load/load.py") is None
    assert edita("producto", str(RAIZ / "nlp" / "regex_extractor.py")) is None
    assert edita("producto", "vision/region_detector.py")
    assert edita("vision", "vision/region_detector.py") is None
    assert edita("vision", "load/load.py") is None
    assert edita("vision", "vision/preprocessor.py") is None
    assert edita("vision", "vision/ocr_engine.py") is None
    assert edita("producto", "vision/ocr_engine.py")
    assert edita("vision", "nlp/normalizador.py")
    assert edita("qa", "nlp/normalizador.py")
    assert edita("producto", "tests/test_normalizador.py") is None


def test_fuera_del_repo():
    assert edita("producto", "C:/Windows/x.py")


@pytest.mark.parametrize("comando", [
    "git commit -m x", "git push origin main", "git checkout -- nlp/normalizador.py", "git add -A",
    "venv/Scripts/python.exe load/load.py", "python -m load.load", "psql -d pricescraper -c 'select 1'",
    "python probar_nlp.py", "python -m evaluador sellar --motivo x", "python -m evaluador splits --generar",
    "echo x > evaluador/comparar.py", "sed -i s/a/b/ evaluador/metricas.py", "rm data/processed/_eval/runs/a.json",
    "python -c \"open('evaluador/splits.json','w')\"", "cp otro.json .claude/settings.json",
])
def test_comandos_prohibidos_para_todos(comando):
    for rol in ("producto", "vision", "qa", "bi"):
        assert corre(rol, comando), comando


def test_holdout_solo_qa():
    assert corre("producto", "python -m evaluador correr --split holdout")
    assert corre("vision", "python -m evaluador correr --split=todo")
    assert corre("qa", "python -m evaluador correr --split holdout") is None


@pytest.mark.parametrize("comando", [
    "venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria",
    "venv/Scripts/python.exe -m evaluador comparar data/processed/_eval/runs/a.json data/processed/_eval/runs/b.json",
    "venv/Scripts/python.exe -m evaluador verificar", "git diff", "git status --short", "git log --oneline -5",
    "venv/Scripts/python.exe -m pytest tests -q",
    "python -c \"import json; print(json.load(open('data/processed/_eval/runs/a.json'))['metricas'])\"",
])
def test_comandos_permitidos(comando):
    assert corre("producto", comando) is None, comando


def test_proceso_bloquea_con_codigo_2():
    evento = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}})
    r = subprocess.run([sys.executable, str(RUTA), "producto"], input=evento, capture_output=True, text=True)
    assert r.returncode == 2 and "git" in r.stderr
    ok = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "evaluador/comparar.py"}})
    assert subprocess.run([sys.executable, str(RUTA), "producto"], input=ok, capture_output=True, text=True).returncode == 0


def test_evento_ilegible_bloquea():
    r = subprocess.run([sys.executable, str(RUTA), "producto"], input="no json", capture_output=True, text=True)
    assert r.returncode == 2


CONSULTA = "venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py"


def test_alcance_bi():
    assert edita("bi", "dashboard/queries.py") is None
    assert edita("bi", "dashboard/templates/dashboard/resumen.html") is None
    assert edita("bi", "docs/bi/metricas.md") is None
    assert edita("bi", "tests/test_dashboard_kpis.py") is None
    for ruta in ("load/vistas.sql", "load/schema.sql", "load/load.py", "nlp/normalizador.py", "vision/ocr_engine.py",
                 ".claude/skills/consulta-analitica/consulta.py"):
        assert edita("bi", ruta), ruta
    assert edita("producto", "dashboard/queries.py")


@pytest.mark.parametrize("comando", [
    CONSULTA + ' --sql "SELECT tienda, count(*) FROM v_precios_actuales WHERE precio_actual > 100 GROUP BY 1"',
    CONSULTA + " --archivo docs/bi/consultas/cobertura.sql --max 50",
    CONSULTA + " --columnas extracciones",
    "venv/Scripts/python.exe -m pytest tests -q",
    "python -c \"import json; print(json.load(open('data/processed/_eval/runs/a.json'))['metricas'])\"",
])
def test_bi_permitidos(comando):
    assert corre("bi", comando) is None, comando


@pytest.mark.parametrize("comando", [
    "python -c \"import psycopg; psycopg.connect('postgresql://x')\"",
    "python -c \"from load.db_builder import get_connection\"",
    "python manage.py shell -c \"from dashboard.models import Tienda\"",
    "python manage.py dbshell",
    "python -m evaluador correr --split dev",
    CONSULTA + ' --sql "SELECT 1" ; rm -rf docs',
    CONSULTA + ' --sql "SELECT 1" > data/processed/x.txt',
    CONSULTA + ' --sql "DELETE FROM tiendas"',
])
def test_bi_prohibidos(comando):
    assert corre("bi", comando), comando


def test_consulta_ro_tambien_para_qa_no_para_especialistas():
    cmd = CONSULTA + ' --sql "SELECT count(*) FROM extracciones WHERE valor > 100"'
    assert corre("qa", cmd) is None
    assert corre("producto", cmd)
    assert corre("vision", CONSULTA + ' --sql "SELECT 1"')


def test_ocr_experimental_solo_vision_y_qa():
    cmd = "venv/Scripts/python.exe -m evaluador ocr --nombre base_heb --tienda heb"
    assert corre("vision", cmd) is None and corre("qa", cmd) is None
    assert corre("producto", cmd)
    assert corre("vision", "venv/Scripts/python.exe -m evaluador correr --ocr-exp base_heb --tienda heb") is None
    assert corre("vision", "python probar_vision.py")


# -- 26-oct-2026: recargar_bd.py y el modulo de tolerancias del juez ------------------------------------------------

@pytest.mark.parametrize("rol", ["producto", "vision", "qa", "bi"])
def test_recargar_bd_prohibido(rol):
    for comando in ("venv/Scripts/python.exe recargar_bd.py todo --si", "python recargar_bd.py limpiar",
                    'python -c "import recargar_bd; recargar_bd.load()"'):
        assert corre(rol, comando)


@pytest.mark.parametrize("rol", ["producto", "vision", "qa", "bi"])
def test_evaluador_calidad_protegido(rol):
    assert edita(rol, "nlp/evaluador_calidad.py")
    assert corre(rol, "sed -i 's/0.01/0.5/' nlp/evaluador_calidad.py")


def test_producto_sigue_editando_el_resto_de_nlp():
    assert edita("producto", "nlp/regex_extractor.py") is None
    assert corre("producto", 'venv/Scripts/python.exe -c "from nlp.evaluador_calidad import TOLERANCIA_PRECIO"') is None
