# Léeme: documentación técnica por módulo

Esta carpeta explica cómo está hecho cada módulo de PriceScraper y por qué se decidió así. Es la referencia técnica del repositorio: se actualiza junto con el código. Si vas a retomar el proyecto, empieza por la arquitectura y después lee el módulo que vayas a tocar.

Para instalar y usar el proyecto (no para entenderlo por dentro), ve al manual de usuario en `docs/manual_usuario/`. Las métricas y consultas del dashboard están en `docs/bi/metricas.md`.

| Archivo | Módulo | Estado |
|---|---|---|
| `00_arquitectura.md` | Visión general: pipeline, datalake, módulos y stack | pendiente |
| `01_scraper.md` | Web scraping de Tiendeo y Ofertomat | pendiente |
| `02_vision.md` | Preprocesamiento, OCR y detección de regiones | pendiente |
| [`03_nlp.md`](03_nlp.md) | Clasificación de bloques, reglas de precio, normalizador y catálogo | piloto (26-oct-2026) |
| `04_load.md` | Asociación producto-precio y carga a PostgreSQL | pendiente |
| `05_base_de_datos.md` | Esquema, vistas, cadenas y respaldos | pendiente |
| `06_evaluador.md` | Ground truth, splits, métricas y cómo medir un cambio | pendiente |
| `07_dashboard.md` | Django, páginas, APIs y métricas de BI | pendiente |
| `08_flujo_con_agentes.md` | Skills, especialistas, QA, guardia y Engram | pendiente |

Estos archivos los genera y mantiene la skill `documentar-proyecto` (`.claude/skills/documentar-proyecto/`). De ellos salen también los borradores en Word por capítulo para la documentación técnica del servicio social.
