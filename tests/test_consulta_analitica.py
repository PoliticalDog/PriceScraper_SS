"""Validacion de solo lectura de .claude/skills/consulta-analitica/consulta.py (sin tocar la BD)."""
import importlib.util

import pytest

from conftest import RAIZ

_spec = importlib.util.spec_from_file_location(
    "consulta", RAIZ / ".claude" / "skills" / "consulta-analitica" / "consulta.py")
consulta = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(consulta)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM tiendas",
    "  select count(*) from extracciones where valor > 100;",
    "WITH x AS (SELECT 1 AS a) SELECT a FROM x",
    "EXPLAIN SELECT * FROM v_precios_actuales",
    "SELECT 'delete from tiendas' AS texto",          # la palabra clave va dentro de un literal
    "SELECT 1 -- update tiendas set x = 1",           # o dentro de un comentario
])
def test_acepta_solo_lectura(sql):
    assert consulta.validar(sql) is None, sql


@pytest.mark.parametrize("sql", [
    "", "DELETE FROM tiendas", "UPDATE tiendas SET activa = false",
    "SELECT 1; DROP TABLE tiendas", "INSERT INTO alertas VALUES (1)",
    "WITH d AS (DELETE FROM tiendas RETURNING *) SELECT * FROM d",
    "SELECT * FROM tiendas FOR UPDATE", "CREATE TABLE x (a int)", "SET ROLE postgres",
    "COPY tiendas TO 'C:/x.csv'", "TRUNCATE extracciones", "GRANT ALL ON tiendas TO public",
])
def test_rechaza_escritura(sql):
    assert consulta.validar(sql), sql
