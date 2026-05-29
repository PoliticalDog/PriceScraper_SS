# PriceScraper

Sistema de extracción, procesamiento e inteligencia de precios de folletos digitales de supermercados mexicanos.

**Fuentes:** Tiendeo.com.mx · Ofertomat.mx  
**Stack:** Python · Playwright · OpenCV · EasyOCR · spaCy · SQLite · PostgreSQL · Django · PySpark

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

Cada modulo tiene su propio script de prueba con menu interactivo:

```bash
# 1. Scraping — descargar folletos de Tiendeo
python probar_scraper.py

# 2. Vision — preprocesar imagenes y extraer texto (OCR)
python probar_vision.py

# 3. NLP — clasificar bloques de texto en producto/precio/promo
python probar_nlp.py

# 4. ETL — transformar y cargar datos estructurados
python probar_etl.py
```

Para inspeccionar la base de datos SQLite generada:

```bash
python view_sqllite.py
```

---

## 📁 Estructura del proyecto

```
PriceScraper_SS/
├── scraper/
│   ├── metodos_scraper.py   # Clase base Playwright
│   ├── downloader.py        # Descarga de imagenes
│   ├── registro.py          # Control de folletos procesados
│   └── sources/
│       ├── tiendeo.py       # Adaptador Tiendeo.com.mx
│       └── ofertomat.py     # Adaptador Ofertomat.mx
├── vision/
│   ├── preprocessor.py      # Pipeline OpenCV
│   └── ocr_engine.py        # EasyOCR + Tesseract
├── nlp/
│   └── regex_extractor.py   # Extractor de entidades
├── etl/
│   └── ...                  # Transformacion y carga de datos estructurados
├── api/                     # Endpoints del sistema
├── data/                    # <- NO incluido en git (ver .gitignore)
│   ├── raw/                 # Imagenes descargadas
│   └── processed/           # Imagenes procesadas + JSONs OCR/NLP
├── logs/                    # <- NO incluido en git
├── probar_scraper.py
├── probar_vision.py
├── probar_nlp.py
├── probar_etl.py
├── view_sqllite.py          # Visor de base de datos SQLite
├── requirements.txt
└── NOTAS_PROYECTO.md        # Contexto del proyecto para retomar desarrollo
```

---

## Notas

- La primera ejecucion de `probar_vision.py` descarga los modelos de EasyOCR automaticamente (~500 MB). Las siguientes ejecuciones son instantaneas.
- El scraper corre en modo `headless=True` por defecto (sin ventana visible). Cambia a `headless=False` en `probar_scraper.py` para ver el navegador durante el scraping.
- Consulta `NOTAS_PROYECTO.md` para el estado actual del desarrollo, pendientes y decisiones tecnicas.
