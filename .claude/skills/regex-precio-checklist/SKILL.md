---
name: regex-precio-checklist
description: Checklist para agregar o modificar reglas de extracción de precio en nlp/regex_extractor.py sin romper las tiendas ya validadas empíricamente. Usar cuando el usuario pida tocar, ajustar, relajar, o agregar patrones/reglas de precio (o clasificación de producto) al módulo NLP de PriceScraper MX.
---

# Checklist para tocar reglas de precio en regex_extractor.py

Este archivo tiene un historial largo de reglas confirmadas empíricamente contra folletos reales de tiendas específicas (ver comentarios en el código, ej. "confirmado en Casa Ley, S-Mart, Soriana Hiper/Mercado, Walmart, Bodega Aurrera, HEB y Chedraui"). Un cambio que mejora una tienda puede romper otra en silencio si no se mide.

## Antes de cambiar una regla

1. Correr la base del evaluador de registros, `venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria`, y anotar la ruta de la corrida (skill `ciclo-experimento`). Si quieres además el recall por bloque, `venv/Scripts/python.exe probar_evaluar_nlp.py` (antes `evaluar_nlp.py`; skill `evaluar-calidad-nlp`).
2. Leer los comentarios existentes alrededor de la regla que se va a tocar — casi siempre documentan CONTRA QUÉ imagen/tienda real se validó y POR QUÉ tiene la forma que tiene (ej. por qué la Regla B de `_extraer_precio_sin_simbolo` exige contexto fuerte cerca). No asumir que una restricción es arbitraria sin leer el comentario primero.

## Al cambiar

- Preferir relajar o agregar reglas de forma aditiva (nuevo patrón, nueva rama en la cadena de reglas) en vez de reescribir una regla ya confirmada.
- Si se relaja una condición de contexto (ej. quitar la exigencia de palabras tipo "antes/ahorra" cerca), mantener alguna señal de proximidad espacial al bloque — no aceptar números sueltos sin ningún contexto, para no confundir SKUs/números de página/cantidades de producto con precios.
- Documentar la nueva regla con el mismo estilo que las existentes: qué patrón resuelve, con qué tienda/folleto real se confirmó, y qué NO cubre a propósito (y por qué).

## Después de cambiar

1. Volver a correr la misma corrida del evaluador y comparar: `venv/Scripts/python.exe -m evaluador comparar <base.json> <nueva.json> --casos`. Además, mide el efecto en producción (precios creados, perdidos y cambiados por tienda) con un script de solo lectura, y revisa una muestra contra la imagen.
2. Comparar contra el baseline: precisión y recall deben subir (o la precisión subir sin que baje el recall) SIN regresiones en las tiendas que ya estaban altas (ej. costco, chedraui, la_comer). Si alguna tienda que antes iba bien ahora baja, es señal de que la regla nueva está capturando falsos positivos en otro lado (ej. tratando un SKU o una cantidad como si fuera un precio).
3. Si hay dudas sobre un caso específico, revisar `data/processed/_evaluacion_nlp/reporte.json` → `fallos_precio` / `fallos_producto` para ver casos concretos con tienda/folleto/página y decidir si el ajuste realmente aplica ahí.
