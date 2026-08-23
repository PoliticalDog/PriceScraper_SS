"""
probar_dashboard.py
PriceScraper — Levanta el dashboard interno de visualizacion (Django).

Uso:
    python probar_dashboard.py
    -> abre http://localhost:8000 en el navegador
"""

import os
import sys

from load.db_builder import verificar_conexion


def main():
    print("\n" + "=" * 55)
    print("   PriceScraper — Dashboard (Django)")
    print("=" * 55)

    if not verificar_conexion():
        print("\n  ✗ No se pudo conectar a PostgreSQL.")
        print("  Verifica que el servidor esté activo y que .env sea correcto.")
        sys.exit(1)

    print("\n  ✓ Conexión OK. Levantando dashboard en http://localhost:8000\n")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "priceScraper_web.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(["manage.py", "runserver", "127.0.0.1:8000"])


if __name__ == "__main__":
    main()
