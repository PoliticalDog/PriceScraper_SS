# web settings

from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# cargar variables de entorno desde .env
load_dotenv(BASE_DIR / ".env", encoding="utf-8")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-key-priceScraper-dashboard-interno")

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# definicion de apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "dashboard",
]

# definicion de middlewares
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "priceScraper_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "priceScraper_web.wsgi.application"

# ----------------- Base de datos -----------------
# Se parsea DATABASE_URL (mismo .env que usa load/db_builder.py) en vez de agregar dj-database-url como dependencia nueva.
_db_url = urlparse(os.getenv("DATABASE_URL", ""))

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _db_url.path.lstrip("/"),
        "USER": _db_url.username,
        "PASSWORD": _db_url.password,
        "HOST": _db_url.hostname,
        "PORT": _db_url.port or 5432,
    }
}

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mazatlan"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

# Procedencia de cada registro (visor de origen del dashboard). Solo lectura: Django sirve desde aqui la imagen
# de la pagina (raw = original, processed = la que vio el OCR, donde caen los bbox) y el fragmento de
# ocr_resultado.json / nlp_resultado.json de esa pagina. La ruta se arma con datos de la BD, nunca con la URL.
ORIGEN_RAW_DIR = BASE_DIR / "data" / "raw"
ORIGEN_PROCESSED_DIR = BASE_DIR / "data" / "processed"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
