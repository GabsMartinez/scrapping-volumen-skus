# Migración a Supabase

Estado: el schema y los datos ya están listos para subir. No se hizo la subida
real porque requiere credenciales de un proyecto Supabase que solo tú tienes.

## Qué se preparó

- **`schema_supabase.sql`** — mismas 3 tablas + vista que `schema.sql` (el que usa
  el Postgres local), pero con RLS habilitado: lectura pública, escritura solo
  con la `service_role key` o conexión directa admin.
- **`db/datos/datos.sql`** — los 822 registros actuales (194 productos +
  228 scrapes + 400 páginas de catálogo) como `INSERT` statements, generado con
  `pg_dump --data-only --column-inserts` desde el Postgres local. Incluye el
  `setval` de las secuencias `scrapes_id_seq` / `catalogo_fabricante_id_seq` al
  final, así los próximos inserts (nuevos scrapes) no chocan con IDs ya usados.
- Se corrigieron las 12 filas de TYCO que apuntaban a `/app/fuentes/...` (ruta
  del contenedor local, inválida fuera de él) — ahora apuntan a
  `https://www.tyco-fire.com/americas-price-book` (la página pública real), con
  el número de página del PDF movido al campo `detalle`.

## Pasos para migrar (cuando tengas el proyecto Supabase)

1. **Crear el proyecto** en supabase.com si no existe uno todavía.
2. **Aplicar el schema**: Dashboard → SQL Editor → pegar el contenido completo
   de `schema_supabase.sql` → Run.
3. **Cargar los datos**: dos formas, cualquiera funciona con solo 822 filas:
   - Pegar `db/datos/datos.sql` completo en el mismo SQL Editor y correr.
   - O por línea de comandos, con el connection string de la sección
     *Project Settings → Database → Connection string* (usar el modo *Session*,
     no *Transaction pooling*, para que corran bien los `setval`):
     ```
     psql "postgresql://postgres:<password>@<host>:5432/postgres" -f db/datos/datos.sql
     ```
4. **Verificar**: `SELECT count(*) FROM productos_criticos;` debería dar 194.
5. **Apuntar los scripts locales a Supabase** (opcional, si quieres seguir
   scrapeando directo contra la nube en vez de local): cambiar las variables
   `DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD` que usan
   `db/seed_productos.py` y `matchers/*.py` por los del connection string de
   Supabase (usar la conexión directa de Postgres, no la API REST — estos
   scripts hacen `INSERT`/`UPDATE` en bruto y como no son `anon`/`authenticated`
   no chocan con las políticas de RLS).

## Pendiente / a tu criterio

- **RLS de lectura pública**: se dejó `USING (true)` para SELECT porque es un
  catálogo de productos, no hay dato sensible (precios de lista públicos,
  descripciones de fabricante). Si vas a exponer esto detrás de un frontend
  público y NO quieres que cualquiera con la URL del proyecto pueda leer todo
  vía la API REST, avísame y lo cambiamos a requerir `authenticated`.
- **Los 2,429 códigos fuera del grupo crítico** (85%→100% del movimiento) no
  están en este export — solo se scrapearon los 194 del grupo crítico. Si
  quieres subir también el ranking completo como tabla de referencia (sin
  scrapear), es un paso aparte.
