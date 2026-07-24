# PriceScraper

Sistema de extracción, procesamiento e inteligencia de precios de folletos digitales de supermercados mexicanos.

**Fuentes:** Tiendeo.com.mx · Ofertomat.mx  
**Stack:** Python · Playwright · OpenCV · EasyOCR (+ Tesseract como fallback/investigación) · spaCy (planeado) · PostgreSQL (psycopg v3) · FastAPI (planeado) · PySpark (planeado)

---

## Requisitos previos

- Python 3.10 o superior
- Git

---

## Configuracion en maquina nueva

### 1. Clonar el repositorio

```bash
git clone https://github.com/tu-usuario/PriceScraper_SS.git
cd PriceScraper_SS
```

### 2. Crear y activar entorno virtual

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS:**
```bash
python -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias Python

```bash
pip install -r requirements.txt
```

### 4. Instalar Chromium para Playwright

> Playwright no incluye el navegador en pip — hay que instalarlo por separado.

```bash
playwright install chromium
```

### 5. Descargar modelo de español para spaCy

```bash
python -m spacy download es_core_news_sm
```

### 6. Crear carpetas necesarias

```bash
mkdir -p data/raw data/processed logs
```

### 7. Restaurar datos desde USB

Las siguientes carpetas y archivos NO están en el repositorio (ver `.gitignore`) y deben copiarse manualmente desde USB o disco externo:

| Elemento | Descripcion |
|---|---|
| `data/` | Datalake completo: imagenes descargadas, JSONs procesados. Puede pesar varios GB. |
| `.env` | Variables de entorno: credenciales, rutas, configuracion local. |
| `logs/` | Opcional. Historial de ejecuciones anteriores. Se regenera al correr el pipeline. |

> Los archivos `.docx` de propuesta/documentacion tambien conviene respaldarlos en USB ya que estan ignorados por git.

---

## Ejecucion del pipeline

Cada modulo tiene su propio script de prueba con menu interactivo. Por ahora se corre modulo por modulo; el orquestador final que encadene todas las etapas (`etl.py`) se construira cuando `load/` este terminado.

```bash
# 1. Scraping — descargar folletos de Tiendeo/Ofertomat
python probar_scraper.py

# 2. Vision — preprocesar imagenes y extraer texto (OCR)
python probar_vision.py

# 3. NLP — clasificar bloques de texto en producto/precio/promo
python probar_nlp.py

# 4. Load/ETL — cargar datos estructurados a PostgreSQL (EN CONSTRUCCION)
python probar_load.py
```

Para inspeccionar la base de datos PostgreSQL generada se usa **pgAdmin 4** (conexion manual a la BD `pricescraper`).

---

## 📁 Estructura del proyecto

```
PriceScraper_SS/
├── scraper/
│   ├── metodos_scraper.py   # Clase base BaseScraper (Playwright)
│   ├── downloader.py        # Descarga de imagenes
│   ├── registro.py          # Control de folletos procesados (idempotencia)
│   └── sources/
│       ├── tiendeo.py       # Adaptador Tiendeo.com.mx
│       └── ofertomat.py     # Adaptador Ofertomat.mx
├── vision/
│   ├── preprocessor.py      # Pipeline OpenCV (perfiles color_normal / color_suave)
│   └── ocr_engine.py        # EasyOCR (principal) + Tesseract (fallback/investigacion)
├── nlp/
│   ├── regex_extractor.py   # Extractor de entidades via regex
│   ├── catalogo_productos.py
│   └── normalizador.py      # API planeada para el ETL (aun no integrada, no es codigo muerto)
├── load/                    # ETL — EN CONSTRUCCION (frente de trabajo actual)
│   ├── db_builder.py        # Conexion PostgreSQL (psycopg v3), ejecuta schema.sql
│   ├── load.py               # Carga: asociacion producto-precio por bounding boxes
│   ├── schema.sql
│   └── vistas.sql            # Vistas para BI, aplicadas manualmente via pgAdmin
├── sources/                  # Comparaciones manuales de perfiles OCR (antecedentes de cambios)
│   └── analisis_perfiles_v3/
├── data/                    # <- NO incluido en git (ver .gitignore)
│   ├── raw/                 # Imagenes descargadas
│   └── processed/           # Imagenes procesadas + JSONs OCR/NLP
├── logs/                    # <- NO incluido en git
├── probar_scraper.py
├── probar_vision.py
├── probar_nlp.py
├── probar_load.py
├── requirements.txt
└── Propuesta_PriceScraper_SS.docx   # Documento de servicio social (objetivos, alcance, metricas)
```

---

## Notas

- La primera ejecucion de `probar_vision.py` descarga los modelos de EasyOCR automaticamente (~500 MB). Las siguientes ejecuciones son instantaneas.
- El scraper corre en modo `headless=True` por defecto (sin ventana visible). Cambia a `headless=False` en `probar_scraper.py` para ver el navegador durante el scraping.
- EasyOCR es el motor OCR principal (mejor desempeno en folletos de retail coloridos). Tesseract se conserva en `vision/ocr_engine.py` como motor independiente, para investigacion y documentacion futura — no se usa en produccion.
- En PostgreSQL 15+ es necesario ejecutar manualmente `GRANT ALL ON SCHEMA public` para el usuario de la app (no viene por defecto).
