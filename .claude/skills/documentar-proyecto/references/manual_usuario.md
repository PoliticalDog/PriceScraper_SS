# Estructura del manual de usuario

Archivos en `docs/manual_usuario/`. El lector quiere poner el proyecto a funcionar y usarlo: instalar, correr cada etapa, recargar, leer el dashboard y trabajar con los agentes. Va de lo general a lo concreto, con comandos que se puedan copiar.

| Archivo | Capitulo | Contenido |
|---|---|---|
| `00_introduccion.md` | Introduccion | Que es PriceScraper, que problema resuelve, que hay en el repo y como leer estos manuales |
| `01_instalacion.md` | Instalacion | Python y venv, `requirements.txt`, PostgreSQL (crear BD y usuario, `schema.sql` y `vistas.sql`), `.env` con el formato de `DATABASE_URL` (sin valores reales), Tesseract y `tessdata/`, Playwright y Chromium, GPU opcional para el OCR |
| `02_flujo_completo.md` | Flujo de datos | Las etapas en orden (scrapear, OCR, NLP, cargar, ver) con el comando de cada una, que produce y donde lo deja (`data/raw`, `data/processed/<fuente>/<tienda>/<folleto>/`) |
| `03_scripts.md` | Scripts del proyecto | `probar_scraper.py`, `probar_vision.py`, `probar_nlp.py`, `probar_load.py`, `catchup_tiendeo.py`, `probar_dashboard.py`: para que sirve cada menu, modo prueba contra modo batch, que reescribe cada uno |
| `04_recargas_y_respaldos.md` | Recargas y respaldos | Cuando hay que reprocesar el NLP y recargar, el respaldo previo (pg_dump + tar de los NLP), como verificar antes y despues, como restaurar. Los respaldos son locales y no van al repo |
| `05_dashboard.md` | Uso del dashboard | Cada pagina con su captura anotada: que muestra, que significan los numeros, filtros, como llegar del dato a la imagen original (visor de origen) |
| `06_trabajo_con_claude.md` | Trabajo con agentes | Como se trabaja con Claude Code en el repo: skills disponibles, especialistas y QA, el ciclo de experimento, la guardia, Engram y la memoria; que pedir y que no |
| `07_problemas_comunes.md` | Problemas comunes | Errores tipicos y su solucion (rutas absolutas en probar_nlp, encoding, GPU, permisos), en formato sintoma / causa / solucion |

## Notas

- **Comandos reales y probados.** Antes de poner un comando, confirma que el script y sus opciones existen. Si un paso necesita una decision (por ejemplo, forzar el reproceso), di que pasa con cada opcion.
- **Capturas.** Cada pagina del dashboard lleva su captura con recuadros numerados y, debajo, la explicacion de cada numero. Las capturas se definen en `docs/manual_usuario/capturas.yaml`.
- **Nada de secretos.** Formatos de ejemplo, nunca credenciales reales.
- **Remite al manual tecnico** cuando el lector necesite entender por que algo funciona asi, en vez de repetirlo.
