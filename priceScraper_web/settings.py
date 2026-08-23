"""
priceScraper_web/settings.py
PriceScraper — configuracion Django del dashboard interno (migrado desde
FastAPI el 23-ago-2026 para cumplir el stack tecnologico documentado en
Propuesta_PriceScraper_SS.docx: Django + Bootstrap 5).

Uso local/interno, sin login -- DEBUG=True es intencional, no hay despliegue
publico planeado por ahora.
"""

from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", encoding="utf-8")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-only-key-priceScraper-dashboard-interno")

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

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

# -- Base de datos --------------------------------------------------------------
# Se parsea DATABASE_URL (mismo .env que usa load/db_builder.py) en vez de
# agregar dj-database-url como dependencia nueva.
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
