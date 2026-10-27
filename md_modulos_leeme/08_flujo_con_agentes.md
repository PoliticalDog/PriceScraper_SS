# Desarrollo asistido por agentes

Desde octubre de 2026, las mejoras de PriceScraper se hicieron con Claude Code y un equipo de agentes especializados definido en `.claude/`. Este documento explica cómo está armado ese equipo, qué puede y qué no puede hacer cada pieza, cómo se lleva un cambio desde la hipótesis hasta la base de datos y qué se aprendió en el camino. No es un módulo del pipeline: es la forma de trabajar sobre él.

## Propósito y alcance

Un folleto mal leído no se arregla con una regla "que parece razonable": una regla que mejora una tienda puede romper otra en silencio. El flujo con agentes existe para que cada cambio se mida contra el ground truth, lo revise alguien distinto de quien lo hizo y lo apruebe una persona antes de llegar a la base de datos.

| Hace | No hace |
|---|---|
| Proponer y medir una hipótesis a la vez con el evaluador (`python -m evaluador`) | Modificar el ground truth, los splits ni las reglas del evaluador |
| Verificar de forma independiente cada cambio (QA) | Hacer commit, push ni recargar la BD sin la aprobación de la persona |
| Analizar la BD en solo lectura y proponer KPIs (BI) | Ver el holdout para iterar (solo QA lo corre, y solo cuando se le pide) |
| Registrar hipótesis, cifras y decisiones en Engram | Sustituir la revisión humana del diff |

Tabla: Alcance del desarrollo asistido por agentes

Lo usa el siguiente alumno que retome el proyecto con Claude Code. Si vas a trabajar sin agentes, las reglas de fondo siguen valiendo: medir antes y después con el evaluador y no tocar el ground truth.

## Qué es Claude Code y cómo se usó

Claude Code es la herramienta de línea de comandos de Anthropic con la que un modelo Claude lee el repositorio, ejecuta comandos y edita archivos dentro de una sesión. En PriceScraper se usó desde julio de 2026: de los 106 commits del repositorio, 86 llevan la línea `Co-Authored-By: Claude ...` (el primero, del 26-jul-2026); 67 de ellos son de octubre de 2026, todos con esa línea. Los mensajes de commit nombran dos modelos: Claude Opus 5.5 (67 commits) y Claude Sonnet 5 (19).

Hasta septiembre se trabajó con una sola sesión. El 11-oct-2026 (commit 13019d8) se armó el esquema actual:

```
                    la persona
            (aprueba objetivo, commit, recarga y push)
                         │
                         ▼
          sesión principal de Claude Code = orquestador
       (propone, delega, resume cifras; no decide por la persona)
          │               │                 │
          ▼               ▼                 ▼
 especialista-producto   qa-evaluador     bi-specialist
 especialista-vision     (solo lectura,   (BD en solo lectura,
 (una hipótesis, dev)     veredicto)       KPIs y dashboard)
          │               │                 │
          └───────────────┴──── Engram ─────┘
                 (memoria compartida entre sesiones)
```

- **El orquestador** es la sesión principal, la que abre la persona. Traduce el objetivo que aprueba la persona ("bajar `asociacion_producto`") en una tarea para un agente, lee su reporte, manda el cambio a QA y presenta a la persona el diff y las cifras. Es la única pieza que puede hacer commit, recargar o hacer push, y **nunca lo hace sin la aprobación explícita de la persona**: es una regla de la persona desde el inicio (Engram #136 y #203: "commits y push solo cuando el usuario lo pide; recargas de BD solo con su aprobación y con respaldo previo").
- **Los agentes** (subagentes de Claude Code) corren con su propio contexto, sus herramientas permitidas y una guardia que bloquea lo que no les toca. Entregan un reporte con formato fijo y no se invocan entre sí: si BI encuentra algo que es del especialista de producto, lo reporta al orquestador, que decide a quién pasárselo.

El protocolo de orquestación está escrito en la skill `ciclo-experimento` (sección "Orquestación (sesión principal)").

## Archivos y responsabilidades

Todo vive en `.claude/` y está en git (las skills se versionan desde el 11-oct-2026, commit d593fde; antes estaban en `.gitignore`).

| Archivo | Responsabilidad |
|---|---|
| `.claude/agents/especialista-producto.md` | Agente de producto: NLP, normalizador y asociación producto-precio en `load/load.py` |
| `.claude/agents/especialista-vision.md` | Agente de visión: regiones (ROI), preprocesamiento y OCR experimental en CPU |
| `.claude/agents/qa-evaluador.md` | Agente de QA: verifica, no edita; único que corre el holdout |
| `.claude/agents/bi-specialist.md` | Agente de BI: BD en solo lectura, KPIs, dashboard Django |
| `.claude/skills/*/SKILL.md` | Siete procedimientos (ver "Skills") |
| `.claude/skills/consulta-analitica/consulta.py` | Única puerta de lectura a PostgreSQL para BI y QA (rol `pricescraper_ro`) |
| `.claude/hooks/guardia_agente.py` | Hook `PreToolUse` que bloquea a los agentes lo que no les toca |
| `.claude/settings.json` | Lista `deny` de permisos del proyecto (aplica también a la sesión principal) |
| `tests/test_guardia_agente.py` | Pruebas de la guardia (13 funciones de prueba) |

Tabla: Archivos del flujo con agentes (.claude/)

Cada agente es un `.md` con un encabezado YAML (`name`, `description`, `tools`, `model`, `skills`, `hooks`, `color`) y, debajo, sus instrucciones. Los cuatro usan `model: inherit` (el mismo modelo que la sesión principal) y precargan sus skills con la clave `skills:`. La `description` es la que lee el orquestador para decidir a quién delega.

Dos detalles de Claude Code que importan aquí (Engram #134):

- Los agentes se cargan **al iniciar la sesión**. Hay que abrir Claude Code en la carpeta `PriceScraper_SS` para que `$CLAUDE_PROJECT_DIR` apunte al repo y la guardia se encuentre.
- Los hooks del encabezado de un agente **solo corren mientras ese agente está activo**: la sesión principal no pasa por la guardia.

## Los agentes

### especialista-producto

| Aspecto | Detalle |
|---|---|
| Rol | Proponer y medir UNA hipótesis de mejora del producto: clasificación de bloques, normalizador, catálogo, marca, asociación producto-precio |
| Herramientas | Read, Grep, Glob, Edit, Write, Bash, `mem_search`, `mem_get_observation`, `mem_save` |
| Skills | `ciclo-experimento`, `regex-precio-checklist` |
| Edita | `nlp/`, `load/load.py`, `tests/` (salvo `test_evaluador.py` y `conftest.py`) |
| No puede | Cambiar el contrato de `nlp_resultado.json` ni el esquema; editar el evaluador; correr el holdout; consultar la BD; hacer commit |
| Entrega | El "Reporte final del especialista" de `ciclo-experimento`: hipótesis, archivos, corridas base y nueva, dev global, error atacado, regresiones, ejemplos, decisión (mantener o revertido) y siguiente hipótesis |

Tabla: Agente especialista-producto (.claude/agents/especialista-producto.md)

Fue el agente más usado: todos los experimentos de precio, nombre y catálogo del 11 al 26-oct-2026 pasaron por él.

### especialista-vision

| Aspecto | Detalle |
|---|---|
| Rol | Proponer y medir UNA hipótesis de visión u OCR: detección de casillas (ROI), preprocesamiento, motor OCR |
| Herramientas | Las mismas que producto |
| Skills | `ciclo-experimento` |
| Edita | `vision/region_detector.py`, `vision/preprocessor.py`, `vision/ocr_engine.py`, en `load/load.py` solo la parte de regiones (`TIENDAS_ROI_HIBRIDO`, `candidatas_roi_pagina`, `regiones_con_precio`, rama ROI) y `tests/` |
| No puede | Reprocesar el OCR de producción (`probar_vision.py` está bloqueado); correr el holdout; cambiar los perfiles por tienda sin evidencia comparable |
| Entrega | El mismo reporte del especialista y, si el cambio vale para todo el acervo, un bloque "Solicitud de batch GPU" para la persona |

Tabla: Agente especialista-vision (.claude/agents/especialista-vision.md)

El OCR se experimenta en CPU con `python -m evaluador ocr --nombre <n> --tienda <t>` (35-45 s por página) contra una base de CPU sobre las mismas páginas, porque EasyOCR en CPU no da exactamente lo mismo que el OCR de producción, hecho en GPU. El reproceso masivo lo lanza la persona en la PC con GPU (skill `preparar-traspaso-gpu`). En Engram no hay observaciones con tema `experimentos/vision/*`: no se encontró registro de que este agente haya cerrado un experimento.

### qa-evaluador

| Aspecto | Detalle |
|---|---|
| Rol | Verificar de forma independiente el cambio de un especialista, o un KPI de BI, y emitir un veredicto APROBAR o RECHAZAR |
| Herramientas | Read, Grep, Glob, Bash, `mem_search`, `mem_get_observation`, `mem_save` (**sin** Edit ni Write) |
| Skills | `ciclo-experimento`, `consulta-analitica` |
| Edita | Nada (la guardia le da alcance vacío) |
| Puede, a diferencia de los demás | Correr `--split holdout`, solo si quien lo invoca lo pide para confirmar un cambio ya aprobado en dev |
| Entrega | El bloque "Veredicto" (archivos, integridad, pruebas, dev global, por tienda, holdout, observaciones) y la observación `experimentos/qa/<slug>` en Engram |

Tabla: Agente qa-evaluador (.claude/agents/qa-evaluador.md)

La regla central del agente es "No confíes en las cifras del especialista: reprodúcelas". Su verificación va en orden: `git status` y `git diff` (cualquier cambio en `evaluador/`, `data/`, `.claude/`, `tests/test_evaluador.py`, `tests/conftest.py`, `load/schema.sql` o `load/vistas.sql` es rechazo inmediato), `python -m evaluador verificar` ("Integridad OK"), `pytest`, dev completo con su propia corrida, `comparar --casos`, revisión de 3-5 ejemplos de `ejemplos_error` y, solo si se le pide, el holdout. Aprobar no implica commit.

### bi-specialist

| Aspecto | Detalle |
|---|---|
| Rol | Analizar los datos cargados, diseñar y validar KPIs, mejorar paneles del dashboard y detectar inconsistencias |
| Herramientas | Las mismas que producto |
| Skills | `consulta-analitica` |
| Edita | `dashboard/`, `docs/bi/`, `tests/` |
| Solo propone | `load/vistas.sql`, `load/schema.sql`, índices y roles: entrega el SQL con su justificación y su consulta de validación, y lo aplica la persona |
| No puede | Usar la conexión de escritura (`DATABASE_URL`, psycopg, `db_builder`, `manage.py shell`); correr el evaluador (lee las corridas guardadas); tocar el pipeline; cambiar un panel existente sin presentar antes una propuesta |
| Entrega | Qué analizó, la propuesta con fórmula y validación independiente, archivos tocados, **Hallazgos para el orquestador** y pendientes que necesitan aprobación |

Tabla: Agente bi-specialist (.claude/agents/bi-specialist.md)

Se agregó el 12-oct-2026 (commit ca8f1fb). Sus hallazgos alimentan a los especialistas: el de "Soriana Hiper con centavos pegados x100" (Engram #269) originó el experimento de centavos pegados que se describe abajo.

## Skills

Una skill es un procedimiento escrito en `.claude/skills/<nombre>/SKILL.md`. Claude Code la activa cuando la petición coincide con su `description`, cuando un agente la precarga con `skills:` o cuando la persona la llama por su nombre (`/nombre`).

| Skill | Para qué sirve | Cuándo se activa |
|---|---|---|
| `ciclo-experimento` | Protocolo común de especialistas y QA: contexto en Engram → base → diagnóstico → una hipótesis → cambio mínimo → medir → decidir → registrar → reportar. Define las métricas y el criterio de regresión | La precargan los especialistas y QA; también el orquestador al coordinarlos |
| `regex-precio-checklist` | Lista de cuidados para tocar reglas de precio en `nlp/regex_extractor.py` sin romper tiendas ya validadas (leer los comentarios de la regla, cambios aditivos, mantener señal espacial) | La precarga especialista-producto; al pedir cambios a reglas de precio |
| `consulta-analitica` | Lectura de PostgreSQL con `consulta.py` (rol `pricescraper_ro`, sesión READ ONLY, 60 s, una sola sentencia SELECT/WITH/EXPLAIN) y protocolo de 7 pasos por KPI; formato de "Hallazgos para el orquestador" | La precargan BI y QA; al analizar datos o revisar un KPI |
| `documentar-proyecto` | Mantiene `md_modulos_leeme/`, el manual de usuario, los borradores en Word por capítulo y las capturas del dashboard | Al pedir documentación, manuales o borradores |
| `evaluar-calidad-nlp` | Corre el comparador antiguo contra el etiquetado manual y separa causas (OCR, clasificación, tipografía) | Al pedir evaluar la calidad OCR+NLP contra el dataset manual. **Desactualizada** (ver abajo) |
| `preparar-traspaso-gpu` | Arma el ZIP en USB y las instrucciones para la IA de la PC con GPU | Cuando una tarea de OCR necesita GPU |
| `catchup-tiendeo` | Lanza `catchup_tiendeo.py` (OCR+NLP solo de `tiendeo`) con la revisión previa de procesos EasyOCR huérfanos | Solo a mano: tiene `disable-model-invocation: true`, así que el modelo no la activa solo; se llama con `/catchup-tiendeo` |

Tabla: Skills del proyecto (.claude/skills/)

**Resuelto el 26-oct-2026: skills que citaban un script que ya no existe.** `regex-precio-checklist`, `evaluar-calidad-nlp` y `preparar-traspaso-gpu` mandaban correr `evaluar_nlp.py`, renombrado a `probar_evaluar_nlp.py` el 3-oct-2026 (commit 842ccf5). Ahora citan el nombre nuevo y, para decidir un cambio, el evaluador de registros (`python -m evaluador correr --split dev --nlp memoria`), como `ciclo-experimento`.

También se actualizaron el 26-oct-2026 las cifras de contexto que habían quedado viejas:

- `ciclo-experimento` cita como base de referencia la corrida limpia `20261026_115424_398c4e4_dev.json` (precisión 33.1%, recall 24.7%, F1 28.3%); antes citaba la del 11-oct (3.8%).
- `especialista-producto` y `especialista-vision` traen la misma base; `bi-specialist` sigue con cifras del diagnóstico del 12-oct-2026 (él mismo dice "verifícalo, puede haber cambiado").

## La guardia de agentes

`.claude/hooks/guardia_agente.py` es un hook `PreToolUse`: Claude Code lo ejecuta antes de cada `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `Bash` o `PowerShell` de un agente, con el rol como argumento (`producto`, `vision`, `qa` o `bi`). Lee el evento por stdin y sale con 0 (permite) o con 2 (bloquea y le explica el motivo al agente). Si el archivo no existe, `python` también sale con 2: **la guardia falla cerrada**.

Se usó un hook y no `disallowedTools` porque un `disallowedTools` con especificador (`Bash(git push *)`) le quitaba al agente Bash entero (Engram #134).

### Qué bloquea y por qué

| Bloqueo | Para quién | Por qué |
|---|---|---|
| Editar `evaluador/`, `data/`, `.claude/`, `tests/test_evaluador.py`, `tests/conftest.py`, `load/schema.sql`, `load/vistas.sql` (`PROTEGIDO`) | Todos | El evaluador es el juez: si un agente pudiera tocar el ground truth, los splits o las reglas, podría "mejorar" las cifras sin mejorar el pipeline. `data/` tiene el GT y los JSON de producción; el esquema y las vistas los decide la persona |
| Editar fuera de su alcance (`EDITABLE`) o fuera del repo | Todos | Cada rol edita solo lo suyo; QA no edita nada |
| Comandos de shell que escriben (`>`, `tee`, `rm`, `mv`, `cp`, `sed -i`, `json.dump`, `Set-Content`...) y mencionan una ruta protegida (`FRAGMENTOS_PROTEGIDOS`: `evaluador/`, `_revision_manual`, `.claude`, `splits.json`, `manifest.json`, `data/processed`...) | Todos | Evita el rodeo de escribir con el shell lo que Edit tiene prohibido |
| `git commit`, `push`, `add`, `checkout`, `reset`, `restore`, `stash`... | Todos | El árbol de git lo cambia la persona (vía el orquestador) |
| `load.py`, `load.load`, `probar_load`, `db_builder`, `psql`, `pg_dump`, `pg_restore`, `createdb`, `dropdb`, `manage.py migrate/flush/...` | Todos | Los agentes no tocan la BD: el evaluador construye los registros en memoria |
| SQL de escritura (`DROP`, `TRUNCATE`, `ALTER`, `DELETE FROM`, `INSERT INTO`, `UPDATE ... SET`) | Todos | Igual |
| `probar_nlp`, `probar_vision`, `probar_scraper`, `catchup_tiendeo`, `orquestador`, `scraper/` | Todos | Reescriben datos de producción (JSON de OCR/NLP o descargas) |
| `evaluador sellar`, `evaluador splits`, `evaluador validacion` | Todos | Sellar el GT, regenerar splits o la validación humana son decisiones de la persona |
| `--split holdout` o `--split todo` | Todos menos QA | El holdout solo confirma; si los especialistas lo vieran, terminarían ajustando reglas a él |
| `evaluador ocr` | Todos menos visión y QA | El OCR experimental es de visión |
| `consulta.py` | Especialistas | Ellos miden con el evaluador, no con la BD |
| `consulta.py` encadenado o redirigido (`;`, `|`, `&`, `` ` ``, `$(`, `>`) | BI y QA | `consulta.py` valida que sea solo lectura; se exige que sea la única llamada |
| psycopg, `DATABASE_URL` (sin `_RO`), `manage.py shell`, `django.setup`, correr el evaluador | BI | BI lee la BD solo por `consulta.py` y las corridas guardadas |

Tabla: Bloqueos de la guardia (.claude/hooks/guardia_agente.py)

El propio archivo lo advierte: "Es una heurística sobre comandos de shell, no un sandbox". El respaldo es `evaluador/manifest.json`, que sella el GT, los splits y las reglas: cualquier cambio deja la corrida "NO VALIDA" y `python -m evaluador verificar` lo detecta. La última línea de defensa es la revisión humana del diff.

### Trampas de la guardia (verificadas el 26-oct-2026)

Las siguientes respuestas se obtuvieron pasando eventos de prueba al script:

| Comando del agente | Resultado | Por qué |
|---|---|---|
| `python -m evaluador correr ... > data/processed/x.txt` | Bloqueado | `>` + `data/processed` |
| `ls data/processed/_eval/runs 2>/dev/null` | **Bloqueado** | El `>` de `2>` cuenta como escritura junto a `data/processed`, aunque el comando solo lea |
| `ls data/processed/_eval/runs \| tail -3` | Permitido | El pipe no es marca de escritura (sí lo es en `consulta.py`) |
| `grep -n nombre_en_pila load/load.py` | **Bloqueado** | Cualquier mención de `load/load.py` en Bash se toma como acceso a la BD; para leerlo hay que usar las herramientas Grep o Read |
| Write en el scratchpad de la sesión | **Bloqueado** | Está fuera del repo |
| `python tests/_herramienta_a2_dev.py > /tmp/salida.txt` | Permitido | La redirección no menciona una ruta protegida |
| `python recargar_bd.py todo` | **Bloqueado** (desde el 26-oct-2026) | Recarga la BD; la corre la persona |
| `git diff`, `git status --short`, `pytest tests -q` | Permitido | Solo lectura |

Tabla: Respuesta de la guardia a comandos de ejemplo (rol producto, salvo consulta.py con rol bi)

Consecuencias prácticas:

- Para leer corridas guardadas en `data/processed/_eval/runs/`, usa Read o Glob, no `ls ... 2>&1`. QA lo anotó el 24-oct-2026: "La guardia de agentes bloquea los comandos con '>' o '2>&1' si aparecen rutas de data/" (Engram #258).
- Como no se puede escribir en el scratchpad, los agentes guardan sus scripts de medición en `tests/_herramienta_*.py` (Engram #257). Son de solo lectura, pytest no los recoge y van al repo (commits 8253daa y 32001ee).
- **`recargar_bd.py` bloqueado desde el 26-oct-2026.** El script respalda, reprocesa el NLP, recarga y limpia la BD. Se agregó al patrón de BD de `PROHIBIDOS` (junto a `load.py` y `pg_dump`), con su prueba en `tests/test_guardia_agente.py`. Ese mismo día se protegió `nlp/evaluador_calidad.py` (de ahí toma el evaluador la tolerancia de precio y los tokens del nombre): el especialista de producto edita `nlp/`, y sin esa protección podía cambiar al juez sin invalidar la corrida.
- **`orquestador.py` bloqueado desde el 27-oct-2026.** Descarga, hace OCR y NLP de producción y carga a la BD; lo corre la persona (o su tarea programada). Se agregó al patrón de scripts de producción, con `test_orquestador_prohibido`.
- La guardia no revisa `Read`, `Grep` ni `Glob`: un agente puede leer cualquier archivo del repo. La protección del holdout es que no se corra con `--split holdout`; el evaluador no guarda ejemplos del holdout.

### settings.json

`.claude/settings.json` tiene una lista `permissions.deny` que Claude Code aplica a toda sesión abierta en el repo, también a la principal (commit 8253daa, 25-oct-2026). No contiene secretos; solo patrones:

| Qué bloquea | Patrones |
|---|---|
| Leer o editar variables de entorno | `Read(**/.env)`, `Read(**/.env.*)`, `Edit(**/.env)`, `Edit(**/.env.*)` |
| Leer o editar llaves y secretos | `**/*.pem`, `**/*.key`, `**/secrets/**` (Read y Edit) |
| Credenciales del usuario | `Read(~/.ssh/**)`, `Edit(~/.ssh/**)`, `Read(~/.aws/**)`, `Read(~/.config/gh/hosts.yml)` |
| Mostrar un `.env` por el shell | `Bash(cat *.env*)`, `head`, `tail`, `less`, `more`, `type` |
| Borrados de raíz | `Bash(rm -rf /)`, `Bash(rm -rf ~)`, `Bash(rm -rf ~/)` |

Tabla: Lista deny de .claude/settings.json (23 reglas)

Así ninguna sesión lee la contraseña de PostgreSQL (`DATABASE_URL` y `DATABASE_URL_RO` viven en `.env`, fuera de git).

## El ciclo de experimento

Es el que fija `ciclo-experimento` y el que se siguió en todos los cambios al pipeline de octubre:

```
1. la persona aprueba el objetivo          ("precios de soriana x100")
2. orquestador → UN especialista            (nunca dos a la vez: comparten el árbol y load.py)
      base dev ANTES de editar → diagnóstico → una hipótesis → cambio mínimo + pruebas
      → misma corrida dev → comparar --casos → producción con tests/_herramienta_*
      → mantener o revertir → Engram experimentos/producto/<slug> → reporte
3. orquestador → qa-evaluador               (con la ruta de la corrida base)
      reproduce todo por su cuenta → APROBAR | APROBAR CON CONDICIONES | RECHAZAR
      → Engram experimentos/qa/<slug>
   (con condiciones: vuelve al paso 2 y después a una QA corta)
4. orquestador → la persona                  diff + cifras de dev y producción
      la persona decide el commit (y el push)
5. recarga con recargar_bd.py                 solo con aprobación y respaldo previo
      verificar antes → respaldo → nlp → load → limpiar → verificar después
6. verificación                               el cambio en la BD cuadra con lo que midieron especialista y QA
      → Engram proyecto/reproceso-nlp-recarga-<fecha>
```

**Criterio para mantener un cambio** (`ciclo-experimento`): la precisión de registros completos sube, el recall no baja, el F1 sube y no hay regresiones que bloqueen (una tienda que cae más de 2 puntos con n ≥ 20 artículos y |z| ≥ 1.96). Se reportan los artículos ganados y perdidos ("+139/−5"), no solo el neto. Subir la precisión descartando registros buenos no cuenta.

**Por qué medir también en producción.** Dev es una muestra (las páginas del ground truth). Un cambio puede dar "+0/−0" en dev y cambiar miles de precios en producción. Por eso especialista y QA simulan el cambio sobre los 821 folletos con scripts `tests/_herramienta_*` (sin escribir nada) y revisan muestras contra las imágenes.

El procedimiento de la recarga, paso por paso, está en `05_load.md` ("Procedimiento") y en el encabezado de `recargar_bd.py`.

### Ejemplo real: centavos pegados de Soriana (25-oct-2026)

1. **Hallazgo de BI** (Engram #269, 19:42). Con la BD de la segunda recarga del día, bi-specialist encontró que 1,693 de 2,941 precios de alimentos de soriana_hiper eran de $1,000 o más: "$2189" (Pepino Verde), "$6989" (Pimiento Morrón). El centavo en superíndice quedaba pegado al entero y el precio salía ×100. Lo reportó como hallazgo de prioridad alta para especialista-producto.
2. **Especialista, primera versión** (Engram #273). Regla: "$" literal + 4 o 5 dígitos sin separador = entero + centavos ("$2189" → $21.89).
3. **QA: APROBAR CON CONDICIONES** (registrado en #275). QA encontró **9 precios reales** que la regla dividía entre 100: una moto de $65,999 salía en $659.99, un minisplit de $17,990, una TV de $4,290. Pidió una guarda que reconociera cuándo la casilla confirma el entero.
4. **Especialista, guarda `_entero_confirmado`** (#273). No divide si la casilla confirma el entero: N × mensualidad MSI = entero, un "DE $X A" o "Antes" que solo es creíble con el entero, u otro monto con coma de miles en el mismo bloque. En su propia revisión encontró un falso positivo de la primera guarda (brandy soriana_mercado 422726 p6, "$31900|" que se volvía $54,141 por un "DE" mal leído) y lo corrigió. En producción la guarda protege exactamente esos 9 y ninguno más; en dev, +0/−0 (dev no tiene esas casillas).
5. **Re-QA: APROBAR** (#275, 22:17). Reprodujo los 9 cambios contra la imagen, integridad OK, 1,324 pruebas en verde, dev P 33.1 / R 24.7 / F1 28.3.
6. **Commit** que pidió la persona: f1b0afe (22:57), con el mensaje "Dev: precision 31.8 -> 33.1, recall 24.6 -> 24.7, F1 27.7 -> 28.3, +3/-0 articulos. Produccion: 2,676 precios /100 (QA: 98% con el entero bien), 564 precios falsos de 2 digitos quitados (QA: 53/53), 0 creados", y 32001ee con las herramientas de medición.
7. **Recarga y verificación** (#276). NLP de 821 folletos y load sin errores. Los PRECIO pasaron de 28,984 a 28,420 (−564, los centavos que ya se habían sumado a otro precio) y los precios de $1,000 o más de 5,179 a 2,503: exactamente los 2,676 divididos. "Todo cuadra exacto con lo medido por QA."

### Los otros dos experimentos del 25-oct-2026

| Experimento | Especialista | QA | Decisión de la persona | Commit y cifras dev | Recarga |
|---|---|---|---|---|---|
| A2-miles: "52,49000" es $2,490, no $2.49 | #257 (24-oct): +9/−0, 624 valores cambian en producción, 0 creados ni perdidos | #258 APROBAR. Reprodujo las cifras con otro método y vio que el costo era mayor de lo reportado: ~64 precios de soriana_hiper pierden sus centavos reales, no ~35 | Commit | 94cc22a: P 18.6 → 19.4, R 14.1 → 14.6, F1 16.0 → 16.7 | #262: precios de $1,000 o más +613 (se esperaban unos +624) |
| Nombre en pila: el nombre es la pila de líneas contiguas de su columna | #259: iteración 1 con +139/−5; iteración 2 agrega el corte por promoción, vigencia y oferta | Primera QA con condición (el corte); #260 APROBAR la iteración 2 | #261: revertir la "protección de pila" (en producción ~55 de 138 empeoraban), aceptar que la Comparativa baje de 9,383 a ~4,840 registros, commit sin los `_herramienta_*`, y recargar solo después de corregir el KPI "% catálogo" | caed57a: P 19.4 → 30.8, R 14.6 → 23.3, F1 16.7 → 26.5 | #262 (junto con dfe3d51, el ajuste del KPI): "% catálogo" 15.1 → 7.5, Comparativa 9,383 → 4,849 |

Tabla: Experimentos del 25-oct-2026 | Fuente: Engram #257-#262 y mensajes de commit 94cc22a y caed57a

El caso de la pila muestra que la persona no solo aprueba: decide qué costo acepta (la Comparativa pierde volumen pero gana validez, porque los grupos que desaparecen eran fragmentos como "Para Asar" o "De Cerdo") y en qué orden van commit, ajuste del KPI y recarga.

## La memoria

Un modelo no recuerda nada entre sesiones. El proyecto usa dos memorias, con fines distintos.

### Engram

Engram es un servidor MCP de memoria persistente (en Claude Code aparece como plugin `engram`). Guarda observaciones en una base local de la máquina de la persona (`engram.db`); no está en el repo. Todo lo de PriceScraper va en el proyecto `pricescraper_ss`.

| Herramienta | Uso |
|---|---|
| `mem_save` | Guardar una observación con `type` (`discovery`, `decision`, `bugfix`, `architecture`...) y `topic_key` |
| `mem_search` | Buscar por palabras clave en el proyecto; devuelve un resumen de 300 caracteres por resultado |
| `mem_get_observation` | Leer completa una observación por su número (#257) |
| `mem_context`, `mem_session_summary` | Historia reciente al iniciar y resumen al cerrar una sesión |

Tabla: Herramientas de Engram que usa el proyecto

Los agentes tienen solo `mem_search`, `mem_get_observation` y `mem_save`. Los temas (`topic_key`) siguen una convención:

| Tema | Qué guarda | Ejemplo |
|---|---|---|
| `experimentos/producto/<slug>` | Hipótesis, archivos, corridas base y nueva, cifras de dev y producción, lo descartado | `experimentos/producto/a2-miles-superindice` (#257) |
| `experimentos/qa/<slug>` | Veredicto de QA con sus cifras reproducidas | `experimentos/qa/centavos-pegados-y-sueltos` (#275) |
| `bi/hallazgos/<slug>`, `bi/<tema>` | Inconsistencias de datos y decisiones de BI | `bi/hallazgos/soriana-centavos-pegados` (#269) |
| `decisiones/<tema>` | Lo que decidió la persona | `decisiones/nombre-partido-pila-commit` (#261) |
| `proyecto/reproceso-nlp-recarga-<fecha>` | Cada recarga: commits, antes y después, respaldos | `proyecto/reproceso-nlp-recarga-2026-10-25c` (#276) |
| `architecture/...` | Diseño del flujo | `architecture/multiagente-evaluador` (#134) |

Tabla: Convención de temas en Engram

**Para qué sirve.** El paso 1 de `ciclo-experimento` es buscar en Engram antes de proponer: así no se repite una hipótesis ya descartada, como la protección de pila o descartar palabras genéricas sueltas. También es la fuente de las secciones "Reglas y decisiones" de estos documentos. Para consultarla, pídele a Claude Code algo como "busca en Engram la regla A2-miles" o "abre la observación #275".

### Memoria de archivos de Claude Code

Claude Code guarda notas en archivos Markdown por proyecto, en el perfil del usuario (`C:\Users\<usuario>\.claude\projects\<carpeta-del-proyecto>\memory\`), con un índice `MEMORY.md` que se carga al iniciar cada sesión. En esta máquina hay cuatro notas: pendientes del 16-oct y del 24-oct-2026, la regla de los respaldos locales y los acuerdos de la documentación. Las preferencias generales de la persona ("responde siempre en español") están en `C:\Users\<usuario>\.claude\CLAUDE.md`. El repo no tiene un `CLAUDE.md` propio.

La diferencia práctica: la memoria de archivos es un resumen corto de "dónde vamos y qué sigue" que la sesión lee sola; Engram es el registro detallado y se consulta a propósito.

**Para el siguiente alumno.** Ni Engram ni la memoria de archivos viajan con el repo. Lo que sí viaja son los mensajes de commit (traen el porqué y las cifras), `md_modulos_leeme/` y `.claude/`. Si la persona te pasa su `engram.db`, los números de observación citados aquí seguirán sirviendo; si no, empiezas con la memoria vacía y estos documentos son el antecedente.

## Buenas prácticas y lecciones aprendidas

- **Medir antes y después, con el mismo evaluador.** La base se corre con el código sin cambios, antes de editar (`ciclo-experimento`, paso 2). En OCR, la base tiene que ser de CPU sobre las mismas páginas: comparar contra producción mezclaría el hardware con el cambio. El evaluador fija `PYTHONHASHSEED=0` porque el desempate de marcas del normalizador depende del orden de un `set`; sin eso, dos corridas iguales no darían lo mismo.
- **Ganados y perdidos, no solo el neto.** "+139/−5" dice más que "+134", y obliga a explicar los 5.
- **Dev no basta: simular en producción.** La guarda de centavos dio +0/−0 en dev y protegía 9 precios en producción; la protección de pila dio 0/0 en dev y empeoraba ~55 nombres en producción (#259).
- **No aprobar sin QA.** En los tres experimentos del 25-oct, QA encontró algo que el especialista no había visto: el costo real de A2-miles (~64 centavos perdidos, no ~35), los 9 precios reales rotos por la primera versión de centavos y el corte que necesitaba la pila. QA reproduce con su propia corrida y, cuando puede, por otro camino (un diff propio con otra clave, #258).
- **Un especialista a la vez.** Comparten el árbol de trabajo y `load/load.py`.
- **Las acciones destructivas se confirman.** Commit, push, recarga y borrados los decide la persona. En la recarga del 25-oct-2026, el clasificador de permisos de Claude Code bloqueó la recarga forzada como "Irreversible Local Destruction" y se hizo con confirmación explícita de la persona (#276; la nota de pendientes del 24-oct lo dice así: "la recarga forzada pide confirmación explícita"). Antes de recargar siempre va el respaldo (`recargar_bd.py respaldo`), fuera del repo.
- **Los respaldos no van a git.** `.gitignore` excluye `*.dump` y `respaldo_*.tar.gz` desde el 25-oct-2026 (commit 8253daa).
- **Límites de sesión: reanudar, no reiniciar.** Cuando un agente se corta por el límite de uso de la API, conviene reanudarlo con su contexto (en Claude Code, mandándole un mensaje al mismo agente) en vez de lanzar uno nuevo, que tendría que rehacer la base y el diagnóstico. Lo mismo vale para la sesión principal: antes de seguir hay que revisar qué quedó hecho. Esta práctica no quedó registrada en Engram ni en los commits; la documento porque así se trabajó. Sí está registrado que los procesos en segundo plano **no sobreviven** al corte de una sesión: en agosto de 2026 un catch-up de OCR se perdió junto con su archivo de salida (Engram #52), y relanzarlo sin revisar dejó procesos EasyOCR duplicados (por eso `catchup-tiendeo` pide `Get-Process python` antes de lanzar).
- **Conocer la guardia.** Evita `2>&1` y `>` junto a rutas de `data/`, usa Grep o Read para `load/load.py`, y guarda los scripts de medición en `tests/_herramienta_*.py`. Si la guardia bloquea algo, el agente no busca rodeos: lo anota en su reporte.
- **El juez no se discute editándolo.** Si un especialista cree que el evaluador se equivoca en un caso, lo reporta con el ejemplo. El juez se validó contra la calificación a ciegas de la persona antes de configurar los agentes: la primera ronda dio 34 de 40 (85%, Engram #133) y `ciclo-experimento` da la validación final como 39/39.

## Limitaciones

- **Costo.** Cada experimento completo (base, iteraciones, dev completo, simulación en producción, QA con corrida propia) consume mucho uso del modelo, y QA duplica a propósito el trabajo del especialista. No hay una cifra registrada de tokens ni de costo por experimento.
- **Agentes que se cortan.** Por límites de uso de la API o de contexto, un agente puede terminar sin entregar su reporte. Hay que revisar qué dejó en el árbol (`git status`, `git diff`) y en Engram antes de reanudarlo.
- **El modelo se equivoca.** Subestimó un costo (A2-miles), propuso una regla que rompía precios reales (centavos, versión 1) y una guarda con un falso positivo (el brandy). Por eso QA verifica de forma independiente y la persona revisa el diff.
- **La guardia es heurística.** Puede bloquear comandos legítimos (`2>/dev/null` junto a `data/processed`) y dejar pasar otros que no debería: un script nuevo que toque la BD no está bloqueado hasta que se agrega a sus patrones (pasó con `recargar_bd.py`, resuelto el 26-oct-2026). La sesión principal no pasa por ella: ahí protegen `settings.json`, el clasificador de permisos y la persona.
- **Contexto viejo en las instrucciones.** Las cifras de "lo que ya se sabe" de los agentes y la "corrida base vigente" de `ciclo-experimento` son del 11 y 12-oct-2026.

## Pruebas

`tests/test_guardia_agente.py` fija el comportamiento de la guardia: rutas protegidas para todos los roles, alcance por rol, rutas fuera del repo, comandos prohibidos y permitidos, holdout solo para QA, OCR experimental solo para visión y QA, `consulta.py` solo para BI y QA, los bloqueos propios de BI, que el proceso salga con código 2 y que un evento ilegible se bloquee.

```
venv/Scripts/python.exe -m pytest tests/test_guardia_agente.py -q
```

Si cambias la guardia, agrega el caso a estas pruebas (como los de `recargar_bd.py` y `nlp/evaluador_calidad.py`, del 26-oct-2026).

## Pendientes

- No hay registro de un experimento cerrado por especialista-vision; queda por probar ese camino completo (OCR en CPU y batch GPU).

## Historial

- **Julio-septiembre de 2026.** Una sola sesión de Claude Code, con skills locales (`catchup-tiendeo`, `evaluar-calidad-nlp`, `preparar-traspaso-gpu`, `regex-precio-checklist`) que estaban en `.gitignore` desde el 7-ago-2026. La calidad se medía con el comparador contra el etiquetado manual.
- **11-oct-2026.** Evaluador de registros contra el ground truth (059f59d), OCR experimental en CPU (68f3a12), agentes de producto, visión y QA con la guardia (13019d8) y skills versionadas, con `ciclo-experimento` (d593fde). Base dev: precisión 3.8%.
- **12-oct-2026.** bi-specialist, `consulta-analitica` y el rol `pricescraper_ro` de solo lectura (ca8f1fb).
- **25-oct-2026.** `.claude/settings.json` con la lista deny (8253daa); tres experimentos y tres recargas en un día.
- **26-oct-2026.** `recargar_bd.py` con los pasos de la recarga y la skill `documentar-proyecto`. Dev: precisión 33.1%, recall 24.7%, F1 28.3% (corrida `20261026_115424_398c4e4_dev.json`).
