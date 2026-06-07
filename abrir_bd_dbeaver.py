"""
abrir_bd_dbeaver.py
PriceScraper MX — Abrir la base SQLite en DBeaver

Este módulo abre el archivo data/pricescraper.db directamente en DBeaver.
No modifica la base de datos; solo lanza el gestor visual.

Uso:
    python abrir_bd_dbeaver.py

Opcional:
    python abrir_bd_dbeaver.py ruta/a/tu_base.db

Notas:
- DBeaver debe estar instalado.
- En Windows, si DBeaver no está en PATH, el script intenta buscarlo en
  Program Files, AppData y rutas comunes.
- En macOS intenta usar la app DBeaver.app.
- En Linux intenta usar el comando dbeaver.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


# Misma ruta que usa tu módulo probar_sqlite.py
DB_PATH = Path("data/pricescraper.db")


def resolver_ruta_db() -> Path:
    """Devuelve la ruta de la BD recibida por argumento o la ruta por defecto."""
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser().resolve()
    return DB_PATH.expanduser().resolve()


def encontrar_dbeaver() -> str | None:
    """Intenta encontrar el ejecutable de DBeaver en Windows, macOS o Linux."""
    sistema = platform.system().lower()

    # 1) Si está en PATH
    for comando in ("dbeaver", "dbeaver-ce", "dbeaver.exe"):
        ruta = shutil.which(comando)
        if ruta:
            return ruta

    # 2) Rutas comunes por sistema
    candidatos: list[Path] = []

    if sistema == "windows":
        home = Path.home()
        candidatos.extend([
            Path(r"C:\Program Files\DBeaver\dbeaver.exe"),
            Path(r"C:\Program Files\DBeaver Community\dbeaver.exe"),
            Path(r"C:\Program Files (x86)\DBeaver\dbeaver.exe"),
            Path(r"C:\Program Files (x86)\DBeaver Community\dbeaver.exe"),
            home / "AppData" / "Local" / "DBeaver" / "dbeaver.exe",
            home / "AppData" / "Local" / "DBeaverCommunity" / "dbeaver.exe",
        ])

    elif sistema == "darwin":
        candidatos.extend([
            Path("/Applications/DBeaver.app/Contents/MacOS/dbeaver"),
            Path("/Applications/DBeaver Community.app/Contents/MacOS/dbeaver"),
        ])

    else:  # Linux
        candidatos.extend([
            Path("/usr/bin/dbeaver"),
            Path("/usr/local/bin/dbeaver"),
            Path("/snap/bin/dbeaver-ce"),
            Path("/var/lib/flatpak/exports/bin/io.dbeaver.DBeaverCommunity"),
        ])

    for ruta in candidatos:
        if ruta.exists():
            return str(ruta)

    return None


def abrir_en_dbeaver(db_path: Path) -> None:
    """Abre la base SQLite en DBeaver."""
    if not db_path.exists():
        print(f"❌ No existe la base de datos:\n   {db_path}")
        print("\nPrimero crea la BD con:")
        print("   python probar_sqlite.py")
        print("y usa la opción 1 → Crear BD y tablas.")
        sys.exit(1)

    dbeaver = encontrar_dbeaver()
    if not dbeaver:
        print("❌ No encontré DBeaver automáticamente.")
        print("\nSoluciones:")
        print("1. Abre DBeaver manualmente.")
        print("2. New Database Connection → SQLite.")
        print(f"3. Selecciona este archivo:\n   {db_path}")
        print("\nTambién puedes agregar DBeaver al PATH del sistema.")
        sys.exit(1)

    print("✅ Base encontrada:")
    print(f"   {db_path}")
    print("✅ Abriendo con DBeaver:")
    print(f"   {dbeaver}")

    sistema = platform.system().lower()

    try:
        if sistema == "darwin":
            # En macOS suele funcionar mejor abrir la app y pasar el archivo.
            subprocess.Popen(["open", "-a", "DBeaver", str(db_path)])
        else:
            subprocess.Popen([dbeaver, str(db_path)])
    except Exception as e:
        print(f"❌ No se pudo abrir DBeaver automáticamente: {e}")
        print("\nÁbrelo manualmente y selecciona la base:")
        print(f"   {db_path}")
        sys.exit(1)


if __name__ == "__main__":
    abrir_en_dbeaver(resolver_ruta_db())
