---
name: preparar-traspaso-gpu
description: Arma el paquete de traspaso (ZIP en USB + instrucciones para la IA de la otra máquina) cuando una tarea de PriceScraper necesita GPU y esta máquina no tiene. Usar cuando el usuario pida preparar, armar o llevar algo a la PC con GPU, o cuando una investigación en CPU concluya que hace falta GPU para seguir.
---

# Preparar traspaso a la PC con GPU

Esta máquina no tiene GPU (`torch.cuda.is_available()` → `False`, confirmado). Cuando una tarea de OCR (EasyOCR) necesita GPU para ser viable en tiempo razonable, el flujo es: preparar un paquete en USB con lo mínimo necesario + un archivo de instrucciones en español para que la IA que opere la otra máquina pueda continuar sin tener que reconstruir el contexto de esta sesión desde cero.

No asumir que hay que llevar el corpus completo — el alcance real depende de la tarea (ver Paso 2). Definir el alcance ANTES de armar el ZIP.

## Paso 1 — Sincronizar código

El código (`nlp/`, `vision/`, scripts sueltos) va por git, no por USB — la otra máquina lo obtiene con `git pull`.

1. `git status` — confirmar que no hay cambios sin commitear que la otra máquina necesite.
2. Si hay cambios relevantes sin commitear, avisar al usuario y ofrecer commitearlos (nunca commitear sin confirmar).
3. `git push` — confirmar con el usuario antes de pushear si no está ya autorizado en la sesión.

## Paso 2 — Definir el alcance de datos

`data/` está en `.gitignore` — todo lo que la otra máquina necesite de ahí debe ir en el ZIP. Preguntar/confirmar con el usuario cuál de estos casos aplica (o si es una mezcla):

- **Catch-up de corpus** (procesar folletos pendientes a escala): llevar `data/raw/{fuente}/**` completo + los `ocr_resultado.json`/`nlp_resultado.json` YA existentes de `data/processed/` (sin las imágenes procesadas `.webp`/`comparacion.jpg`, pesan mucho y se regeneran solas) — esto es lo que permite que el script de catch-up detecte qué ya está al día y lo salte.
- **Experimento dirigido** (ej. probar una resolución o perfil distinto sobre un puñado de folletos/páginas puntuales): llevar SOLO esas imágenes de `data/raw/{fuente}/{tienda}/{folleto_id}/` + el `_contenido.json` correspondiente de `data/raw/_revision_manual/tiendeo/{tienda}/` si se va a medir contra el dataset manual. No llevar el corpus completo para esto — es innecesario y hace el ZIP pesado sin necesidad.
- **Otro**: ajustar el alcance a lo que la tarea realmente necesita; el criterio siempre es "¿qué archivo de `data/` necesita la otra máquina para poder correr esto y no puede regenerarse solo?"

Confirmar el tamaño estimado del ZIP antes de comprimir (`du`/`Get-ChildItem -Recurse | Measure-Object -Sum Length`) — si se dispara a varios GB, revisar si de verdad hace falta todo eso.

## Paso 3 — Armar el ZIP

Nombrar con la fecha de HOY (cuando se prepara, no cuando se ejecutará): `pricescraper_traspaso_{descripcion_corta}_AAAA-MM-DD.zip`, guardado en `D:\` (o la unidad USB que corresponda — confirmar con el usuario si no es obvio).

## Paso 4 — Escribir las instrucciones para la IA de la otra máquina

Archivo `.txt` en español, en la raíz del USB, nombrado `INSTRUCCIONES_{descripcion_corta}_AAAA-MM-DD.txt`. Esta IA NO tiene el contexto de esta conversación — el archivo tiene que ser autocontenido. Estructura:

1. **Contexto**: qué se está investigando/haciendo y por qué (1-2 párrafos, en el mismo nivel de detalle que le darías a un colega que no vio la sesión). Si hay una hipótesis siendo probada, decirla explícitamente y qué resultado la confirmaría o refutaría.
2. **Setup**: `git pull origin main`, descomprimir el ZIP dentro de `data/` (mergear, no reemplazar), verificar `Get-Process python` antes de lanzar nada (lección ya aprendida: procesos EasyOCR huérfanos de sesiones previas compiten por recursos si no se limpian).
3. **Qué correr**: comandos exactos, con los parámetros ya resueltos (no dejarle a la otra IA que adivine `ancho_objetivo`, `usar_gpu=True`, etc. — dárselo explícito). Recordar activar GPU explícitamente donde aplique (`OCREngine(usar_gpu=True)` — el default es `False` porque los scripts se pensaron para esta máquina sin GPU).
4. **Qué medir y cómo reportar**: qué métrica mirar (ej. precisión/recall de registros con `python -m evaluador correr --ocr-exp <nombre>`, o recall de producto/precio por bloque con `probar_evaluar_nlp.py`, antes `evaluar_nlp.py`), y qué formato de resultado traer de vuelta (tabla, JSON, lo que sea más fácil de leer al volver).
5. **Qué empaquetar de vuelta**: nombrar el ZIP de resultados con la fecha REAL de ejecución (no la de hoy) para poder identificarlo al reincorporar el USB — ej. `pricescraper_resultados_{descripcion_corta}_AAAA-MM-DD.zip`.

## Paso 5 — Verificación antes de dar por listo

1. Confirmar que el ZIP de datos y el `.txt` de instrucciones existen en el USB (`Get-ChildItem D:\` o `ls`).
2. Confirmar que el código relevante está pusheado (`git log origin/main..HEAD` debe estar vacío, o el usuario confirma que ya pusheó).
3. Recordarle al usuario que la verificación real del resultado solo pasa cuando vuelve con el USB — no es verificable desde esta sesión.

## Al volver con resultados

Si el usuario trae un ZIP de resultados: extraerlo, mergear en `data/processed/` (o donde corresponda), y comparar contra el baseline de esta sesión (buscar en memoria con `mem_search` si no está fresco en contexto) antes de sacar conclusiones — mismo criterio que la skill `regex-precio-checklist`: no asumir mejora, medirla.
