# De donde sale cada dato

Orden de confianza: **codigo > pruebas > `docs/` > Engram > `sources/` > `Propuesta_PriceScraper_SS.docx`**. Lo de abajo en la lista describe con frecuencia versiones anteriores; usalo para el historial y verificalo antes de afirmar algo como actual.

## Por modulo

| Modulo | Codigo | Pruebas | Documentacion e historial |
|---|---|---|---|
| Scraper | `scraper/metodos_scraper.py` (BaseScraper), `scraper/sources/` (adaptadores), `scraper/downloader.py`, `scraper/registro.py`, `probar_scraper.py`, `catchup_tiendeo.py` | `tests/test_*scraper*`, `tests/test_*registro*` (confirma con Glob) | Propuesta, capitulo 4 (modulo web scraping) |
| Vision | `vision/preprocessor.py`, `vision/ocr_engine.py`, `vision/region_detector.py`, `probar_vision.py` | `tests/test_*vision*`, `tests/test_*region*`, `tests/test_*ocr*` | `sources/vision/*` (benchmarks 00-10, `configuracion_ocr_por_tienda.md`), propuesta (modulo vision), Engram `experimentos/vision/*` |
| NLP | `nlp/regex_extractor.py` (clasificacion y reglas de precio), `nlp/normalizador.py`, `nlp/catalogo_productos.py`, `nlp/salida_json.py` (contrato de `nlp_resultado.json`), `probar_nlp.py` | `tests/test_regex_*`, `tests/test_normalizador*`, `tests/test_catalogo*` | `sources/nlp/*`, skill `regex-precio-checklist`, Engram `experimentos/producto/*` y `experimentos/qa/*` |
| Load | `load/load.py` (construir_registros_pagina, nombre_en_pila, metodo_nombre, Loader), `load/db_builder.py`, `probar_load.py` | `tests/test_load_*` | Engram `proyecto/reproceso-nlp-recarga-*` |
| Base de datos | `load/schema.sql`, `load/vistas.sql`, `load/diagrama_ER_V3.svg` | — | `sources/modelado_bd/*` (v1 es historico), `docs/bi/metricas.md` |
| Evaluador | `evaluador/` (`__main__.py`, `comparar.py`, `metricas.py`, `gt.py`, `splits.py`, `integridad.py`) | `tests/test_evaluador.py` | skill `ciclo-experimento`, `evaluador/manifest.json`, `sources/vision/ground_truth_resumen.md` |
| Dashboard | `dashboard/` (`views.py`, `queries.py`, `urls.py`, `models.py`, `templates/dashboard/`), `priceScraper_web/settings.py`, `probar_dashboard.py` | `tests/test_dashboard_*` | `docs/bi/metricas.md` (fuente principal de los KPIs), `docs/bi/consultas/`, `sources/dashboard/*` |
| Agentes | `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`, `.claude/hooks/guardia_agente.py`, `.claude/settings.json` | — | Engram (proyecto `pricescraper_ss`) |

## Engram

Busca con `mem_search` en el proyecto `pricescraper_ss` usando el nombre de la regla, la funcion o el modulo, y abre la observacion completa con `mem_get_observation`. Las observaciones de experimentos traen hipotesis, cifras de dev y produccion, ejemplos y lo que se descarto: es la mejor fuente para las secciones "Reglas y decisiones" e "Historial". Cita la observacion por numero (#255).

## Git

`git log --oneline -- <ruta>` da la historia de un archivo; los mensajes de commit del proyecto explican el porque y traen las cifras de dev. Cita el commit por su hash corto.

## Cifras actuales

Para conteos de la BD usa la consulta de solo lectura o el script de verificacion de recargas; para calidad, la corrida dev mas reciente en `data/processed/_eval/runs/`. Pon siempre la fecha.
