# Módulo Web Scraping

El módulo de web scraping es el primer eslabón del pipeline. Navega Tiendeo.com.mx y Ofertomat.mx con un navegador Chromium controlado por Playwright, encuentra los folletos vigentes de cada tienda, captura las URLs de sus páginas en el CDN de cada plataforma y las descarga como imágenes en el datalake local (`data/raw/`). Lleva además un registro de lo ya descargado para que cada corrida solo baje lo nuevo.

## Propósito y alcance

Las dos plataformas muestran los folletos en un visor que se arma con JavaScript: el HTML inicial no trae las imágenes de las páginas, y estas solo se piden al CDN cuando el visor las muestra. Por eso el scraper usa un navegador real y escucha las peticiones de red en lugar de leer el HTML.

| Hace | No hace |
|---|---|
| Listar los folletos de cada tienda con su título y vigencia (fecha de inicio y fin) | Leer el texto de las imágenes (vision) |
| Capturar las URLs de todas las páginas de un folleto y descargarlas | Clasificar precios y productos (nlp) |
| Guardar las páginas en `data/raw/<fuente>/<tienda>/<folleto_id>/` | Cargar nada a PostgreSQL (load) |
| Registrar cada folleto descargado en `data/registro_folletos_scrapeados.json` | Revisar si el folleto descargado es de la tienda correcta (eso se hizo a mano; ver Limitaciones) |

Tabla: Alcance del módulo Web Scraping

## Entradas y salidas

**Entrada:** las URLs de las páginas de cada tienda, fijas en el código: el diccionario `TIENDAS` de `scraper/sources/tiendeo.py` (16 cadenas) y el de `scraper/sources/ofertomat.py` (16 cadenas, de las que solo se recorren las 4 de `TIENDAS_UNICAS`). No hay archivo de configuración: agregar una tienda es agregar una línea a ese diccionario.

**Salida 1: las imágenes (datalake crudo).** Una carpeta por folleto con sus páginas numeradas en orden. Estructura real al 26-oct-2026 (recortada):

```
data/
├── registro_folletos_scrapeados.json      ← registro acumulativo (salida 2)
├── folletos_tiendeo_bodega-aurrera.json   ← listado de la última corrida de una tienda (salida 3)
└── raw/
    ├── tiendeo/                           ← 16 carpetas de tienda, 813 folletos, 5,848 páginas
    │   ├── merco/
    │   │   └── 433552/
    │   │       ├── pagina_001.webp
    │   │       └── pagina_002.webp
    │   ├── sam's_club/ ...
    │   └── soriana_hiper/
    │       └── 430899/  pagina_001.webp … pagina_061.webp   ← el folleto más largo
    ├── ofertomat/                         ← 4 carpetas de tienda, 39 folletos, 74 páginas
    │   ├── 7_eleven/
    │   │   └── 136018/  pagina_001.webp … pagina_007.webp
    │   ├── arteli/  calimax/  walmart_express/
    └── _revision_manual/                  ← no lo escribe el scraper (ver abajo)
```

El nombre de la carpeta de tienda sale del nombre que muestra la plataforma, normalizado por `normalizar_nombre` (`scraper/downloader.py`): sin acentos, en minúsculas y con `_` en lugar de espacios. Por eso "Soriana Híper" queda como `soriana_hiper`, "Sam's Club" como `sam's_club` (el apóstrofo se conserva) y "7 Eleven" como `7_eleven`. Si la tarjeta no trae tienda, la carpeta es `desconocidos` (hoy no existe ninguna).

`data/raw/_revision_manual/` no es salida del scraper: guarda el etiquetado manual (`<folleto>_contenido.json`) que el evaluador usa como ground truth (`evaluador/gt.py`, `RAIZ_GT`).

**Salida 2: el registro.** `data/registro_folletos_scrapeados.json` es un diccionario cuya clave es `fuente:folleto_id`. Lo escribe `Registro.marcar_procesado` (`scraper/registro.py`) cada vez que termina un folleto. Dos entradas reales:

```
"tiendeo:433552": {
  "fuente": "tiendeo", "folleto_id": "433552",
  "procesado_at": "2026-10-25T19:41:59.410596",
  "tienda": "Merco", "titulo": "Más cerca de ti",
  "fecha_inicio": "2026-10-23", "fecha_fin": "2026-10-29",
  "url_folleto": "https://www.tiendeo.mx/Catalogos/433552"
},
"ofertomat:136018": {
  "fuente": "ofertomat", "folleto_id": "136018",
  "procesado_at": "2026-08-04T11:31:00.335289",
  "tienda": "7 Eleven",
  "titulo": "Vista previa las ofertas de la tienda 7-Eleven - 7-Eleven folleto desde el 30/07/2026",
  "fecha_inicio": "2026-07-30", "fecha_fin": "2026-08-26",
  "url_folleto": "https://www.ofertomat.mx/7-eleven/7-eleven-folleto-desde-jueves-30-07-2026-136018/"
}
```

`procesado_at` es el momento de la descarga, no el del OCR. El campo `url_folleto` existe desde el commit af787c4 (29-jul-2026): de las 883 entradas, 347 son anteriores y no lo tienen.

**Salida 3: el listado de la última corrida.** `data/folletos_tiendeo_<slug>.json` o `data/folletos_ofertomat_<slug>.json`: la lista de folletos que se vio en el sitio, con `url_preview` incluida. Se sobrescribe en cada corrida y solo la generan los flujos de una sola tienda (`scrapear_tiendeo`, `scrapear_ofertomat`), no el rastreo completo. Hoy solo existe `folletos_tiendeo_bodega-aurrera.json` (9-sep-2026). Ningún otro módulo lo lee.

**Salida 4: el log.** `logs/scraper.log`, con rotación a 5 MB y 5 respaldos (`RotatingFileHandler` en `probar_scraper.py`).

**Quién consume estas salidas y qué se rompe si cambian:**

| Consumidor | Qué lee | Qué se rompe si cambia |
|---|---|---|
| `probar_vision.py` y `catchup_tiendeo.py` | Carpetas de `data/raw/` que contienen `pagina_*.webp` (búsqueda recursiva con `rglob`) | Si las páginas no se llaman `pagina_NNN.webp`, la visión no las ve |
| `load/load.py` (`Loader._leer_metadata`, constante `RUTA_REGISTRO_SCRAPER`) | La entrada `fuente:folleto_id` del registro: `titulo`, `fecha_inicio`, `fecha_fin`, `procesado_at` (→ `scrapeado_at`) y `url_folleto` (→ `url_origen`) | Si cambian las claves o la ruta del registro, la tabla `folletos` queda sin vigencia ni título |
| Estructura `<fuente>/<tienda>/<folleto_id>` | `data/processed/` replica la misma ruta; load toma de ahí la fuente, la tienda y el id | Cambiar la jerarquía desconecta raw, processed y la BD |

Tabla: Consumidores de las salidas del scraper

## Archivos y responsabilidades

| Archivo | Responsabilidad | Piezas clave |
|---|---|---|
| `scraper/metodos_scraper.py` | Clase base abstracta: navegador, medidas anti-bot, reintentos, retardos y scroll | `BaseScraper` (`iniciar`, `cerrar`, `_navegar`, `reintentar`, `_delay_aleatorio`, `_scroll_hasta_abajo`; abstractos `obtener_folletos` y `obtener_paginas_folleto`), `USER_AGENTS` |
| `scraper/sources/tiendeo.py` | Adaptador de Tiendeo: listado por tienda y páginas por bloques `flyerPage` | `TiendeoScraper` (`scrapear_tienda`, `_parsear_tarjetas`, `obtener_paginas_folleto`, `_capturar_bloque`, `_filtrar_por_publication_id`, `_extraer_desde_dom`, `_ordenar_paginas`, `_extraer_fechas`, `_extraer_fechas_detalle`), `TIENDAS`, `MAX_PAGINAS`, `PAGINAS_POR_BLOQUE`, `PATRON_PUBLICATION_ID` |
| `scraper/sources/ofertomat.py` | Adaptador de Ofertomat: listado y páginas navegando `?page=N` | `OfertomatScraper` (`_navegar` propio, `scrapear_tienda`, `obtener_paginas_folleto`, `obtener_fechas_detalle`, `_extraer_fechas_url`), `TIENDAS`, `TIENDAS_UNICAS`, `PALABRAS_BASURA`, `_ES_PAGINA_CDN` |
| `scraper/downloader.py` | Descarga asíncrona de las imágenes y rutas del datalake | `Downloader` (`descargar_paginas`, `_descargar_una`, `HEADERS`, `REFERERS`), `ruta_folleto`, `normalizar_nombre`, `DATA_RAW` |
| `scraper/registro.py` | Registro persistente de folletos descargados | `Registro` (`ya_procesado`, `marcar_procesado`, `total_procesados`, `listar`), `RUTA_REGISTRO` |
| `probar_scraper.py` | Orquestador de consola: menú, rastreo por tienda o completo, vigencia de respaldo y log | `scrapear_tiendeo`, `scrapear_tiendeo_todas_tiendas`, `scrapear_ofertomat`, `scrapear_ofertomat_todas_tiendas`, `main` |
| `catchup_tiendeo.py` | No hace scraping: corre OCR y NLP sobre lo que el scraper dejó pendiente (paso siguiente del pipeline) | `catchup_vision`, `catchup_nlp`, `FUENTES` |

Tabla: Archivos del módulo Web Scraping

## Cómo funciona

### Flujo de una corrida

```
probar_scraper.py  (menú: 1 Tiendeo · 2 Ofertomat · 3 ambas)
   │
   ├─ Registro()                      carga data/registro_folletos_scrapeados.json
   │
   ├─ por cada tienda  (pausa aleatoria de 3 a 8 s entre tiendas)
   │     ├─ scraper.scrapear_tienda(slug)          → lista de folletos (tarjetas del listado)
   │     ├─ registro.ya_procesado(...)              → se quedan solo los nuevos
   │     │
   │     └─ por cada folleto nuevo  (un navegador nuevo por folleto)
   │           ├─ scraper.obtener_paginas_folleto(url)   → URLs de las páginas en el CDN
   │           ├─ vigencia de respaldo desde la página de detalle, si el listado no la trajo
   │           ├─ Downloader.descargar_paginas(...)      → data/raw/<fuente>/<tienda>/<id>/pagina_NNN.webp
   │           └─ registro.marcar_procesado(...)         → se guarda el registro en disco
   │
   └─ logs/scraper.log
```

Un error en una tienda o en un folleto se registra en el log y la corrida sigue con el siguiente (en los flujos de rastreo completo). Cada folleto abre y cierra su propio navegador (`async with TiendeoScraper(...)`), así que un visor que se cuelga no contamina al siguiente.

### Patrón adaptador

`BaseScraper` concentra todo lo que es igual en las dos fuentes y declara dos métodos abstractos que cada adaptador implementa a su manera:

- `obtener_folletos(categoria_url)`: devuelve una lista de diccionarios con `fuente`, `folleto_id`, `tienda`, `titulo`, `url_folleto`, `url_preview`, `fecha_inicio` y `fecha_fin`.
- `obtener_paginas_folleto(url_folleto)`: devuelve las URLs de las imágenes, ordenadas por página.

Si cambia el HTML de una plataforma, solo se toca su adaptador. Para agregar una tercera fuente hay que crear `scraper/sources/<fuente>.py` con una clase que herede de `BaseScraper`, agregar su `Referer` en `Downloader.REFERERS` y su flujo en `probar_scraper.py`.

### Medidas anti-bot y de fiabilidad

| Medida | Dónde | Detalle |
|---|---|---|
| Rotación de User-Agent | `USER_AGENTS`, `BaseScraper.iniciar` | 4 perfiles (Chrome Windows, Chrome macOS, Firefox Windows, Chrome Linux); se elige uno al azar por navegador |
| Ocultar la automatización | `BaseScraper.iniciar` | Argumento `--disable-blink-features=AutomationControlled` y script que deja `navigator.webdriver` como `undefined` |
| Navegador "normal" | `BaseScraper.iniciar` | Ventana de 1366×768 y `locale="es-MX"` |
| Retardo aleatorio tras cada navegación | `_delay_aleatorio` | Entre `delay_min` = 1.5 s y `delay_max` = 3.5 s (`random.uniform`) |
| Pausa entre tiendas | `scrapear_*_todas_tiendas` | Entre 3 y 8 s |
| Pocas descargas simultáneas | `Downloader(max_concurrentes=2)` en `probar_scraper.py` | Semáforo de `asyncio`; el valor por defecto de la clase es 3 |
| `Referer` de la plataforma | `Downloader.REFERERS`, `_headers_para` | Las imágenes se piden como si vinieran del sitio de la fuente |
| Reintentos | `BaseScraper.reintentar` | 3 intentos con 5 s de espera (2 intentos en los bloques de Tiendeo y en las páginas de Ofertomat) |
| Scroll gradual | `_scroll_hasta_abajo` | Baja en pasos proporcionales con pausas de 0.8 s para que cargue el contenido diferido (12 pasos en Tiendeo, 4 en Ofertomat) |

Tabla: Medidas anti-bot y de fiabilidad del scraper

### Tiendeo: listado de folletos

`scrapear_tienda(slug)` abre la página de la tienda (`TIENDAS[slug]`), hace 12 pasos de scroll y `_parsear_tarjetas` recorre los enlaces `a[href*='/Catalogos/']`. De cada tarjeta, `_extraer_datos_tarjeta` saca:

- `folleto_id`: el número de `/Catalogos/<id>`; la URL del folleto se normaliza a `https://www.tiendeo.mx/Catalogos/<id>`.
- `tienda` y `titulo`: los textos de `h4` y `h3` de la tarjeta (o de su contenedor `js-flyer` en la tarjeta destacada).
- Vigencia: `_extraer_fechas` la lee del `alt` de la imagen ("2024-06-01T... - 2024-06-30T...").

Cada página de tienda trae, además de sus folletos, un widget de "recomendados" con tarjetas de otras cadenas. Por eso se descarta toda tarjeta cuya tienda, normalizada con `_normalizar_comparacion`, no coincida con el slug pedido ("Soriana Híper" y `soriana-hiper` dan ambos `sorianahiper`). Al final se eliminan los duplicados por URL.

### Tiendeo: páginas del folleto por bloques `flyerPage`

Tiendeo usa el visor de Shopfully. Las imágenes viven en `es-mx-media-publications.shopfully.cloud` con el patrón `/publications/page_assets/<publication_id>/<num_pagina>/page_<n>_level_<nivel>_<hash>.webp`; el hash no se puede predecir, así que hay que dejar que el visor las pida. Además, el visor solo pide las páginas cercanas a la que muestra. `obtener_paginas_folleto` abre el folleto en bloques:

```
flyerPage=1  → captura ~5 páginas
flyerPage=6  → captura las siguientes
flyerPage=11 → ...                      (avanza de PAGINAS_POR_BLOQUE = 5 en 5, hasta MAX_PAGINAS = 60)
se detiene cuando un bloque no trae páginas o no trae ninguna nueva
```

Ejemplo real del log (25-oct-2026, folleto 433553 de Merco): el bloque 1 captura 2 páginas, el bloque 6 no trae ninguna nueva y el folleto termina con 2 páginas. Cada bloque tarda de 10 a 13 s.

Dentro de cada bloque, `_capturar_bloque`:

1. Registra un listener pasivo `page.on("request")` que guarda toda petición de imagen (`.webp`, `.jpg`, `.jpeg`, `.png`) cuya URL contenga `publications/page_assets`, `page_level`, `_level_1_` o `_level_2_`.
2. Navega con `wait_until="networkidle"`. En el primer bloque lee el `publication_id` del visor directamente del HTML (`_publication_id`): el del folleto real aparece antes que el del widget de recomendados. En ese mismo HTML lee la vigencia de la barra de título (`_extraer_fechas_detalle`, formato "(DD/MM/YY - DD/MM/YY)") y la deja en `self.fechas_fallback`.
3. Espera hasta 2.5 s; si no hubo redirección, hace scroll dentro del visor (`_scroll_visor`) y espera 1.5 s más.
4. Si el sitio redirige a otro folleto (listener `framenavigated`), descarta las URLs capturadas después de la redirección.
5. `_filtrar_por_publication_id` se queda solo con las URLs del `publication_id` del folleto y descarta las de otros folletos (miniaturas del widget). Si todavía no conoce el id, elige el grupo con más URLs y, en empate, el que tenga `_level_4_`.
6. Si el listener no capturó nada en el primer bloque, `_extraer_desde_dom` busca las URLs en el HTML (`src`, `data-src`, `data-lazy-src`, `srcset` y una expresión regular).

Al final, `_ordenar_paginas` ordena por el número de página de la URL. Si hay URLs `level_2`, devuelve solo esas.

### Ofertomat: listado y páginas

`scrapear_tienda(slug)` abre `https://www.ofertomat.mx/<slug>/`. `_parsear_tarjetas` toma los enlaces que terminan en un id de 5 o más dígitos (`-(\d{5,})/`), que empiezan con `/<slug>/` y cuyo texto no contiene ninguna de las `PALABRAS_BASURA` (logos, redes sociales, botones). La tienda sale del primer segmento de la URL (`/7-eleven/...` → "7 Eleven"), el título del `alt` de la imagen y la fecha de inicio de la URL (`_extraer_fechas_url`: `desde-jueves-30-07-2026` → 2026-07-30). Ofertomat no publica la fecha de fin en el listado.

Ofertomat redefine `_navegar`: espera por defecto `domcontentloaded` más 3 s fijos y un tiempo límite de 45 s, porque el sitio hace peticiones continuas de geolocalización y analítica y nunca llega a `networkidle`. Si el renderizador de Chromium falla, recrea la pestaña con la misma configuración anti-bot.

Las páginas viven en `na.leafletscdn.com` detrás de un proxy thumbor con URL firmada (`.../mx/data/<N>/<folleto_id>/<num>.jpg`), y el visor solo pide la imagen de la página que muestra. `obtener_paginas_folleto` navega la URL del folleto y luego `?page=2`, `?page=3`… (hasta `MAX_PAGINAS` = 30) con `esperar="commit"`, y espera hasta 4 s a que el visor pida una imagen nueva del mismo `folleto_id` (`patron_pagina_propia`). El folleto termina en la primera página que no pide ninguna imagen nueva. `_ordenar_paginas` ordena por el número final de la URL (`_ES_PAGINA_CDN`). Según Engram #18, un folleto de 6 páginas tarda unos 45 s y uno de 2, unos 22 s.

La fecha de fin se obtiene con una navegación aparte a la página del folleto (`obtener_fechas_detalle`), que busca la frase "durante los días DD/MM/YYYY - DD/MM/YYYY" (`_extraer_fechas_detalle`).

### Vigencia de los folletos

| Fuente | Fecha de inicio | Fecha de fin | Respaldo |
|---|---|---|---|
| Tiendeo | `alt` de la imagen de la tarjeta | `alt` de la imagen de la tarjeta | Si la tarjeta no trae fecha de inicio: barra de título del folleto "(DD/MM/YY - DD/MM/YY)", leída en el primer bloque |
| Ofertomat | URL del folleto (`desde-<día>-DD-MM-YYYY` o `desde-<día>-DDMMYYYY`) | Nunca en el listado | Siempre que falte: frase "durante los días ..." de la página de detalle |

Tabla: Origen de la vigencia por fuente

Al 26-oct-2026, 882 de las 883 entradas del registro tienen las dos fechas. La única sin vigencia es `tiendeo:416937`, a propósito: Tiendeo recicló ese id para un banner distinto, y ponerle las fechas del banner habría fechado mal los 137 productos del folleto original (commit af787c4, Engram #43 y #44).

### Descarga

`Downloader.descargar_paginas` crea la carpeta con `ruta_folleto(fuente, tienda, folleto_id)` y lanza una tarea por página con `aiohttp`, limitadas por el semáforo. Cada página se guarda como `pagina_NNN.<ext>`, donde NNN es su posición en la lista ordenada (no el número del CDN) y la extensión es `webp` si la URL contiene "webp" y `jpg` en otro caso. Si el archivo ya existe, no se vuelve a descargar. Las páginas que fallan se cuentan en el log y el folleto se registra con las que sí bajaron.

### Registro y autocorrección

`Registro.ya_procesado(fuente, folleto_id, tienda)` responde `True` solo si la clave está en el registro **y** su carpeta existe y no está vacía. Si alguien mueve o borra la carpeta de un folleto, la siguiente corrida lo vuelve a descargar sin tocar el JSON. Este comportamiento se usó en la limpieza manual de julio de 2026: los folletos dudosos se movieron fuera de `data/raw/tiendeo/` y el scraper los trató como pendientes (Engram #25).

`marcar_procesado` reescribe el JSON completo después de cada folleto, así que una corrida interrumpida conserva lo que ya terminó.

## Reglas y decisiones

- **Playwright en vez de requests o Selenium.** Requests + BeautifulSoup no ejecuta JavaScript y los folletos no están en el HTML inicial; Selenium se descartó por ser más lento y por su menor soporte para observar las peticiones de red (propuesta, tabla "Decisiones Web Scraping"). BeautifulSoup se usa solo para leer el HTML ya renderizado.
- **Escuchar la red en vez de leer el DOM.** La primera versión encontraba 0 páginas por folleto ("[Tiendeo] 0 páginas encontradas en https://www.tiendeo.mx/Catalogos/413250") porque las URLs del CDN solo existen cuando el visor las pide. El listener de peticiones resolvió el problema; la lectura del DOM quedó como respaldo (propuesta, "Problemáticas encontradas").
- **Bloques `flyerPage` contra la carga diferida.** Con un solo acceso, folletos de 17 y 24 páginas (413647 y 413250 de Walmart) daban 5 imágenes. Se descartó construir las URLs por número (el hash no se puede predecir) y hacer clic en "siguiente" (el visor está encapsulado). `?flyerPage=N` obliga al visor a empezar en la página N (propuesta, tabla "Estrategia solución lazy loading").
- **Filtrar las tarjetas y las páginas de otros folletos (commit 489010a, 24-jul-2026).** El widget de recomendados metía unos 12 o 13 folletos de otras cadenas en cada listado, y en el visor la heurística de "el `publication_id` con más peticiones" podía anclarse al folleto equivocado y mezclar páginas. Ahora se filtra la tarjeta por tienda y se toma el `publication_id` del HTML. Antes del arreglo, una revisión folleto por folleto encontró 62 de 286 folletos de Tiendeo con marca ajena o páginas mezcladas (Engram #25).
- **`page.on("request")` y no `page.route()` en Ofertomat (commit 9998f8d).** Se confirmó con pruebas reales que activar el interceptor `page.route()`, aunque no bloquee nada, hace que el visor deje de pedir las páginas después de la primera. Con la escucha pasiva, el visor se comporta como en un navegador normal. El costo es no poder bloquear fuentes ni analítica para acelerar la carga (Engram #18).
- **Solo las tiendas únicas de Ofertomat.** El rastreo de Ofertomat recorre `TIENDAS_UNICAS` (`arteli`, `calimax`, `7-eleven`, `walmart-express`), las cadenas que Tiendeo no tiene, para no duplicar folletos de supermercados que ya llegan por Tiendeo (commit 9998f8d, Engram #15).
- **`Referer` por fuente.** Antes se mandaba siempre el de tiendeo.mx, también al CDN de Ofertomat (commit 9998f8d).
- **`url_folleto` en el registro (commit af787c4).** Antes la URL solo quedaba en los JSON por tienda, que se sobrescriben en cada corrida; recuperar 44 URLs de Ofertomat obligó a leerlas del log. Load la guarda como `url_origen`.
- **Nombre del registro (commit 139be4a).** Se renombró `data/folletos_procesados.json` a `data/registro_folletos_scrapeados.json` porque se confundía con `paginas.procesado_at` de la BD, que es el momento del OCR.

## Configuración

| Constante o parámetro | Valor | Dónde | Para qué |
|---|---|---|---|
| `headless` | `True` | `BaseScraper.__init__`, `probar_scraper.py` | `False` muestra la ventana del navegador (útil para depurar) |
| `delay_min` / `delay_max` | 1.5 / 3.5 s | `BaseScraper.__init__` | Retardo aleatorio tras cada navegación |
| Tiempo límite de navegación | 30 s (Tiendeo) / 45 s (Ofertomat) | `BaseScraper._navegar`, `OfertomatScraper._navegar` | `page.goto` |
| `MAX_PAGINAS` (Tiendeo) | 60 | `scraper/sources/tiendeo.py` | Último `flyerPage` que se intenta |
| `PAGINAS_POR_BLOQUE` | 5 | `scraper/sources/tiendeo.py` | Salto entre bloques |
| `OfertomatScraper.MAX_PAGINAS` | 30 | `scraper/sources/ofertomat.py` | Última `?page=N` que se intenta |
| `max_concurrentes` | 2 (3 por defecto en la clase) | `probar_scraper.py`, `Downloader.__init__` | Descargas simultáneas |
| `timeout` de descarga | 30 s | `Downloader.__init__` | Por imagen |
| `DATA_RAW` | `data/raw` (relativo a la raíz del repo) | `scraper/downloader.py` | Raíz del datalake crudo |
| `RUTA_REGISTRO` | `data/registro_folletos_scrapeados.json` (relativo al directorio de trabajo) | `scraper/registro.py` | Registro de folletos |
| `TIENDAS` | 16 URLs | Cada adaptador | Tiendas que se recorren |
| `TIENDAS_UNICAS` | 4 slugs | `scraper/sources/ofertomat.py` | Tiendas de Ofertomat que se recorren |

Tabla: Parámetros del módulo Web Scraping

## Cómo se corre

Desde la raíz del repo (las rutas `data/` y `logs/` son relativas al directorio de trabajo) y con el entorno virtual del proyecto. Las versiones fijadas en `requirements.txt` son `playwright==1.58.0`, `beautifulsoup4==4.14.3` y `aiohttp==3.13.3`. En una máquina nueva, Playwright necesita su Chromium (`venv/Scripts/python.exe -m playwright install chromium`).

```
venv/Scripts/python.exe probar_scraper.py
   1 --> Tiendeo      (una tienda de las 16, o 0 = rastreo completo de las 16)
   2 --> Ofertomat    (una de las 4 tiendas únicas, o 0 = las 4)
   3 --> Ambas fuentes (rastreo completo de Tiendeo y luego de Ofertomat)
```

La corrida descarga de internet y escribe en `data/`. Una corrida completa de Tiendeo revisa 16 tiendas y solo baja los folletos nuevos; en las últimas seis corridas registradas en `logs/scraper.log` bajó entre 0 y 37 folletos (la del 25-oct-2026 bajó 31 y dejó 832 folletos de Tiendeo en el registro).

Después del scraper, `catchup_tiendeo.py` corre OCR y NLP solo sobre las carpetas que aún no tienen `ocr_resultado.json` o `nlp_resultado.json`:

```
venv/Scripts/python.exe catchup_tiendeo.py                         # tiendeo, CPU
venv/Scripts/python.exe catchup_tiendeo.py --gpu --fuente todas    # tiendeo + ofertomat, GPU (requiere torch con CUDA)
```

## Pruebas

No hay pruebas automáticas del scraper: ningún archivo de `tests/` importa `scraper/` ni `probar_scraper.py` (revisado con grep el 26-oct-2026). Se verifica con corridas reales y revisando el log y el disco:

- En `logs/scraper.log`, cada folleto debe mostrar "N páginas encontradas" y "N/N páginas descargadas". Los avisos "Descartando página de otro folleto" son el filtro por `publication_id` en funcionamiento, no errores.
- Comparar el número de páginas descargadas con el que muestra el visor del sitio para un par de folletos.
- Abrir la primera y la última página de algunos folletos nuevos para confirmar que son de la tienda correcta.

Estado del datalake al 26-oct-2026 (lectura de `data/` en esa fecha):

| Fuente | Entradas en el registro | Carpetas en `data/raw` | Páginas | Última corrida |
|---|---|---|---|---|
| tiendeo | 832 | 813 (16 tiendas) | 5,848 (mediana 4 por folleto, máximo 61) | 25-oct-2026 |
| ofertomat | 51 | 39 (4 tiendas) | 74 | 4-ago-2026 |

Tabla: Estado del datalake crudo al 26-oct-2026

Las 31 entradas del registro sin carpeta son folletos que se movieron o borraron a mano: 19 de Tiendeo (16 de Soriana Híper) y 12 de Ofertomat de mayo de 2026 (Walmart y Bodega Aurrera, de antes de limitar Ofertomat a las tiendas únicas). Si vuelven a aparecer en un listado, el scraper los descargará de nuevo.

## Limitaciones conocidas y pendientes

- **Nadie revisa que el folleto sea de la tienda.** Los dos filtros de 489010a evitan las mezclas conocidas, pero Tiendeo ya recicló ids (416937) y llegó a contaminar folletos con páginas ajenas (un menú de "Super Kompras / La Placita" al final de folletos de chedraui y bodega_aurrera, Engram #25). La revisión de julio de 2026 fue manual.
- **Ofertomat lleva sin correr desde el 4-ago-2026.** El código está completo (listado, todas las páginas y vigencia), pero no hay corrida que confirme que el sitio no cambió desde entonces. De sus 39 folletos, 25 tienen una sola página y todos son del 24-jul-2026, el día del arreglo multipágina. Al menos dos no cuadran: Engram #18 registra que calimax 135688 tiene 6 páginas reales y arteli 135652 tiene 2, pero sus carpetas solo tienen 1. No se determinó la causa (no se corrió el scraper). Como el registro los marca como procesados, no se vuelven a bajar a menos que se borre su carpeta.
- **Títulos de Ofertomat con prefijo.** El `alt` trae "Vista previa las ofertas de la tienda ...", y la limpieza solo quita el slug cuando el título empieza con él, así que el prefijo llega al registro y a la BD.
- **Páginas `.jpg` invisibles para la visión.** El descargador guarda `.jpg` cuando la URL no contiene "webp", pero `probar_vision.py` y `catchup_tiendeo.py` solo buscan `pagina_*.webp`. Hoy todas las páginas descargadas son `.webp` (0 `.jpg` en `data/raw`), así que no ha pasado.
- **Nivel de resolución de Tiendeo.** `_ordenar_paginas` devuelve solo las URLs `level_2` cuando hay alguna, y el listener no captura `_level_4_` explícitamente (entra por `publications/page_assets`). En el log de octubre de 2026 aparecen descargas `level_4`. No se verificó si algún folleto mezcla niveles y pierde páginas por esta regla.
- **Folletos de más de 60 páginas.** `MAX_PAGINAS` corta en el bloque que empieza en la página 56. El folleto más largo descargado (soriana_hiper 430899) tiene 61 páginas, en el límite.
- **`PALABRAS_BASURA` cambió sin querer y ya se corrigió.** En la depuración del commit 607a746 (7-sep-2026) la flecha "→" del conjunto se reemplazó por "-->" junto con los comentarios, y el filtro dejó de descartar enlaces con "→". Se restauró el 26-oct-2026; como Ofertomat no se corría desde el 4-ago, no afectó ningún dato.
- **Texto desactualizado en el menú.** La opción 0 de Tiendeo dice "Todas las tiendas (categoría supermercados)", pero recorre las 16 tiendas de `TIENDAS`; la categoría de supermercados ya no se usa desde 9998f8d.
- **Sin pruebas automáticas.** Los parsers (`_extraer_fechas`, `_extraer_fechas_detalle`, `_extraer_fechas_url`, `_filtrar_por_publication_id`, `_ordenar_paginas`) son funciones puras que se podrían probar con HTML y URLs guardadas, sin red.

## Historial

- **Mayo-junio de 2026.** Primera versión con `BaseScraper` y adaptadores (commits ef834e6 a 7e0a474). Se resolvieron las 0 páginas con el listener de red y la carga diferida con `flyerPage`. Ofertomat quedó "en desarrollo" en la propuesta, y también se descargaba una portada `preview.webp` por folleto.
- **24-jul-2026.** Ofertomat funcional: navegación `?page=N`, `page.on("request")`, `TIENDAS_UNICAS` y `Referer` por fuente; se quitó `scrapear_categoria` de Tiendeo (9998f8d). El mismo día se corrigió la mezcla de folletos entre tiendas en Tiendeo (489010a).
- **29-jul-2026.** Vigencia de respaldo desde la página de detalle en las dos fuentes y `url_folleto` en el registro (af787c4).
- **7-ago-2026.** El registro pasó de `folletos_procesados.json` a `registro_folletos_scrapeados.json` (139be4a).
- **7-sep-2026.** Depuración de código inactivo (607a746): se quitaron `Downloader.descargar_preview` y el argumento `--no-sandbox` de Chromium.

Diferencias con el capítulo de la propuesta (`Propuesta_PriceScraper_SS.docx`) que conviene actualizar:

| Dice la propuesta | Hoy |
|---|---|
| `iniciar_navegador()` | El método es `iniciar()` |
| `scrapear_categoria()` en Tiendeo | Se eliminó en 9998f8d; solo existe `scrapear_tienda()` |
| Ofertomat "en desarrollo" | Completo para las 4 tiendas únicas (última corrida 4-ago-2026) |
| Registro en `data/folletos_procesados.json` | `data/registro_folletos_scrapeados.json` |
| Log en `data\logs` | `logs/scraper.log` en la raíz del repo |
| "Cinco técnicas" anti-bot (lista cuatro) | Ver la tabla de medidas anti-bot de este documento |
| Se descarga la portada (preview) | Ya no se descarga (607a746) |
| `Folletos_tiendeo_{tienda}.json` en cada corrida | Solo en la corrida de una tienda, no en el rastreo completo |

Tabla: Diferencias entre la propuesta y el código actual
