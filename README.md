# 🛒 PriceScraper

Sistema de extracción, procesamiento e inteligencia de precios de folletos digitales de supermercados mexicanos.

**Fuentes:** Tiendeo.com.mx · Ofertomat.mx  
**Stack:** Python · Playwright · OpenCV · EasyOCR · spaCy · PostgreSQL · Django · PySpark

---

## ⚙️ Requisitos previos

- Python 3.10 o superior
- Git

---

## 🚀 Configuración en máquina nueva

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

> **Nota:** La carpeta `data/` no está en el repositorio (ver `.gitignore`).  
> Si cambias de máquina, copia la carpeta `data/` manualmente desde USB o disco externo.

---

## ▶️ Ejecución del pipeline

Cada módulo tiene su propio script interactivo con menú:

```bash
# 1. Scraping — descargar folletos de Tiendeo
python probar_scraper.py

# 2. Visión — preprocesar imágenes y extraer texto (OCR)
python probar_vision.py

# 3. NLP — clasificar bloques de texto en producto/precio/promo
python probar_nlp.py
```

---

## 📁 Estructura del proyecto

```
PriceScraper_SS/
├── scraper/
│   ├── metodos_scraper.py   # Clase base Playwright
│   ├── downloader.py        # Descarga de imágenes
│   ├── registro.py          # Control de folletos procesados
│   └── sources/
│       ├── tiendeo.py       # Adaptador Tiendeo.com.mx
│       └── ofertomat.py     # Adaptador Ofertomat.mx
├── vision/
│   ├── preprocessor.py      # Pipeline OpenCV
│   └── ocr_engine.py        # EasyOCR + Tesseract
├── nlp/
│   └── regex_extractor.py   # Extractor de entidades
├── data/                    # ← NO incluido en git (ver .gitignore)
│   ├── raw/                 # Imágenes descargadas
│   └── processed/           # Imágenes procesadas + JSONs OCR/NLP
├── logs/                    # ← NO incluido en git
├── probar_scraper.py
├── probar_vision.py
├── probar_nlp.py
├── requirements.txt
└── NOTAS_PROYECTO.md        # Contexto del proyecto para retomar desarrollo
```

---

## 📋 Notas

- La primera ejecución de `probar_vision.py` descarga los modelos de EasyOCR automáticamente (~500 MB). Las siguientes ejecuciones son instantáneas.
- El scraper corre en modo `headless=True` por defecto (sin ventana visible). Cambia a `headless=False` en `probar_scraper.py` para ver el navegador durante el scraping.
- Consulta `NOTAS_PROYECTO.md` para el estado actual del desarrollo, pendientes y decisiones técnicas.