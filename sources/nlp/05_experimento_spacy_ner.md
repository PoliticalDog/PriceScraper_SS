# Experimento: viabilidad de integrar spaCy al pipeline NLP

**Fecha:** 23-ago-2026
**Script:** `probar_spacy_ner.py` (no modifica `nlp/regex_extractor.py` ni la BD — mismo patrón que `probar_hibrido_roi.py`, es solo para decidir si vale la pena integrar)
**Motivo:** `Propuesta_PriceScraper_SS.docx` especifica *"spaCy con modelo entrenado en español (es_core_news_sm) para reconocimiento de entidades nombradas (PRODUCTO / PRECIO / PROMO)"*. Nunca se había usado en el proyecto — ni siquiera el modelo estaba descargado. Se evaluó si integrarlo mejora o empeora el pipeline actual (regex puro, 75.2% de recall de PRODUCTO medido contra el dataset manual).

## Metodología

Mismo dataset (65 folletos etiquetados a mano, `data/raw/_revision_manual/tiendeo/`) y misma métrica de recall (`recall_texto`/`corpus_de_bloques` de `nlp/evaluador_calidad.py`, la que ya usa `evaluar_nlp.py`) — para que los números fueran directamente comparables al 75.2% ya establecido, sin inventar una metodología nueva.

Se probaron dos formas de usar spaCy **sin entrenar un modelo custom** (que se analiza aparte, ver más abajo):

1. **NER pre-entrenado** (`es_core_news_sm`, labels `LOC/MISC/ORG/PER`): un bloque OCR se considera "producto" si contiene una entidad `MISC` u `ORG` (proxy razonable de "nombre propio" — marca o producto).
2. **PhraseMatcher**: cargado con el **mismo vocabulario que ya usa el regex actual** (`nlp/normalizador.CATALOGO_CANONICO` + `nlp/catalogo_productos.CATALOGO`, sin agregar nada nuevo) — para comparar el *motor* de matching, no el catálogo.

## Resultados

### Recall de PRODUCTO (global, 1818 artículos evaluados)

| Método | Recall |
|---|---:|
| **Regex actual (baseline, ya en producción)** | **75.2%** |
| spaCy NER pre-entrenado | 28.4% |
| spaCy PhraseMatcher (mismo catálogo) | 18.8% |

Ambos enfoques de spaCy quedan muy por debajo del regex actual, en todas las tiendas sin excepción (ver tabla completa en `data/processed/_evaluacion_nlp/reporte_spacy.json`).

### Por qué falla cada uno

- **NER pre-entrenado**: `es_core_news_sm` se entrenó con texto de noticias/Wikipedia genérico — no tiene ningún concepto de "producto de supermercado". De 17,363 bloques OCR evaluados, **8,802 (50.7%) no recibieron ninguna entidad**, y las que sí se asignaron (`LOC` 2,100, `MISC` 2,834, `ORG` 1,746, `PER` 1,881) son una señal débil e indirecta, no diseñada para este dominio.
- **PhraseMatcher**: aunque usa el catálogo real del proyecto, solo matcheó el **6.9%** de los bloques (1,199 de 17,363). Esto confirma un hallazgo de la sesión anterior (expansión del catálogo canónico): el catálogo por sí solo es angosto frente a la diversidad real de productos. El regex actual compensa esto con la heurística `_es_probable_producto` (bloques en mayúsculas, palabras largas sueltas, 2+ palabras de longitud razonable) — una capa de recall que el experimento de PhraseMatcher no tenía equivalente, por diseño (se quería aislar el motor de matching, no replicar el pipeline completo).

### Rendimiento (velocidad)

Mismo corpus exacto (37,064 bloques OCR, 65 folletos), medido en la misma máquina:

| Método | Velocidad | Relativo |
|---|---:|---:|
| **Regex actual** | 8,599 bloques/seg | 1x (referencia) |
| spaCy optimizado (`tok2vec`+`ner` únicamente, resto del pipeline deshabilitado) | 700 bloques/seg | **~12x más lento** |
| spaCy pipeline completo (tokenizer+parser+morfología+lematizador+NER) | 622 bloques/seg | ~14x más lento |

Deshabilitar los componentes no usados (`parser`, `morphologizer`, `lemmatizer`, `attribute_ruler`) solo dio ~13% de mejora — el costo dominante es `tok2vec` (la capa de embeddings compartida), que no se puede evitar sin perder NER también.

## Sobre entrenar un modelo custom (lo que realmente proponía la documentación)

El modelo pre-entrenado nunca iba a reconocer "PRODUCTO/PRECIO/PROMO" como tipos de entidad — esos labels no existen en `es_core_news_sm`; solo se obtienen entrenando un NER custom. Evalué qué tomaría hacerlo bien, sin ejecutarlo (fuera de alcance de esta sesión):

1. **Anotación de datos con spans de caracteres**: el dataset manual actual (`_contenido.json`) guarda nombres de producto como texto libre, sin posición exacta dentro de un bloque OCR — el entrenamiento de NER de spaCy exige `(texto, [(inicio_char, fin_char, label), ...])` por ejemplo. Como el OCR fragmenta un mismo producto en varios bloques (la razón por la que `evaluar_nlp.py` mide cobertura de tokens y no coincidencia exacta), proyectar el ground truth actual a spans exactos no es automático — requeriría re-anotación manual o una heurística de mapeo propensa a error. Este paso es, con margen, el más caro.
2. **Volumen de datos**: 65 folletos es poco para que un NER generalice bien, sobre todo con el nivel de ruido OCR de este proyecto (acentos rotos, fragmentación, mayúsculas/minúsculas inconsistentes). Los benchmarks públicos de NER en español suelen entrenar con miles de documentos.
3. **Entrenamiento e iteración**: config de spaCy (`spacy init config` + `spacy train`), split train/dev, y probablemente varias vueltas de ajuste — la parte más "mecánica", pero no trivial.

Estimado: **2-3 días solo para la anotación/conversión de datos, +1-2 días de entrenamiento e iteración** — y con un resultado incierto, porque 65 folletos es un dataset pequeño para NER y el regex actual ya fue afinado en varias sesiones contra fallos reales (prioridades 1-4 del plan de mejora).

## Recomendación

**No integrar spaCy.** Ni el modelo pre-entrenado (28.4%/18.8% de recall, ~12x más lento) ni la ruta de entrenar uno custom (costo de anotación alto, dataset pequeño, resultado incierto frente a un regex ya maduro) justifican el cambio. El hallazgo es honesto y medido, no una suposición: se corrió el experimento real contra el mismo dataset y la misma métrica que ya usa el proyecto.

Igual que con PySpark y Plotly, esto se documenta como decisión técnica evaluada — no como omisión.
