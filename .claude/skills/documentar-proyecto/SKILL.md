---
name: documentar-proyecto
description: Genera y mantiene la documentacion de PriceScraper para quien retome el proyecto de servicio social. Cubre un manual de usuario (instalacion, flujo completo scraper -> OCR -> NLP -> carga -> dashboard, recargas y respaldos, uso del dashboard con capturas anotadas, trabajo con los agentes de Claude) y un manual tecnico con un .md por modulo (scraper, vision, nlp, load, evaluador, dashboard, base de datos). Los .md de docs/ son la fuente de verdad; de ellos salen el .docx con la plantilla de estilos del proyecto y las capturas del panel web, tomadas con Playwright/Chromium con recuadros y etiquetas. Usala siempre que pidan documentar, escribir o actualizar el manual, la guia, el README de un modulo, explicar el proyecto a otro alumno, dejar antecedentes o entregables del servicio social, generar el Word del manual, o tomar o rehacer capturas del dashboard, aunque no digan "manual".
---

# Documentar PriceScraper

Quien lee esto es el siguiente alumno de servicio social: sabe programar, pero no conoce el proyecto. Tiene que poder instalarlo, correrlo, entender por que cada modulo es como es y seguir mejorandolo sin repetir experimentos que ya fallaron. Escribe para esa persona: concreto, en espanol, con rutas, comandos y ejemplos reales del repo.

## Que se produce y donde

| Producto | Ruta | Notas |
|---|---|---|
| Manual de usuario | `docs/manual_usuario/NN_tema.md` | Como usarlo. Estructura en `references/manual_usuario.md` |
| Manual tecnico | `docs/manual_tecnico/NN_modulo.md` (un archivo por modulo) | Como esta hecho y por que. Estructura en `references/manual_tecnico.md` |
| Capturas | `docs/manual_usuario/capturas/*.png` | Se generan con `scripts/capturas_dashboard.py` a partir de `docs/manual_usuario/capturas.yaml` |
| Word | `docs/entregables/<manual>.docx` | Se genera con `scripts/md_a_docx.py`; nunca se edita a mano |

Los `.md` son la fuente de verdad: van a git, se revisan en los diffs y se actualizan junto con el codigo. El `.docx` y las capturas se regeneran a partir de ellos. Si alguien edita el Word a mano, ese cambio se pierde en la siguiente generacion, asi que todo cambio va al `.md`.

## Flujo de trabajo

1. **Alcance.** Identifica que modulos o temas pide la persona. "Actualiza el manual de nlp" toca solo `docs/manual_tecnico/03_nlp.md`; "documenta el proyecto" es todo, y conviene hacerlo modulo por modulo, mostrando el primero antes de seguir.
2. **Fuentes.** Lee `references/fuentes.md`: dice de donde sale cada dato de cada modulo (codigo, pruebas, docs, Engram, `sources/`). El orden de confianza es codigo > pruebas > `docs/` > Engram > `sources/` > la propuesta original. Lo historico describe versiones anteriores (el modelo de BD de 5 tablas, spaCy como extractor principal) y se cita como historia, no como estado actual.
3. **Verifica antes de escribir.** Cada nombre de funcion, constante, ruta, comando, tabla o cifra que pongas debe existir hoy: abre el archivo o haz grep. Las cifras de calidad (precision, recall, F1, conteos de la BD) llevan fecha y de donde salen ("dev, corrida 20261025_203621"). Si algo no se puede verificar, dilo en el texto en vez de inventarlo.
4. **Escribe el `.md`** con la estructura de la referencia que corresponda y las convenciones de abajo.
5. **Capturas** (manual de usuario y la parte del dashboard): agrega o ajusta las entradas en `docs/manual_usuario/capturas.yaml` y corre el script (ver abajo). Mira cada PNG con Read antes de citarlo: una captura con la grafica vacia, una tabla "Cargando..." o un recuadro desfasado no sirve.
6. **Genera el Word** con `scripts/md_a_docx.py` y revisa el resultado (ver abajo).
7. **Reporta** a la persona que archivos cambiaron, que verificaste y que quedo pendiente o sin verificar.

## Convenciones de los .md

Son las de la plantilla `Propuesta_PriceScraper_SS.docx`, para que el Word salga con el mismo formato que el resto del servicio social:

- `# Titulo` = capitulo (estilo `Titulos_capitulos`). Un `#` por archivo.
- `## Seccion` = titulo numerado de nivel 1 (`Titulo_punteado`); `###` nivel 2; `####` nivel 3. No escribas los numeros a mano: Word los pone.
- Tablas con sintaxis de tuberias. Justo despues de la tabla, una linea `Tabla: descripcion` produce el pie "Tabla n – descripcion. Fuente: Creación propia.". Si la fuente es otra: `Tabla: descripcion | Fuente: Engram #255`.
- Imagenes con `![descripcion](capturas/archivo.png)`. El pie sale como "Figura n – descripcion. Fuente: Creación propia.". La ruta es relativa al `.md`.
- Codigo y diagramas de texto en bloques con triple acento grave: salen con el estilo `resaltado_codigo_diagramas`.
- Listas con `-` o `1.`; negritas `**...**`, codigo en linea con acentos graves.
- Glosario y referencias en formato IEEE, como en la propuesta, cuando el capitulo los necesite.

## Capturas del dashboard

`scripts/capturas_dashboard.py` abre el panel en Chromium sin ventana (Playwright ya esta en el venv porque lo usa el scraper), ejecuta las acciones de cada captura, dibuja recuadros de color con etiquetas numeradas sobre los elementos y guarda el PNG. Los recuadros se calculan desde el selector CSS del elemento, asi que siguen al elemento aunque cambie el diseno.

```bash
venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/capturas_dashboard.py \
    --config docs/manual_usuario/capturas.yaml --salida docs/manual_usuario/capturas [--solo resumen_kpis]
```

- Si el dashboard no responde en `--base` (por defecto `http://127.0.0.1:8000`), el script levanta `manage.py runserver` y lo apaga al final. Necesita PostgreSQL arriba.
- Formato del YAML y ejemplo comentado en `assets/capturas_ejemplo.yaml`. Cada captura tiene `archivo`, `url`, `esperar` (selector que indica que la pagina ya cargo), `acciones` opcionales (`clic`, `escribir`, `seleccionar`, `esperar`, `esperar_ms`), `recorte` opcional (`auto`, un selector, `pagina` o `ventana`) y `anotaciones` (`selector`, `etiqueta`, `color` opcional). Sin `recorte`, la imagen encierra todas las anotaciones con un margen.
- Usa selectores estables (los `id` de las plantillas en `dashboard/templates/dashboard/`). Antes de escribir una anotacion, confirma con grep que el selector existe.
- La etiqueta del recuadro es corta ("2. Filtro de folleto"); la explicacion larga va en el texto del manual, refiriendose al numero.
- Para imagenes que no son del panel (por ejemplo, una pagina de folleto con sus cajas OCR), dibuja con PIL sobre el PNG a partir de las coordenadas `bbox`; no hace falta este script.

## Generar el Word

```bash
venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/md_a_docx.py \
    --portada docs/manual_tecnico/portada.yaml --salida docs/entregables/manual_tecnico.docx \
    docs/manual_tecnico/*.md
```

- Usa `Propuesta_PriceScraper_SS.docx` (raiz del repo) como plantilla: conserva sus estilos, margenes, encabezado y pie, y vacia su contenido. Si la plantilla no esta, el script se detiene y lo dice: no inventes otro formato.
- `portada.yaml` lleva `titulo`, `subtitulo`, `proyecto`, `presenta`, `tutor` y `fecha`. Hay un ejemplo en `assets/portada_ejemplo.yaml`.
- El documento trae indice general, indice de tablas y de figuras como campos de Word: al abrirlo, Word pregunta si actualiza los campos. Hay que decirle que si; eso esta bien y es lo esperado.
- Despues de generar, comprueba el resultado con `python -c "import docx; ..."` o leyendo los conteos que imprime el script (parrafos por estilo, tablas, figuras). Un capitulo sin `Titulos_capitulos` o una tabla sin pie es senal de que el `.md` no siguio las convenciones.
- Los `.docx` estan en `.gitignore` (`*.docx`). Se entregan, no se versionan.

## Lo que no se hace

- No copies parrafos de `sources/` o de la propuesta sin verificarlos contra el codigo actual. Si algo cambio, escribe como es hoy y, si la historia ayuda a entender, agrega "Antes ..., se cambio porque ..." con su referencia.
- No pongas secretos: nada de `.env`, contrasenas o la `DATABASE_URL` real. Escribe el formato (`postgresql://usuario:clave@localhost:5432/pricescraper`).
- No cambies codigo, la BD ni la configuracion para que algo "quede bien en el manual". Si encuentras un error o algo confuso, reportalo a la persona.
