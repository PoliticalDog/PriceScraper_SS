---
name: documentar-proyecto
description: Genera y mantiene la documentacion de PriceScraper para el servicio social. Mantiene en el repo un .md por modulo (md_modulos_leeme/: scraper, vision, nlp, load, base de datos, evaluador, dashboard, agentes) y el manual de usuario para el siguiente desarrollador (docs/manual_usuario/: instalacion, flujo completo, recargas y respaldos, dashboard con capturas anotadas, trabajo con los agentes de Claude). De esos .md genera borradores en Word por capitulo, con la plantilla de estilos de la persona, para que ella los integre a sus dos entregables (documentacion tecnica y manual de usuario), y le avisa que cambio desde el ultimo borrador. Toma capturas del panel web con Playwright/Chromium con recuadros y etiquetas. Usala siempre que pidan documentar, escribir o actualizar el manual, un leeme o README de un modulo, la documentacion tecnica, explicar el proyecto a otro alumno, dejar antecedentes o entregables del servicio social, generar o actualizar un borrador en Word, saber que cambio en la documentacion, o tomar o rehacer capturas del dashboard, aunque no digan "manual".
---

# Documentar PriceScraper

Hay dos lectores. El **siguiente alumno de servicio social** sabe programar pero no conoce el proyecto: tiene que poder instalarlo, correrlo, entender por que cada modulo es como es y seguir mejorandolo sin repetir experimentos que ya fallaron. La **persona duena del proyecto** arma con esto sus entregables y necesita borradores bien hechos que pueda integrar con su propia redaccion. Escribe concreto, en espanol, con rutas, comandos y ejemplos reales del repo.

## Dos capas (acordado con la persona el 26-oct-2026)

1. **Los .md del repo son la referencia tecnica** y se actualizan cuando cambia el codigo. Es lo que encuentra quien clona el repo.
2. **Los borradores en Word son de la persona.** Se generan por capitulo con su plantilla; ella los integra a sus entregables con su redaccion. Una vez integrados, ese texto es suyo: nunca se regenera ni se edita su documento.

Los cambios viajan asi: codigo → `.md` → borrador nuevo o aviso de cambios → ella actualiza su documento. Si ella corrige un dato en su documento, lo lleva al `.md` (la persona te lo dice o te pasa su `.docx`; leelo y propon el cambio al `.md`).

| Producto | Ruta | Va a git |
|---|---|---|
| Un `.md` por modulo (referencia tecnica) | `md_modulos_leeme/NN_modulo.md` + `md_modulos_leeme/README.md` (indice) | Si |
| Manual de usuario (capitulos) | `docs/manual_usuario/NN_tema.md` | No: `docs/` es solo local |
| Capturas del dashboard | `docs/manual_usuario/capturas/*.png`, definidas en `docs/manual_usuario/capturas.yaml` | No (local) |
| Borradores por capitulo | `docs/entregables/documentacion_tecnica/borrador_NN_x.docx` y `docs/entregables/manual_usuario/borrador_NN_x.docx` | No (`*.docx` en `.gitignore`) |
| Registro de borradores entregados | `docs/entregables/registro_borradores.yaml` (que `.md` y que commit se entrego) | No (local) |
| Portadas (para un documento completo) | `docs/entregables/portada_*.yaml` | No (local) |

Solo `md_modulos_leeme/` (y la skill) van a git: `docs/` y `sources/` son locales por decision de la persona (26-oct-2026); no los agregues al repo. Los documentos originales de la persona estan en la raiz del repo, fuera de git.

Las estructuras estan en `references/manual_tecnico.md` (como encaja cada modulo en el documento tecnico de la persona, que parte de su `Propuesta_PriceScraper_SS.docx`) y `references/manual_usuario.md`.

## Flujo de trabajo

1. **Alcance.** Identifica que modulos o capitulos pide la persona. "Actualiza el de nlp" toca solo `md_modulos_leeme/03_nlp.md` y su borrador; "documenta el proyecto" se hace capitulo por capitulo, mostrando cada uno antes de seguir.
2. **Fuentes.** Lee `references/fuentes.md`: dice de donde sale cada dato de cada modulo. El orden de confianza es codigo > pruebas > `docs/` > Engram > `sources/` > la propuesta original. Lo historico describe versiones anteriores (el modelo de BD de 5 tablas, spaCy como extractor principal) y se cita como historia, no como estado actual.
3. **Verifica antes de escribir.** Cada nombre de funcion, constante, ruta, comando, tabla o cifra debe existir hoy: abre el archivo o haz grep. Las cifras de calidad (precision, recall, F1, conteos de la BD) llevan fecha y de donde salen ("dev, corrida 20261025_224754"). Si algo no se puede verificar, dilo en el texto en vez de inventarlo.
4. **Escribe o actualiza el `.md`** con la estructura de la referencia y las convenciones de abajo. Actualiza `md_modulos_leeme/README.md` si agregas un modulo.
5. **Capturas** (manual de usuario y partes del dashboard): agrega o ajusta entradas en `docs/manual_usuario/capturas.yaml` y corre el script (ver abajo). Mira cada PNG con Read antes de citarlo: una grafica vacia, una tabla "Cargando..." o un recuadro desfasado no sirve. El estilo de las capturas (recuadros de color, etiqueta corta numerada, explicacion en el texto) lo aprobo la persona: no lo cambies.
6. **Genera el borrador del capitulo** (ver abajo) y revisa los conteos que imprime el script.
7. **Reporta** que archivos cambiaron, que verificaste, que quedo sin verificar y la ruta del borrador.

## Convenciones de los .md

Son las de la plantilla `Propuesta_PriceScraper_SS.docx`, para que el borrador pegue en el documento de la persona sin reformatear:

- `# Titulo` = el titulo del archivo (en un borrador de capitulo baja a seccion numerada; en un documento completo es `Titulos_capitulos`). Un `#` por archivo.
- `## Seccion`, `###`, `####` = niveles de `Titulo_punteado`. No escribas los numeros a mano: Word los pone.
- Tablas con sintaxis de tuberias. Justo despues de la tabla, una linea `Tabla: descripcion` produce el pie "Tabla n – descripcion. Fuente: Creación propia.". Si la fuente es otra: `Tabla: descripcion | Fuente: Engram #255`.
- Imagenes con `![descripcion](ruta/relativa.png)`. El pie sale como "Figura n – descripcion. Fuente: Creación propia.".
- Codigo y diagramas de texto en bloques con triple acento grave: salen con el estilo `resaltado_codigo_diagramas`.
- Listas con `-` o `1.`; negritas `**...**`, codigo en linea con acentos graves.

## Borradores en Word

Un borrador por capitulo, para integrar dentro del documento de la persona:

```bash
venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/md_a_docx.py --capitulo \
    --registro docs/entregables/registro_borradores.yaml \
    --salida docs/entregables/documentacion_tecnica/borrador_03_nlp.docx md_modulos_leeme/03_nlp.md
```

- `--capitulo` quita portada e indices y baja los titulos un nivel: el `#` del archivo queda como seccion numerada (`Titulo_punteado` nivel 1), igual que "Módulo Vision" dentro del "CAPITULO 4" de su documento. Arriba pone una nota con el `.md`, el commit y la fecha de origen.
- `--registro` anota que version se entrego. Genera el borrador desde un estado con commit; si la nota dice "cambios sin commit", avisale a la persona que ese borrador no corresponde a un commit.
- Usa `Propuesta_PriceScraper_SS.docx` (raiz del repo) como plantilla. Si no esta, el script se detiene: no inventes otro formato.
- Sin `--capitulo` genera un documento completo con portada (`--portada docs/entregables/portada_*.yaml`) e indices como campos de Word: al abrirlo, Word pregunta si actualiza los campos; hay que decirle que si.

## Avisar que cambio desde el ultimo borrador

Cuando la persona pregunte que cambio, o al terminar un cambio de codigo que afecta un modulo ya entregado:

1. Lee `docs/entregables/registro_borradores.yaml` para saber que commit se le entrego de cada capitulo.
2. `git diff --no-index <copia_entregada> <fuente.md>` muestra el cambio exacto (la copia de lo entregado queda junto al borrador como `borrador_x.entregado.md`; para `md_modulos_leeme/` tambien sirve `git diff <commit> -- <fuente.md>`).
3. Resume para ella, por seccion: que se agrego, que cambio (dato viejo → dato nuevo) y que se quito, con el texto nuevo listo para pegar. Si el cambio es grande, genera el borrador completo de nuevo y dile que secciones cambiaron.

## Capturas del dashboard

`scripts/capturas_dashboard.py` abre el panel en Chromium sin ventana (Playwright ya esta en el venv porque lo usa el scraper), ejecuta las acciones de cada captura, dibuja recuadros de color con etiquetas numeradas sobre los elementos y guarda el PNG. Los recuadros se calculan desde el selector CSS del elemento, asi que siguen al elemento aunque cambie el diseno.

```bash
venv/Scripts/python.exe .claude/skills/documentar-proyecto/scripts/capturas_dashboard.py \
    --config docs/manual_usuario/capturas.yaml --salida docs/manual_usuario/capturas [--solo resumen_general]
```

- Si el dashboard no responde en `--base` (por defecto `http://127.0.0.1:8000`), el script levanta `manage.py runserver` y lo apaga al final. Necesita PostgreSQL arriba.
- Formato del YAML y ejemplo comentado en `assets/capturas_ejemplo.yaml`. Cada captura tiene `archivo`, `url`, `esperar` (selector que indica que la pagina ya cargo), `acciones` opcionales (`clic`, `escribir`, `seleccionar`, `esperar`, `esperar_ms`), `recorte` opcional (`auto`, un selector, `pagina` o `ventana`) y `anotaciones` (`selector`, `etiqueta`, `color` opcional). Sin `recorte`, la imagen encierra todas las anotaciones con un margen.
- Usa selectores estables (los `id` de `dashboard/templates/dashboard/`). Confirma con grep que el selector existe antes de anotarlo.
- Los `id` de pagina del visor de origen cambian con cada recarga de la BD: si una captura del visor falla, busca otra pagina con precios.
- Para imagenes que no son del panel (por ejemplo, una pagina de folleto con sus cajas OCR), dibuja con PIL sobre el PNG a partir de las coordenadas `bbox`.

## Lo que no se hace

- No edites ni regeneres el documento de la persona; solo sus borradores en `docs/entregables/`.
- No copies parrafos de `sources/` o de la propuesta sin verificarlos contra el codigo actual. Si algo cambio, escribe como es hoy y, si la historia ayuda a entender, agrega "Antes ..., se cambio porque ..." con su referencia.
- No pongas secretos: nada de `.env`, contrasenas o la `DATABASE_URL` real. Escribe el formato (`postgresql://usuario:clave@localhost:5432/pricescraper`).
- No cambies codigo, la BD ni la configuracion para que algo "quede bien en el manual". Si encuentras un error o algo confuso, reportalo a la persona.
