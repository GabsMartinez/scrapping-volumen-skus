-- =========================================================================
-- schema.sql - se aplica solo automáticamente la PRIMERA vez que se crea
-- el volumen de Postgres (docker-entrypoint-initdb.d). Justo después se
-- carga db/datos/datos.sql (los datos ya scrapeados y curados).
-- =========================================================================

-- El grupo crítico: los 194 códigos que cubren el 85% del movimiento,
-- cargado desde data/entrada/codigos_criticos_dominios.xlsx (ver db/seed_productos.py).
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
    -- copia de conveniencia de las specs estructuradas de scrapes (mismas
    -- columnas, ver más abajo) para poder consultarlas sin JOIN. La fuente
    -- de verdad sigue siendo scrapes/scrapes_ultimo -- estas se repueblan
    -- desde ahí (UPDATE ... FROM scrapes_ultimo), no se editan a mano acá.
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
    -- volumen APROXIMADO de la pieza (no del empaque), calculado desde
    -- dimensiones_texto por enriquecimiento/completar_volumen*.py.
    -- volumen_metodo documenta la fórmula/supuesto y volumen_confianza
    -- qué tan firme es el dato (alta/media/baja + motivo).
    volumen_cm3         NUMERIC,
    volumen_metodo      TEXT,
    volumen_confianza   TEXT,
    creado_en           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Un producto puede tener varios intentos de scrape (reintentos, o más de
-- una fuente/URL); se guarda el historial completo, no solo el último.
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
    -- specs estructuradas, parseadas de descripcion cuando el sitio fuente
    -- las publica en secciones/pares claros (ver db/extraer_specs.py);
    -- quedan NULL cuando la fuente no las expone así, no se inventan.
    material            TEXT,
    acabado             TEXT,
    aprobaciones        TEXT,
    funcion_texto       TEXT,
    tamano              TEXT,
    k_factor            TEXT,
    specs_adicionales   TEXT,
    -- peso/dimensiones: solo poblado donde el fabricante publica una
    -- ficha con tabla real de peso por unidad (ver db/phd_pesos_*.py).
    -- dimensiones_texto son medidas de INGENIERÍA (distancia entre
    -- tornillos, diámetro de varilla, etc.), NO el tamaño de empaque/caja
    -- del producto -- no usar directamente como bounding box de bodega.
    peso_lbs            NUMERIC,
    peso_kg             NUMERIC,
    dimensiones_texto   TEXT,
    dimensiones_fuente  TEXT,
    scrapeado_en    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scrapes_codigo ON scrapes(codigo);

-- Catálogo crudo de cada fabricante (todo lo que el spider de ese dominio
-- pudo recorrer). Independiente de productos_criticos: no todo lo que
-- publica el fabricante corresponde a uno de nuestros códigos, y el
-- cruce código->producto_catalogo se hace aparte (ver matchers/*.py),
-- porque nuestros códigos internos (ej. "B240", "P1G73") NO coinciden
-- literalmente con el modelo del fabricante (ej. "MODEL 240"): hay que
-- normalizar y machear, no buscar texto exacto en el sitio.
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

-- Vista de conveniencia: el MEJOR scrape conocido por código (lo que
-- eventualmente se sincroniza a Supabase). "Mejor" no es "más reciente":
-- un código puede tener intentos en más de un dominio (ej. MECH se prueba
-- primero en fu-mech.com y, si no aparece ahí, en meide.mx) y si el
-- dominio que falló se vuelve a correr después del que sí tuvo éxito, un
-- ORDER BY scrapeado_en DESC simple mostraría el 'no_encontrado' más
-- nuevo en vez del 'ok' más viejo. Por eso 'ok' siempre gana primero, y
-- entre estados iguales se desempata por más reciente.
CREATE OR REPLACE VIEW scrapes_ultimo AS
SELECT DISTINCT ON (codigo) *
FROM scrapes
ORDER BY codigo, (estado = 'ok') DESC, scrapeado_en DESC;
