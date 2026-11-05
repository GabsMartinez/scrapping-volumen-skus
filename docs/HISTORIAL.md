# Historial del proyecto (metodología y decisiones)

Scrapea descripción/serie (y precio si el sitio lo publica) de los 194
códigos críticos (85% del movimiento) en los sitios oficiales de sus
fabricantes, cruzando `data/entrada/codigos_criticos_dominios.xlsx` contra
`modulos/fabricantes.py`. Todo corre local en Docker (Postgres +
Scrapy/Playwright); Supabase se conecta después.

## Por qué NO es "un spider genérico para todos los dominios"

Cada fabricante tiene un catálogo distinto y **ninguno de los que se
revisaron hasta ahora tiene búsqueda por código funcional**:

- `fu-mech.com` (MECH, 62.6% del movimiento crítico): `/?s=<texto>` y
  cualquier `/product_cat/<x>/` devuelven siempre el mismo listado
  completo (~109 productos) — no filtran de verdad. Nuestro código
  interno (ej. `B240`, `P1G73`) tampoco es el modelo real del fabricante
  (ej. `MODEL 240`): es un alias interno de la distribuidora.

Por eso el patrón que se usó para MECH (y que hay que repetir, revisando
cada sitio a mano, para los otros 9 dominios) es:

1. **Spider de catálogo** (`spiders/<marca>_catalogo_spider.py`): recorre
   TODO el catálogo público del fabricante una sola vez y guarda cada
   producto en `catalogo_fabricante` (dominio, url, título, modelo
   detectado, descripción). No busca por código porque no se puede.
2. **Matcher** (`matchers/<marca>_matcher.py`): cruza `productos_criticos`
   (nuestros códigos) contra `catalogo_fabricante`, normalizando texto
   (número de modelo embebido + palabra clave del tipo de pieza ES->EN),
   e inserta los matches en `scrapes`.

Esto significa: **sí, hay que revisar página por página, proveedor por
proveedor** — no hay atajo genérico, cada sitio tiene su propia lógica de
navegación y su propia forma de nombrar modelos. `modulos/fabricantes.py`
es el mapa de qué dominio le toca a cada marca.

## Cómo se investiga un sitio nuevo antes de escribir el spider

1. Abrir el dominio con Playwright real (no solo lectura estática) y
   revisar: ¿tiene búsqueda que de verdad filtra? ¿tiene categorías?
   ¿cuántas páginas de producto hay en total?
2. Abrir 2-3 páginas de producto y ver dónde está el modelo real
   (normalmente en el `<h1>` o en la URL) y la descripción (normalmente
   en `<meta property="og:description">`, a veces en el cuerpo).
3. **Ojo con los timeouts**: varios de estos sitios de catálogo B2B nunca
   llegan a `"load"` ni a `"networkidle"` (algún recurso de terceros se
   queda colgado) aunque el servidor responde al instante (confirmable
   con `curl`). La solución que funcionó en MECH:
   `wait_until="commit"` + bloquear `image/font/media/stylesheet` vía
   `page.route()` + esperar un selector real (`wait_for_selector`) en vez
   de un evento de ciclo de vida. Ver `mech_catalogo_spider.py`.
4. Con eso ya se puede escribir el spider de catálogo + el matcher.
5. **Si Playwright recibe 403 pero el sitio no debería estar bloqueando nada**,
   probar una petición HTTP simple (`curl`/`urllib`) antes de rendirse:
   pasó en reliablesprinkler.com que el WAF bloqueaba el fingerprint de
   Chromium automatizado (Y también el downloader HTTP de Scrapy/Twisted)
   pero dejaba pasar una petición simple sin problema. Cuando eso pasa,
   el spider de ese dominio se escribe como script plano en `crawlers/`
   en vez de spider de Scrapy (ver `crawlers/reliable_crawler.py`).
6. **Buscar también un "price book" en PDF** antes de crawlear el sitio
   (ej. página `/americas-price-book` en tyco-fire.com): si el fabricante
   publica lista de precios oficial, es mejor fuente que scrapear páginas
   de producto una por una — tiene precio EXACTO por variante (acabado,
   temperatura, talla), cosa que casi ninguna página de producto muestra
   públicamente. Ver `matchers/tyco_matcher.py` para el patrón completo
   (incluye cómo conseguir el PDF real cuando el link visible es un
   visor JS de Widen/otro DAM, no el archivo).

## Auditoría de vigencia de los PDFs (2026-08-05)

Buena pregunta que vale la pena dejar documentada: **¿los PDFs que se
usaron como fuente son la versión vigente, o convenía sacar el dato de
la página web en vivo en su lugar?** Se revisó cada uno (metadata de
creación/modificación del PDF + comparación contra la página en vivo del
sitio) antes de dar la sesión por cerrada:

- **TYCO price book**: el link "View PDF Version" de la página en vivo
  (`/americas-price-book`) hoy sigue apuntando exactamente al mismo
  archivo que se descargó (`TFPP_PB_01-26_v1-1.pdf`, ModDate 2026-07-01)
  — es la versión vigente, no había una más nueva. De paso se encontró
  que también publican una versión en Excel (`TFPP_PB_01-26_v1.zip`),
  que sería más confiable de parsear que el PDF (sin el problema de
  columnas por posición) — queda como mejora pendiente si hace falta más
  precisión en TYCO.
- **meide.mx SÍ tiene páginas HTML reales**, no todo es PDF (nav:
  TUBERIA, RANURADO, VÁLVULAS) — se habían usado solo los PDFs sin
  revisar esto. Para STRAP/RC/tubería roja, `url_fuente` ahora apunta a
  esas páginas vivas (`/coples-y-conexiones-ranuradas/`,
  `/jinan-mech-piping/`) en vez del PDF — una página viva se actualiza
  sola, un PDF descargado es una foto fija. El PDF queda solo como
  referencia técnica en la descripción.
- **Tubería A795/A53**: las fichas que se habían usado primero eran de
  2020/2021. Se encontró una ficha combinada más nueva
  (`STEEL-PIPE-BROCHURE-2026.3.12.pdf`, la más reciente que existe) con
  **los mismos valores dimensionales** (diámetro, espesor de pared,
  peso) — tiene sentido, son specs de norma ASTM, no cambian con el
  tiempo. Se cambió la referencia a la versión más nueva de todas formas,
  por prolijidad.
- **Soporte tipo pera (GSD9) y beam clamp (3034)**: no tienen página
  viva equivalente en el menú de meide.mx, así que se quedan con el PDF
  como fuente — pero su ModDate es 2026-05-14 (hace ~3 meses), vigente.
- **2 PDFs viejos que se habían descargado al principio para explorar**
  (catálogo BS de 2017, catálogo grooved de 2015) **nunca se usaron como
  fuente de ningún match** — se verificó con grep sobre todos los
  matchers antes de borrarlos de `data/fuentes/`.

## PHD Manufacturing — no estaba en el diccionario original

PHD (21 códigos, **15.2% del movimiento crítico** — la marca más grande
que quedaba sin tocar) nunca tuvo dominio asignado en `fabricantes.py`;
quedó en el grupo `Sin_Dominio` desde el cruce original. El dominio real
es **phd-mfg.com** ("PHD Manufacturing", fabricante de soportes/bracing
sísmico para el sector de sprinklers — encontrado por búsqueda web, no
estaba en ningún lado del proyecto). Se agregó a `fabricantes.py`, se
volvió a correr `cruzar_ranking_proveedores.py` para que pasara a
`Con_Dominio`, y se re-sembró Postgres.

El sitio es WordPress: HTTP simple funciona (sin WAF), pero el número de
"Figure: ###" de cada producto se renderiza vía JS en varias páginas —
por eso `crawlers/phd_crawler.py` sí usa Playwright (a diferencia de
`reliable_crawler.py`, que no lo necesitaba). Resultado: **21/21 (100%)**,
20 por figura principal de la página + 1 (FIG 353) encontrada mencionada
dentro del texto de otra página ("Domestic Beam Clamp", cuya figura
principal es 350 pero el texto aclara "el diseño universal del 3/8" Fig.
353...").

## Progreso por dominio (194 códigos críticos, 11 dominios con marca mapeada)

| Marca | Dominio | % del movimiento crítico | Estado |
|---|---|---|---|
| MECH | fu-mech.com + meide.mx | 62.6% | **Hecho — 105/105 (100%)**. fu-mech.com resolvió 103 (tercera pasada por palabra clave para códigos sin número de modelo: TAPON MACHO→PLUG Model 291, RED BUSHING→Model 241, manguera→Flexible Hose, TE MEC SAL ROS→MODEL 3J). meidegroup.com no responde (ECONNREFUSED, bloqueo geográfico), así que para lo que fu-mech.com no publica se buscó el fabricante real (Jinan Meide Casting Co.) y su distribuidor mexicano **meide.mx**: soporte tipo pera (PGSD9→GSD9), STRAP (P3L→"U-Bolt Mechanical Tee" MT1), tubería roja ASTM A795/A53, reductor concéntrico (RC), beam clamp (G3034→tipo 3034). |
| TYCO | tyco-fire.com, jci.com | 11.0% | **Hecho — 16/16 (100%)**. 12 con precio exacto en USD del price book PDF; los 4 escudos/tapas (sin código "TY###" en el nombre) matchearon contra la página familia "Sprinkler Cover Plate Assemblies, Escutcheons, Guards and Shields". |
| RELIABLE | reliablesprinkler.com | 9.1% | **Hecho — 23/23 (100%)**. 258 productos crawleados (con `crawlers/reliable_crawler.py`, NO Scrapy: el WAF del sitio deja pasar `urllib` pero bloquea a Playwright Y al downloader de Scrapy con 403). 18 por K-factor + tipo; 1 más (K16.8 ESFR Pendent) por código de modelo embebido (JL-17); los 4 escudos restantes matchearon contra las páginas familia "Escutcheons"/"Cover Plates". |
| ERICO | erico.com (redirige a nvent.com) + api.ferguson.com (ficha original ERICO) | 7.7% | **Hecho — 11/11 (100%)**. 8 códigos se venden hoy como "nVent CADDY". Los 3 de FIG 100 parecían descontinuados (brochure vigente y buscador de nVent no lo listan, tampoco la base de cruce de competidores de ASC), pero la ficha ORIGINAL de ERICO (marca "www.erico.com") sigue alojada y distribuida por Ferguson aunque ya no esté enlazada en el sitio actual — el producto sigue siendo real. |
| ANVIL | anvilintl.com (redirige a asc-es.com, "ASC Engineered Solutions") | 5.2% | **Hecho** — el sitio corre búsqueda real con Algolia (API key pública de solo-lectura, capturada del tráfico de red). 1/1 código (100%), con specs completas y hasta el equivalente cruzado en otras marcas (confirma el match de ERICO Fig 115). |
| GLOBE | globefiresprinkler.com no resuelve → Globe fue adquirida por Victaulic (2018), línea GL-xxxx ahora en **victaulic.com** como FireLock V-xxxx | 2.7% | **Hecho — 7/7 (100%)**. El filtro real del catálogo (`vtc_product_categories/fire-sprinklers/`) tenía el widget con `display:none` hasta hacer clic en los headers de acordeón (Categories/K Factor/Deflector); automatizado con Playwright. Con Standard Coverage + K5.6 + Upright/Pendent aparecieron las series correctas: FL-QR (Upright→V2704) y FL-SR (Upright→V2703). El Pendent QR (V2708 vs V2762) queda "confianza media" (la página lista ambos K5.6 sin distinguir liso/empotrado). Los 3 escudos matchearon contra la página familia "FireLock™ Sprinkler Escutcheons". |
| SIMPLEX | johnsoncontrols.com | 0.9% | **Hecho — 2/2 (100%)**. Las fichas reales NO están en johnsoncontrols.com sino en **docs.johnsoncontrols.com** (portal "Simplex/Autocall Knowledge Exchange", indexado por Google pero no enlazado desde el sitio principal) — ficha oficial "TrueAlarm Analog Sensors" confirma 4098-9714 y 4098-9792 exactos. |
| KIDDE | kidde.com (no estaba en fabricantes.py) | 0.2% | **Hecho — 1/1 (100%)**. El modelo original (0914E, iónico, batería 9V) está descontinuado; se usó el sucesor directo confirmado externamente (10SDR), con la diferencia de tecnología/batería anotada en el detalle. |
| WILSON & COUSINS | wilsoncousins.com no resuelve → **wilsonandcousins.com** (dominio real) | 0.6% | **Hecho** — 3/3 (100%), encontrados navegando categoría → subtaller por talla (sin buscador ni crawl). |
| TYLER UNION | tylerunion.com | 0.1% | **Hecho** — 1/1, match por familia de producto ("Tufgrip™ Restraint for Ductile Iron Pipe"). |
| STAR PIPE | starpipeproducts.com | 0.1% | **Hecho** — 1/1, match por número de ítem embebido (PVCPK4004) + sufijo HD ("PVC Stargrip® Series 4000HD"). |
| PHD | phd-mfg.com (no estaba en fabricantes.py) | 15.2% | **Hecho — 21/21 (100%)**. Ver sección propia más abajo. |
| TANDL | tandl.cn (no estaba en fabricantes.py) | 1.1% | **Hecho — 2/2 (confianza parcial)**. "TANDL" a secas no daba nada; buscando "threaded rod manufacturer" apareció TANDL Industry Co., Ltd. (Shanghai, 2005). Su sitio confirma marca y categoría exacta pero es un placeholder de leads B2B sin fichas de producto — sin talla/spec exacta confirmada. |

MECH + TYCO + RELIABLE + ERICO + ANVIL ya cubren **95.2%** del movimiento
del grupo crítico (de los que tienen dominio conocido) — son los que más
vale la pena terminar primero, y ya están **todos hechos**.

## Resultado final: 194/194 (100%)

Todos los códigos del grupo crítico (85% del movimiento) quedaron con
descripción/serie real. El último tramo (de 97.4% a 100%) salió de
seguir tirando del hilo en vez de aceptar la primera respuesta negativa:

- **MECH: 105/105 (100%)** — 3 técnicas en fu-mech.com (talla exacta,
  familia, palabra clave única) + meide.mx como segunda fuente para lo
  que fu-mech no publica.
- **TYCO, RELIABLE, GLOBE: 100%** — el último tramo salió de páginas
  "familia" genéricas de accesorios (escudos/cover plates) que no
  distinguen acabado/talla individual, pero sí confirman que es el
  producto correcto.
- **SIMPLEX: 100%** — las fichas reales viven en
  `docs.johnsoncontrols.com` (portal "Simplex/Autocall Knowledge
  Exchange"), un dominio que no estaba mapeado y que Google indexa por
  fuera del sitio principal `johnsoncontrols.com`.
- **KIDDE: 100%** — el modelo original (0914E, iónico, batería 9V) está
  descontinuado; se usó su sucesor directo confirmado externamente
  (10SDR), con la diferencia de tecnología/batería anotada en el detalle.
- **ERICO: 11/11 (100%)** — el FIG 100 (soporte tipo pera) parecía
  descontinuado tras 3 verificaciones negativas (brochure oficial
  vigente de nVent CADDY sin listarlo, base de cruce de competidores de
  ASC/Anvil sin ninguna referencia, búsqueda propia del sitio sin
  resultado). La fuente real terminó siendo una ficha técnica ORIGINAL
  de ERICO (marca "www.erico.com" en el pie de página) que sigue
  alojada y distribuida por Ferguson (`api.ferguson.com`) aunque ya no
  está enlazada desde ningún lado del sitio actual de nVent — el
  producto sigue siendo real y pedible, solo dejó de estar en el
  marketing vigente.
- **TANDL: 2/2 (confianza parcial)** — "TANDL" resultó ser un fabricante
  real de sujetadores en Shanghai (`tandl.cn`, TANDL Industry Co., Ltd.,
  desde 2005), encontrado buscando "threaded rod manufacturer" en vez de
  "TANDL" a secas. Su sitio confirma la marca y la categoría exacta
  (Threaded Rods / Fixings) pero es un placeholder de generación de
  leads B2B sin fichas de producto ni specs — se aceptó el match porque
  confirma el fabricante real, con el límite (sin talla/spec exacta)
  anotado explícitamente en el detalle.
- 4 dominios en 100%: ANVIL (1/1), WILSON & COUSINS (3/3), TYLER UNION
  (1/1) y STAR PIPE (1/1).

### Auditoría de falsos positivos (después de la segunda pasada de MECH)

Después de subir la cobertura de MECH con la pasada por familia, se
auditaron los matches con queries de sanidad (candidatos con un solo
resultado y puntaje de palabra clave 0, filas repetidas con orientación
distinta, etc.) y aparecieron **3 bugs reales**, ya corregidos:

1. **MECH — "300 LBS" confundido con "MODEL 300"**: la clase de presión
   ANSI ("ACx300 LBS") coincidía con el número de un modelo real de
   fu-mech (tapón/CAP), así que una UNIÓN (`B220`) y una TE (`B130`)
   quedaban mal etiquetadas como tapón. Fix: se excluyen los números
   seguidos de "LBS" antes de extraer el token de modelo — la UNIÓN y la
   TE ahora matchean correctamente contra `MODEL 220` y `MODEL 130`.
2. **MECH — segunda medida de talla confundida con modelo**: en
   códigos con dos tallas (ej. `P3L 48X21`, un STRAP), el "21" del
   segundo tramo coincidía por casualidad con un modelo real de otra
   pieza (`MODEL B21X`, una válvula). Fix de fondo: cuando el único
   candidato no tiene NINGUNA palabra clave del tipo de pieza que lo
   confirme, ya no se acepta el match (antes, "un solo candidato" se
   tomaba como suficiente por sí solo — resultó no serlo).
3. **TYCO — precio de Upright asignado a un código Pendent (y
   viceversa)**: el price book lista una fila por orientación
   (`Upright_parte  Pendent_parte  Acabado  Temp  Precio`, con un guion
   en la columna que no aplica), pero el matcher tomaba la primera fila
   que coincidía en SIN+temperatura+acabado sin fijarse cuál de las dos
   columnas tenía el guion. 3 códigos Pendent (`73PDQRCR12`,
   `73PDSRCR12`, `74PDQRCR34`) tenían el precio de su contraparte
   Upright. Fix: se detecta de qué orientación es cada fila (por cuál
   columna trae guion) y se descarta si no coincide con la orientación
   del código.

La aplicación de estos 3 fixes bajó el conteo total de 118 a 111 (se
perdieron algunos matches que resultaron ser incorrectos) y corrigió 3
precios de TYCO — **menos cobertura pero datos confiables**, que es lo
que importa para una base que va a alimentar decisiones de compra.
- 2 dominios sin ningún match confirmado — **no por falta de intento**,
  sino porque forzar un match habría arriesgado meter datos de un
  producto equivocado en la base:
  - **GLOBE**: fuente real identificada (ahora es victaulic.com/FireLock
    tras la compra de Globe por Victaulic en 2018), pero no se pudo
    aislar con confianza la serie "standard coverage" exacta entre
    varias series K5.6 candidatas.
  - **SIMPLEX**: buscador de johnsoncontrols.com funciona pero no expone
    fichas por SKU (Simplex se vende vía instalador certificado).
- Los 24 códigos restantes de los 194 (marcas PHD, TANDL, KIDDE) siguen
  en `Sin_Dominio`: nunca se les asignó dominio en `fabricantes.py`, así
  que no se intentó scrapear nada — es la próxima frontera si se quiere
  seguir subiendo cobertura.

### Cómo se llegó de 41% a 91% en MECH

1. **Segunda pasada de matching por FAMILIA en fu-mech.com**: fu-mech no
   publica una página por talla para acoples y tees mecánicas — publica
   una sola página por familia completa (ej. "MODEL 1G" cubre todas las
   tallas del acople rígido `P1G73`, `P1G42`...). Buscando el prefijo
   `P<modelo>` como token completo (con fallback al modelo base si el
   código trae un sufijo "S" que fu-mech no distingue, ej. `P3GS` →
   `MODEL 3G`) se recuperaron códigos que la primera pasada no
   encontraba (ver `matchers/mech_matcher.py`).
2. **Auditoría de falsos positivos** (ver sección más abajo): bajó el
   conteo pero subió la confianza.
3. **Segunda fuente para lo que fu-mech.com genuinamente no publica**:
   `meidegroup.com` (el dominio original en `fabricantes.py`) no
   responde — se encontró que el fabricante real es Jinan Meide Casting
   Co. y que su distribuidor mexicano `meide.mx` sí publica fichas
   técnicas PDF por producto, cubriendo soporte tipo pera, STRAP,
   tubería roja y reductor concéntrico (ver `matchers/meide_matcher.py`).

Quedan 9 códigos sin match — revisados a mano, sin ficha encontrada con
confianza suficiente (2 de ellos, "TAPON MACHO", casi matchean contra una
ficha CAP de meide.mx pero esa ficha es de un tapón RANURADO y el
nuestro es ROSCADO, así que se descartó a propósito en vez de forzarlo).

## Cómo correr esto

Ver el `README.md` de la raíz: todo se corre con `python main.py <comando>`
(o los atajos `scripts/correr.ps1` / `scripts/correr.sh`), y la base se
carga sola desde `db/datos/datos.sql` la primera vez que se levanta Docker.

## Specs estructuradas (material, acabado, tamaño, K-factor, aprobaciones)

`scrapes` tiene 7 columnas adicionales (`material`, `acabado`, `aprobaciones`,
`funcion_texto`, `tamano`, `k_factor`, `specs_adicionales`), pobladas por
`enriquecimiento/extraer_specs.py` a partir del texto YA capturado — no vuelve a scrapear.
Cubre solo 2 dominios, los únicos donde la fuente publica esto en secciones o
pares "Label: Valor" identificables sin ambigüedad:

- **phd-mfg.com** (21/21): se corrigió antes un bug en `crawlers/phd_crawler.py`
  que cortaba la descripción a 500 caracteres justo donde empezaban
  MATERIAL/FINISH/Approvals — ahora captura la ficha completa.
- **reliablesprinkler.com** (18/23 — los otros 5 no tienen specs en su
  página, solo el `<title>`): ya traía pares Label: Valor, solo hacía falta
  separarlos y decodificar entidades HTML (`&#8243;` = `″`).

Los demás dominios (fu-mech.com, tyco-fire.com, erico.com, victaulic.com,
anvil, etc.) quedaron sin tocar a propósito: fu-mech solo tenía el
`og:description` (genérico, ~68 caracteres), y el resto se resolvió con
fichas armadas a mano o PDFs sin texto de sobra para parsear sin arriesgar
datos incorrectos.

**Precio:** solo TYCO publica precio de lista público (16/16 productos, 12
con precio exacto). Las otras 12 marcas no publican precio en sus páginas —
es estándar en distribución B2B contra-incendios (precio vía representante),
no es un límite de scraping.

**Peso y dimensiones (para calcular espacio en bodega):** el Excel de
proveedores NO trae esto (solo código/nombre/familia/marca/modelo) — la
única fuente posible son las fichas técnicas en PDF de cada fabricante, y
cada familia de producto trae su propia estructura de tabla (algunas
indexan por número de figura, otras por tamaño de tubería, otras por
tamaño de varilla), así que no hay un parser genérico único: cada formato
necesitó su propio código/pasada manual.

Importante: `dimensiones_texto` casi siempre son medidas de **ingeniería**
(distancia entre tornillos, diámetro de varilla, altura del cuerpo, etc.),
tal como las publica el fabricante — **no** es el tamaño de la
caja/empaque del producto. Ningún fabricante publica eso en su web
pública; para bounding-box real de bodega haría falta la ficha de
empaque/logística del proveedor, no el catálogo. `volumen_cm3` (más
`volumen_metodo` y `volumen_confianza`, que documentan exactamente qué se
midió/asumió) es una aproximación calculada a partir de esas medidas de
ingeniería — cilindro real (`π×r²×h`) cuando la pieza es genuinamente
redonda con diámetro+largo confirmados, o caja envolvente cuando es una
pieza irregular (abrazadera, gancho) y solo sirve como sobrestimación
razonable del espacio que ocupa, nunca como volumen de material exacto.

### Estado al 2026-08-10 (ronda 2 — 8 ERICO + 4 TYCO — y ronda MECH — 105 fu-mech.com + meide.mx — revisados de nuevo)

| Marca | # códigos | material | peso | volumen | Notas |
|---|---|---|---|---|---|
| MECH | 105 | 81 | 0 | 95 | **95/105 con volumen (2026-08-11) — solo queda 1 familia sin dato.** 60 cerrados en la ronda MECH inicial (Rigid Coupling, Mechanical Tee 3G/3J, Flexible Hose, Elbow 45, Tee 130/130S, BMI roscados, Support hanger GSD9, Beam Clamp 3034). Los 35 restantes se cerraron en rondas de verificación manual del usuario, cada una destapando una fuente que la búsqueda automática no había visto: acople 1N completo (7/7, vía un PDF individual y luego un **catálogo maestro de 88 páginas** de fu-mech.com), codo 90/90S (8/8, vía una imagen thumbnail de WordPress), Tee 3J combo (1/1, texto oculto de un PDF recortado), reductor concéntrico 240 (5/5), STRAP (10/10) y tapa simple 300 (4/4) — estas últimas 3 resueltas al final vía **fichas individuales de producto en meide.mx** ("PRODUCT-data-sheet-DS-400-XXX", mismo fabricante Jinan Meide, encontradas por el usuario y confirmadas por la API REST de WordPress de ese sitio). Se corrigieron 4 errores de mapeo del matcher original. Queda solo tubería roja A795/A53 (10/105) sin volumen: el folleto del fabricante da peso por metro pero nunca un largo de barra estándar de venta. Detalle completo por familia en `FALTANTES.md` y `enriquecimiento/completar_volumen_mech.py`. |
| RELIABLE | 23 | 22 | 0 | 22 | 22/23 con material+dimensiones+volumen vía boletines reales (bulletins). Ningún boletín publica peso. Se detectaron y corrigieron 2 familias mal mapeadas por URL (SIN real no coincidía con la página guardada en `scrapes_ultimo`): 4 códigos eran realmente J112/JL112 (Bulletin 172), no GL112; 2 códigos eran F1FR80 estándar (Bulletin 063), no F1FR80-300. Único sin volumen: `73PQRBRO12` (SIN RA3415, modelo G5-56) — **boletín correcto encontrado en la ronda de seguimiento (034, no el 051/074 revisados antes)**, confirma material y diámetro real del cuerpo (58mm), pero el fabricante no publica una altura total del cuerpo — sin volumen por falta de ese eje, no por falta de ficha. |
| PHD | 21 | 21 | 11 | 11 | Cerrado — los 10 restantes (soportes antisísmicos FIG 010/015/030/031) no tienen peso propio publicado, solo capacidad de carga estructural. Confirmado por 2ª fuente independiente (datasheet individual "View Data Sheet") en la ronda de seguimiento. |
| TYCO | 16 | 16 | 0 | 15 | **15/16 con volumen.** Encontrados y corregidos 3 errores de material donde se había aplicado la ficha de un modelo/serie equivocado (TY-L vs TY-FRB vs TY-B). Los 4 escudos se cerraron en la ronda 2: P/N real embebido en `nombre_producto` identificó el estilo exacto en TFP770 y TFP181 — cilindro real, confianza alta, 4/4. **2 códigos más resueltos en la ronda de seguimiento**: `73A3B2A1` (TY3331, TFP176, cilindro envolvente 92.40 cm³) y `73PQBROI12` (TY3531, TFP181 Figura 2 — dimensiones del conjunto cuerpo+copa, no del escudo — 161.03 cm³), ambos confianza media. Único sin volumen: `75B1B2A2` (TY5137, TFP220 revisada a fondo — solo da alturas, ningún diagrama trae el ancho/diámetro del cuerpo upright). |
| ERICO | 11 | 8 | 0 | 7 | FIG 300/310 (Cast Iron, dimensiones parciales documentadas, sin volumen — falta eje de altura/largo) y FIG 100 (dimensiones de ficha Ferguson) resueltos; **FIG 115 cerrado en ronda 2**: ficha real `nvent.com/.../115-standard-duty-loop-hanger-0/pdf` (pedida directo con `curl`, Playwright topaba con Cloudflare) trae tabla+diagrama con OD/A/B/C/RS — 4/4 con material, dimensiones y volumen (confianza media). |
| GLOBE (Victaulic) | 7 | 7 | 0 | 7 | Cerrado — material+volumen para los 7 (4 rociadores confianza alta vía diagrama, 3 escudos/cover plates confianza media vía tabla). Victaulic no publica peso para ninguno de estos códigos. |
| WILSON & COUSINS | 3 | 3 | 0 | 3 | Cerrado. |
| SIMPLEX | 2 | 0 | 2 | 2 | Peso/dimensiones de distribuidor (no fabricante directo), confianza media/baja. |
| KIDDE, TYLER UNION, STAR PIPE | 3 | 3 | 3 | 2 | Cerrados (Star Pipe: se corrigió un error — el material NO es PVC, es hierro dúctil; "PVC" en el nombre describe la tubería para la que sirve). |
| ANVIL | 1 | 1 | 1 | 1 | **Resuelto (2026-08-11)** — `6A20012341` es el único código de rango de tallas de los 194 (1/2"-1", verificado exhaustivamente que no hay más casos así). Ficha submittal real con diagrama A/B/C/F/G; se cargó la talla del medio (3/4") como representante, 10.56 cm³, confianza baja — las 3 tallas del rango dan volúmenes muy similares (9.84-11.04 cm³). |
| TANDL | 2 | 0 | 0 | 0 | Sitio placeholder de leads B2B sin fichas de producto, confirmado que no hay nada que sacar. |

**Total: 166/194 con volumen, 27/194 con peso, 172/194 con material.** (Los 10 PHD de peso nuevo: catálogo maestro `FireProtectionSeismicCatalog_1216.pdf` da peso por unidad aunque no dimensión física. ANVIL `6A20012341` es el único código de rango de tallas de los 194, verificado exhaustivamente. Los +2 más recientes son TYCO `73A3B2A1`/`73PQBROI12`, resueltos en la ronda de seguimiento página-por-página — ver `FALTANTES.md`.)
De esos 163, 8 los cerró la ronda 2 (ERICO+TYCO) y 155 salieron de MECH:
60 de la ronda MECH inicial y 95 de una serie de rondas de verificación
manual del usuario (acople 1N, codo 90°/90S, Tee 3J, reductor 240,
STRAP, tapa simple 300) que pasó por un catálogo maestro de 88 páginas
de fu-mech.com y terminó en una biblioteca de fichas individuales de
producto en meide.mx — ver detalle completo en `FALTANTES.md`, empezando
por la sección "Ronda fichas individuales meide.mx".

Pendiente real restante fuera de MECH (28 códigos, ver `FALTANTES.md`
sección "Ronda seguimiento página-por-página" para el detalle completo):
`73PQRBRO12` de Reliable (boletín correcto encontrado — 034 — pero sin
altura del cuerpo publicada), `75B1B2A2` de TYCO (ficha TFP220 revisada
a fondo, solo da alturas), los 4 ERICO FIG 300/310 (ficha real con
diagrama, confirmado 4 veces incluida la pestaña "Details" en vivo de
nvent.com, pero el fabricante no publica altura total del cuerpo ni
largo a lo largo de la viga), los 10 PHD de soportes antisísmicos, y los
10 de tubería roja MECH (confirmado en 8 documentos distintos del
fabricante). El resto de marcas están cerradas — lo que falta no tiene
el dato publicado por el fabricante, no es falta de búsqueda.

**Metodología clave aprendida esta ronda** (aplicar a lo que falta):
1. No busques solo la palabra "Weight"/"Dimensions" como texto — muchas
   veces la medida está pegada a un diagrama técnico y hay que renderizar
   la página como imagen (`pdfplumber` → `.to_image()` → ver el PNG) para
   entender qué mide cada letra.
2. Cuidado con el diámetro del **escudo/cover plate** (accesorio) vs el
   diámetro del **cuerpo del rociador** — en TYCO, 73.0mm era el escudo;
   el cuerpo real medía 57.2mm. Buscar explícitamente "face of sprinkler
   fitting" o equivalente.
3. Verificar que el **SIN/modelo exacto** de la ficha coincide con el
   código antes de aplicar nada — modelos con nombres casi idénticos
   (TY313 vs TY3131 vs TY3111) pueden ser productos físicamente
   distintos, documentados en fichas TFP distintas, con material y
   dimensiones diferentes.
4. Volumen: cilindro real (`π×r²×h`) para piezas redondas con
   diámetro+largo confirmados; caja envolvente solo para piezas
   irregulares.

## Auditoría: PDF de cada página fuente

`data/capturas_fuentes/` (generado por `herramientas/capturar_fuentes_pdf.py`) tiene un PDF
de cada una de las 58 páginas/documentos únicos usados como fuente en todo
el scraping — para poder comparar a mano lo que quedó en la base contra la
página real, sin tener que volver a navegar cada sitio. `data/capturas_fuentes/manifiesto.csv`
mapea cada PDF a su `url_fuente` y a los códigos que lo usan. 57/58 capturados
(el que falta, la ficha ERICO FIG 100 vía api.ferguson.com, responde muy lento
y da timeout — el texto ya extraído de ahí sigue disponible en `scrapes`).

## Migración a Supabase

El schema y los datos actuales (194 productos, 228 scrapes, 400 páginas de
catálogo) ya están listos para subir — ver `db/schema_supabase.sql` (mismo
schema + RLS: lectura pública, escritura solo con service_role/conexión
directa), `db/datos/datos.sql` (los datos, como INSERTs) y los
pasos concretos en `docs/MIGRACION_SUPABASE.md`. Se probó restaurar ambos
archivos en una base Postgres vacía y los conteos cierran exacto (194/228/400).

## Estructura

Ver el `README.md` de la raíz (estructura de carpetas actualizada).

## Decisiones ya tomadas (para no repreguntar)

- **robots.txt se ignora a propósito**: es catálogo público (descripciones,
  series, precios de lista), no hay login ni datos personales.
- **Solo se scrapean marcas con dominio oficial conocido** en
  `fabricantes.py` (170-194 de los 194 códigos según el dominio se sepa o
  no); las que no tienen dominio quedan en `Sin_Dominio` sin intentar
  búsqueda genérica por ahora.
- **twisted==24.7.0 pineado**: la imagen base trae una Twisted mucho más
  nueva (26.x) que rompe `scrapy_playwright` (falta
  `_setAcceptableProtocols` en el contextfactory de Scrapy 2.12). Si se
  actualiza `scrapy` a una versión más nueva, probar si ya no hace falta
  este pin.
