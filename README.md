# PriceScraper

Sistema de extracción, procesamiento e inteligencia de precios de folletos digitales de supermercados mexicanos (proyecto de servicio social). Descarga los folletos de Tiendeo y Ofertomat, lee su texto con OCR, clasifica precios y productos, los carga a PostgreSQL y los muestra en un dashboard web.

```
Tiendeo / Ofertomat → scraper/ → data/raw → vision/ (OCR) → nlp/ → load/ → PostgreSQL → dashboard/
```

**Stack en uso:** Python 3.12 · Playwright · OpenCV · EasyOCR · reglas regex con geometría + RapidFuzz · PostgreSQL 18 (psycopg 3) · Django 6 · pytest.

**Documentación técnica:** [`md_modulos_leeme/`](md_modulos_leeme/README.md), un archivo por módulo (arquitectura, scraper, visión, NLP, base de datos, carga, evaluador, dashboard y desarrollo con agentes). Empieza por `00_arquitectura.md`.

## Instalación rápida (Windows)

Requisitos: Python 3.12 (con el lanzador `py`), Git y PostgreSQL 18. Es la única combinación probada.

```
py -3.12 -m venv venv
venv/Scripts/python.exe -m pip install -r requirements.txt
venv/Scripts/python.exe -m playwright install chromium
```

`requirements.txt` está en UTF-16; pip lo lee bien. Trae paquetes que el pipeline ya no usa (spaCy, FastAPI, Django REST Framework, APScheduler, PySpark): se instalan pero no hay que configurarlos.

Base de datos, como superusuario de PostgreSQL:

```sql
CREATE USER pricescraper_user WITH PASSWORD '<clave>';
CREATE DATABASE pricescraper OWNER pricescraper_user;
\c pricescraper
GRANT ALL ON SCHEMA public TO pricescraper_user;
```

Archivo `.env` en la raíz (no se sube a git):

```
DATABASE_URL=postgresql://usuario:clave@localhost:5432/pricescraper
```

Si la clave lleva símbolos, escríbelos codificados en la URL (`@` → `%40`).

Después:

1. La primera conexión crea las tablas desde `load/schema.sql` (por ejemplo, `venv/Scripts/python.exe probar_load.py`, opción 4).
2. Aplica `load/vistas.sql` a mano (pgAdmin o `psql -f load/vistas.sql`): `db_builder.py` no crea las vistas y el dashboard las necesita.
3. `venv/Scripts/python.exe manage.py migrate` crea las tablas internas de Django.
4. Verifica con `venv/Scripts/python.exe -m pytest tests -q` (no necesita la base de datos).

La carpeta `data/` (imágenes y JSON del pipeline, varios GB), el `.env`, `docs/`, `sources/` y los respaldos de la BD son locales: no están en git y se copian aparte.

## Uso

| Paso | Comando |
|---|---|
| Descargar folletos | `venv/Scripts/python.exe probar_scraper.py` |
| OCR + NLP de lo pendiente | `venv/Scripts/python.exe catchup_tiendeo.py` (`--gpu` si hay CUDA) |
| Cargar a la BD lo nuevo | `venv/Scripts/python.exe probar_load.py` |
| Recarga completa con respaldo (tras cambiar `nlp/` o `load/`) | `venv/Scripts/python.exe recargar_bd.py todo` |
| Dashboard | `venv/Scripts/python.exe manage.py runserver` → `http://127.0.0.1:8000` |
| Medir la calidad del pipeline | `venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria` |

Tabla: Comandos principales

Cada script de la raíz (`probar_*.py`) tiene un menú interactivo con modo prueba (un folleto) y modo batch. El detalle de cada etapa, sus archivos de entrada y salida, y por qué funciona así está en `md_modulos_leeme/`.

## Estructura

```
PriceScraper_SS/
├── scraper/            Playwright: adaptadores de Tiendeo y Ofertomat, descarga y registro
├── vision/             preprocesamiento por tienda, OCR (EasyOCR) y detección de regiones
├── nlp/                clasificación de bloques, reglas de precio, catálogo y normalizador
├── load/               asociación producto-precio, carga a PostgreSQL, schema.sql y vistas.sql
├── evaluador/          juez de calidad contra el ground truth (dev y holdout)
├── dashboard/          app Django: páginas, APIs y consultas
├── priceScraper_web/   proyecto Django (settings, urls)
├── tests/              pruebas (pytest); tests/_herramienta_*.py son scripts de medición
├── md_modulos_leeme/   documentación técnica por módulo
├── .claude/            agentes, skills y guardia para trabajar con Claude Code
├── recargar_bd.py      recarga completa con respaldo y verificación
└── data/, logs/        locales (fuera de git)
```

## Desarrollo

Los cambios al pipeline se miden con el evaluador antes y después, y se aceptan solo si mejoran precisión y recall sin regresiones por tienda (`md_modulos_leeme/06_evaluador.md`). En octubre de 2026 el desarrollo se hizo con Claude Code y agentes especializados con revisión de QA; cómo trabajar así está en `md_modulos_leeme/08_flujo_con_agentes.md`.
