-- =============================================================================
-- PriceScraper MX — schema.sql
-- Definición de tipos, tablas e índices en PostgreSQL
--
-- Uso:
--   psql -U <usuario> -d <base_datos> -f schema.sql
--
-- Idempotente: se puede ejecutar múltiples veces sin error.
-- Orden: extensiones → ENUMs → tablas → índices
-- =============================================================================


-- =============================================================================
-- 0. EXTENSIONES
-- =============================================================================

-- Búsqueda de similitud en texto_norm (productos con typos o variaciones OCR)
CREATE EXTENSION IF NOT EXISTS pg_trgm;


-- =============================================================================
-- 1. TIPOS ENUM
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE fuente_enum AS ENUM (
        'tiendeo',
        'ofertomat'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE estado_folleto_enum AS ENUM (
        'pending',
        'processing',
        'done',
        'error'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE tipo_extraccion_enum AS ENUM (
        'PRODUCTO',
        'PRECIO',
        'PRECIO_ANTERIOR',
        'AHORRO',
        'PROMO',
        'EVENTO_PROMO',
        'ATRIBUTO',
        'DESCARTE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;


-- =============================================================================
-- 2. TABLAS
-- =============================================================================

-- -----------------------------------------------------------------------------
-- tiendas
-- Cadenas comerciales scrapeadas (Soriana, Walmart, Chedraui, etc.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tiendas (
    id          SERIAL          PRIMARY KEY,
    nombre      VARCHAR(100)    NOT NULL,
    slug        VARCHAR(60)     NOT NULL UNIQUE,
    fuente_slug VARCHAR(60),
    activa      BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  tiendas             IS 'Cadenas comerciales scrapeadas';
COMMENT ON COLUMN tiendas.slug        IS 'Identificador canónico normalizado (post-corrección ETL)';
COMMENT ON COLUMN tiendas.fuente_slug IS 'Slug original del scraper, puede ser erróneo (ej. walmart cuando es soriana)';


-- -----------------------------------------------------------------------------
-- folletos
-- Folletos digitales con metadata de vigencia y origen
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS folletos (
    id                  SERIAL                  PRIMARY KEY,
    tienda_id           INTEGER                 NOT NULL REFERENCES tiendas(id),
    folleto_id_fuente   VARCHAR(30)             NOT NULL,
    fuente              fuente_enum             NOT NULL,
    titulo              VARCHAR(200),
    fecha_inicio        DATE,
    fecha_fin           DATE,
    url_origen          TEXT,
    total_paginas       INTEGER                 DEFAULT 0,
    perfil_ocr          VARCHAR(40),
    motor_ocr           VARCHAR(20),
    scrapeado_at        TIMESTAMP,
    estado              estado_folleto_enum      NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMP               NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_folleto_fuente_id UNIQUE (fuente, folleto_id_fuente)
);

COMMENT ON TABLE  folletos                    IS 'Folletos digitales scrapeados con metadata de vigencia';
COMMENT ON COLUMN folletos.folleto_id_fuente  IS 'ID asignado por la fuente (Tiendeo/Ofertomat)';
COMMENT ON COLUMN folletos.fecha_fin          IS 'NULL para Ofertomat, que no expone fecha de fin';
COMMENT ON COLUMN folletos.perfil_ocr         IS 'Perfil de preprocesamiento: color_normal, color_suave, etc.';
COMMENT ON COLUMN folletos.motor_ocr          IS 'Motor OCR usado: easyocr';


-- -----------------------------------------------------------------------------
-- paginas
-- Páginas individuales de cada folleto con métricas de calidad OCR/NLP
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS paginas (
    id                  SERIAL      PRIMARY KEY,
    folleto_id          INTEGER     NOT NULL REFERENCES folletos(id) ON DELETE CASCADE,
    numero_pagina       INTEGER     NOT NULL,
    archivo_imagen      VARCHAR(100),

    -- Métricas OCR
    total_bloques_ocr   INTEGER     DEFAULT 0,
    confianza_ocr_prom  FLOAT,

    -- Métricas NLP
    total_productos     INTEGER     DEFAULT 0,
    total_precios       INTEGER     DEFAULT 0,
    total_promos        INTEGER     DEFAULT 0,
    total_atributos     INTEGER     DEFAULT 0,
    tasa_util           FLOAT,
    procesado_at        TIMESTAMP,

    CONSTRAINT uq_pagina_folleto_num UNIQUE (folleto_id, numero_pagina)
);

COMMENT ON TABLE  paginas           IS 'Páginas individuales de cada folleto';
COMMENT ON COLUMN paginas.tasa_util IS 'Ratio entidades útiles / total bloques OCR (benchmark de calidad)';


-- -----------------------------------------------------------------------------
-- productos_canonicos
-- Catálogo deduplicado de identidades de producto (v3, 22-ago-2026).
-- Semilla: nlp/normalizador.py (CATALOGO_CANONICO, match exacto/fuzzy).
-- Para texto sin match en el catálogo se inserta igual con metodo_norm=
-- 'heuristico' (ver extracciones.metodo_norm) -- así el catálogo crece
-- orgánicamente y las filas heurísticas quedan filtrables/auditables en vez
-- de perderse como texto suelto.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS productos_canonicos (
    id              SERIAL          PRIMARY KEY,
    nombre_canonico VARCHAR(150)    NOT NULL UNIQUE,
    categoria       VARCHAR(60),
    marca           VARCHAR(80),
    aliases         TEXT[]          NOT NULL DEFAULT '{}',
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  productos_canonicos            IS 'Catálogo deduplicado de productos, uno por identidad canónica';
COMMENT ON COLUMN productos_canonicos.categoria  IS 'Departamento amplio (catalogo_productos.py): alimentos, linea_blanca, etc.';
COMMENT ON COLUMN productos_canonicos.aliases    IS 'Variantes de texto OCR ya vistas para este producto (crece con el tiempo)';


-- -----------------------------------------------------------------------------
-- extracciones
-- Tabla principal del pipeline. Un evento por entidad NLP detectada.
-- Desde v3 (22-ago-2026) tambien persiste filas PRODUCTO y ATRIBUTO (antes
-- se calculaban y se descartaban, solo su texto quedaba embebido en la fila
-- PRECIO asociada por cercania bbox).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS extracciones (
    id              BIGSERIAL               PRIMARY KEY,
    pagina_id       INTEGER                 NOT NULL REFERENCES paginas(id)   ON DELETE CASCADE,
    folleto_id      INTEGER                 NOT NULL REFERENCES folletos(id),
    tienda_id       INTEGER                 NOT NULL REFERENCES tiendas(id),

    -- Clasificación NLP
    tipo            tipo_extraccion_enum    NOT NULL,
    texto_raw       TEXT                    NOT NULL,
    texto_norm      VARCHAR(300),
    categoria_nlp   VARCHAR(60),

    -- Valores numéricos
    valor           FLOAT,
    valor_anterior  FLOAT,
    texto_promo     VARCHAR(300),

    -- Calidad OCR
    confianza_ocr   FLOAT,

    -- Posición en imagen (asociación posicional producto→precio/atributo)
    bbox_x          INTEGER,
    bbox_y          INTEGER,
    bbox_ancho      INTEGER,
    bbox_alto       INTEGER,

    -- Asociación a producto (v3, 22-ago-2026)
    -- producto_extraccion_id: fila PRODUCTO real (misma tabla) que
    --   _asociar_por_cercania/asociar_producto_por_region emparejó con este
    --   PRECIO/ATRIBUTO -- antes solo se copiaba el texto, la fila se perdía.
    -- producto_canonico_id: identidad deduplicada (ver productos_canonicos),
    --   NULL si el producto asociado fue descartado por el normalizador.
    producto_extraccion_id BIGINT              REFERENCES extracciones(id),
    producto_canonico_id   INTEGER             REFERENCES productos_canonicos(id),
    confianza_norm          FLOAT,
    metodo_norm              VARCHAR(20),

    created_at      TIMESTAMP               NOT NULL DEFAULT NOW()
);

-- CREATE TABLE IF NOT EXISTS no-opea sobre una extracciones ya existente (BD
-- de produccion) -- las columnas nuevas de arriba nunca se crearian sin este
-- ALTER explicito. Idempotente para instalaciones nuevas (donde ya vienen en
-- el CREATE TABLE) y necesario para migrar la BD existente.
ALTER TABLE extracciones
    ADD COLUMN IF NOT EXISTS producto_extraccion_id BIGINT  REFERENCES extracciones(id),
    ADD COLUMN IF NOT EXISTS producto_canonico_id    INTEGER REFERENCES productos_canonicos(id),
    ADD COLUMN IF NOT EXISTS confianza_norm           FLOAT,
    ADD COLUMN IF NOT EXISTS metodo_norm               VARCHAR(20);

COMMENT ON TABLE  extracciones                          IS 'Entidades NLP extraídas: un evento por bloque OCR clasificado';
COMMENT ON COLUMN extracciones.texto_raw                IS 'Texto OCR original sin modificar';
COMMENT ON COLUMN extracciones.texto_norm               IS 'Nombre canónico (filas PRODUCTO/PRECIO) o texto limpio';
COMMENT ON COLUMN extracciones.valor                    IS 'Precio actual en MXN o monto de ahorro';
COMMENT ON COLUMN extracciones.valor_anterior           IS 'Precio anterior encontrado por proximidad bbox (≤300px euclidiano)';
COMMENT ON COLUMN extracciones.confianza_ocr            IS 'Score de confianza EasyOCR: 0.0 – 1.0';
COMMENT ON COLUMN extracciones.producto_extraccion_id   IS 'Fila PRODUCTO asociada por cercanía/ROI (self-FK). Solo aplica a PRECIO/ATRIBUTO';
COMMENT ON COLUMN extracciones.producto_canonico_id     IS 'Identidad canónica deduplicada, ver productos_canonicos. NULL si se descartó por ruido';
COMMENT ON COLUMN extracciones.confianza_norm           IS 'Score 0.0–1.0 del match contra productos_canonicos (solo filas PRODUCTO)';
COMMENT ON COLUMN extracciones.metodo_norm              IS 'exacto | fuzzy | fuzzy_bajo | heuristico | sin_match (nlp/normalizador.py)';


-- -----------------------------------------------------------------------------
-- eventos_promo
-- Campañas comerciales detectadas (Julio Regalado, Hot Sale, Buen Fin…)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS eventos_promo (
    id              SERIAL          PRIMARY KEY,
    folleto_id      INTEGER         NOT NULL REFERENCES folletos(id),
    tienda_id       INTEGER         NOT NULL REFERENCES tiendas(id),
    nombre_evento   VARCHAR(100)    NOT NULL,
    texto_raw       VARCHAR(200),
    fecha_inicio    DATE,
    fecha_fin       DATE,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_evento_folleto UNIQUE (folleto_id, nombre_evento)
);

COMMENT ON TABLE  eventos_promo               IS 'Campañas comerciales detectadas en folletos';
COMMENT ON COLUMN eventos_promo.nombre_evento IS 'Slug normalizado: julio_regalado, hot_sale, buen_fin, etc.';


-- -----------------------------------------------------------------------------
-- alertas
-- Monitoreo de precios por producto/tienda (capa BI futura)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alertas (
    id              SERIAL          PRIMARY KEY,
    tienda_id       INTEGER         REFERENCES tiendas(id),
    slug_producto   VARCHAR(200)    NOT NULL,
    umbral_precio   FLOAT           NOT NULL,
    activa          BOOLEAN         NOT NULL DEFAULT TRUE,
    disparada_at    TIMESTAMP,
    created_at      TIMESTAMP       NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  alertas               IS 'Alertas de precio por producto. tienda_id NULL = aplica a todas las tiendas';
COMMENT ON COLUMN alertas.slug_producto IS 'Slug del nombre canónico del producto a monitorear';


-- =============================================================================
-- 3. ÍNDICES
-- =============================================================================

-- folletos
CREATE INDEX IF NOT EXISTS ix_folleto_tienda_fecha  ON folletos     (tienda_id, fecha_inicio);
CREATE INDEX IF NOT EXISTS ix_folleto_fuente        ON folletos     (fuente);
CREATE INDEX IF NOT EXISTS ix_folleto_estado        ON folletos     (estado);

-- extracciones
CREATE INDEX IF NOT EXISTS ix_ext_tipo              ON extracciones (tipo);
CREATE INDEX IF NOT EXISTS ix_ext_tienda_tipo       ON extracciones (tienda_id, tipo);
CREATE INDEX IF NOT EXISTS ix_ext_folleto_pagina    ON extracciones (folleto_id, pagina_id);
CREATE INDEX IF NOT EXISTS ix_ext_valor             ON extracciones (valor);
CREATE INDEX IF NOT EXISTS ix_ext_confianza         ON extracciones (confianza_ocr);
CREATE INDEX IF NOT EXISTS ix_ext_texto_norm_trgm
    ON extracciones USING gin (texto_norm gin_trgm_ops);
CREATE INDEX IF NOT EXISTS ix_ext_producto_extraccion ON extracciones (producto_extraccion_id);
CREATE INDEX IF NOT EXISTS ix_ext_producto_canonico   ON extracciones (producto_canonico_id);

-- productos_canonicos
CREATE INDEX IF NOT EXISTS ix_prodcanon_categoria   ON productos_canonicos (categoria);
CREATE INDEX IF NOT EXISTS ix_prodcanon_nombre_trgm
    ON productos_canonicos USING gin (nombre_canonico gin_trgm_ops);

-- eventos_promo
CREATE INDEX IF NOT EXISTS ix_evento_nombre         ON eventos_promo (nombre_evento);
CREATE INDEX IF NOT EXISTS ix_evento_tienda         ON eventos_promo (tienda_id);
CREATE INDEX IF NOT EXISTS ix_evento_fechas         ON eventos_promo (fecha_inicio, fecha_fin);

-- alertas
CREATE INDEX IF NOT EXISTS ix_alerta_tienda_prod    ON alertas (tienda_id, slug_producto);
CREATE INDEX IF NOT EXISTS ix_alerta_activa         ON alertas (activa);


-- =============================================================================
-- FIN schema.sql
-- =============================================================================
