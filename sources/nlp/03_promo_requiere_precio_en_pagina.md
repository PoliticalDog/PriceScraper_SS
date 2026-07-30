# Regla: PROMO exige al menos un precio en la pagina (jul 2026)

Continua `01_modulo_nlp.docx` / `02_modulo_nlp_v3_catalogo.docx`. Hallazgo
surgido al revisar por que `data/raw/tiendeo/walmart/416937` (folleto de solo
2 paginas) no tenia contenido real: son "portadas" publicitarias tipo banner
de video (TVs, "hasta 40%", "Compra ahora", "¡Envío en Horas!"), sin ningun
producto ni precio real -- comunes quiza en otros folletos tambien.

## Diagnostico

Corrida real de OCR+NLP sobre esas 2 paginas confirmo: **0 precios falsos**
-- el regex de precio no confunde tamaños de pantalla (`55"`, `65"`) ni
porcentajes ("hasta 40%") con precios. El problema no era en la tabla
`extracciones` de tipo PRECIO, sino en dos lugares:

1. `"hasta 40%"` se clasificaba como **PROMO** sin ningun chequeo de que
   hubiera un precio o producto real cerca -- a diferencia del paso de
   "precio sin simbolo" (`_extraer_precio_sin_simbolo`), que si exige
   contexto de precio (`_hay_contexto_precio`, radio 220px) antes de
   aceptar, `_es_promo` aceptaba por patron de texto puro. Esto insertaba una
   PROMO huerfana en `extracciones`, sin producto ni precio asociado.
2. `"Precios bajos todos los d[i]as"` se clasifica como EVENTO_PROMO (slogan
   repetido, ya documentado como falso positivo en otras sesiones) -- no
   se toco en este cambio, es un problema distinto.

Las promociones bancarias/MSI ("BBVA", "meses sin intereses", "tarjetas de
credito") NO estan afectadas por este hallazgo -- ya se descartan antes, en
`PATRONES_DESCARTE` (paso 1 de `_clasificar`), independiente de la regla de
PROMO.

## Regla agregada

`nlp/regex_extractor.py`: nueva funcion `RegexExtractor._pagina_tiene_precio()`
-- escaneo liviano (misma logica de extraccion de precio, sin side effects)
sobre TODOS los bloques de la pagina antes de clasificar. `procesar_pagina()`
lo calcula una vez y lo pasa a `_clasificar()` como `hay_precio_en_pagina`.

El paso 3 de `_clasificar` ahora exige `self._es_promo(texto) and hay_precio_en_pagina`
para aceptar PROMO -- si la pagina no tiene NINGUN precio, el bloque cae al
resto de la cascada (heuristica de producto / descarte) en vez de insertarse
como promo huerfana.

Se eligio el chequeo a **nivel de pagina completa**, no un radio de distancia
como en `_hay_contexto_precio`: una promo tipo "20% en toda la categoria"
puede estar legitimamente lejos de un precio especifico en una pagina con
muchos productos -- un radio fijo (220px) arriesgaba rechazar promos validas.
El chequeo por pagina es mas conservador, solo descarta cuando la pagina
entera no tiene ningun precio (el caso real: portadas publicitarias puras).

## Validacion

- `walmart/416937` (folleto real, 2 paginas sin precios): `"hasta 40%"` ya no
  se clasifica como PROMO (cae a PRODUCTO, que sin un precio en la pagina
  nunca se inserta en `extracciones` -- ver `load/load.py::_procesar_pagina`).
- `bodega_aurrera/413505/pagina_001` (pagina real con 7 precios): la promo
  `"Cia 16%"` (OCR de "Hasta 16%" o similar) se sigue detectando sin cambios
  -- confirma que el fix no afecta promos legitimas.

## Pendiente relacionado, no resuelto en este cambio

`data/processed/tiendeo/walmart/416937` tiene datos de OTRO folleto (frutas/
verduras, 11 paginas) -- data vieja de una version anterior de ese
`folleto_id` que Tiendeo reemplazo por el banner publicitario actual (2
paginas). El folder de processed no se limpio cuando cambio el contenido del
folleto. No es un problema de deteccion NLP, es staleness de datos -- fuera
de alcance de este cambio.
