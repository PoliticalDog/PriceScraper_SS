# Arquitectura del sistema

PriceScraper convierte folletos digitales de supermercados mexicanos (imágenes) en precios estructurados y consultables. El sistema es un pipeline local de cinco etapas: descargar los folletos, leer su texto, clasificarlo, cargarlo a una base de datos y mostrarlo en un dashboard. Este capítulo da la vista de conjunto; cada etapa tiene su propio documento en esta carpeta.

## El pipeline

Cada etapa lee lo que dejó la anterior en disco y escribe su propio resultado, así que se puede volver a correr una etapa sin repetir las demás (por ejemplo, reprocesar el NLP sin volver a hacer OCR).

```
 Tiendeo / Ofertomat (web)
        │  scraper/         Playwright + captura de las imágenes del visor
        ▼
 data/raw/<fuente>/<tienda>/<folleto>/pagina_NNN.webp
        │  vision/          OpenCV (preprocesamiento por tienda) + EasyOCR
        ▼
 data/processed/<fuente>/<tienda>/<folleto>/ocr_resultado.json
        │  nlp/             reglas + geometría + catálogo: clasifica cada bloque de texto
        ▼
 data/processed/<fuente>/<tienda>/<folleto>/nlp_resultado.json
        │  load/            asocia producto con precio, normaliza nombres, inserta en PostgreSQL
        ▼
 PostgreSQL (tablas + vistas de load/schema.sql y load/vistas.sql)
        │  dashboard/       Django: páginas y APIs de consulta
        ▼
 http://127.0.0.1:8000
```

En paralelo, el **evaluador** (`evaluador/`) mide la calidad del pipeline contra un conjunto etiquetado a mano (ground truth): es el juez que decide si un cambio en vision, NLP o load mejora o empeora los datos.

## Módulos

| Módulo | Carpeta | Entrada | Salida | Documento |
|---|---|---|---|---|
| Scraper | `scraper/` | Sitios de Tiendeo y Ofertomat | Imágenes de cada página y registros JSON | `01_scraper.md` |
| Visión | `vision/` | `data/raw/.../pagina_NNN.webp` | `ocr_resultado.json` (bloques con texto, confianza y caja) | `02_vision.md` |
| NLP | `nlp/` | `ocr_resultado.json` | `nlp_resultado.json` (bloques clasificados: precio, producto, promoción...) | `03_nlp.md` |
| Base de datos | `load/schema.sql`, `load/vistas.sql` | — | Tablas y vistas | `04_base_de_datos.md` |
| Carga (ETL) | `load/` | `nlp_resultado.json` + `ocr_resultado.json` | Filas en PostgreSQL | `05_load.md` |
| Evaluador | `evaluador/` | Ground truth + el pipeline en memoria | Precisión, recall y F1 por tienda | `06_evaluador.md` |
| Dashboard | `dashboard/`, `priceScraper_web/` | Vistas de PostgreSQL | Páginas web y APIs JSON | `07_dashboard.md` |

Tabla: Módulos del sistema

Cada módulo tiene un script orquestador en la raíz con menú interactivo: `probar_scraper.py`, `probar_vision.py`, `probar_nlp.py`, `probar_load.py` y `probar_dashboard.py`. `catchup_tiendeo.py` corre OCR y NLP de lo que falte en una sola pasada.

Desde el 27-oct-2026, `orquestador.py` corre el pipeline completo sin menú: scraper → OCR → NLP → carga, cada etapa solo sobre lo nuevo. Reutiliza las funciones de los scripts anteriores (`scrapear_tiendeo_todas_tiendas`, `catchup_vision`, `catchup_nlp`, `Loader.cargar_batch(forzar=False)` y `recargar_bd.verificar`). Si una etapa truena o tiene errores, las siguientes siguen con lo que ya está en disco y el resumen lo reporta (decisión de la persona); sale con código 1 para que la tarea programada (`orquestador_semanal.bat`) lo note. `--respaldo` hace un `pg_dump` antes de cargar. No sustituye a `recargar_bd.py`: no reprocesa ni recarga lo que ya estaba.

**Ofertomat está deshabilitado** desde el 26-oct-2026 por lo complejo de su scrapeo (última descarga: 4-ago-2026). El adaptador `scraper/sources/ofertomat.py` se conserva para arreglarlo en el futuro. El orquestador solo scrapea Tiendeo; el OCR, el NLP y la carga recorren las dos fuentes porque los 39 folletos de Ofertomat ya descargados siguen en `data/` y en la BD.

## El datalake local

Todo el material intermedio vive en `data/`, que no está en git porque pesa varios GB:

| Ruta | Contenido |
|---|---|
| `data/raw/<fuente>/<tienda>/<folleto>/` | Páginas descargadas (`pagina_001.webp`, ...). Al 26-oct-2026: 16 tiendas de tiendeo y 4 de ofertomat |
| `data/processed/<fuente>/<tienda>/<folleto>/` | `ocr_resultado.json`, `nlp_resultado.json` y las páginas preprocesadas |
| `data/processed/_eval/runs/` | Corridas guardadas del evaluador (una por medición) |
| `data/processed/_v*/`, `_benchmark_*` | Resultados de experimentos de visión (historial) |
| `data/registro_folletos_scrapeados.json` | Registro acumulado de lo ya descargado (evita descargas repetidas) |
| `data/backups_bd/` | Respaldos antiguos de la base de datos |

Tabla: Organización del datalake (data/)

Los respaldos recientes de la BD (`respaldo_antes_reproceso_nlp_*.dump`) se guardan fuera del repositorio, en la carpeta padre, y nunca se suben a git.

## Stack tecnológico real

Versiones según `requirements.txt` (archivo en UTF-16) y el entorno `venv/` al 26-oct-2026. Python 3.12.2.

| Componente | Tecnología | Uso real |
|---|---|---|
| Scraping | Playwright 1.58.0, aiohttp 3.13.3, BeautifulSoup4 4.14.3 | Navegador Chromium para los visores con JavaScript; descarga concurrente de imágenes |
| Imagen | OpenCV 4.13, scikit-image 0.26, Pillow 12.1 | Preprocesamiento y detección de regiones |
| OCR | EasyOCR 1.7.2 (con PyTorch 2.10), pytesseract 0.3.13 | EasyOCR es el único motor del pipeline; Tesseract solo se elige a mano en el menú de `probar_vision.py` (el respaldo automático propuesto se descartó con mediciones, ver `02_vision.md`) |
| NLP | `re` (regex) + RapidFuzz 3.14.5 | Clasificación por reglas con geometría; coincidencia aproximada contra el catálogo |
| Base de datos | PostgreSQL + psycopg 3.3.4 | `load/db_builder.py` usa psycopg 3; Django usa su backend de PostgreSQL |
| Web | Django 6.0.3 | Dashboard; Bootstrap, Chart.js y DataTables en el navegador |
| Pruebas | pytest 9.0.2 | 1,349 pruebas al 26-oct-2026, sin tocar la base de datos |
| Configuración | python-dotenv 1.2.2 | `DATABASE_URL` en `.env` |

Tabla: Stack tecnológico en uso

Comparado con el stack propuesto al inicio del servicio social:

- **spaCy** (3.8.11) está instalado, pero no se usa en el pipeline: el experimento de reconocimiento de entidades se documentó y se descartó a favor de reglas con geometría, que son más controlables y medibles (ver `03_nlp.md`).
- **FastAPI, Django REST Framework, APScheduler y PySpark** no se usan; el dashboard sirve sus datos con vistas JSON de Django y el pipeline se corre a mano.
- **Pandas** solo se usa en scripts de análisis (`probar_evaluar_nlp.py`), no en el pipeline.
- El código usa **psycopg 3** (`import psycopg`). `requirements.txt` lo lista desde el 26-oct-2026 (`psycopg` y `psycopg-binary` 3.3.4); antes solo traía `psycopg2-binary` y una instalación desde cero fallaba al conectar.

## Configuración y ejecución

- **Base de datos:** la conexión sale de `DATABASE_URL` en `.env` (formato `postgresql://usuario:clave@localhost:5432/pricescraper`). `load/db_builder.py` la usa para el pipeline y `priceScraper_web/settings.py` para Django (idioma `es-mx`, zona horaria `America/Mazatlan`).
- **GPU:** el OCR corre en CPU por defecto. Los reprocesos masivos se hicieron en otra máquina con GPU; la skill `preparar-traspaso-gpu` arma ese paquete.
- **Recarga de datos:** cuando cambia el NLP o la carga, se respalda la BD, se reprocesa el NLP de todos los folletos y se recarga con `Loader().cargar_batch(forzar=True)`. El procedimiento completo está en `05_load.md`.

## Volumen de datos

Al 26-oct-2026, después de la última recarga: 821 folletos de 20 tiendas, 223,188 extracciones (bloques clasificados), 28,420 precios y 28,172 registros visibles en el dashboard (precios con producto asociado).

## Cómo se trabaja en el repositorio

El desarrollo de octubre de 2026 se hizo con Claude Code y un equipo de agentes definidos en `.claude/`:

| Pieza | Para qué |
|---|---|
| `especialista-producto`, `especialista-vision` | Proponen y miden una mejora a la vez (NLP/carga o visión/OCR) |
| `qa-evaluador` | Verifica cada cambio de forma independiente y aprueba o rechaza |
| `bi-specialist` | Analiza los datos de la BD y diseña métricas del dashboard (solo lectura) |
| Skills (`ciclo-experimento`, `regex-precio-checklist`, `consulta-analitica`, `documentar-proyecto`...) | Procedimientos fijos que siguen los agentes |
| `.claude/hooks/guardia_agente.py` | Impide que los agentes toquen el ground truth, la BD o el esquema |

Tabla: Agentes y herramientas del repositorio (.claude/)

Ningún cambio al pipeline entra sin medirse con el evaluador y pasar por QA; el commit, la recarga de la BD y el push los decide la persona responsable. Las decisiones y experimentos quedaron registrados en Engram (memoria persistente del proyecto, proyecto `pricescraper_ss`) y en los mensajes de commit.
