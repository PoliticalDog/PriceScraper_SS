#!/usr/bin/env python
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. ¿Está activo el entorno virtual "
            "y Django instalado?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
