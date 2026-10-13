"""Los umbrales de fecha del panel de cobertura (dashboard/queries.py) deben coincidir con v_folletos_vigencia.

queries.py solo replica los umbrales para mostrarlos en el panel; la regla vive en load/vistas.sql. Se leen ambos
archivos como texto (importar queries.py exige Django configurado).
"""
import re

from conftest import RAIZ


def _constante(nombre: str) -> int:
    texto = (RAIZ / "dashboard" / "queries.py").read_text(encoding="utf-8")
    return int(re.search(rf"^{nombre}\s*=\s*(\d+)", texto, re.M).group(1))


def _vista() -> str:
    texto = (RAIZ / "load" / "vistas.sql").read_text(encoding="utf-8")
    return re.search(r"CREATE OR REPLACE VIEW v_folletos_vigencia AS(.*?);", texto, re.S).group(1)


def test_umbrales_de_fecha_iguales_a_la_vista():
    vista = _vista()
    antiguo = re.search(r"fecha_inicio < f\.scrapeado_at::date - (\d+)", vista)
    futuro = re.search(r"fecha_inicio > f\.scrapeado_at::date \+ (\d+)", vista)
    larga = re.search(r"fecha_fin - f\.fecha_inicio > (\d+)", vista)
    assert antiguo and futuro and larga, "cambio la forma de las reglas en la vista: actualiza esta prueba"
    assert int(antiguo.group(1)) == _constante("DIAS_INICIO_ANTIGUO")
    assert int(futuro.group(1)) == _constante("DIAS_INICIO_FUTURO")
    assert int(larga.group(1)) == _constante("DIAS_VIGENCIA_LARGA")
