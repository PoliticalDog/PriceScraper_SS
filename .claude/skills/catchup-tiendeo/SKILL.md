---
name: catchup-tiendeo
description: Lanza el catch-up de OCR+NLP restringido a la fuente "tiendeo" de PriceScraper MX, con las verificaciones de seguridad aprendidas de incidentes previos (procesos EasyOCR huérfanos). Usar cuando el usuario pida relanzar, continuar, retomar o revisar el avance del catch-up de OCR/vision/NLP de tiendeo.
disable-model-invocation: true
---

# Catch-up de OCR+NLP — tiendeo

Lanza `catchup_tiendeo.py`, que procesa SOLO `data/raw/tiendeo/**` (nunca "ofertomat" — decisión explícita del usuario, pausado a propósito hasta que se pida lo contrario). Reusa la lógica de `probar_vision.py` / `probar_nlp.py` sin prompts interactivos, así que se puede correr en background.

## Antes de lanzar (obligatorio)

Verificar que no haya un batch huérfano de una sesión anterior corriendo:

```
Get-Process python -ErrorAction SilentlyContinue
```

Si aparece algo, avisar al usuario antes de continuar — NO matar procesos sin confirmar qué son (podría ser trabajo legítimo del usuario). Este chequeo existe porque en una sesión previa un job de OCR quedó huérfano y, al relanzarlo sin saberlo, se duplicaron procesos EasyOCR compitiendo por recursos (hubo que terminarlos manualmente dos veces).

## Lanzar

Correr en background, con log dedicado:

```
venv/Scripts/python.exe catchup_tiendeo.py > logs/catchup_tiendeo_run.log 2>&1
```

## Mientras corre

- La fase de vision (OCR/EasyOCR) es lenta en CPU (~3-4 min/folleto en la máquina sin GPU). Si el usuario pregunta el avance, leer las últimas líneas de `logs/catchup_tiendeo_run.log` y reportar: folleto actual, folletos completados (comparar contra el total pendiente que el script imprime al arrancar), errores, ritmo estimado y tiempo restante estimado.
- La fase de NLP corre después de vision, es CPU-only y rápida (segundos a minutos para decenas de folletos) — no necesita GPU.
- Si el usuario decide cancelar (por ejemplo por lentitud, para terminarlo en una PC con GPU), usar TaskStop con el task_id del proceso en background y confirmar con `Get-Process python` que no quedó nada huérfano. El progreso parcial no se pierde: el script solo procesa folletos sin `ocr_resultado.json`, la próxima corrida retoma automáticamente donde quedó.

## Al terminar

Reportar folletos procesados, errores (si los hay), y sugerir correr la skill `evaluar-calidad-nlp` si el usuario quiere medir el impacto contra el dataset manual.
