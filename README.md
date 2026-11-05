# scraper-precios

Scrapea descripción, serie, specs, peso, volumen y precio (cuando el sitio
lo publica) de los **194 códigos críticos** (85% del movimiento) en los
sitios oficiales de sus fabricantes, y lo deja en Postgres y en un
reporte Excel.

Estado actual de la base (`db/datos/datos.sql`): 194/194 con match,
173 con material, 166 con volumen, 27 con peso, 12 con precio de lista.

## Estructura

```
scraper_precios/
├── main.py                   # punto de entrada único: python main.py <comando>
├── docker-compose.yml        # Postgres + contenedor scraper (Scrapy + Playwright)
├── Dockerfile
├── requirements.txt
├── scrapy.cfg
├── .env.example              # plantilla de .env (puerto, credenciales, Supabase)
├── scripts/
│   ├── correr.ps1            # atajos Windows:     .\scripts\correr.ps1 excel
│   └── correr.sh             # atajos Linux/Mac:   scripts/correr.sh excel
├── scraper_precios/          # paquete Scrapy
│   ├── config.py             # rutas + conexión a Postgres (un solo lugar)
│   ├── settings.py, items.py, pipelines.py
│   └── spiders/              # mech_catalogo_spider (fu-mech.com)
├── crawlers/                 # crawlers fuera de Scrapy (Reliable: WAF; PHD: JS)
├── matchers/                 # un archivo por marca: código interno <-> fabricante
├── enriquecimiento/          # specs, peso y volumen (en orden, ver main.py)
├── reportes/
│   └── exportar_excel.py     # genera el Excel
├── herramientas/             # scripts de investigación/auditoría (PDFs, boletines)
├── db/
│   ├── schema.sql            # tablas + vista scrapes_ultimo
│   ├── schema_supabase.sql   # mismo esquema con RLS para Supabase
│   ├── datos/datos.sql       # TODOS los datos ya scrapeados y curados
│   ├── seed_productos.py     # carga el Excel de entrada
│   └── limpiar_dump.py
├── data/
│   ├── entrada/              # codigos_criticos_dominios.xlsx (input)
│   ├── fuentes/              # PDFs usados por los matchers (price book TYCO, fichas)
│   ├── capturas_fuentes/     # PDF de cada página fuente + manifiesto.csv (auditoría)
│   ├── boletines_reliable/   # boletines PDF de Reliable + texto extraído
│   └── exploracion/          # HTML/PNG/PDF sueltos de la investigación
├── salidas/excel/            # aquí se genera el reporte Excel
└── docs/
    ├── HISTORIAL.md          # metodología y decisiones, dominio por dominio
    ├── FALTANTES.md          # qué falta y por qué, ronda por ronda
    ├── SEGUIMIENTO_PAGINAS.md
    └── MIGRACION_SUPABASE.md
```

## Cómo correrlo

Requisito: Docker. La primera vez que se levanta, Postgres crea las tablas
y carga `db/datos/datos.sql` solo: no hace falta volver a scrapear nada.

```powershell
# Windows (PowerShell)
.\scripts\correr.ps1 levantar     # construye y levanta todo, muestra el estado
.\scripts\correr.ps1 excel        # genera salidas\excel\reporte_scraper_precios.xlsx
.\scripts\correr.ps1 estado       # conteos de la base
.\scripts\correr.ps1 respaldar    # guarda la base en db\datos\datos.sql
.\scripts\correr.ps1 psql         # consola SQL
.\scripts\correr.ps1 bajar        # apaga (los datos quedan en el volumen)
```

En Linux/Mac/Git Bash es igual con `scripts/correr.sh <comando>`.
Postgres queda en `localhost:5437` (cambiable con `DB_PUERTO_HOST` en `.env`).

Sin los atajos, todo es `docker compose exec scraper python main.py <comando>`:

| Comando | Qué hace |
|---|---|
| `estado` | conteos: con match, material, peso, volumen, precio |
| `excel [--salida ruta]` | genera el reporte Excel (solo lee la base) |
| `seed` | carga `data/entrada/codigos_criticos_dominios.xlsx` |
| `crawl [mech\|reliable\|phd\|todos]` | recorre el catálogo de los fabricantes |
| `match [marca\|todos]` | cruza códigos internos contra el catálogo |
| `enriquecer [paso\|todos]` | specs, peso y volumen, en orden |
| `pipeline` | seed + crawl + match + enriquecer + excel |
| `listar` | muestra crawlers, matchers y pasos |

## El Excel

`python main.py excel` genera `salidas/excel/reporte_scraper_precios.xlsx`:

- **Resumen**: avance por marca (códigos, % del movimiento, con match,
  material, peso, volumen, precio) con fila de totales.
- **Productos**: una fila por código: datos internos, mejor fuente
  (con link), specs, peso, dimensiones, volumen y su confianza.
- **Pendientes**: códigos sin volumen y qué más les falta.
- **Scrapes**: historial completo de intentos.
- **Catalogo**: catálogo crudo crawleado de cada fabricante.
- **Columnas**: qué significa cada columna.

El volumen es una aproximación de la pieza a partir de medidas de
ingeniería del fabricante, no el tamaño del empaque.

## Antes de re-correr matchers o enriquecimiento

La base actual tiene correcciones manuales hechas ronda por ronda (ver
`docs/FALTANTES.md`). Los matchers **borran y reinsertan** los scrapes de
su dominio, y varios `completar_*.py` **agregan** texto a
`specs_adicionales` (correrlos dos veces duplica notas). Por eso `match`,
`enriquecer` y `pipeline` se niegan a correr si la base ya tiene datos,
salvo con `--forzar`. Antes de forzar: `respaldar`.

## Correr sin Docker

Con Postgres accesible y `pip install -r requirements.txt` (+
`playwright install chromium` para crawlers), desde la raíz:
`python main.py <comando>`. La conexión se toma de `DB_HOST`, `DB_PORT`,
`DB_NAME`, `DB_USER`, `DB_PASSWORD` (ver `scraper_precios/config.py`).

## Más detalle

- `docs/HISTORIAL.md`: por qué cada sitio necesitó su propio crawler o
  matcher, auditorías de falsos positivos y decisiones tomadas.
- `docs/FALTANTES.md` y `docs/SEGUIMIENTO_PAGINAS.md`: lo que falta y por qué.
- `docs/MIGRACION_SUPABASE.md`: cómo subir esquema y datos a Supabase.
