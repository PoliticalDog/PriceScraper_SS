# Módulo NLP

El módulo NLP es el tercer eslabón del pipeline. Recibe el texto que el OCR leyó en cada página de folleto (`ocr_resultado.json`) y clasifica cada bloque en una de ocho categorías: precio, precio anterior, ahorro, promoción, campaña, producto, atributo o descarte. No asocia el producto con su precio; eso lo hace el módulo de carga (`load/load.py`).

## Propósito y alcance

Un folleto no trae datos estructurados: trae cientos de bloques de texto sueltos, muchos mal leídos por el OCR ("$429" puede llegar como "8429", "s429" o "$" y "429" en bloques distintos). El NLP decide qué es cada bloque usando expresiones regulares, la geometría de la página (tamaño y posición de los bloques) y un catálogo de productos.

| Hace | No hace |
|---|---|
| Clasificar cada bloque OCR y extraer el valor numérico de precios, precios anteriores y ahorros | Unir el producto con su precio (load) |
| Reconstruir precios partidos en varios bloques (entero + centavos en superíndice) | Leer la imagen (vision) |
| Asignar categoría a productos y atributos con el catálogo | Guardar en la base de datos (load) |
| Detectar la campaña del folleto (Julio Regalado, Hot Sale...) | Calcular métricas de calidad (evaluador) |

Tabla: Alcance del módulo NLP

## Entradas y salidas

**Entrada:** `data/processed/<fuente>/<tienda>/<folleto>/ocr_resultado.json`, producido por el módulo de visión. Cada página trae su ancho (`ancho_pagina`) y sus bloques con texto, confianza del OCR y caja (`bbox`):

```
{"pagina": "pagina_003.webp", "ancho_pagina": 1800, "confianza_prom": 0.642,
 "bloques": [{"texto": "$429", "confianza": 0.675,
              "bbox": {"x": 1261, "y": 520, "ancho": 303, "alto": 129}, "motor": "easyocr"}, ...]}
```

**Salida:** `nlp_resultado.json` en la misma carpeta. El contrato lo arma `nlp/salida_json.py` (`resultado_nlp`) y lo consumen `load/load.py` y el evaluador. Trae un resumen con totales por categoría y la tasa útil (bloques que no son descarte / total), y por página una lista por categoría:

```
"resumen": {"total_productos": 231, "total_precios": 52, "total_precios_anterior": 7,
            "total_promos": 4, "total_atributos": 1, "total_descartes": 110, "tasa_util": 0.728, ...}
"paginas": [{"pagina": "pagina_003.webp",
             "precios":   [{"texto": "$429", "valor": 429.0, "confianza": 0.675, "bbox": {...}}],
             "productos": [{"texto": "...", "confianza": 0.44, "bbox": {...}, "categoria": ""}],
             "precios_anteriores": [{"texto": "...", "valor": ..., "candidatos": [...], ...}], ...}]
```

Ejemplo real: bodega_aurrera, folleto 413505, página 3 (tiendeo).

Los descartes solo se cuentan en el resumen: no se guardan por página. Las claves `total_financiero` y `financiero` existen pero siempre van en cero y vacías (reservadas).

Si cambia este contrato (nombres de claves, estructura de `bbox`), se rompen `load/load.py`, el evaluador y la base de datos. Por eso los agentes del proyecto tienen prohibido cambiarlo sin aprobación.

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `nlp/regex_extractor.py` | Clasificador de bloques y reglas de precio (unas 2,400 líneas) | `RegexExtractor.procesar_pagina`, `_clasificar`, `_extraer_precio`, `_extraer_precio_sin_simbolo`, `_detectar_precios_fusionados`, `slug_evento` |
| `nlp/normalizador.py` | Convierte el texto de un producto en un nombre canónico comparable | `Normalizador.normalizar` → `ResultadoNorm` (`nombre_canonico`, `confianza_norm`, `metodo`) |
| `nlp/catalogo_productos.py` | Catálogo de categorías con palabras clave, tipos de producto y marcas | `CATALOGO`, `buscar_categoria(texto)` → `(encontrado, categoria, es_atributo)` |
| `nlp/salida_json.py` | Arma el contenido de `nlp_resultado.json` sin escribir en disco | `clasificar_paginas_ocr`, `resultado_nlp` |
| `nlp/evaluador_calidad.py` | Funciones del comparador antiguo contra el etiquetado manual; el evaluador actual reutiliza su normalización de texto | `tokens_significativos`, `recall_texto`, `TOLERANCIA_PRECIO` |
| `probar_nlp.py` | Orquestador: menú, modo prueba y modo batch; escribe los JSON | `procesar_carpeta(carpeta, extractor, forzar)` |

Tabla: Archivos del módulo NLP

El normalizador no lo llama `probar_nlp.py`: lo usan `load/load.py` (al cargar) y el evaluador. Por eso `nlp_resultado.json` guarda el texto del producto tal como lo leyó el OCR, sin nombre canónico.

## Cómo funciona

### Flujo por página

`RegexExtractor.procesar_pagina` recorre la página en este orden:

```
bloques OCR de la página
   │
   ├─ pasada previa: ¿la página tiene algún precio real?  (_pagina_tiene_precio)
   ├─ pre-paso: anticipos de apartado, mensualidades MSI, puntos y plazos junto a su rótulo → DESCARTE
   ├─ pre-paso: precios partidos entero + centavos en superíndice → PRECIO  (_detectar_precios_fusionados)
   │
   ├─ por cada bloque restante (confianza ≥ 0.15):  _clasificar
   │     0. ¿es la campaña del folleto?                → EVENTO_PROMO
   │     1. ¿es ruido, letra chica, banco, tienda...?  → DESCARTE
   │     2. ¿"Antes: $X" o "DE $X A"?                  → PRECIO_ANTERIOR
   │     3. ¿mecánica de promoción (3x2, %, regalo)?   → PROMO
   │     4. ¿"Ahorra $X"?                              → AHORRO
   │     5. ¿precio con "$" (o confirmado por cuota)?  → PRECIO
   │     6. ¿precio sin "$" con contexto suficiente?   → PRECIO
   │     7. ¿está en el catálogo?                      → PRODUCTO o ATRIBUTO
   │     8. ¿parece nombre de producto?                → PRODUCTO
   │     9. nada de lo anterior                        → DESCARTE
   │
   └─ al final: los centavos ya sumados a otro precio dejan de ser precio propio
```

El orden importa: cada paso solo ve lo que no atraparon los anteriores. Por ejemplo, la campaña se evalúa antes del descarte porque "72ANIVERSARIO]" de casa_ley caía en el descarte de símbolos raros.

El comentario largo al inicio de `nlp/regex_extractor.py` todavía pone el precio antes de la promoción y omite el slug `fiestas_patrias`; el orden real es el del diagrama (el de `_clasificar`).

### Limpieza del texto

Antes de clasificar, `_limpiar_texto` aplica las `CORRECCIONES_OCR` del extractor (8 sustituciones): "@" → "o", "$ 429" → "$429", "$16,o00" → "$16,000", espacios repetidos y "||" o "!!" sobrantes. Los bloques con confianza OCR menor a `CONFIANZA_MINIMA` (0.15) no se clasifican. El normalizador tiene su propia lista de correcciones (ver "Normalización del nombre").

### Escala de la página

Los umbrales en píxeles (distancias de contexto, tamaño de los superíndices) se calibraron con páginas de 1500 px de ancho (`ANCHO_REFERENCIA_UMBRALES`). Cada página multiplica esos umbrales por `factor_escala = ancho_pagina / 1500`, para que una página procesada a 1800 px se comporte igual.

### Descartes

`PATRONES_DESCARTE` tiene 38 expresiones regulares; `_es_descarte` las prueba en orden y, como respaldo, descarta todo bloque de más de 3 caracteres con más del 40% de caracteres raros. Además, el paso 1b de `_clasificar` descarta las condiciones de compra ("Válido en compras mayores a $238", "En compras desde $500") antes de buscar precios. Por familia:

| Familia | Qué atrapa | Ejemplos reales | Desde |
|---|---|---|---|
| Forma del bloque | 1-2 caracteres (salvo 2 dígitos, que pueden ser un precio entero), solo símbolos, 3+ caracteres especiales seguidos, consonantes sin vocales | "xkcd bnm" | jul-2026; excepción de 2 dígitos 19-ago-2026 |
| Web | URLs | "www.walmart.com.mx" | jul-2026 |
| Vigencias y letra legal | Vigencia, vencimiento, "válido", "del N de", "hasta agotar", "sujeto a", "términos y condiciones", días de la semana con fecha, rangos de fecha | "Sábado 30 de Mayo", "Del 03 al 21 de junio 2026" | calendario 23-ago-2026; rangos 2f616c3 |
| Restricciones de compra | Límite por cliente y avisos de canal | "Maximo 10 Kg. Por Cliente", "Aplican restricciones", "Tambien En: App" | 23-ago-2026 |
| Tiendas | Nombre de la tienda solo, lemas y frases de canal | "Soriana", "en tienda y en línea", "híper", "cashback", "La supercampeona de los precios bajos" | jul-2026; lemas 85e9e95 |
| Geografía | Estados de México y sus abreviaturas | "Jalisco", "QROO" | jul-2026 |
| Bancos y financiamiento | Bancos solos o combinados, frases de MSI, montos "MN.", listas de categorías con MSI, rótulo "N MSI \| $X" | "BBVA", "$6,000 MN.", "En Electrónica, Cómputo, Fotografía, Videojuegos", "9MSI\|$1,44433)" | 4f78684; MSI 7fad080 |
| Marketing | Verbos de campaña con "¡" leído "i", frases completas de slogan, portada y cierre, palabras sueltas de folleto, etiquetas genéricas | "iConsiente a mamá", "imágenes ilustrativas", "Desde:", "PRECIO ESPECIAL", "SuPeR OFERTA" | 4f78684; puntuación pegada 2f616c3 |
| Rótulos de casilla | El rótulo de precio separado de su número | "todos los dias", "Apartalo con", "a solo:", "AHORRA", "COMPRA", "cada", "Llévate", "Aurrera" | c468950, 05ca950 |
| Rótulos de promoción, lealtad y servicio | Pedazos de frases que el OCR parte en bloques | "Intcrcscs", "'300 puntos", "Te regala", "Monedero", "PRECIAZO", "SÚPER", "Adicional", "Envío", "Garantía extendida" | 2f616c3 |
| Logos de envase | Marca propia impresa en el empaque y su encabezado | "Golden Hills" (con 30+ variantes OCR), "un brillo de calidad" | jul-2026 |
| Especificaciones sueltas | Tallas y capacidades sin producto | "Tallas: CH", "128 GB" | jul-2026 |

Tabla: Familias de PATRONES_DESCARTE (nlp/regex_extractor.py)

Las reglas que siguen el criterio actual comparten dos ideas:

- **Anclar al bloque completo.** El patrón de rótulos exige que el bloque sea solo el rótulo, sin dígitos: "a solo $149" y "Ahorra $245" siguen siendo precio, y "Todos los dias Leche" sigue siendo producto. Por eso estas reglas no cambian ninguna regla de precio. La única excepción es "Apártalo con $629.90": en Chedraui ese monto es el anticipo de apartado (10% del precio), no el precio, y el bloque entero se descarta.
- **No descartar palabras genéricas sueltas.** El 23-ago-2026 se intentó descartar palabras como "mimarca", "variedad", "pieza" o "gramos" solas, y la cobertura de producto bajó de 75.2% a 73.8%: el OCR parte "Frijol pinto Mimarca 900 gramos" en tres bloques, y descartar "Mimarca" perdía parte del producto real. Solo quedaron las frases que nunca son fragmento de un nombre.

Cifras de las reglas de rótulos (dev y producción sin holdout):

- c468950 (11-oct-2026): dev precisión 6.0 → 7.1, recall 5.7 → 6.8; registros con un rótulo como producto, 95 → 0.
- 2f616c3 (12-oct-2026): unos 8,200 bloques de producción pasan de PRODUCTO a DESCARTE sin que cambie ningún PRECIO, PROMO o ATRIBUTO. Falsos positivos conocidos: unos 40 bloques (menos de 0.5%), siempre fragmentos de un nombre partido ("Super" de "Arroz Super Extra Ley", "PROTECCION" en cremas).

### Campañas

`slug_evento(texto)` decide si un bloque **es** la campaña del folleto y devuelve su slug canónico, el mismo que usa el dashboard. Las campañas están en `CAMPANAS_EVENTO`, una lista de 10 tuplas (slug, patrón, estricta):

| Slug | Reconoce | Estricta | Ejemplos reales que sí son campaña |
|---|---|---|---|
| `julio_regalado` | "julio regalad..." | No | "JULIOREGALADOE", "Julioregaladods" |
| `hot_sale` | "hot sale", "hot-sale" | No | "Este Hot Sale obtén con", "hotsale com mx" |
| `buen_fin` | "buen fin" | No | "El Buen Fin" |
| `regreso_a_clases` | "regreso a clases", "back to school", "temporada escolar" | No | "El regreso a clases empieza con el", "enBack To School" |
| `aniversario` | "aniversario/a" | No | "72ANIVERSARIO]", "EESTADE/72ANIVERSARIO" |
| `ofertones` | "ofertón..." con "0" por "o" | No | "oFERTONONON]", "Portiofertones" |
| `liquidacion` | "liquidación(es)" | No | "LIQUIDACION DERoPA" |
| `navidad` | "navidad", "temporada navideña" | Sí | "en Navidad" |
| `halloween_dia_de_muertos` | "halloween", "día de (los) muertos" | Sí | "Halloween", "en Día de muertos" |
| `fiestas_patrias` | "fiesta(s) patrias" | Sí | "PARA LAS FIESTAS PATRIAS" |

Tabla: Campañas reconocidas (CAMPANAS_EVENTO en nlp/regex_extractor.py) | Fuente: tests/test_eventos_campania.py

Cómo decide:

1. Si el bloque tiene algo de `_EXCLUSION_EVENTO` no es campaña: un "$" o un número con decimales, "excepto", "códigos", "participantes", "reservamos", "términos", "condiciones", "consulta", "aplica", "válido", "vigencia", un banco (Banamex, BBVA, Santander, Banorte, HSBC, Invex), "http"/"www" o "MSI"/"meses"/"intereses". Así quedan fuera "(excepto códigos de liquidación)", "Consulta términos y condiciones en www.banamex.com/hotsale" y "Julio Regalado $29.90".
2. Gana la primera campaña de la lista que aparece en el texto (en el corpus no hay bloques con dos campañas).
3. Se quita la campaña y se cuentan las palabras que sobran, sin contar los conectores de `_CONECTORES_EVENTO` ("en", "el", "este", "para", "gran", "feliz", "com", "mx"...) ni un año "20dd". En una campaña normal sobra como mucho una palabra de 3+ caracteres ("DERoPA"). En una **estricta** no puede sobrar ninguna de 2+ caracteres, porque navidad, halloween y fiestas patrias también son adjetivos de producto: "Plato desechable Halloween;", "Halloween; 12 cm", "BAÑO NAVIDAD", "Fiestas patrias banderín 3 pzas" y "Back to School 100 hojas" son productos.

Se evalúa en el paso 0 de `_clasificar`, antes del descarte, y load la reutiliza: `_normalizar_nombre_evento` llama a `slug_evento` y solo inserta el evento si hay slug, con las fechas de vigencia del folleto.

Antes del commit 85e9e95 (16-oct-2026), el patrón aceptaba cualquier bloque que *contuviera* la campaña o un lema, y load guardaba el texto completo: 45 slugs distintos para 77 eventos, con la letra chica de HEB y nombres de producto ("Vela aromática Navidad Santa") como campañas. Los lemas ("Precios Bajos Todos los Días", "La supercampeona de los precios bajos") pasaron a DESCARTE. En la recarga del 16-oct-2026 quedaron 125 eventos en 115 folletos con 9 slugs (halloween 31, aniversario 24, ofertones 21, regreso_a_clases 14, julio_regalado 13, navidad 8, fiestas_patrias 8, hot_sale 4, liquidacion 2; Engram #227). `fiestas_patrias` se agregó después de QA, con aprobación de la persona.

### Precio anterior y ahorro

`_extraer_precio_anterior` reconoce dos formas y devuelve una lista de **candidatos** (todas las lecturas razonables del monto, la primera es `valor`):

- **"Antes: $X"** (`PATRON_PRECIO_ANTERIOR`): "antes", "antos" (error OCR) o "precio anterior" como palabra completa, para que "desinfectantes 35pz" no cuente. Tolera el "$" leído como `* # s S ' { +`.
- **"DE $X A"** (`PATRON_DE_A`, diseño de Soriana): el primer monto es el anterior y el precio actual va en otro bloque. Tolera los centavos en superíndice ilegibles ("@", "oo", "u") y exige que la "A" no vaya seguida de un número, así "de 180 gr a 220 gr" no cuenta. Como Soriana siempre imprime centavos en superíndice, aquí la lectura con centavos va primero.

`_candidatos_precio_anterior` genera las lecturas porque el texto solo no basta para elegir:

| Texto OCR | Candidatos (en orden) | Lectura real |
|---|---|---|
| "Antes: $699" | 699, 6.99 | 699 |
| "Antes 81090" | 81,090 · 810.90 · 1,090 · 10.90 | $10⁹⁰ con el "$" leído 8 |
| "Antes 522,99000" | 522,990 · 22,990 | $22,990⁰⁰ |
| "DE $22,99000 A" | 22,990 | $22,990⁰⁰ |
| "DE $3690 A" | 36.90 · 3,690 | según el precio actual |
| "Antes 3,395" | 3,395 · 1,395 | Chedraui tacha el "Antes" y la raya deforma el 1 inicial |

Tabla: Lecturas del precio anterior (resultados de _extraer_precio_anterior, verificados el 26-oct-2026)

Load elige la lectura coherente: `emparejar_precios_anteriores` (en `load/load.py`) empareja cada precio anterior con un precio actual por geometría (misma columna, pegado arriba o abajo, uno a uno, sin mensualidades) y `_lectura_coherente` toma el primer candidato que da un descuento creíble, entre 3% y 50% (`DESCUENTO_MIN` y `DESCUENTO_MAX`; el p95 del ground truth es 47%). Si el precio actual es "5XXX" y su otra lectura (el "5" como "$") también cuadra, no empareja. Con este cambio (commit 7819d24, 11-oct-2026), sobre 276 pares del ground truth la precisión del precio anterior subió de 26% a 84% y el recall de 22% a 28%; antes, un mismo "antes" acababa en varios precios y el 47% de los descuentos salía mayor a 70%.

**Ahorro.** `PATRON_AHORRO` lee "Ahorra/Ahorras" + monto y tolera el "$" leído como "5": "Ahorras $32.90" → 32.90, "Ahorras 5755.00" → 755.00. El ahorro y el precio anterior también sirven de contexto a las reglas de precio: en Walmart (Ahora / Antes / Ahorra en la misma casilla) `_restas_antes_ahorro` calcula Antes − Ahorra para decidir si "5454" es $54.54 o $454 (28 de 28 bloques cuadraron en dev, 11-oct-2026).

### Promociones

Una promoción es una mecánica de precio, no la campaña. Hay dos grupos:

| Grupo | Patrones | Ejemplos | Condición |
|---|---|---|---|
| Fuerte (`PATRONES_PROMO_FUERTE`, 8) | N×M, "$X por cada $Y" (también con el "$" leído s/5/8/{), "mitad de precio", "segunda a mitad", "compra uno y llévate", paquetes repetidos | "3x2", "2x$50", "$10 por cada $50", "s25 por cada $100", "1x$33.90 3x$67.80" | Ninguna |
| Débil (`PATRONES_PROMO_DEBIL`, 4) | Porcentaje, "te regalamos", "lleva", "paga", "gratis", "bonificación", "precio con promo", "hasta N%", "descuento de N%" | "hasta 40%", "GRATIS)", "25% de descuento" | La página debe tener algún precio |

Tabla: Promociones fuertes y débiles (nlp/regex_extractor.py)

La débil exige precio porque, sin él, casi siempre es un banner publicitario. El caso que lo motivó fue walmart 416937, dos portadas de televisores con "hasta 40%" y ningún producto con precio: el bloque se guardaba como una PROMO huérfana (commit ea1fe82, jul-2026; `sources/nlp/03_promo_requiere_precio_en_pagina.md`, Engram #38). `_pagina_tiene_precio` revisa la **página completa**, no un radio alrededor del bloque, porque una promo como "20% en toda la categoría" puede estar lejos de cualquier precio y un radio fijo la perdería. Si la página no tiene precio, el bloque sigue la cascada y hoy termina como PRODUCTO por la heurística; load no lo inserta porque no tiene precio. La fuerte no necesita esa condición: "4x3" en una página de llantas sin precio unitario sigue siendo una promoción real.

La promoción se evalúa antes del ahorro y del precio. Por eso "$10 por cada $50" de La Comer es PROMO y no un precio de $50: antes del commit 6d0670b (12-oct-2026), la versión con el "$" mal leído caía en el precio y se quedaba con el monto de compra. Las promociones bancarias y de MSI no llegan aquí: ya se descartaron en el paso 1.

### Precios con "$"

`_extraer_precio` reconoce "$" + número con miles y decimales, prefijos ("desde", "a sólo") y sufijos ("c/u", "MXN"). También tolera el "$" leído como "s", "S" u "8" pegado a los dígitos (`PATRON_PRECIO_OCR_CORRUPTO`).

Un caso especial son los **centavos pegados**: en el diseño de soriana el OCR junta entero y centavos en un solo bloque ("$1989" es $19.80). Un "$" literal seguido de 4 o 5 dígitos sin separador se lee como entero + centavos (`PATRON_CENTAVOS_PEGADOS`), salvo que la casilla confirme el entero (`_entero_confirmado`): una mensualidad cuyo total da el entero (9 MSI de $288.33 = $2,595), un "DE $X A" que solo es creíble con el entero, u otro monto con coma de miles en el mismo bloque.

### Precios sin "$"

Es la parte más delicada. El OCR pierde o confunde el "$" con frecuencia, pero un número suelto también puede ser un gramaje, un modelo o un porcentaje. `_extraer_precio_sin_simbolo` aplica reglas con distinta exigencia de contexto:

| Regla | Forma | Ejemplo | Condición |
|---|---|---|---|
| A-miles / A2-miles | dígito espurio + miles con coma | "52,49000" → $2,490 | El superíndice se ignora: tres dígitos tras la coma siempre son miles |
| A2 | dígito espurio + número con decimal | "824.95" → $24.95 | — |
| A-escala | 5/6/8/s + entero de 2 dígitos | "835" → $35 | Todos los números de 3 caracteres del mismo tamaño en la página empiezan con 5/6/8/s (al menos 2) |
| A | dígito espurio + entero | "8249" → $249 | Se intenta después de B-4 |
| B-5 | 5 dígitos | "15490" → $154.90 | Contexto de precio |
| B-4 | 4 dígitos | "6990" → $69.90 | Contexto de precio |
| B-3 | 3 dígitos | "999" → $9.99 | Contexto fuerte |
| B-2 | 2 dígitos | "15" → $15 | Contexto fuerte; no continúa un nombre |
| C | miles con coma | "12,499" → $12,499 | No ambiguo |

Tabla: Reglas de precio sin "$" (nlp/regex_extractor.py)

El **contexto fuerte** son palabras como "a sólo", "de oferta", "antes", "ahorra", "c/u" o "paquete" cerca del número (`PATRON_CONTEXTO_PRECIO_FUERTE`). La palabra "puntos" cerca anula el contexto, y un año (2020-2029) nunca se lee como precio.

Desde el 24-oct-2026, un número de dígitos puros sin "$" se rechaza si mide menos de 1.3 veces la mediana del texto de la página (`ALTO_MIN_PRECIO_SIN_SIMBOLO`; un precio siempre es más grande que el texto) o si continúa un nombre (el "14" de "iPhone 14"). Hay dos excepciones: un rótulo de precio de la casilla encima ("PRECIAZO", "PRECIO BODEGA") o un "$" que el OCR leyó como bloque aparte, pegado a la izquierda.

### Precios partidos en dos bloques

Muchos folletos imprimen el precio con los centavos en superíndice ("$39⁹⁹"), y el OCR los lee como dos bloques. `_detectar_precios_fusionados` une un entero corto con un bloque de 2 dígitos más chico, a su derecha y alineado arriba (`_es_superindice_de`). Los centavos usados ya no cuentan como precio propio (antes salían "$90" y "$99" sueltos).

### Rótulos de casilla: mensualidades, anticipos, puntos y plazos

En varias tiendas la casilla trae, junto al precio grande, montos que **no** son el precio: la mensualidad de meses sin intereses, el anticipo para apartar, los puntos de lealtad o el plazo. El OCR suele leer el rótulo y su número en bloques separados; el rótulo ya es DESCARTE, y el número quedaba suelto y alguna regla lo volvía PRECIO. Los pre-pasos de `procesar_pagina` marcan esos números como DESCARTE antes de clasificar (y los excluyen de los precios fusionados):

| Función | Rótulo | Qué descarta | Ejemplo real |
|---|---|---|---|
| `_detectar_anticipos_apartado` | "Apartalo con" solo (`PATRON_ROTULO_APARTADO`) | El bloque con dígitos más pegado a su derecha, en la misma línea: el anticipo (10% del precio o $50 fijo) | Chedraui 428354: "Apartalo con" + "$59990" |
| `_detectar_montos_de_rotulo` con `PATRON_ROTULO_MSI` | "9MSI", "(12MsI\|", "I2MSI" | Igual: la mensualidad a la derecha | Chedraui: "9MSI" + "$77722" |
| `_detectar_cantidades_de_rotulo`, puntos | "puntos" (`PATRON_ROTULO_PUNTOS`) | Cantidad sin "$" a la izquierda o arriba, alto ≤ 2.5× el rótulo | Soriana Hiper 416269 p2: "CON \| 50 \| PUNTOS" salía como "$50 Zanahoria" |
| `_detectar_cantidades_de_rotulo`, plazo | "Meses sin intereses" partido (`PATRON_ROTULO_PLAZO`) | A la izquierda o arriba: un entero que es plazo usual (`MESES_MSI`) | Soriana Hiper 422326: "18" junto a "Meses sin" / "intereses" |
| `_detectar_cantidades_de_rotulo`, mensualidad | El mismo rótulo | A la derecha o abajo: cualquier monto de alto ≤ 2.5×, solo si hay un plazo suelto cerca | La mensualidad "$193.89" de esa misma insignia |

Tabla: Pre-pasos de rótulos de casilla (nlp/regex_extractor.py)

La geometría es la misma en todos: el número es el bloque más pegado al rótulo por cada lado, a una separación de −15 a 30 px a 1500 px de referencia (`GAP_ANTICIPO_MIN` y `GAP_ANTICIPO_MAX`), en la misma línea (centros alineados) o apilado (traslape de al menos la mitad del más angosto). El precio grande de la casilla mide 3× o más el rótulo y queda más lejos, así que no entra. Cuando el rótulo y el monto vienen en el mismo bloque ("9MSI|$1,44433)", "Apártalo con $629.90"), los atrapa `PATRONES_DESCARTE`; un precio real antes del rótulo ("$5,999 o 12 MSI de $499.92") se conserva como $5,999.

Los mismos rótulos también **confirman** precios. `_precio_por_cuotas` (paso 4b de `_clasificar`) resuelve el precio grande de Chedraui cuando el OCR leyó su "$" como 8/5/6/S: de las lecturas posibles de "S7995" ($7,995, $79.95...) elige la que cuadra con N × mensualidad o 10 × anticipo de los rótulos de la misma casilla (debajo del precio, a menos de 220 px y con traslape horizontal), con tolerancia de N centavos. En chedraui 428354 p8, "S7995" cuadra con el anticipo de $799.50, 9 × $888.33 y 12 × $666.25: es $7,995. El anticipo fijo de $50 (`ANTICIPO_MINIMO`) no confirma nada, porque lo traen igual juguetes de $429 y de $929. Si dos lecturas empatan en votos, no se decide.

Cifras de producción sin holdout, todas revisadas en imágenes por el agente de QA:

- 1838425 y 7fad080 (12-oct-2026): los anticipos y las mensualidades de Chedraui dejan de ser precio; con las mensualidades, 674 precios de Chedraui pasan a descarte, y en 530 de ellos N × monto cuadra con un precio de la página.
- 6d0670b (12-oct-2026): con los puntos y los plazos, 812 PRECIO dejan de serlo (soriana_hiper 486, soriana_mercado 220, la_comer 70, chedraui 26, heb 7), sin perder ningún precio real.
- 5823d76 (12-oct-2026): `_precio_por_cuotas` corrige 58 precios de Chedraui. Exigir dos rótulos a favor habría perdido 32 de ellos.

### Heurística de producto

Lo que no fue descarte, precio ni promoción y no está en el catálogo pasa por `_es_probable_producto`. Exige al menos 4 caracteres y una palabra alfabética de 3+ letras (quitando la puntuación que el OCR pega: "Suavitel?", "HUGGIES:"). Después basta cualquiera de estas condiciones:

- contiene una palabra de `KEYWORDS_PRODUCTO` (lámpara, aceite, detergente, leche, queso, pañal, botella, paquete... y unidades como kg, ml, lt, g, pza);
- está todo en mayúsculas y mide de 4 a 60 caracteres;
- es una sola palabra de 4+ letras ("Ciel", "Saba", "Tela": fragmentos de nombres que el OCR corta);
- tiene 2+ palabras y mide de 4 a 80 caracteres.

Es permisiva a propósito: el OCR parte los nombres en varios bloques y cada pedazo cuenta. Lo que no es producto se filtra antes, en los descartes; por eso las reglas de rótulos se agregaron a `PATRONES_DESCARTE` y no endureciendo esta función. Ojo: `_hay_producto_cerca`, el contexto que piden las reglas B-4 y B-5 de precio sin "$", usa esta misma heurística y el catálogo. **Cambiarla también cambia qué números se aceptan como precio.**

### Catálogo de categorías

`CATALOGO` (en `nlp/catalogo_productos.py`) tiene 20 categorías: 19 de producto y una de atributos técnicos. Cada una tiene `keywords` (tipos de producto) y algunas una lista opcional de `marcas`. Conteo con código al 26-oct-2026:

| Clave | Nombre | Keywords | Marcas |
|---|---|---|---|
| `linea_blanca` | Línea Blanca | 29 | — |
| `electronica` | Electrónica | 67 | 4 |
| `videojuegos` | Videojuegos | 20 | — |
| `pequenos_electrodomesticos` | Pequeños Electrodomésticos | 36 | — |
| `ropa` | Ropa y Calzado | 53 | — |
| `alimentos` | Alimentos y Bebidas | 200 | 14 |
| `frutas_verduras` | Frutas y Verduras | 61 | — |
| `limpieza` | Limpieza del Hogar | 50 | 8 |
| `cuidado_personal` | Cuidado Personal | 38 | 5 |
| `muebles_hogar` | Muebles y Hogar | 50 | — |
| `herramientas` | Herramientas | 23 | — |
| `juguetes` | Juguetes y Bebés | 18 | — |
| `deportes` | Deportes y Ejercicio | 15 | — |
| `mascotas` | Mascotas | 12 | — |
| `farmacia` | Farmacia y Salud | 18 | — |
| `optica` | Óptica | 7 | — |
| `papeleria` | Papelería y Útiles Escolares | 51 | — |
| `automotriz` | Automotriz | 25 | — |
| `motocicletas` | Motocicletas y Movilidad | 11 | — |
| `atributos_tecnicos` | Atributo Técnico | 57 | — |
| **Total** | | **841** | **31** |

Tabla: Categorías de CATALOGO con su número de palabras clave (contadas con len() el 26-oct-2026; incluye 5 repetidas dentro de su propia lista)

`buscar_categoria(texto)` devuelve `(encontrado, nombre de la categoría, es_atributo)` con estas reglas:

1. **Bordes de palabra.** Una keyword de 3 letras o menos exige palabra completa ("lg", "tv", "pc"). Las demás no pueden empezar a mitad de palabra, pero sí pegadas a un número, a un "de" pegado por el OCR ("DEPOLLO") o después de una letra basura al inicio ("IQUESO"). Las de `_PALABRA_COMPLETA` ("regio") tampoco pueden terminar a mitad de palabra: "REGIONAL" no es Regio.
2. **Gana la más larga, no la primera.** "camaron" gana a "cama", "frijol" a "refri", "crema dental" a "crema". En empate se respeta el orden del catálogo.
3. **Primero el tipo, después la marca** (pedido de la persona, 23-oct-2026; commit 9a1a450). Las marcas solo deciden si el texto no trae ningún tipo de producto: "Vaso Colgate" es Muebles y Hogar y "Colgate 100 ml" es Cuidado Personal.
4. **Criterio de atributo.** `es_atributo` es verdadero solo si la keyword ganadora es de `atributos_tecnicos` ("quemadores", "pantalla ips", "watts", "recargable", "zoom óptico"...); entonces `_clasificar` marca el bloque como ATRIBUTO en vez de PRODUCTO. Como gana la más larga, "Pantalla IPS" es atributo pero "Pantalla" sola es Electrónica. Una marca nunca es atributo.

La categoría que se guarda en la entidad es el nombre legible ("Alimentos y Bebidas"). El normalizador la convierte a la clave con `_NOMBRE_A_SLUG`, y "Frutas y Verduras" se mapea a `alimentos`. Con el commit 9a1a450, los precios sin categoría en producción bajaron de 61.4% a 56.3% y la categoría del evaluador en dev subió de 52.0 a 55.1.

### Normalización del nombre

`Normalizador.normalizar` busca el nombre canónico del producto en tres pasos y deja constancia del método:

| Método | Cuándo | Umbral |
|---|---|---|
| `exacto` | El texto (o un alias) está en `CATALOGO_CANONICO` | — |
| `fuzzy` | Coincidencia aproximada (rapidfuzz) alta | ≥ 0.80 (`UMBRAL_ALTO`) |
| `fuzzy_bajo` | Coincidencia aproximada aceptable | ≥ 0.60 (`UMBRAL_BAJO`) |
| `heuristico` | Sin coincidencia: se usa el texto del folleto | hasta 150 caracteres |
| `sin_match` | Basura o vacío: se descarta | — |

Tabla: Métodos del normalizador (nlp/normalizador.py)

El recorrido completo es este:

```
texto del producto
   ├─ PATRONES_BASURA ............................. → sin_match (descartado)
   ├─ _extraer_marca (MARCAS_CONOCIDAS)
   ├─ _limpiar: CORRECCIONES_OCR y unidades
   ├─ _normalizar_base: minúsculas, sin acentos ni puntuación
   ├─ ¿igual a un nombre o alias? ................. → exacto
   ├─ fuzzy token_set_ratio ≥ 60, largo ≥ 0.2 y cobertura → fuzzy / fuzzy_bajo
   ├─ ¿más de 150 caracteres? ..................... → sin_match (descartado)
   └─ texto del folleto capitalizado + categoría del catálogo → heuristico
```

**`CATALOGO_CANONICO`** tiene 104 nombres canónicos con 248 alias (352 entradas de búsqueda), cada uno con su categoría: alimentos 64, cuidado personal 8, limpieza 7, línea blanca 5, electrónica 5, ropa 5, pequeños electrodomésticos 4, videojuegos 4 y mascotas 2. Ejemplo: "Plátano" con los alias "platano", "pltano", "platano macho" y "plátanos".

**Correcciones OCR.** El normalizador tiene sus propias 19 `CORRECCIONES_OCR`: 11 palabras mal leídas ("pltano" → "plátano", "cebolca" → "cebolla", "cerzeva" → "cerveza", "xampoo" → "shampoo", "labadera" → "lavadora", "refri" → "refrigerador"...) y 8 unidades normalizadas ("2 kgs" → "2 kg", "1 litro" → "1 l", "500 grs" → "500 g", "pzs" → "pza").

**`PATRONES_BASURA`** (10) descartan el texto antes de buscar: solo números, 1-3 letras, "del videojuego", "en tienda/línea", "visita tu tienda", "en mancuernas", "en línea de", "noincluye", "precio bajo/especial" y cantidades solas como "12 pzs".

**Marca.** `_extraer_marca` busca cada una de las 84 `MARCAS_CONOCIDAS` con borde de palabra (`_patron_marca`), de la más larga a la más corta: las de 4 letras o menos y "modelo" como palabra completa (se acepta un número pegado), y las demás sin empezar a mitad de palabra salvo una letra basura del OCR ("CMaruchan") y con lo que sea pegado al final ("Pinols", "ARIEL1.8"). Hasta el 26-oct-2026 era subcadena y 4,711 PRODUCTO de producción tenían una marca falsa ("Ace" en "Aceite", "Sol" en "solo", "Lg" en "algodón", "Roma" en "aroma"). La devuelve capitalizada y la devuelve capitalizada ("Golden Hills"). Ese valor va a `productos_canonicos.marca`. Entre marcas del mismo largo, el desempate depende del orden de un `set`; por eso el evaluador se relanza solo con `PYTHONHASHSEED=0` para que dos corridas iguales den lo mismo.

**Regla de cobertura del fuzzy (commit ecbaa5d, 11-oct-2026).** `token_set_ratio` da 100 si *un* token del texto está en el catálogo ("Salsa Chamoy" → Salsa, "Audífonos Vibe Beam 2 negro" → Audifonos) y premia parecidos de letras sin palabras en común ("MORENA" → Mayonesa, "res para asar" → Pasta para sopa, "Figura" → FIFA). Ahora el fuzzy solo se acepta si `_canonico_cubre_texto`: cada palabra significativa del texto (3+ letras, sin conectores ni unidades) aparece en el alias o en el canónico, igual o con un error OCR leve:

- `fuzz.ratio` ≥ 85 (`FUZZY_TOKEN_COBERTURA`): "pechuca" ~ "pechuga";
- o, en palabras de 6+ letras (`LARGO_MINIMO_LEVENSHTEIN`), Levenshtein normalizado ≥ 0.78 (`LEVENSHTEIN_COBERTURA`): "Acondklonador" ~ "acondicionador", "Oexaca" ~ "oaxaca".

Si no lo cubre, se conserva el texto del folleto como `heuristico`. Los umbrales no se bajan por estas razones: con 80 (Indel), "Milanesa" vuelve a ser Mayonesa; con 0.75, "Refritos" vuelve a ser Refresco; y en palabras de 4-5 letras una letra distinta ya es otro producto ("jabon" ~ "jamon", "popa" ~ "papa"). La guarda no se aplica si el heurístico pasaría de 150 caracteres, para que nunca cambie qué bloques se aceptan como producto.

Resultado en dev: precisión 7.1 → 10.6, recall 6.8 → 10.2, F1 7.0 → 10.4 (+53 / −1 artículos) y categoría 44.0% → 47.7%. Costo aceptado: 7 artículos pasan de un canónico correcto a texto OCR ilegible ("Papcl Hlgienko", "Gaxesas", "Jazatun") y los nombres sucios del dashboard en dev subieron de 379 a 613 de 1,488.

**`LARGO_MAXIMO_HEURISTICO` = 150** es el largo de `productos_canonicos.nombre_canonico` (VARCHAR(150)). Un texto más largo es letra chica (sucursales, vigencias): no es producto y además no cabe. Antes del commit 12487e0 (8-oct-2026) desbordaba la columna, y en la recarga de octubre de 2026 hizo rollback de 13 folletos completos.

## Reglas y decisiones

Las decisiones importantes y por qué se tomaron:

- **El "$" leído como dígito necesita la escala de la página.** "879"+"99" es $79.99 en merco, pero "544"+"90" es $544.90 en casa_ley. Ni el ancho ni la confianza separan los dos casos; lo que sí los separa es el primer dígito de los demás números del mismo tamaño en la página. Por eso `PATRON_ENTERO_FUSION` no acepta "$" + 3 dígitos y la regla A-escala exige que toda la página use esa forma (commits 43e4040 y 6865f14; Engram #253, #265 y #266).
- **El filtro por altura se calibró sin perder precios reales.** El diagnóstico de las 360 páginas que el filtro deja sin precio (25-oct-2026) dio 42 de 50 sin precios reales y ninguna con precios sin "$" quitados por el filtro (Engram #263).
- **Los centavos pegados se protegen con la casilla.** La primera versión dividía entre 100 nueve precios reales (moto $65,999 → $659.99). La guarda `_entero_confirmado` los protege a los nueve sin tocar los demás (Engram #275).
- **Campañas con slug canónico.** Antes el texto completo se guardaba como campaña (45 variantes de "julio regalado"); ahora `slug_evento` devuelve uno de los slugs de `CAMPANAS_EVENTO` y excluye lemas y letra chica (commit 85e9e95).
- **Los rótulos se descartan anclados al bloque completo.** Así no tocan ninguna regla de precio, y un nombre real que contiene la palabra ("Súper Value", "Hasta 35 horas de batería") no se pierde (commits c468950 y 2f616c3).
- **La promo débil exige un precio en la página y la fuerte no** (commit ea1fe82): ver "Promociones".
- **El NLP entrega candidatos y load decide.** El precio anterior no se resuelve con el texto solo; se resuelve con el precio actual emparejado (commit 7819d24).
- **El fuzzy solo vale si explica todo el texto** (commit ecbaa5d): un nombre del folleto fiel es mejor que un canónico equivocado.
- **Se descartó spaCy como extractor principal.** El experimento NER quedó documentado en `sources/nlp/05_experimento_spacy_ner.md` y `06_viabilidad_ner_custom.docx`; las reglas con geometría resultaron más controlables y medibles con el evaluador.

Cada regla nueva se mide con el evaluador (dev completo) y la revisa el agente de QA antes del commit (skill `ciclo-experimento`; las reglas de precio siguen además la skill `regex-precio-checklist`).

## Configuración

| Constante | Valor | Para qué |
|---|---|---|
| `CONFIANZA_MINIMA` | 0.15 | Bloques con menos confianza OCR se ignoran |
| `ANCHO_REFERENCIA_UMBRALES` | 1500 px | Ancho con el que se calibraron las distancias |
| `DISTANCIA_MAX_CONTEXTO_PRECIO` | 220 px | Radio para buscar contexto de precio |
| `ALTO_MIN_PRECIO_SIN_SIMBOLO` | 1.3 | Un precio sin "$" mide al menos 1.3× la mediana del texto |
| `ALTO_MAX_CENTAVOS_VS_ENTERO` | 0.75 | Tamaño máximo del superíndice respecto al entero |
| `MESES_MSI` | 3, 6, 9, 12, 15, 18, 24 | Plazos válidos para confirmar un precio por su mensualidad |
| `GAP_ANTICIPO_MIN` / `GAP_ANTICIPO_MAX` | −15 / 30 px | Separación entre un rótulo y su monto o cantidad |
| `ALTO_MAX_ANTICIPO_VS_ROTULO` / `ALTO_MAX_CANTIDAD_VS_ROTULO` | 2.5 / 2.5 | Alto máximo del monto respecto a su rótulo |
| `ANTICIPO_MINIMO` | $50 | Anticipo fijo que no confirma ningún precio |
| `UMBRAL_ALTO` / `UMBRAL_BAJO` | 0.80 / 0.60 | Similitud mínima del normalizador |
| `RATIO_LONGITUD_MINIMO` | 0.2 | Largo mínimo del texto respecto al alias en un fuzzy |
| `FUZZY_TOKEN_COBERTURA` / `LEVENSHTEIN_COBERTURA` | 85 / 0.78 | Tolerancia OCR por palabra en la regla de cobertura |
| `LARGO_MAXIMO_HEURISTICO` | 150 | Largo máximo de un nombre heurístico (= VARCHAR(150) de la BD) |
| `DESCUENTO_MIN` / `DESCUENTO_MAX` (en `load/load.py`) | 0.03 / 0.50 | Descuento creíble para elegir el candidato del precio anterior |

Tabla: Constantes principales del módulo NLP

## Cómo correrlo

### probar_nlp.py

Se corre desde la raíz del repo, porque las rutas (`data/processed`, `logs/nlp.log`) son relativas:

```
venv/Scripts/python.exe probar_nlp.py
```

El menú tiene dos modos:

- **1 · Modo prueba.** Lista las carpetas que tienen `ocr_resultado.json`, con su estado ("procesado" o "pendiente"). Procesa la carpeta elegida **aunque ya tenga** `nlp_resultado.json` (lo sobrescribe), imprime la clasificación de cada página y el resumen del folleto, y avisa si la tasa útil queda por debajo de 30%.
- **2 · Modo batch.** Procesa solo los folletos **sin** `nlp_resultado.json` y pide confirmación antes de empezar. No rehace los que ya existen: no sirve para reprocesar después de cambiar una regla.

El registro queda en `logs/nlp.log` (rota a los 5 MB, guarda 5 archivos).

Los dos modos solo listan las carpetas de producción (`carpetas_con_ocr()`: `tiendeo/` y `ofertomat/`, 821 folletos al 26-oct-2026). Hasta el 26-oct-2026 recorrían todo `data/processed/`, que también guarda experimentos (`_v2_C_tesseract_perfiles/`...) y respaldos (`tiendeo_anterior_2026-10-06/`): 1,463 `ocr_resultado.json` en total.

Para **reprocesar producción** después de un cambio aprobado usa `python recargar_bd.py nlp` (o `todo`, que además respalda y recarga la BD; ver `05_load.md`). Por dentro llama a `procesar_carpeta` con `forzar=True` sobre `carpetas_con_ocr()`. Ojo: `procesar_carpeta` calcula `carpeta.relative_to(Path("data/processed"))`, así que necesita rutas **relativas** a la raíz del repo. Con una ruta absoluta falla con `ValueError` en todos los folletos sin escribir nada (Engram #227):

```
from pathlib import Path
from nlp.regex_extractor import RegexExtractor
from probar_nlp import procesar_carpeta

ex = RegexExtractor()
for fuente in ("tiendeo", "ofertomat"):
    for ocr in Path("data/processed", fuente).rglob("ocr_resultado.json"):   # ruta relativa
        procesar_carpeta(ocr.parent, ex, forzar=True)
```

Reprocesar sobrescribe los JSON que están cargados en la base de datos. Lo decide la persona, con respaldo previo, y después hay que recargar la BD con load (ver `05_load.md`).

### Medir un cambio con el evaluador

Un cambio del NLP no se mide reprocesando: se mide **en memoria**. `nlp/salida_json.py` separa la construcción del JSON de la escritura en disco, y el evaluador la reutiliza. Con `--nlp memoria`, `FuentePipeline` (en `evaluador/pipeline.py`) toma el `ocr_resultado.json` de cada página del ground truth, llama a `resultado_nlp(ocr, clasificar_paginas_ocr(ocr, RegexExtractor()))` con el código actual, aplica la misma asociación de load y compara los registros contra el ground truth sin escribir nada en `data/processed/<fuente>/`. Con `--nlp disco` lee los `nlp_resultado.json` que están cargados en la BD.

```
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria        # base, ANTES de editar
# ... cambio en nlp/ + pruebas en tests/ ...
venv/Scripts/python.exe -m pytest tests -q
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria        # nueva
venv/Scripts/python.exe -m evaluador comparar <base.json> <nueva.json> --casos
```

Las corridas se guardan en `data/processed/_eval/runs/`. Un cambio se mantiene solo si la precisión sube, el recall no baja, el F1 sube y no hay regresiones por tienda que bloqueen. Se reportan los artículos ganados y los perdidos (por ejemplo "+53 / −1"), no solo el neto. El protocolo completo (diagnóstico, regresiones, registro en Engram, revisión de QA) está en la skill `ciclo-experimento`; el holdout no se usa para iterar.

## Pruebas

Las reglas tienen pruebas unitarias con cajas reales de folletos en `tests/`:

- Reglas de precio: `test_regex_precio_espurio.py`, `test_regex_precio_espurio_miles.py`, `test_regex_precio_fusionado.py`, `test_regex_precio_bare_alto.py`, `test_regex_precio_signo_suelto.py`, `test_regex_precio_digito_signo_escala.py`, `test_regex_precio_centavos_pegados.py`, `test_regex_precio_centavos_pegados_guarda.py`, `test_regex_centavos_consumidos.py`, `test_regex_precio_cuotas.py`.
- Rótulos y promociones: `test_regex_rotulos_casilla.py`, `test_regex_rotulos_promo.py`, `test_regex_mensualidad_msi.py`, `test_regex_anticipo_apartado.py`, `test_regex_cantidades_rotulo.py`, `test_eventos_campania.py`.
- Catálogo y normalizador: `test_catalogo_productos.py`, `test_normalizador_cobertura.py`.

`test_eventos_campania.py` fija las campañas que sí y las que no (con textos reales de producción); `test_catalogo_productos.py`, la prioridad del tipo sobre la marca y los bordes de palabra; y `test_normalizador_cobertura.py`, los falsos amigos que la regla de cobertura debe seguir rechazando ("MORENA", "Milanesa", "Refritos", "Jabón").

```
venv/Scripts/python.exe -m pytest tests -q                      # suite completa (1,349 pruebas al 26-oct-2026)
venv/Scripts/python.exe -m evaluador correr --split dev --nlp memoria   # calidad del pipeline contra el ground truth
```

Los archivos `tests/_herramienta_*.py` no son pruebas: son scripts de medición de los agentes y pytest no los recoge.

Calidad en dev al 26-oct-2026 (corrida limpia `20261026_115424`, commit 398c4e4; la del 25-oct `20261025_224754` da lo mismo): precisión 33.1%, recall 24.7%, F1 28.3%, medida sobre registros completos producto + precio. En esa corrida el error más frecuente vuelve a ser la lectura del precio: entre los registros con error, `precio_mal_leido` suma 321 y `asociacion_producto` (módulo load) 287, seguidos de `precio_huerfano` con 133. Contados por artículo del ground truth, son 420 y 356, más 300 de `clasificacion` (archivo `data/processed/_eval/runs/20261026_115424_398c4e4_dev.json`, NLP en memoria, sin cambios sin commit).

## Limitaciones conocidas y pendientes

- **alsuper sin "$"**: el primer dígito de los centavos se pega al precio ("699" es $69.90 y sale $99); en la muestra de QA solo 1 de 6 salió bien.
- **"550 mg"** de cajas de analgésicos se lee como $50.
- **"$ddd" de soriana** ("$780" = $7.80) sigue sin dividirse, porque "$379" también puede ser un precio real.
- **Centavos sueltos restantes** (~390) junto a enteros de 3 dígitos o enteros que el OCR deformó.
- **"AHORRA $25 por cada $100"** de heb se lee como un precio de $25.
- **"30 Aniversario"** de peluches Pokémon en chedraui 431870 y 431871 sale como campaña `aniversario` (Engram #227).
- **Marcas cortas con basura pegada**: con el borde de palabra del 26-oct-2026, unas 30 marcas reales de 4 letras o menos dejan de detectarse cuando el OCR les pega una letra ("Lalao", "Doveo"). Es el costo de no marcar "Aceite" como "Ace".
- **Letra basura al inicio en el catálogo**: la tolerancia que acepta "IQUESO" atrapaba palabras reales ("Apollo" → pollo, "operativo" → pera, "toreo" → oreo, "soledad" → oled). Desde el 26-oct-2026 `_NO_SON_PRODUCTO` las excluye (68 categorías falsas menos en producción); la regla se mantiene porque acierta en la mayoría de sus 680 casos (`tests/_herramienta_doc_letra_inicial.py`). Otras palabras así pueden aparecer con folletos nuevos.
- **Nombres ilegibles**: desde la regla de cobertura, el texto OCR sucio se conserva como heurístico en vez de forzar un canónico ("Papcl Hlgienko"). Se ataca al aceptar el bloque como producto o en el OCR.
- **Rótulos**: unos 40 fragmentos de nombres reales se descartan como rótulo ("Super" de "Arroz Super Extra Ley"). Riesgos sin casos en el corpus, fijados en pruebas: un precio sin "$" pequeño junto a "puntos" sin cantidad legible, y una cuota de la casilla de abajo que cuadre por azar con `_precio_por_cuotas`.

## Historial

La primera versión (julio de 2026) clasificaba con regex simples y un catálogo de palabras clave (`sources/nlp/01_modulo_nlp.docx`); la v3 agregó el catálogo canónico (`02_modulo_nlp_v3_catalogo.docx`). En julio y agosto se agregaron la promo que exige precio (`03_promo_requiere_precio_en_pagina.md`) y las reglas de precio sin "$" B-2 a B-5 (`04_cobertura_bare_digits_2_5.md`). Desde octubre de 2026 las reglas usan la geometría de la página y se validan con el evaluador; su historia detallada está en los mensajes de commit (`git log -- nlp/`) y en Engram (proyecto `pricescraper_ss`, temas `experimentos/producto/*` y `experimentos/qa/*`).
