---
name: evaluar-calidad-nlp
description: Corre probar_evaluar_nlp.py (antes evaluar_nlp.py; comparación OCR+NLP vs el dataset de etiquetado manual de tiendeo) e interpreta los resultados separando causa raíz -- fallo de OCR, fallo de clasificación NLP, o pérdida real de dígitos por tipografía. Usar cuando el usuario pida evaluar, medir, o revisar la calidad/recall del pipeline OCR+NLP de PriceScraper MX, o comparar contra el dataset manual.
---

# Evaluación de calidad OCR+NLP (tiendeo)

## Correr

```
venv/Scripts/python.exe probar_evaluar_nlp.py
```

Se llamaba `evaluar_nlp.py` hasta el 3-oct-2026 (commit 842ccf5). Mide el recall por bloque (¿el OCR/NLP vio este producto o precio?), no el registro que muestra el dashboard. Para decidir si un cambio se queda, el juez es el evaluador de registros: `venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria` (skill `ciclo-experimento`, `md_modulos_leeme/06_evaluador.md`).

Es idempotente y rápido (solo lee JSON ya generados en `data/processed/`, no reprocesa OCR/NLP). Guarda detalle completo (incluye cada caso fallido individual, no solo agregados) en `data/processed/_evaluacion_nlp/reporte.json`.

## Cómo leer los resultados

El reporte da varias métricas separadas — no las trates como un solo número de "calidad":

- **PROD (OCR)** vs **PROD (NLP)**: la diferencia entre ambas aísla fallos de clasificación (el texto se leyó pero el regex no lo etiquetó como producto) de fallos de imagen (el OCR nunca lo leyó).
- **PRECIOS**: suele ser la métrica más baja y la que más confunde. Antes de concluir "el NLP falla", diagnosticar la causa real revisando `fallos_precio` en el reporte: para cada precio no encontrado, chequear si el bloque OCR de esa página tenía TODOS los dígitos del precio esperado (recuperable con un ajuste de regex — ver la skill `regex-precio-checklist`), si estaban repartidos en 2 bloques OCR cercanos (recuperable con una heurística de fusión de bloques), o si de plano no aparecen completos en ningún bloque de la página (pérdida real de OCR/tipografía, no arreglable solo con regex, necesita mejor resolución o segunda pasada de OCR).
- **PROMOS**: OJO — en el dataset manual (`*_contenido.json`), el campo `texto` de `promociones_pagina` es la descripción del producto/categoría al que aplica la promo, NO la mecánica de la promo. La mecánica real ("3X2", "25% de descuento") está en el campo `notas`. Comparar contra el campo equivocado da falsos 0% de recall en todas las tiendas — ya pasó una vez (07-ago-2026), el comparador se corrigió para usar `notas`.

## Al reportar al usuario

No dar solo el número global — desglosar por tienda (la tabla del reporte ya lo hace), porque el recall varía mucho entre tiendas (ej. alsuper/casa_ley con recall de OCR notablemente más bajo que el resto, posiblemente por densidad de texto o tamaño de fuente pequeño en esos folletos). Señalar explícitamente los folletos "sin datos" (pendientes de OCR, ver `folletos_sin_datos` en el reporte) que quedan excluidos de las métricas, para no dar una falsa sensación de cobertura del 100% del dataset manual.
