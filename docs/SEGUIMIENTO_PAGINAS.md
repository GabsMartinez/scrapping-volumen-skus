# Seguimiento de páginas — 28 códigos sin volumen (actualizado 2026-08-11)

Lista de trabajo para revisar página por página. Cada bloque es un
dominio/familia con sus códigos, la página fuente real, qué falta
exactamente, y una casilla para marcar cuando se revise.

Estado global: **166/194 con volumen** — quedan estos 28. Detalle
narrativo completo de cada ronda en `FALTANTES.md` (ver sección "Ronda
seguimiento página-por-página" para lo resuelto en esta pasada).

---

## ✅ RESUELTOS ESTA RONDA (2 códigos)

Gracias a los links que mandaste, se encontraron las fichas técnicas
exactas por SIN (el price book de TYCO no tiene diagramas, pero cada
renglón dice qué ficha usar):

- **`73A3B2A1`** (TY3331, TYCO horizontal sidewall) — ficha **TFP176**,
  Figura 1: diámetro del deflector 46.0mm × largo del cuerpo 55.6mm.
  **92.40 cm³**, confianza media.
- **`73PQBROI12`** (TY3531, TYCO RFII oculto) — ficha **TFP181**, Figura
  2 (dimensiones del conjunto cuerpo+copa, no del escudo que ya
  teníamos): diámetro 63.5mm (punto medio) × profundidad 50.85mm (punto
  medio). **161.03 cm³**, confianza media.

---

## 🔲 1. ERICO FIG300/310 — nVent (4 códigos) — EN CURSO

Mandaste el contenido completo de la pestaña "Details" (tabla + diagrama
A/FT/RS/F1) — coincide exacto con los mismos 3 valores que ya teníamos
del PDF (Rod Size, ancho de cuello A, espesor máximo de ala FT) más
cargas estáticas (no son medidas de tamaño). **4ª fuente que confirma el
mismo vacío**: no se publica el eje de altura total ni el de largo a lo
largo de la viga en ningún lado revisado (PDF, distribuidor alterno,
Details tab en vivo, Wayback Machine).

- [ ] `6D10000012` — FIG 300 1/2" — https://www.nvent.com/en-us/caddy/products/300-universal-beam-clamp-0
- [ ] `6D10000038` — FIG 300 3/8" — https://www.nvent.com/en-us/caddy/products/300-universal-beam-clamp-0
- [ ] `6D30000012` — FIG 310 1/2" — https://www.nvent.com/en-us/caddy/products/310-universal-beam-clamp-thick-flange-0
- [ ] `6D30000038` — FIG 310 3/8" — https://www.nvent.com/en-us/caddy/products/310-universal-beam-clamp-thick-flange-0

**Genuinamente sin más de dónde sacarlo salvo que aparezca una ficha de
otro distribuidor con un diagrama distinto.**

---

## 🔲 2. TYCO TY5137 — tyco-fire.com (1 código) — mismo tipo de vacío que ERICO

Ficha **TFP220** (Series EC-11) revisada a fondo, las 8 páginas. Figura
1 solo acota alturas (61.9mm total, 42.7mm cuerpo, 12.7mm nominal
make-in) — ningún diagrama trae el ancho/diámetro del cuerpo. Las
medidas de escudo (2-7/8" DIA, etc.) de las Figuras 2-6 son de la
versión **pendent** (TY5237/TY6237) con escudo empotrado — no aplican,
nuestro código es **upright** (sin escudo).

- [ ] `75B1B2A2` — TY5137 K11.2 3/4" — https://www.tyco-fire.com/americas-price-book (ficha: TFP220)

---

## 🔲 3. Reliable G5-56 — reliablesprinkler.com (1 código) — boletín correcto encontrado, falta 1 eje

El 074.pdf que mandaste es el boletín correcto del sitio pero para el
SIN equivocado (RA1414/RA1425/RA1435/RA1485 = familia F1FR56). Nuestro
código tiene SIN **RA3415** = modelo **G5-56**, que está en el
**Boletín 034** (lo encontré por búsqueda dirigida por el SIN). Confirma
material exacto y diámetro real del cuerpo/copa (58mm, Figura 3) — pero
no acota una altura total del cuerpo (el único otro número es la holgura
de instalación del conjunto completo con cover plate, no la altura del
cuerpo solo).

- [ ] `73PQRBRO12` — RA3415/G5-56 K5.6 1/2" oculto bronce — https://www.reliablesprinkler.com/files/bulletins/034.pdf

**Si aparece en algún lado una ficha con la altura del cuerpo del G5-56
(sin cover plate), esto se resuelve.**

---

## ✅ 4. MECH tubería roja A795/A53 — meide.mx (10 códigos) — CERRADO, sin dato

Confirmado con 8 documentos distintos del fabricante en total (4 en la
ronda anterior + 4 catálogos nuevos que mandaste — grooved fittings,
soportería, 2 de válvulas, ninguno es de tubería). Dan peso por metro
pero **nunca un largo de barra estándar de venta**. El único "20'" que
apareció al buscar en el catálogo de coples (página 71) se revisó como
imagen: es un encabezado de tabla de un ejemplo de expansión térmica
("Pipe length (m): 1, 5, 10, 20, 30, 40"), no tiene nada que ver con
largo de barra de venta — descartado.

- [ ] `1A1JINA114` — 1-1/4" — https://www.meide.mx/jinan-mech-piping/
- [ ] `1AJINAR002` — 2"
- [ ] `1AJINAR003` — 3"
- [ ] `1AJINAR004` — 4"
- [ ] `1AJINAR112` — 1-1/2"
- [ ] `1AJINAR114` — 1-1/4"
- [ ] `1AJINAR212` — 2-1/2"
- [ ] `1B1JINA001` — 1" (A53 GrB)
- [ ] `1BJINAR001` — 1" (A53 GrB)
- [ ] `1BJINAR114` — 1-1/4" (A53 GrB)

---

## ✅ 5. PHD soportes antisísmicos — phd-mfg.com (10 códigos) — CERRADO, sin dato

Confirmado con las fichas individuales "View Data Sheet" de los 3
modelos (FIG010, FIG015, FIG031 — las 3 revisadas como imagen, no solo
el 031 que trajo el usuario): mismo patrón en las 3, el único número en
el diagrama es `1"` etiquetando el tubo de arriostramiento (un
accesorio que el cliente compra aparte), nunca una medida del cuerpo de
la abrazadera/pieza. 4 fuentes independientes en total (catálogo
maestro + 3 fichas individuales) dan el mismo resultado. Peso SÍ está
cargado para los 10.

- [ ] `3SALPHD002` — FIG 031-030, 2" — https://www.phd-mfg.com/products/pipe-hangers-devices/seismic-bracing-pipe-hangers-devices/clamping-pipe-attachment-2/
- [ ] `3SALPHD003` — FIG 031-030, 3"
- [ ] `3SALPHD004` — FIG 031-030, 4"
- [ ] `3SALPHD006` — FIG 031-030, 6"
- [ ] `3SALPHD212` — FIG 031-030, 2-1/2"
- [ ] `3SATPHD002` — FIG 010-030, 2" — https://www.phd-mfg.com/products/pipe-hangers-devices/seismic-bracing-pipe-hangers-devices/sway-brace-pipe-attachment/
- [ ] `3SATPHD003` — FIG 015-030, 3" — https://www.phd-mfg.com/products/fire-protection-seismic/seismic-bracing/large-sway-brace-pipe-attachment-2/
- [ ] `3SATPHD004` — FIG 015-030, 4"
- [ ] `3SATPHD006` — FIG 015-030, 6"
- [ ] `3SATPHD212` — FIG 015-030, 2-1/2"

---

## ✅ 6. TANDL — sitio placeholder, sin fichas (2 códigos) — CERRADO

Certificado SSL vencido, sitio de leads B2B sin fichas de producto
reales.

- [ ] `6E1TCH0038` — varilla roscada 3/8"x3m — https://www.tandl.cn/Threaded-Rods-U-Bolts-L-Bolts.html
- [ ] `6F1GTCH038` — chazo rosca interna 3/8" — https://www.tandl.cn/Fixings.html

---

## Resumen por estado

| Bloque | Códigos | Estado |
|---|---|---|
| **Resueltos esta ronda (TYCO)** | **2** | ✅ Cargados y sincronizados a Supabase |
| ERICO FIG300/310 (nVent) | 4 | 🔲 Confirmado sin más fuentes (4 revisadas) |
| TYCO TY5137 | 1 | 🔲 Confirmado sin más fuentes (mismo tipo que ERICO) |
| Reliable G5-56 | 1 | 🔲 Boletín correcto encontrado, falta 1 eje |
| MECH tubería roja | 10 | ✅ Cerrado sin dato (8 documentos revisados) |
| PHD soportes antisísmicos | 10 | ✅ Cerrado sin dato (2 fuentes independientes) |
| TANDL | 2 | ✅ Cerrado sin dato (sitio sin fichas) |
| **Total sin volumen** | **28** | |
