# Estructura del manual tecnico

Un archivo por modulo en `docs/manual_tecnico/`, numerado en el orden del pipeline. El lector quiere saber como esta hecho cada modulo, que entra y que sale, y por que se decidio asi, para cambiarlo sin romper lo que ya se valido.

| Archivo | Capitulo |
|---|---|
| `00_arquitectura.md` | Vision general: el pipeline, el datalake (`data/raw` → `data/processed`), los modulos y como se conectan, el stack real (verificado en `requirements.txt`, que esta en UTF-16) |
| `01_scraper.md` | Web scraping (Tiendeo, Ofertomat) |
| `02_vision.md` | Preprocesamiento, OCR y deteccion de regiones |
| `03_nlp.md` | Clasificacion de bloques, reglas de precio, normalizador y catalogo |
| `04_load.md` | Asociacion producto-precio, carga a PostgreSQL, recargas |
| `05_base_de_datos.md` | Esquema, vistas, cadenas, respaldos |
| `06_evaluador.md` | Ground truth, splits, metricas, como medir un cambio |
| `07_dashboard.md` | Django, paginas, APIs, consultas, metricas BI |
| `08_flujo_con_agentes.md` | Skills, especialistas, QA, guardia de agentes, Engram |

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
