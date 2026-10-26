---
name: ciclo-experimento
description: Protocolo comun de los agentes especialistas de PriceScraper (producto/NLP, vision) para proponer un cambio y medirlo con el evaluador de registros contra el ground truth, sin tocar GT, splits ni reglas. Usar al ejecutar un experimento de mejora del pipeline o al orquestar a los agentes especialistas y QA.
---

# Ciclo de experimento con el evaluador

El evaluador (`python -m evaluador`) es el juez compartido. Mide lo que el dashboard mostraria: registros
producto + precio + precio anterior por pagina, emparejados uno a uno contra el ground truth.
Validado contra calificacion humana a ciegas (39/39). **Nadie lo modifica**: GT, splits, reglas y
`manifest.json` son decision de la persona.

## Metricas

- **Principal: precision de registros completos** = registros correctos / registros en el dashboard.
- **Obligatorias: recall y F1.** Subir precision descartando registros buenos NO es mejora:
  si el recall baja, el cambio se rechaza aunque la precision suba.
- Regresion: una tienda cae > 2 pts con n >= 20 articulos. Bloquea si ademas es significativa (|z| >= 1.96).
  Tiendas con menos de 20 articulos se reportan con conteos, no bloquean.
- Errores por primera etapa que fallo: `ocr_no_leido`, `clasificacion`, `precio_mal_leido`,
  `asociacion_producto`, `producto_descartado`, `asociacion_antes`; en registros sobrantes ademas
  `precio_huerfano`, `promo_como_producto`, `duplicado`.

## Pasos (en orden)

Python del proyecto: `venv/Scripts/python.exe` (el de sistema no tiene las dependencias).

1. **Contexto.** `mem_search` en Engram (proyecto `pricescraper_ss`) con el tema del experimento:
   no repitas hipotesis ya probadas y descartadas.
2. **Base** con el codigo actual, ANTES de editar:
   `venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria`
   Anota la ruta de la corrida guardada (data/processed/_eval/runs/...). Si sale "NO VALIDA", detente y repórtalo.
3. **Diagnostico.** Elige casos concretos del error que atacas en `ejemplos_error[<codigo>][<tienda>]` del
   JSON de la corrida (hasta 10 por codigo y tienda, con `registro`, `esperado` y bbox). La imagen de la pagina esta en
   `data/raw/tiendeo/<tienda>/<folleto>/<pagina>`; mirala con Read si hace falta.
   Si la hipotesis depende del diseno de la pagina (donde va el nombre respecto al precio), mira antes
   `venv/Scripts/python.exe -m evaluador catalogo [--tienda T]`: diseno por tienda y por folleto, solo dev.
   Varias tiendas cambian de diseno entre folletos (alsuper, s-mart, heb): no propongas reglas por nombre de tienda.
   Formula UNA hipotesis acotada ("el normalizador acepta coincidencias fuzzy de un solo token").
4. **Cambio minimo** dentro de tu alcance. No cambies contratos JSON (nlp_resultado.json) ni el esquema de PostgreSQL.
   Agrega o ajusta pruebas en `tests/` (nunca `tests/test_evaluador.py`).
5. **Medir:** `venv/Scripts/python.exe -m pytest tests -q` y luego la misma corrida del paso 2.
   Despues: `venv/Scripts/python.exe -m evaluador comparar <base.json> <nueva.json> --casos [--tienda T] [--max N]`.
   Ademas de los netos, `--casos` dice cuantos articulos se ganaron y cuantos se perdieron por tienda, y lista cada uno.
   Reporta los dos numeros (p. ej. "+35 / -6"), no solo el neto, y explica los perdidos.
   Las dos corridas deben ser con `correr` sin `--sin-guardar` (solo las guardadas traen el detalle por caso).
   Para iterar rapido puedes usar `--tienda <t> --sin-guardar`, pero la decision se toma con dev completo.
   **Cambios de OCR** (`vision/preprocessor.py`, `vision/ocr_engine.py`): el OCR de produccion no cambia hasta reprocesar,
   asi que se miden con OCR experimental en CPU: `evaluador ocr --nombre <n> [--tienda T]` y `evaluador correr --ocr-exp <n>`,
   con una base de CPU sobre las mismas paginas (ver especialista-vision). Esa decision se toma por las tiendas medidas;
   el reproceso masivo se pide como batch GPU a la persona.
6. **Decidir.** Mantener solo si: precision sube, recall no baja, F1 sube, sin regresiones que bloqueen.
   Si no, revierte TU cambio a mano (Edit) y deja constancia de por que fallo: un resultado negativo tambien vale.
7. **Registrar** en Engram con `mem_save` (type `discovery`, topic_key `experimentos/<rol>/<slug>`):
   hipotesis, archivos tocados, metricas base -> nueva (precision, recall, F1, errores atacados),
   regresiones por tienda, decision.
8. **Reportar** a quien te invoco (formato abajo). No hagas commit, no recargues la BD, no corras el holdout.

## Reporte final del especialista

```
Hipotesis: ...
Archivos modificados: ... (o "revertido")
Corridas: base=<ruta>  nueva=<ruta>
Dev global: precision a->b | recall a->b | F1 a->b
Error atacado: <codigo> a->b
Regresiones: ninguna | <tienda: delta, n, z>
Ejemplos: 2-3 casos concretos que mejoraron y cualquiera que empeoro
Decision: mantener | revertido
Siguiente hipotesis sugerida: ...
```

## Orquestacion (sesion principal)

1. La persona aprueba el objetivo (por ejemplo "bajar `asociacion_producto`").
2. Se invoca UN especialista a la vez (`especialista-producto` o `especialista-vision`): comparten el arbol de trabajo
   y `load/load.py`, asi que nunca en paralelo.
3. Si el especialista decide "mantener", se invoca `qa-evaluador` con la ruta de la corrida base.
4. Con APROBAR de QA, se presenta a la persona: diff, cifras dev y, si lo pide, el holdout que corre QA.
   El commit y la recarga de la BD los decide la persona.
5. Con RECHAZAR, se revierte el cambio y la siguiente hipotesis parte del reporte.

Corrida base de referencia (dev, nlp memoria, commit 398c4e4, 26-oct-2026): `data/processed/_eval/runs/20261026_115424_398c4e4_dev.json`
(precision 33.1%, recall 24.7%, F1 28.3%). Igual corre tu propia base antes de editar: el codigo puede haber cambiado.
La primera base (11-oct-2026, afccff2) daba F1 3.6%; la evolucion esta en `md_modulos_leeme/06_evaluador.md`.

## Lo que esta prohibido (lo bloquea la guardia de agentes)

- Editar `evaluador/`, `data/`, `.claude/`, `tests/test_evaluador.py`, `tests/conftest.py`, `load/schema.sql`, `load/vistas.sql`.
- `git commit/push/add/checkout/...`, recargar la BD, `psql`, `probar_nlp.py`, `probar_vision.py` (reescriben produccion).
- `evaluador ocr` es solo de vision y QA.
- `evaluador sellar`, `evaluador splits`, `--split holdout` (este ultimo solo QA).
Si crees que el juez esta equivocado en un caso, NO lo "arregles": reportalo con el ejemplo.
