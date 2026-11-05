-- =========================================================================
-- schema_supabase.sql - versión de schema.sql lista para pegar en el
-- SQL Editor de Supabase (o correr con psql contra el connection string
-- de Supabase). Diferencias contra db/schema.sql:
--
--   1. RLS (Row Level Security) habilitado en las 3 tablas. Supabase
--      expone automáticamente cualquier tabla vía su API REST
--      (PostgREST) usando la clave "anon" — sin RLS, esa clave podría
--      leer Y ESCRIBIR todo. Acá se agrega:
--        - Lectura pública (anon + authenticated): sí, es un catálogo
--          de productos, no hay dato sensible.
--        - Escritura: NINGUNA policy para anon/authenticated -> solo se
--          puede escribir con la "service_role key" (que Supabase hace
--          bypass RLS automáticamente) o conectándose directo por
--          Postgres con la connection string de admin. Los scripts
--          (seed_productos.py, matchers/*.py) deben usar esa conexión
--          directa o la service_role key, NUNCA la anon key.
--   2. La vista scrapes_ultimo se marca security_invoker=true (PG 15+,
--      que es lo que usa Supabase) para que respete el RLS de la tabla
--      scrapes en vez de correr con los privilegios del dueño de la vista.
--
-- Cómo aplicar:
--   Opción A (rápida, sin datos): pegar este archivo completo en
--     Supabase Dashboard -> SQL Editor -> Run.
--   Opción B (con datos): ver docs/MIGRACION_SUPABASE.md.
-- =========================================================================

CREATE TABLE IF NOT EXISTS productos_criticos (
    codigo              TEXT PRIMARY KEY,
    nombre_producto     TEXT,
    marca               TEXT,
    modelo              TEXT,
    familia             TEXT,
    movimiento_total    NUMERIC,
    pct_acum            NUMERIC,
    dominios_oficiales  TEXT,
    tiene_dominio       BOOLEAN NOT NULL DEFAULT FALSE,
    -- copia de conveniencia de las specs de scrapes -- ver schema.sql.
    material            TEXT,
    acabado             TEXT,
    aprobaciones        TEXT,
    funcion_texto       TEXT,
    tamano              TEXT,
    k_factor            TEXT,
    specs_adicionales   TEXT,
    peso_lbs            NUMERIC,
    peso_kg             NUMERIC,
    dimensiones_texto   TEXT,
    dimensiones_fuente  TEXT,
    -- volumen aproximado de la pieza -- ver schema.sql.
    volumen_cm3         NUMERIC,
    volumen_metodo      TEXT,
    volumen_confianza   TEXT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrapes (
    id              SERIAL PRIMARY KEY,
    codigo          TEXT NOT NULL REFERENCES productos_criticos(codigo),
    dominio         TEXT NOT NULL,
    url_fuente      TEXT,
    descripcion     TEXT,
    serie           TEXT,
    precio          TEXT,
    moneda          TEXT,
    estado          TEXT NOT NULL CHECK (estado IN ('ok', 'no_encontrado', 'error')),
    detalle         TEXT,
    material            TEXT,
    acabado             TEXT,
    aprobaciones        TEXT,
    funcion_texto       TEXT,
    tamano              TEXT,
    k_factor            TEXT,
    specs_adicionales   TEXT,
    -- dimensiones_texto son medidas de INGENIERÍA, NO tamaño de empaque/
    -- caja -- no usar directamente como bounding box de bodega.
    peso_lbs            NUMERIC,
    peso_kg             NUMERIC,
    dimensiones_texto   TEXT,
    dimensiones_fuente  TEXT,
    scrapeado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scrapes_codigo ON scrapes(codigo);

CREATE TABLE IF NOT EXISTS catalogo_fabricante (
    id              SERIAL PRIMARY KEY,
    dominio         TEXT NOT NULL,
    url             TEXT NOT NULL,
    titulo          TEXT,
    modelo_detectado TEXT,
    descripcion     TEXT,
    scrapeado_en    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (dominio, url)
);

-- 'ok' siempre gana sobre 'no_encontrado'/'error', aunque sea más viejo
-- (un código puede tener intentos en más de un dominio; ver schema.sql).
CREATE OR REPLACE VIEW scrapes_ultimo AS
SELECT DISTINCT ON (codigo) *
FROM scrapes
ORDER BY codigo, (estado = 'ok') DESC, scrapeado_en DESC;

ALTER VIEW scrapes_ultimo SET (security_invoker = true);

-- =========================================================================
-- RLS: lectura pública, escritura solo con service_role / conexión directa.
-- =========================================================================
ALTER TABLE productos_criticos   ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrapes              ENABLE ROW LEVEL SECURITY;
ALTER TABLE catalogo_fabricante  ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Lectura pública" ON productos_criticos
    FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY "Lectura pública" ON scrapes
    FOR SELECT TO anon, authenticated USING (true);

CREATE POLICY "Lectura pública" ON catalogo_fabricante
    FOR SELECT TO anon, authenticated USING (true);
