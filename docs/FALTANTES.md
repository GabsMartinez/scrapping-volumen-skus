# Faltantes de volumen (`volumen_cm3`) — estado al 2026-08-11 (ronda 2 + ronda MECH + ronda P1N + ronda codo 90 + ronda revisión MECH thumbnails + ronda reclasificación 1N + ronda catálogo maestro + ronda fichas individuales meide.mx + ronda ANVIL FIG69 + ronda seguimiento página-por-página)

De 194 códigos críticos, **166 tienen volumen calculado** (verificado
directo en la base: `SELECT marca, COUNT(*) FILTER (WHERE volumen_cm3 IS
NOT NULL) FROM productos_criticos GROUP BY marca`). Quedan **28 sin
volumen**. Este archivo combina el resultado de diez rondas — todas con
sección propia más abajo.

## Ronda seguimiento página-por-página (2026-08-11) — resolución de 2/4 códigos TYCO + hallazgos en Reliable/PHD/MECH

El usuario armó su propia lista de seguimiento por página (`SEGUIMIENTO_PAGINAS.md`)
y aportó links nuevos para cada bloque pendiente. Resultado por bloque:

**TYCO — 2 de 3 códigos resueltos.** El link que el usuario encontró
(`tyco.widen.net/s/dxcjwj2w5b/tfpp_pb_08-26_v1`) es el Price Book completo
de TYCO (245 páginas) — no trae diagramas, pero cada renglón de precio
indica la ficha técnica (TFP) exacta a usar por SIN, lo que permitió
confirmar con certeza (sin adivinar por nombre parecido) cuál ficha
corresponde a cada uno de los 3 códigos restantes:

- **`73A3B2A1`** (TY3331, TY-FRB Horizontal Sidewall) → **TFP176**, Figura 1
  (ya descargada de una ronda anterior, pero solo se había leído el texto,
  no visto la imagen completa). Trae diagrama acotado real: diámetro del
  deflector (punto más ancho) 1-13/16" (46.0mm) y largo total del cuerpo
  (cara de conexión a superficie de asiento del escudo) 2-3/16" (55.6mm).
  **Resuelto**: cilindro envolvente, **92.40 cm³**, confianza **media**
  (deflector tipo abanico, no un disco perfecto — mismo criterio ya usado
  en TY9226 ESFR).
- **`73PQBROI12`** (TY3531, Series RFII Concealed Pendent) → **TFP181**,
  Figura 2 (misma ficha ya usada para el escudo `72ESBLI012`, pero esta
  vez se leyó la Figura 2, que da las dimensiones del **conjunto
  cuerpo+copa de soporte**, distintas de las del escudo/cover plate:
  diámetro de agujero de paso C = 2-3/8 a 2-5/8" (60.3-66.7mm) y
  profundidad instalada D = 1-3/4 a 2-1/4" (44.5-57.2mm). **Resuelto**:
  cilindro envolvente usando el punto medio de cada rango, **161.03 cm³**,
  confianza **media** (son holgura de instalación, no una medida fija
  única).
- **`75B1B2A2`** (TY5137, Series EC-11 Upright) → **TFP220**. Revisada a
  fondo (8 páginas) incluyendo las que no se habían leído antes: Figura 1
  solo acota alturas (2-7/16"/61.9mm total, 1-11/16"/42.7mm cuerpo,
  1/2"/12.7mm nominal make-in) — **no hay diámetro/ancho del cuerpo en
  ningún diagrama**. Las medidas de escudo de las Figuras 2-6 (2-7/8" DIA,
  etc.) son de las versiones **pendent** (TY5237/TY6237) con escudo
  empotrado — no aplican a nuestro código, que es **upright** (sin
  escudo). **Sigue sin volumen**, mismo tipo de vacío que ERICO
  FIG300/310 — confirmado exhaustivamente, no por falta de revisión.

**RELIABLE — boletín equivocado corregido, pero sigue sin volumen.** El
074.pdf que trajo el usuario es el boletín correcto para el sitio pero
para el SIN equivocado (RA1414/RA1425/RA1435/RA1485, familia F1FR56) —
nuestro código `73PQRBRO12` tiene SIN RA3415 (modelo G5-56), que
pertenece al **Boletín 034** (encontrado por búsqueda dirigida por el
SIN, no por la página de producto del sitio, que llevaba a un boletín
distinto — el 051, modelo DRY de otro SIN — revisado y descartado en una
ronda anterior). El Boletín 034 sí confirma material exacto (Body Brass
Alloy, Levers/Deflector/Load Screw Bronze Alloy) y dimensión real del
cuerpo/copa: diámetro 2-5/16" (58mm), Figura 3. **Pero no acota una
altura total del cuerpo** (el único otro número, D=1-3/4 a 2-1/4", es la
holgura de instalación del conjunto completo con cover plate, no la
altura del cuerpo solo) — **sigue sin volumen**, mismo tipo de vacío que
ERICO y TY5137.

**PHD — confirmado cerrado por 2ª fuente independiente.** El usuario
encontró que la página de categoría (`sway-brace-pipe-attachment/`) tiene
un link "View Data Sheet" por producto, llevando a un PDF individual
(`031_11-12-25.pdf`, distinto del catálogo maestro ya revisado). Mismo
resultado: el diagrama (Longitudinal/Front View/Side View/Lateral) no
trae una sola medida acotada, solo ángulos de instalación (30°, 30-90°).
Confirma el cierre ya documentado, ahora con una segunda fuente
independiente revisada.

**MECH tubería roja — confirmado cerrado, 4 catálogos nuevos revisados.**
El usuario encontró 4 catálogos grandes de meide.mx (grooved fittings,
soportería, 2 de válvulas) — se revisaron completos (página por página,
buscando "random length"/"standard length"/A795) y **ninguno menciona
tubería como tal** (son de fittings, soportes y válvulas, no de tubo).
No aportan nada nuevo — confirma que el largo de barra sigue sin
publicarse en ningún documento del fabricante, van 8 documentos distintos
revisados en total entre esta ronda y la anterior.

**ERICO FIG300/310 — sigue pendiente.** El usuario pasó el contenido
completo de la pestaña "Details" de nvent.com (tabla + diagrama con
letras A/FT/RS/F1) — coincide exactamente con los mismos 3 valores ya
conocidos del PDF (Rod Size, ancho de cuello A, espesor máximo de ala
FT) más las cargas estáticas F1/F2, que no son medidas de tamaño. **4ª
fuente que confirma el mismo vacío**: no se publica el eje de altura
total ni el de largo a lo largo de la viga en ningún lado. Se mantiene
sin volumen.

Sincronizado a Supabase (166/194). SQL en
`db/export/` vía archivo temporal (mismo patrón de toda la sesión).
PDFs nuevos guardados en `data/capturas_fuentes/` (reliablesprinkler.com,
phd-mfg.com, meide.mx — ver `manifiesto.csv`).

## Nota metodológica: ¿cuántos códigos son en realidad un "rango de tallas"? (2026-08-11)

Se verificó explícitamente sobre los 194 códigos si `6A20012341` (ANVIL
FIG69, ver ronda abajo) era un caso aislado o si había más códigos donde
el nombre interno no especifica una talla puntual (que sería un problema
mucho más grande de lo pensado). Importante: **que la ficha del
fabricante tenga una tabla con muchas tallas es normal y no es el
problema** — eso pasa en casi todas las fichas de este proyecto, y
siempre se sabe qué fila usar porque el nombre del código ya trae la
talla exacta (ej. "TAPA RAN 2\""). El problema real sería que el
**código mismo** no especificara una talla puntual.

Se probaron 2 búsquedas sobre `nombre_producto` de los 194:
1. Patrón de rango real (comilla de pulgada + guion + otra medida, ej.
   `1/2"-1"`) — **excluye** falsos positivos como fracciones mixtas
   (`1-1/4"`, sin comilla antes del guion), números de figura
   (`FIG 031-030`), y part numbers (`4098-9714`). Resultado: **solo
   `6A20012341`**.
2. Códigos sin ninguna talla explícita en el nombre (ni fracción, ni
   comilla, ni K-factor). Resultado: 3 códigos (`73EBROW512`,
   `SI40989792`, `SI40989714`) — pero los 3 ya tenían volumen cargado
   porque son productos de modelo único sin dimensión de tubería (un
   escudo por modelo, un sensor de humo, una base de sensor), no
   códigos de rango.

**Conclusión: `6A20012341` es el único código de rango de tallas en los
194.** No hace falta re-auditar el resto.

## Ronda ANVIL FIG69 (2026-08-11) — resolución de 1 código

El usuario encontró la pestaña "Technical Data" en la página del
producto en asc-es.com, con un submittal real (`SS-SUB-69-v01`, Anvil
FIG 69 Adjustable Swivel Ring) que trae diagrama con letras A/B/C/F/G
etiquetadas y tabla completa por talla. `6A20012341` es el único código
de rango de tallas del proyecto (ver nota metodológica arriba) — cubre
1/2", 3/4" y 1", cada una con B/G/RodSize reales, dando volúmenes muy
similares entre sí (9.84 a 11.04 cm³, ~11% de spread). Se calcularon
las 3 con caja envolvente B×G×RodSize (mismo patrón que los ganchos
tipo pera de PHD/ERICO, pero acá con 2 ejes reales en vez de 1) y,
confirmado con el usuario, se cargó la talla del medio (3/4") como
representante: **10.56 cm³**, confianza **baja** (por ser código de
rango — la fórmula en sí es media/alta).

## Ronda fichas individuales meide.mx (2026-08-11) — resolución de 15 códigos

El usuario encontró 4 catálogos PDF grandes en meide.mx y pidió
revisarlos. Al buscar en la API REST de WordPress de ese sitio
(`/wp-json/wp/v2/media?search=...`) aparecieron, además de esos 4
catálogos generales, una **biblioteca de fichas individuales por
producto** ("PRODUCT-data-sheet-DS-400-XXX") que no se habían visto
antes — resolviendo de un tiro casi todo lo que quedaba de MECH:

- **STRAP "T Mecánica U-bolt" (modelo 3L/MT1) — 10/10 códigos, RESUELTO.**
  Ficha `DS-400-MT1-01-E` (U-Bolt Mechanical Tee) trae tabla completa
  A/B/C por combinación nominal×hueco — justo lo que ni la página de
  categoría ni el catálogo maestro de fu-mech.com tenían. Caja
  envolvente A×B×C real, confianza **alta**. Volúmenes: 2"×1"=363.05cm³,
  3"×1"=836.22cm³, 1½"×1"=309.17cm³, 1¼"×1"=293.40cm³,
  2"×1¼"=607.39cm³, 2½"×1"=452.24cm³, 1½"×½"=293.40cm³,
  1½"×¾"=293.40cm³, 1¼"×½"=276.61cm³, 1¼"×¾"=276.61cm³. Material
  confirmado: Hierro dúctil ASTM A536 Grade 65-45-12.
- **Tapa ranurada simple 300/300TX — 4/4 códigos, RESUELTO.** Ficha
  `DS-CP-300-01-E` (Cap, sin agujero) — el fabricante SÍ publica la
  tapa simple que necesitábamos, solo que en una ficha individual
  distinta a la tabla "300 con agujero" del catálogo maestro de
  fu-mech.com. Cilindro real π×(D/2)²×L, confianza **alta**:
  1¼"=33.18cm³, 1½"=43.06cm³, 2"=67.11cm³, 2½"=98.36cm³.
- **`3E12002112` (reductor 240, 2"×1½") — confirmado.** Ficha
  `DS-400-RC-02-E` (Grooved Concentric Reducer) confirma L=64mm,
  el mismo valor ya usado en las otras 4 combinaciones vía el catálogo
  maestro de fu-mech.com — 2 fuentes independientes del mismo
  fabricante coinciden exacto. 232.71cm³, confianza **media**.

**Revisado y confirmado que NO resuelve nada nuevo**: el folleto
`STEEL-PIPE-BROCHURE-2026.3.12.pdf` (tubería roja A795/A53) trae peso
por metro y tolerancias, pero **no publica un largo de barra estándar**
("Length tolerance is +20mm/0" — tolerancia sobre lo que se pida, no un
largo fijo). Confirma que el dato sigue sin publicarse; los 10 códigos
de tubería roja quedan sin volumen.

PDFs guardados en `data/capturas_fuentes/meide.mx/ficha_real_DS-*.pdf`.

Revisando el pie de página de varias fichas MECH ya descargadas
("01-GROOVED BROCHURE V12.indd"), se dedujo que todas son recortes de un
**catálogo maestro de 88 páginas** ("MECH-GROOVED-NEW-.pdf", 11.8MB).
Se encontró vía búsqueda en la API REST de WordPress
(`/wp-json/wp/v2/media?search=grooved`) y se descargó completo.

Este catálogo trae tablas **limpias y completas** para 1N/1NS/1NH/240 —
resolviendo ambigüedades y corrupciones de texto que los recortes
individuales (de una sola página) no permitían leer con certeza:

**Acople 1N/1NS — 7 códigos, todos confirmados o corregidos, confianza sube a alta:**
- `3A20000003`, `3A20000114`, `3A20000212`: **confirmados exactos** (mismo
  valor que ya estaba cargado, ahora con una segunda fuente limpia).
- `3A20000002` (2"): **corregido** de 473.00 cm³ (supuesto de reducción,
  ronda P1N original) a **456.50 cm³** (A=83, B=125, C=44mm — fila limpia
  del catálogo maestro, no existía antes en ninguna fuente legible).
- `3A20000004` (4"): **corregido** de 1311.00 cm³ a **1435.50 cm³** — el
  recorte individual solo tenía legible la variante O.D. 108.0mm (una
  variante de schedule distinta); el código interno dice "114" (O.D.
  114.3mm), que en el recorte individual estaba corrupta. El catálogo
  maestro trae ambas variantes limpias: A=145, B=198, C=50mm.
- `3A20000006` (6", P1NS): corrección menor de 2756.00 a **2766.40 cm³**
  (B=266 en vez de 265mm, mismo dato, versión limpia sin ruido de OCR).
- `3A20000112` (1½"): **resuelto por primera vez** — su fila estaba
  corrupta en las 2 fuentes anteriores (recorte individual y su texto
  oculto). El catálogo maestro la trae limpia: A=70, B=110, C=44mm →
  **338.80 cm³**.

**Reductor concéntrico 240 — 4 códigos, resueltos por primera vez:**
la tabla del recorte individual (`ficha_real_conc-red-grvd-model-240.pdf`)
solo cubría desde 6" en adelante; el catálogo maestro trae la tabla
COMPLETA desde 1¼"×1" hasta 24"×20", incluyendo las 4 combinaciones que
necesitábamos, todas con L=64mm:
  - `3E12002114` (2"×1¼"): 232.71 cm³
  - `3E12002122` (2½"×2"): 341.06 cm³
  - `3E12112114` (1½"×1¼"): 149.30 cm³
  - `3E12212112` (2½"×1½"): 341.06 cm³
  (Caja envolvente L×D×D, D=O.D. del lado grande, confianza media —
  mismo patrón que otras piezas MECH de un solo eje de longitud real.)

**Confirmado que NO resuelve (revisado a fondo en las 88 páginas):**
- **STRAP/"3L" (U-Bolt Mechanical Tee)**: el catálogo SÍ nombra el
  producto (página 12, índice; página 73, instrucciones de instalación)
  pero **no incluye ninguna tabla de dimensiones para él** en todo el
  documento — confirma que sigue sin dato, no es que no se buscara.
- **End Cap 300/300TX**: el catálogo trae la tabla completa de "300"
  (Cap with Concentric Hole) y "300PX" (Cap with Eccentric Hole), pero
  **todas las filas son tapas CON agujero** de una talla menor en el
  centro — nuestros códigos son tapas simples sin agujero, y ese
  producto no aparece en ninguna de las 88 páginas.

Catálogo guardado en
`data/capturas_fuentes/fu-mech.com/ficha_real_catalogo-maestro-MECH-GROOVED-NEW.pdf`.

## Ronda reclasificación 1N no-reductora (2026-08-11) — corrección de 4 códigos

Al revisar los 32 códigos MECH restantes (ronda anterior), se encontró
texto oculto (fuera del área visible/imprimible) en el mismo PDF del
acople 1N: una **segunda tabla, para un producto NO reductor** ("1N
Flexible Coupling" y "1NS Light-duty Flexible Coupling" — talla única
por fila, a diferencia de la tabla reductora usada en la ronda P1N
original, que junta 2 tallas por fila). Se verificó manualmente con
`pdfplumber.extract_words()` filtrando por coordenadas fuera del
mediabox del PDF, confirmando fila por fila cuáles estaban limpias y
cuáles corruptas (texto de 2 filas superpuesto en las mismas
coordenadas, por ser un recorte de un catálogo más ancho a 2 páginas).

El código interno de estos productos (ej. "P1N 89" = solo "3", una
talla) encaja de forma más literal con la tabla no-reductora (una talla
por fila) que con la reductora (donde había que asumir "reducido un
paso hacia abajo"). Se recalcularon 4 de los 5 códigos ya cargados en
la ronda P1N, con confianza **media** (sube de "baja", porque ya no
hace falta ningún supuesto — es lectura directa de la fila que coincide
exacto con la talla):

| Código | Talla | Valor anterior (reductor, supuesto) | Valor nuevo (no-reductor, directo) |
|---|---|---|---|
| `3A20000003` | 3" | 888.72 cm³ (baja) | **828.00 cm³** (A=115, B=160, C=45mm) |
| `3A20000004` | 4" | 1465.20 cm³ (baja) | **1311.00 cm³** (A=138, B=190, C=50mm) |
| `3A20000212` | 2½" | 621.00 cm³ (baja) | **617.76 cm³** (A=96, B=143, C=45mm) |
| `3A20000006` | 6" (P1NS) | 2733.60 cm³ (media) | **2756.00 cm³** (A=200, B=265, C=52mm) |

`3A20000002` (2") **se quedó con el valor anterior** (473.00 cm³, confianza
baja): la fila equivalente en la tabla no-reductora (50mm/2") también
está corrupta/superpuesta en el PDF, sin dato limpio alternativo.
`3A20000114` (1¼") ya se había cargado en la ronda anterior directamente
desde esta misma tabla no-reductora (297.44 cm³, fila limpia, sin
cambios). `3A20000112` (1½") sigue sin volumen — su fila en ambas tablas
está corrupta.

Sincronizado a Supabase. Cálculo documentado directamente en
`volumen_metodo`/`volumen_confianza` de cada código (no hay script
separado para este ajuste puntual, se aplicó por SQL directo).

## Ronda "revisión MECH thumbnails" (2026-08-10, noche) — resolución de 2/32 códigos

El usuario pidió revisar de nuevo TODAS las ~32 familias MECH que seguían
sin volumen, buscando específicamente el mismo patrón que resolvió el
codo 90° (una imagen thumbnail de WordPress del PDF, tipo
`nombre-pdf-WIDTHxHEIGHT-N.jpg`, no un botón de descarga obvio).

**Búsqueda del patrón del codo 90°**: se revisaron las 6 páginas objetivo
(fu-mech.com: end-cap-300tx, conc-red-grvd-model-240, mech-tee-thd-model-3j,
red-coupling-model-1n; meide.mx: jinan-mech-piping, coples-y-conexiones-
ranuradas) de dos formas — HTML estático vía `curl` y render completo con
Playwright (JS/DOM final, igual que vería un usuario real en navegador,
capturado porque se detectó que al menos una página del sitio —
elbow-90-model-90x, donde el usuario encontró el thumbnail a mano— tiene
la sección de "DOWNLOAD" vacía en el HTML servido por `curl` y poblada
solo vía JS). **Resultado: ninguna de las 6 páginas tiene el patrón de
thumbnail del PDF**, ni en HTML estático ni en el DOM final renderizado.
Se confirmó además (sitemaps de fu-mech.com y meide.mx) que no existe
ninguna página de producto individual para "STRAP P3L"/"3L" en ningún
dominio.

**Hallazgo distinto (no buscado, pero real)**: al inspeccionar con
`pdfplumber` los PDFs ya descargados en la ronda MECH anterior, se
encontró que varios de ellos tienen texto embebido **fuera del área
visible/imprimible de la página** (el `mediabox` de estos PDFs mide
665.6pt de ancho, pero hay palabras con coordenada x0 hasta 1150pt o
negativa hasta -1100pt) — son recortes de una página de un catálogo
impreso más ancho (spread a 2 páginas), y el contenido de texto de la
página vecina quedó fusionado en el mismo stream de texto al recortar
para el botón de descarga del sitio, aunque nunca se dibuja/imprime.
Se extrajo con `pdfplumber.extract_words()` filtrando por coordenada x
fuera del mediabox y agrupando por `top`, verificando palabra por palabra
que no hubiera caracteres intercalados de otra fila superpuesta (varios
candidatos SÍ estaban corruptos por superposición de dos páginas en las
mismas coordenadas y se descartaron sin usar):

- **`3B32004212`** (Tee 3J, 4"×2-1/2") — el texto fuera de mediabox del
  PDF `ficha_real_mech-tee-thd-model-3j.pdf` es la **continuación de la
  misma tabla 3J** (confirmado por header y progresión de tallas
  continua). Fila "100×65 / 114.3×73.0" limpia, coincide exacto con el
  código interno "P3JS 114X73": A=188, B=104.5, C=102, D=70mm. **Resuelto,
  confianza media-alta** (dato real de tabla oficial, pero método de
  extracción inédito en este proyecto — flageado para verificación
  independiente del usuario, ver lista en el reporte).
- **`3A20000114`** (P1N 42, 1-1/4") — el texto fuera de mediabox del PDF
  `ficha_real_red-coupling-model-1n.pdf` resultó ser una tabla **"1N
  Flexible Coupling" (NO reductora)**, distinta de la tabla reductora ya
  usada en la ronda P1N. Fila 32mm/1-1/4" limpia: A=65, B=104, C=44mm →
  **297.44 cm³, confianza media**. **Importante**: esto sugiere que los
  otros 5 códigos P1N ya cargados en la ronda anterior con el supuesto
  "reducción un paso hacia abajo" (`3A20000002`, `3A20000003`,
  `3A20000004`, `3A20000212`, y posiblemente `3A20000006`) podrían
  pertenecer en realidad a esta tabla NO reductora en vez de a la
  reductora — **no se tocaron esta ronda** (fuera del alcance de los 32
  códigos asignados), queda pendiente de decidir con el usuario.
- **`3A20000112`** (P1N 48, 1-1/2") — la fila equivalente (40mm) en la
  misma tabla "1N Flexible Coupling" aparece con caracteres de dos filas
  distintas del catálogo superpuestos en las mismas coordenadas
  (superposición real, no legible con certeza) — se dejó sin volumen en
  vez de arriesgar un número mal leído.

**Confirmado sin cambios (30 códigos)** — mismas razones que la ronda MECH
anterior, ya documentadas más abajo en "Familias MECH que siguen sin
volumen": tubería roja A795/A53 (10), STRAP P3L (11), Grooved End Cap
300/300TX (4), Grooved Concentric Reducer 240 (4), y el acople 1N
`3A20000112` (1, ver arriba).

PDFs/filas nuevas documentadas en `data/capturas_fuentes/manifiesto.csv` (sin
descarga de PDF nuevo — mismos archivos ya existentes, releídos con más
profundidad). Cálculo reproducible en `enriquecimiento/completar_volumen_mech.py`
(familias `mech_tee_3j` y `1n_flex_noreductor`).

## Ronda codo 90°/90S (2026-08-10, noche) — resolución manual de 8/8 códigos

El usuario encontró en la página de fu-mech.com una imagen thumbnail de
WordPress (`90°-Elbow-9090S-1-pdf-212x300-1.jpg`) que el agente MECH no
había visto (no era un botón "Click Here To Download" obvio como en el
resto de familias). A partir del nombre del thumbnail se localizó el PDF
completo real: `https://fu-mech.com/wp-content/uploads/2023/01/90°-Elbow-9090S-1.pdf`
(484 KB, tabla oficial con dimensión única `L` por talla para modelos
**90** y **90S** — no existe variante "90X" en este documento, esa
página del sitio parece ser un error de navegación anterior). Los 8
códigos, cerrados con el mismo patrón ya usado en otros codos MECH
(caja envolvente `L×L×D`, D=Pipe O.D. de la misma tabla, confianza
**media**):

| Código | Talla / modelo | L (mm) | D=Pipe O.D. (mm) | Volumen |
|---|---|---|---|---|
| `3C20000001` | 1", modelo 90 | 57 | 33.7 | 109.49 cm³ |
| `3C20000112` | 1½", modelo 90 | 70 | 48.3 | 236.67 cm³ |
| `3C20000114` | 1¼", modelo 90 | 70 | 42.4 | 207.76 cm³ |
| `3C20000002` | 2", modelo 90S | 70 | 60.3 | 295.47 cm³ |
| `3C20000212` | 2½", modelo 90S | 76 | 73.0 | 421.65 cm³ |
| `3C20000003` | 3", modelo 90S | 85.5 | 88.9 | 649.88 cm³ |
| `3C20000004` | 4", modelo 90S | 101 | 114.3 | 1165.97 cm³ |
| `3C20000006` | 6", modelo 90S | 140 | 168.3 | 3298.68 cm³ |

## Ronda P1N (2026-08-10, noche) — resolución manual de 5/7 códigos

El usuario descargó a mano el PDF real de fu-mech.com
(`Reducing-Flexible-Coupling1N-2.pdf`) y confirmó que es **byte-idéntico**
(528,232 bytes) al que el agente MECH ya había usado — no era un problema
de descarga. Revisando la tabla junto con el usuario se encontró que:

- **`3A20000006`** (6", código interno "P1NS") en realidad es la variante
  **1NS** (Light-duty Reducing Coupling), que tiene **una sola fila** en
  toda la ficha — sin ambigüedad. Cargado con confianza **media**:
  A=200mm, B=268mm, C=51mm → **2733.60 cm³**.
- Los otros 6 son variante **1N** (reductor estándar), que sí tiene
  múltiples filas por talla (2"→3 filas candidatas, 3"→5, 4"→7, 2½"→9,
  1½"→2, 1¼"→0). Se aplicó un supuesto explícito, confianza **baja**:
  *"el número interno es el lado GRANDE del reductor, reducido un paso
  estándar hacia abajo"* (por analogía con la familia no-reductora
  1G/1GS, donde el número interno sí es la talla exacta). Esto resolvió
  4 de los 6:
  - `3A20000002` (2"→1½"): A=86, B=125, C=44mm → **473.00 cm³**
  - `3A20000003` (3"→2½"): A=115, B=168, C=46mm → **888.72 cm³**
  - `3A20000004` (4"→3"): A=148, B=198, C=50mm → **1465.20 cm³**
  - `3A20000212` (2½"→2"): A=100, B=138, C=45mm → **621.00 cm³**
  - `3A20000112` (1½") y `3A20000114` (1¼") **quedan sin volumen**: la
    combinación "un paso hacia abajo" (1½"×1") no existe en ninguna
    tabla del fabricante, y 1¼" no existe en absoluto en ningún modelo
    1N/1NS/1NH. No se fuerza el supuesto donde no hay fila que lo
    respalde.

| Dominio (fuente real) | Marca | # sin volumen | Con material | Con dimensiones | Estado |
|---|---|---|---|---|---|
| fu-mech.com + meide.mx | MECH | 10 | 81 | 95 | **95/105 con volumen**: 60 de la ronda MECH + acople 1N (7/7) + codo 90/90S (8/8) + reductor 240 (5/5) + STRAP (10/10) + tapa simple 300 (4/4), estas últimas cinco resueltas manualmente por el usuario revisando el sitio y catálogos del fabricante. Ver sección "Ronda MECH" más abajo para el detalle completo por familia. |
| phd-mfg.com | PHD | 10 | 10 | 0 | Sin volumen (confirmado en `FireProtectionSeismicCatalog_1216.pdf`, catálogo maestro: son ensambles articulados FIG 010/015/031 + FIG 030, sin tabla de dimensión física, solo capacidad de carga). **Peso SÍ se cargó para los 10** (antes en 0): FIG010/015/031 + FIG030 (1.46 lbs fijo), confianza alta salvo FIG010/015 (media — ambigüedad de talla de varilla de arriostre 1"/1¼", se asumió 1"). |
| erico.com | ERICO | 4 | 4 | 4 | **Cerrado esta ronda** — FIG 300/310 (Universal Beam Clamp): ficha técnica real SI tiene diagrama (revisado como imagen), pero solo publica Rod Size + ancho de cuello (A) + espesor MÁXIMO de ala aceptado (FT, una capacidad, no una medida fija) — falta por completo el eje de altura total del cuerpo y el de largo a lo largo de la viga. Dimensiones parciales guardadas y documentadas en `specs_adicionales`, sin volumen para no inventar un eje. |
| tandl.cn | TANDL | 2 | 0 | 0 | Cerrado — sitio placeholder de leads B2B, sin fichas de producto. |
| reliablesprinkler.com | RELIABLE | 1 | 0 | 0 | Cerrado — `73PQRBRO12`, sin boletín vigente localizado con el SIN/rosca correcto. |
| ~~asc-es.com~~ | ~~ANVIL~~ | 0 | 1 | 1 | **Resuelto** — `6A20012341` (ver "Ronda ANVIL FIG69" arriba): ficha submittal real con diagrama A/B/C/F/G, talla del medio (3/4") del rango cargada como representante, 10.56 cm³, confianza baja. |

TYCO quedó **cerrado 16/16** esta ronda (ver detalle abajo) — ya no
aparece en la tabla de pendientes. (Nota: en la ronda "seguimiento
página-por-página", 3 códigos TYCO adicionales que habían quedado sin
volumen en la Ronda 2 de ERICO/TYCO — ver esa sección — se resolvieron
2/3, ver arriba.)

## Ronda 2 (2026-08-10) — resultado de los 12 códigos "por revisar de nuevo"

### ERICO (8 códigos, nVent CADDY)

- **FIG 115 — Standard Duty Loop Hanger (4 códigos, RESUELTOS)**:
  `6A10000003`, `6A10000004`, `6A10000006`, `6A10000212`. El endpoint
  `nvent.com/en-us/caddy/products/115-standard-duty-loop-hanger-0/pdf`
  (pedido directo vía `curl` con User-Agent de navegador — Playwright
  chocaba con el bot-check de Cloudflare en la página HTML normal) sí
  entrega una ficha técnica real "system-generated" con tabla de medidas
  por talla **y diagrama** con letras `OD` (diámetro real del aro), `A`
  (altura total), `B` (altura del aro sin el collar), `C` (altura del
  collar) y `RS` (diámetro de varilla). A diferencia del cálculo anterior
  para PHD FIG141/ERICO FIG100 (que no tenían diámetro real y usaban la
  altura también como ancho, por falta de dato), aquí SÍ hay un diámetro
  real (`OD`) — mejor dato que antes. Volumen = caja envolvente
  `OD × A × RS` (profundidad sigue sin dato publicado, se usa Rod Size
  como aproximación conservadora, mismo supuesto ya usado en PHD/ERICO
  FIG100). Material confirmado: Acero (Steel), acabado Pregalvanizado.
  Confianza: **media** (2 de 3 ejes reales, antes era "baja" con 1 de 2).
- **FIG 300/310 — Universal Beam Clamp (4 códigos, CERRADOS sin
  volumen)**: `6D10000012`, `6D10000038`, `6D30000012`, `6D30000038`. Se
  encontró y descargó la ficha técnica real (mismo patrón `/pdf` que
  FIG115) y se **renderizó el diagrama como imagen** para revisarlo
  visualmente (no solo texto) — confirma que la pieza solo publica Rod
  Size, el ancho del cuello donde entra la varilla (`A`, una sola medida
  real del cuerpo) y `Flange Thickness` (`FT`, el espesor MÁXIMO de ala
  que la mordaza acepta — una capacidad/rating, no una medida fija de la
  pieza). Verificado también contra una ficha alterna de otro
  distribuidor autorizado (alldataresource.com) — mismos 3 valores, sin
  dato adicional. Falta por completo el eje de altura total del cuerpo Y
  el eje de largo a lo largo de la viga (ninguno está en ningún diagrama
  publicado) — **no se calculó volumen** para no inventar un eje que no
  está documentado en ninguna fuente. Dimensiones parciales (RS, A, FT)
  guardadas en `dimensiones_texto` y el razonamiento completo en
  `specs_adicionales`. Material (Cast Iron) ya estaba confirmado de una
  ronda anterior y se mantiene.

### TYCO (4 escudos, RESUELTOS — TYCO queda 16/16 con revisión completa)

Los 4 códigos traen el P/N real de TYCO embebido en `nombre_producto`
(ej. `567154010` = P/N `56-715-4-010` sin guiones), lo que permitió
identificar el estilo EXACTO de escudo en la ficha TFP correspondiente
antes de aplicar cualquier medida (evitando repetir el error de la ronda
anterior de confundir diámetro de escudo con diámetro de cuerpo):

- **`72ESBLI012`** (ESCUDO BLANCO P/ROC OCULTO 1/2") = P/N `56-792-4-135`,
  "Cover Plate" Signal White para rociadores ocultos (Series RFII,
  DS-C, DS-ECC comparten el mismo P/N y pieza física). Ficha **TFP181**
  (ya estaba descargada de una ronda anterior para el rociador RFII, se
  reutilizó para el escudo) trae, página 3, etiquetas explícitas:
  `COVER PLATE DIAMETER DIMENSION A: 3-1/4in (82,6mm)` y `COVER PLATE
  PROFILE DEPTH DIMENSION B: 3/16in (4,8mm)` — sin ambigüedad con el
  cuerpo del rociador. Material: Latón (Brass). Cilindro real, confianza
  **alta**. Volumen: **25.72 cm³**.
- **`7A2T000012`** (ESCUDO DOBLE BLANCO 1/2") = P/N `56-715-4-010` =
  Style 15 Recessed Escutcheon, Signal White, 1/2" NPT.
- **`7A10000012`** (ESCUDO DOBLE CROMADO 1/2") = P/N `56-715-9-010` =
  Style 15 Recessed Escutcheon, Chrome Plated, 1/2" NPT.
- **`7A10000034`** (ESCUDO DOBLE CROMADO 3/4") = P/N `56-700-9-010` =
  Style 40 Recessed Escutcheon, Chrome Plated, 3/4" NPT.

  Estos 3 vienen de la ficha **TFP770** (Two-Piece Recessed Escutcheons,
  Styles 10/15/20/30/40/50/70 — descargada nueva esta ronda), que trae
  diagrama por estilo con diámetro del `CLOSURE` (el escudo visible) y
  la altura total del ensamble (mounting plate + closure). Style 15:
  73.0mm × 25.4mm → **106.31 cm³** (mismo volumen para blanco y cromado,
  solo cambia el acabado). Style 40: 73.0mm × 28.6mm → **119.70 cm³**.
  Material: acero al carbono cromado/recubierto blanco según acabado.
  Cilindro real, confianza **alta** para los 3.

PDFs reales nuevos en `data/capturas_fuentes/` (ver `manifiesto.csv`, filas
agregadas al final): `erico.com/ficha_real_fig115.pdf`,
`erico.com/ficha_real_fig300.pdf`, `erico.com/ficha_real_fig310.pdf`,
`tyco-fire.com/TFP770.pdf`; más una fila nueva que documenta la
reutilización de `tyco-fire.com/TFP181.pdf` como fuente de dimensiones
del escudo `72ESBLI012`.

## Ronda MECH (2026-08-10) — resultado de los 105 códigos fu-mech.com + meide.mx

Los 105 códigos MECH habían quedado marcados "cerrados, sin dato" en una
fase anterior, **antes** de establecerse el método de renderizar
páginas/PDFs como imagen. Esta ronda los reintentó a fondo.

**Hallazgo clave**: fu-mech.com sí publica fichas técnicas PDF reales
descargables (botón "Click Here To Download" en cada página de producto),
que la ronda anterior nunca siguió — el print-to-pdf de la página con
Playwright solo capturaba un ícono roto donde iba ese botón (bloquea
`image/font/media` por diseño). Se descargaron **18 PDFs reales nuevos**
a `data/capturas_fuentes/fu-mech.com/ficha_real_*.pdf` (ver `manifiesto.csv`,
filas agregadas al final) y se renderizaron a imagen con `pdfplumber`
(`herramientas/render_mech_pdfs.py`) para leer las tablas de medidas por talla.

**Resultado: 60/105 con volumen** en esta ronda — 37 con confianza alta (tabla oficial
de 3 ejes reales, sin supuestos, o medida exacta que coincide con el
nombre del producto), 22 con confianza media (1-2 ejes reales + O.D. de
tubería como proxy de un eje faltante) y 7 con confianza baja (mismo
supuesto ya aceptado en la ronda de PHD/ERICO FIG141/FIG100). Más
7/7 del acople 1N, 8/8 del codo 90/90S, 5/5 del reductor 240, 10/10 del
STRAP y 4/4 de la tapa simple 300 (rondas posteriores, ver arriba) =
**95/105 con volumen en total dentro de MECH**. El cálculo completo por
familia vive en `enriquecimiento/completar_volumen_mech.py`
(`docker compose exec scraper python enriquecimiento/completar_volumen_mech.py`,
re-corrible, hace upsert).

### Familias MECH cerradas (60 códigos)

| Familia | Códigos | Método | Confianza |
|---|---|---|---|
| meide.mx Support-hanger GSD9 (pera) | 7 | Caja envolvente D×D×RodSize (mismo patrón que PHD FIG141/ERICO FIG100) | baja |
| meide.mx Beam Clamp 3034 | 1 | Caja envolvente real A×B1×D (ficha con 2 vistas) | media-alta |
| fu-mech Rigid Coupling 1G/1GS | 10 | Caja envolvente real A×B×C (tabla oficial UL/FM) | alta |
| fu-mech Mechanical Tee 3G (grooved outlet, saddle) | 9 | Caja envolvente real A×B×C | alta |
| fu-mech Mechanical Tee 3J (threaded outlet, saddle) | 6 de 7 | Caja envolvente real A×B×C | alta |
| fu-mech Elbow 45 modelo 120 (corregido de "120X") | 6 | Caja envolvente L×L×D (D=Pipe O.D. de la misma tabla) | media |
| fu-mech Tee modelo 130/130S (corregido de "130X") | 6 | Caja envolvente L×L×D | media |
| fu-mech BMI Elbow 90 (modelo 90) | 2 | Caja envolvente A×A×D (D=O.D. tubería, tabla ASME B1.20.1 de la misma ficha) | media |
| fu-mech BMI Elbow 90R (reductor) | 1 | Caja envolvente A×B×D | media |
| fu-mech BMI Tee 130 (roscado — no confundir con el grooved 130) | 1 | Caja envolvente (2A)×A×D | media |
| fu-mech BMI Plug modelo 291/291S | 3 | Cilindro real π(D/2)²×A | media |
| fu-mech BMI Red Bush modelo 241 | 3 | Cilindro real (D=lado mayor roscado) | media |
| fu-mech BMI Red Socket modelo 240 | 3 | Cilindro real | media |
| fu-mech BMI Sockets modelo 220 | 1 | Cilindro real | media |
| fu-mech Flexible Hose (SS trenzada, estilo MDFB) | 1 | Cilindro real π(D/2)²×L, medida exacta de tabla oficial (48"=1200mm, 1/2", O.D. 26.8mm) | alta |

Nota de método: para las piezas irregulares (codos, tees, coples con
bridas/tornillos) se usó caja envolvente con los ejes que la tabla oficial
publica; cuando solo había 1 eje real (L, center-to-end), se completó con
el O.D. de tubería (publicado en la MISMA ficha, tabla ASME B1.20.1, no es
un dato externo) como proxy del diámetro del cuerpo — confianza "media" en
vez de "alta" por ese supuesto adicional. Para piezas roscadas
axisimétricas (tapones, bushings, coples) se usó cilindro real; ahí el
O.D. de tubería también aproxima el diámetro exterior real del casting
(que en los bushings hexagonales es levemente mayor — se documenta como
subestimación conocida en `volumen_metodo` de cada código).

### Familias MECH que siguen sin volumen (25 códigos), con razón documentada

Actualizado tras la ronda "fichas individuales meide.mx" (2026-08-11) —
ver esa sección más arriba para el detalle completo de qué se revisó y
cómo. **Solo queda 1 familia MECH sin dato: tubería roja.**

| Familia | Códigos | Por qué sigue sin dato |
|---|---|---|
| meide.mx jinan-mech-piping (tubería roja A795/A53) | 10 | **Confirmado exhaustivamente (2026-08-11)**: se revisaron 4 documentos distintos del fabricante — página HTML, `STEEL-PIPE-BROCHURE-2026.3.12.pdf`, `ERW-Steel-Pipe-SCH-10-ASTM-A795.pdf`, `MECH-FP-STEEL-PIPES.pdf` (catálogo de 9 páginas) y `Welded-Steel-Pipes-SCH-40-PIPES.pdf` — todos dan la misma tabla de peso por metro y "Length tolerance +20mm/0" (tolerancia sobre lo que se pida, no un largo fijo de venta). El dato genuinamente no se publica en ningún lado; no se puede asumir un largo de barra sin arriesgar el número. |
| ~~fu-mech Red Coupling modelo 1N~~ | 0 | **Resuelto 7/7** (ver "Ronda catálogo maestro" arriba) — el catálogo maestro trae la tabla "1N Standard Flexible Coupling" completa y limpia, incluyendo la fila 1½" que estaba corrupta en todas las fuentes anteriores. |
| ~~meide.mx STRAP "T Mecánica U-bolt", modelo "3L"~~ | 0 | **Resuelto 10/10** (ver "Ronda fichas individuales meide.mx" arriba) — la ficha individual `DS-400-MT1-01-E` sí tiene la tabla A/B/C completa; no estaba en la página de categoría ni en el catálogo maestro de fu-mech.com, pero sí como ficha de producto propia de meide.mx. |
| ~~fu-mech Elbow 90 modelos 90S/90X~~ | 0 | **Resuelto 8/8 en la ronda "codo 90/90S" (ver arriba)** — el usuario encontró la ficha real vía una imagen thumbnail de WordPress que no era un botón de descarga obvio. |
| ~~fu-mech Grooved End Cap modelo 300/300TX~~ | 0 | **Resuelto 4/4** (ver "Ronda fichas individuales meide.mx" arriba) — la ficha individual `DS-CP-300-01-E` (Cap simple sin agujero) sí existe, en meide.mx, distinta a la tabla "con agujero" del catálogo maestro de fu-mech.com. |
| ~~fu-mech Grooved Concentric Reducer modelo 240~~ | 0 | **Resuelto 4/4** (ver "Ronda catálogo maestro" arriba) — el catálogo maestro trae la tabla completa desde 1¼"×1" hasta 24"×20", cubriendo las 4 combinaciones que el recorte individual (que solo llegaba desde 6") no tenía. |
| ~~fu-mech Mechanical Tee 3J, combinación 4"x2-1/2"~~ | 0 | **Resuelto esta ronda** (`3B32004212`) — la fila 100×65 estaba en el mismo PDF pero fuera del área visible/imprimible de la página (continuación de la tabla en lo que era la página siguiente del catálogo impreso). |

### Correcciones de mapeo encontradas y aplicadas esta ronda (en `scrapes`)

Al verificar cada modelo/talla contra la ficha real (paso obligatorio de la
metodología) aparecieron 4 errores de mapeo del matcher original, ya
corregidos en la tabla `scrapes` local (no afecta Supabase, que se
sincroniza aparte):

1. **`3E12AC1141`** — matcheado por error a la ficha de la válvula "Brass
   Pressure Reducing Valve Y11X-702A" (coincidencia de palabra
   "reducing"/"reductor"). El producto real es una reducción roscada
   ("RED COPA ACx300 LBS ROSC. 1¼"x1""), misma familia que
   `3E12AC0112`/`3E12AC0134` (BMI Red Socket Model 240). Corregido.
2. **4 códigos "RED CON RAN X RAN"** (`3E12002114`, `3E12002122`,
   `3E12112114`, `3E12212112`) — matcheados a la página del reductor
   concéntrico **roscado** ("240NX"), pero el nombre del producto dice
   explícitamente "RAN X RAN" (ranurado) y el modelo es "P240" sin
   sufijo. Corregido a `mech-grooved-conc-red-grvd-model-240`.
3. **6 códigos "CODO 45 RAN"** (modelo interno "P120", sin sufijo X) —
   matcheados a la página "120X" (rango de tallas grandes 3"-10"), pero
   las tallas reales (1¼"-4") están fuera de ese rango y coinciden con el
   rango de la página "120" sin sufijo (1"-12"). Corregido.
4. **6 códigos "TE RAN"** (modelo interno "P130"/"P130S") — mismo patrón
   que el anterior, corregido de "130X" a "130"/"130S".

Este archivo se actualiza a medida que se cierra cada bucket (ver
también `README.md`, sección "Estado al 2026-08-10").
