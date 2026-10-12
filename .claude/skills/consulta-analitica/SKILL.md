---
name: consulta-analitica
description: Protocolo para consultar PostgreSQL en solo lectura, construir y validar KPIs de PriceScraper (sin duplicados por joins, con fuente, formula y confiabilidad documentadas) y reportar inconsistencias de datos al orquestador. Usar al analizar datos, definir o revisar una metrica o un panel del dashboard, o al verificar un KPI.
---

# Consulta analitica y validacion de KPIs

## Herramienta (unica puerta a la BD)

```
venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --columnas <tabla_o_vista>
venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --sql "SELECT ..." [--max N] [--json]
venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --archivo docs/bi/consultas/<x>.sql
venv/Scripts/python.exe .claude/skills/consulta-analitica/consulta.py --sql "SELECT ..." --contar
```

Usa el rol `pricescraper_ro` (DATABASE_URL_RO, solo SELECT), abre la sesion READ ONLY, corta a los 60 s
y rechaza todo lo que no sea una sola sentencia SELECT / WITH / EXPLAIN. Llamalo solo: sin `;`, `|`, `&&` ni `>`.
Las consultas largas van en archivos `docs/bi/consultas/*.sql` para que queden versionadas junto a la metrica.

## Modelo de datos (verificalo con --columnas antes de usarlo; no asumas)

- `extracciones` es el hecho central: una fila por bloque clasificado (`tipo` PRODUCTO, PRECIO, PRECIO_ANTERIOR, AHORRO,
  PROMO, EVENTO_PROMO, ATRIBUTO). Un PRECIO apunta a su fila PRODUCTO (`producto_extraccion_id`) y a
  `productos_canonicos` (`producto_canonico_id`). Lo que ve el dashboard es `tipo='PRECIO' AND valor IS NOT NULL
  AND texto_norm IS NOT NULL` (= `v_precios_actuales`).
- Dimensiones: `tiendas`, `folletos` (fechas de vigencia `fecha_inicio`/`fecha_fin`, fuente), `paginas` (metricas OCR/NLP).
- `metodo_norm` vive en la fila PRODUCTO: `exacto | fuzzy | fuzzy_bajo` = producto del catalogo; `heuristico` = texto del
  folleto tal cual (no es una identidad confiable para agrupar entre tiendas).
- Calidad medida del pipeline: corridas del evaluador en `data/processed/_eval/runs/*.json` (precision/recall por tienda,
  errores por tipo). Usa la corrida dev mas reciente con `meta.codigo.cambios_sin_commit = false`. No corras el evaluador.

## Protocolo para cada KPI (en orden)

1. **Pregunta de negocio** en una frase y el grano (por tienda, por folleto, por semana, por producto de catalogo...).
2. **Columnas verificadas** con `--columnas` para cada tabla o vista que uses.
3. **Joins sin duplicar:** cuenta filas de la tabla base, luego de cada join (`--contar`). Si el conteo crece y no debia,
   la relacion no es 1:1: agrega antes de unir o usa `EXISTS`. Nunca `COUNT(*)` sobre un join sin justificar el grano.
4. **Limpieza explicita:** declara que excluyes y cuanto pesa (precios atipicos < $1 o > $100,000, duplicados exactos
   mismo folleto+pagina+texto+valor, folletos con fechas anomalas, categoria vacia: `''` en `categoria_nlp` y NULL en el
   canonico significan lo mismo). Prefiere mediana a promedio y a min/max cuando haya ruido OCR.
5. **Confiabilidad:** acompana cada KPI de producto o precio con su confiabilidad: % de registros con producto de catalogo
   y la precision de la tienda segun el evaluador. Si la base es mayormente heuristica, dilo en el panel.
6. **Validacion independiente:** reproduce la cifra con una segunda consulta escrita de otra forma (otro camino de joins o
   desde la tabla base en lugar de la vista). Si no cuadra, no se publica.
7. **Documenta** en `docs/bi/metricas.md`: nombre, pregunta, formula, fuente (tablas/vistas/archivo), filtros y
   exclusiones, grano, confiabilidad, consulta (ruta del .sql), consulta de validacion, fecha y autor.

## Inconsistencias: se reportan, no se arreglan

Si encuentras datos incoherentes (duplicados, valores imposibles, relaciones rotas, categorias o eventos basura,
cifras que no cuadran entre paneles, una vista que mide otra cosa de lo que dice), no los corrijas en la BD ni en el
pipeline: reportalos en la seccion **Hallazgos para el orquestador** de tu entrega:

```
- Hallazgo: <que pasa, en una frase>
  Evidencia: <consulta o ruta .sql> -> <cifra>
  Impacto: <que panel o KPI se distorsiona y cuanto>
  Origen probable: dato del pipeline (OCR/NLP/load) | vista o consulta | catalogo | GT | otro
  Para: especialista-producto | especialista-vision | qa-evaluador | persona
  Prioridad: alta | media | baja
```

y guardalo en Engram (`mem_save`, type `discovery`, topic_key `bi/hallazgos/<slug>`). El orquestador decide a quien
se lo pasa; tu no invocas a otros agentes.
