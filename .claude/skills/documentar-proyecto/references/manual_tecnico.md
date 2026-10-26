# Estructura de la documentacion tecnica

Un archivo por modulo en `md_modulos_leeme/`, numerado en el orden del pipeline, mas un `README.md` que sirve de indice para quien clona el repo. El lector quiere saber como esta hecho cada modulo, que entra y que sale, y por que se decidio asi, para cambiarlo sin romper lo que ya se valido.

## Como encaja en el documento de la persona

La documentacion tecnica es un entregable separado que parte de su `Propuesta_PriceScraper_SS.docx` (raiz del repo, fuera de git). Ese documento ya tiene: Capitulo 1 (introduccion, objetivos, justificacion, marco teorico, estado del arte), Capitulo 2 (productos esperados, metodologia, cronograma, stack propuesto, riesgos, metricas de exito), Capitulo 3 (arquitectura y modelo de BD) y Capitulo 4 (desarrollo: modulos web scraping y vision, NLP incompleto). Los capitulos 1 y 2 son redaccion suya: no se reescriben, solo se le avisa si algo quedo desactualizado (por ejemplo, el stack propuesto contra el real, o las metricas de exito contra los resultados).

| Archivo | Borrador | Donde va en su documento |
|---|---|---|
| `00_arquitectura.md` | `borrador_00_arquitectura.docx` | Capitulo 3 · Arquitectura del sistema: el pipeline, el datalake (`data/raw` → `data/processed`), los modulos y el stack real (verificado en `requirements.txt`, que esta en UTF-16) |
| `04_base_de_datos.md` | `borrador_04_base_de_datos.docx` | Capitulo 3 · Modelo de base de datos (reemplaza el modelo de 5 tablas de la propuesta) |
| `01_scraper.md` | `borrador_01_scraper.docx` | Capitulo 4 · Modulo Web Scraping (actualiza lo que ya tiene) |
| `02_vision.md` | `borrador_02_vision.docx` | Capitulo 4 · Modulo Vision (actualiza lo que ya tiene) |
| `03_nlp.md` | `borrador_03_nlp.docx` | Capitulo 4 · Modulo NLP |
| `05_load.md` | `borrador_05_load.docx` | Capitulo 4 · Modulo de carga (ETL) |
| `06_evaluador.md` | `borrador_06_evaluador.docx` | Capitulo 4 · Evaluacion de calidad |
| `07_dashboard.md` | `borrador_07_dashboard.docx` | Capitulo 4 · Dashboard y BI |
| `08_flujo_con_agentes.md` | `borrador_08_flujo_con_agentes.docx` | Capitulo 4 · Desarrollo asistido por agentes |

Tabla: archivo del repo, borrador y su lugar en el documento tecnico de la persona. Los borradores van en `docs/entregables/documentacion_tecnica/`.

Para los modulos que su documento ya cubre (scraper, vision), el `.md` se escribe completo igual, y al entregar el borrador se le dice que secciones de su texto actual siguen vigentes y cuales cambiaron.

## Plantilla de cada modulo

Adapta los titulos al modulo; no todos necesitan todas las secciones. Lo que no debe faltar: proposito, entradas y salidas, decisiones con su porque, y como probarlo.

```markdown
# Modulo NLP

Una o dos frases: que hace y en que lugar del pipeline esta.

## Proposito y alcance
Que problema resuelve y que NO hace (por ejemplo: no asocia producto con precio, eso es load).

## Entradas y salidas
- Entrada: archivo, formato, quien lo produce. Un fragmento real recortado del JSON.
- Salida: archivo, formato (contrato), quien lo consume. Fragmento real.
Si el contrato cambia, que se rompe.

## Archivos y responsabilidades
Tabla: archivo | responsabilidad | funciones o clases clave.

## Como funciona
El flujo paso a paso, con un diagrama de texto si ayuda. Las piezas importantes con su nombre real
(clase, metodo, constante) y un ejemplo con datos reales ("$2189" -> $21.89).

## Reglas y decisiones
Por cada regla relevante: que hace, por que existe (que caso real la motivo), que se probo y se
descarto, y con que cifras se decidio. Cita el commit o la observacion de Engram.

## Configuracion
Constantes, umbrales y parametros que se ajustan, con su valor actual y donde estan.

## Pruebas
Que archivos de `tests/` lo cubren, como correrlos, que casos fijan.

## Limitaciones conocidas y pendientes
Lo que aun falla, con su volumen y la idea de solucion si la hay.

## Historial
Version anterior y por que cambio, en pocas lineas, con la referencia a `sources/`.
```

## Notas para escribirlo bien

- **El porque es lo valioso.** Que `PATRON_ENTERO_FUSION` no acepte "$" + 3 digitos parece arbitrario hasta que se explica que "879"+"99" es $79.99 en merco y $544.90 en casa_ley. Esa explicacion evita que el siguiente alumno lo "arregle" y rompa 100 precios.
- **Cifras con fecha y fuente.** "Dev 25-oct-2026: P 33.1 / R 24.7 / F1 28.3 (corrida 20261025_203621)". Sin fecha, una cifra no sirve.
- **Ejemplos reales.** Un ejemplo con folleto y pagina ("soriana_hiper 416269 p1 'Cebolla Blanca' $1880 -> $18.80") se puede ir a ver; uno inventado no.
- **Largo.** Un modulo grande como nlp puede ocupar varias paginas; uno chico, una. Prefiere tablas y listas a parrafos largos para lo que es referencia.
