# Léeme: documentación técnica por módulo

Esta carpeta explica cómo está hecho cada módulo de PriceScraper y por qué se decidió así. Es la referencia técnica del repositorio: se actualiza junto con el código. Si vas a retomar el proyecto, empieza por la arquitectura y después lee el módulo que vayas a tocar.

| Archivo | Módulo |
|---|---|
| [`00_arquitectura.md`](00_arquitectura.md) | Visión general: pipeline, datalake, módulos, stack y cómo se trabaja en el repo |
| [`01_scraper.md`](01_scraper.md) | Web scraping de Tiendeo y Ofertomat |
| [`02_vision.md`](02_vision.md) | Preprocesamiento, OCR y detección de regiones |
| [`03_nlp.md`](03_nlp.md) | Clasificación de bloques, reglas de precio, normalizador y catálogo |
| [`04_base_de_datos.md`](04_base_de_datos.md) | Esquema, vistas, cadenas y respaldos |
| [`05_load.md`](05_load.md) | Asociación producto-precio y carga a PostgreSQL |
| [`07_dashboard.md`](07_dashboard.md) | Django, páginas, APIs y métricas de BI |

El evaluador de calidad (`06`) y el flujo de trabajo con agentes de Claude (`08`) se documentarán después.

Estos archivos los genera y mantiene la skill `documentar-proyecto` (`.claude/skills/documentar-proyecto/`).
