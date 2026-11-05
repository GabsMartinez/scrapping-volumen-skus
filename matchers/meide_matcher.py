# =========================================================================
# meide_matcher.py - MECH, segunda fuente: meidegroup.com (el dominio
# original en fabricantes.py) no responde — ECONNREFUSED tanto por curl
# como por Playwright, probablemente bloqueado geográficamente. El
# fabricante real es Jinan Meide Casting Co., cuyo distribuidor mexicano
# meide.mx SÍ responde y publica fichas técnicas (PDF) por producto que
# fu-mech.com no tiene.
#
# Cubre las familias que fu-mech.com confirmadamente NO publica (ver
# README, "Por qué MECH quedó en 70% y no más"):
#   - SOPORTE TIPO PERA (PGSD9xx) -> ficha "Support hanger - Ring hanger",
#     modelo real GSD9 (nuestro código le agrega el prefijo "P").
#   - STRAP / TEE MEC (P3Lxxxxx)  -> ficha "DI GROOVED U-BOLT MECHANICAL
#     TEE" (MT1): la descripción ("saddle-shaped... U-bolt") es
#     exactamente un STRAP.
#   - TUB ROJA AC ASTM 795 SCH 10 -> ficha "Welded Steel Pipe - ASTM A795
#     SCH 10" (Jinan Mech Piping Technology Co., la división de tubería).
#   - TUB ROJA / TUBO AC A53 SCH 40 -> ficha "Welded Steel Pipe - ASTM
#     A53 SCH 40".
#   - RED CON RAN X RAN (reductor concéntrico ranurado) -> ficha "DI
#     GROOVED FITTINGS - GROOVED CONCENTRIC REDUCER" (RC).
#
# Los PDFs se descargaron a mano (búsqueda web + verificación de
# contenido) y quedan en data/fuentes/.
#
# VERIFICACIÓN DE VIGENCIA (2026-08-05): meide.mx SÍ tiene páginas HTML
# reales además de los PDFs (nav: TUBERIA, RANURADO, VÁLVULAS) — se
# revisaron y confirman los mismos productos en español, así que para
# STRAP/RC/tubería se usa la página viva como url_fuente principal (se
# actualiza sola, a diferencia de un PDF fijo) y el PDF queda como
# referencia técnica en la descripción. Para pera (GSD9) y beam clamp
# (3034) no existe página viva equivalente (no están en el menú
# principal) — se usó el PDF, pero se verificó el metadata: ModDate
# 2026-05-14, así que están vigentes.
# Los PDFs de tubería A795/A53 que se habían usado primero eran de
# 2020/2021; se encontró una ficha combinada más nueva (2026-03-12,
# "Jinan Mech Piping Technology Co.") con LOS MISMOS valores
# dimensionales (norma ASTM, no cambia) — se cambió la referencia a esa
# versión más reciente por prolijidad, aunque el dato en sí no había
# cambiado.
#
# No cubre TAPON MACHO / RED BUSHING (ya resueltos en mech_matcher.py,
# fu-mech.com) ni MANGUERA FLEX (fu-mech.com) — no se encontró ficha
# específica para manguera en meide.mx.
#
# Uso:
#   docker compose exec scraper python matchers/meide_matcher.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


# (patrón que debe aparecer en nombre_producto, url, serie, descripción)
FAMILIAS = [
    (
        re.compile(r"PGSD9", re.IGNORECASE),
        "https://www.meide.mx/wp-content/uploads/2026/05/Support-hanger-Ring-hanger-Pera.pdf",
        "Support hanger - Ring hanger, modelo GSD9",
        "Se usa para la conexión de tuberías y fija su posición; las tuercas se "
        "conectan a accesorios roscados unidos a edificios o vigas de acero. "
        "Rango: 1/2\"(DN15)-12\"(DN300). Norma de diseño: MSS SP-58. Apto para "
        "suspensión de tubería de acero SCH40 en protección contra incendios, "
        "suministro de agua y drenaje.",
    ),
    (
        # "STRAP" + "TEE MEC" ya identifica la familia sola: algunos
        # códigos ni siquiera traen el "P3L" pegado en el nombre.
        re.compile(r"STRAP.*TEE MEC|P3L\s*\d", re.IGNORECASE),
        "https://www.meide.mx/coples-y-conexiones-ranuradas/",
        "T Mecánica U-bolt (página viva meide.mx; ficha técnica: PRODUCT-data-sheet-DS-400-MT1-01-E-U-BOLT-MECHANICAL-TEE.pdf)",
        "El U-bolt mecánico de tres vías es una pieza de conexión en forma de "
        "silla de montar para conectar el ramal en el medio del tubo y el perno "
        "en U en la cubierta inferior; el ramal es conexión roscada. Se puede "
        "conectar a rociadores contra incendios, manómetros, desagües, etc. "
        "Rango: 1-1/4\"(DN32)-6\"(DN150), 175-300 PSI.",
    ),
    (
        re.compile(r"ASTM\s*795|ASTM\s*A795", re.IGNORECASE),
        "https://www.meide.mx/jinan-mech-piping/",
        "Welded Steel Pipe - ASTM A795 SCH 10 (Jinan Mech Piping Technology Co.; "
        "ficha técnica: STEEL-PIPE-BROCHURE-2026.3.12.pdf)",
        "Tubería roja: estándar en sistemas contra incendio en México, se entrega "
        "pintada de rojo con acabado epoxy. Norma ASTM A795 (tubería de acero "
        "soldada negra/galvanizada para protección contra incendios), Cédula 10. "
        "Aprobada UL, FM, SII. Tallas 3/4\"-8\".",
    ),
    (
        re.compile(r"\bA53\b", re.IGNORECASE),
        "https://www.meide.mx/jinan-mech-piping/",
        "Welded Steel Pipe - ASTM A53 SCH 40 (Jinan Mech Piping Technology Co.; "
        "ficha técnica: STEEL-PIPE-BROCHURE-2026.3.12.pdf)",
        "Tubería roja: estándar en sistemas contra incendio en México, se entrega "
        "pintada de rojo con acabado epoxy. Norma ASTM A53 (tubería de acero "
        "soldada negra/galvanizada para protección contra incendios), Cédula 40. "
        "Aprobada UL, FM, SII. Tallas 1/2\"-10\".",
    ),
    (
        re.compile(r"RED CON RAN", re.IGNORECASE),
        "https://www.meide.mx/coples-y-conexiones-ranuradas/",
        "Cople Ranurado / Reductor Concéntrico (página viva meide.mx; ficha "
        "técnica: PRODUCT-data-sheet-DS-400-RC-CONCENTRIC-REDUCER.pdf)",
        "Reductor concéntrico ranurado para conexión de tubería ranurada; se usa "
        "para cambios de diámetro, con los centros de ambos extremos en línea "
        "recta. Rango: 1-1/4\"(DN32)-14\"(DN350).",
    ),
    (
        re.compile(r"FIG\.?\s*G?3034", re.IGNORECASE),
        "https://www.meide.mx/wp-content/uploads/2026/05/DS-1A7-3034-01-E-Mordaza.pdf",
        "Malleable Iron Wide-Mouth Top Beam Clamp, tipo 3034",
        "Mordaza (clamp) de hierro maleable de boca ancha para conectar con la "
        "estructura de acero, evita perforar o soldar en la superficie del "
        "perfil. Solo se ajustan los tornillos para hacer/deshacer la conexión.",
    ),
]


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT p.codigo, p.nombre_producto FROM productos_criticos p
            LEFT JOIN scrapes s ON s.codigo = p.codigo AND s.dominio = 'fu-mech.com'
            WHERE p.marca = 'MECH' AND (s.estado IS NULL OR s.estado != 'ok')
        """)
        pendientes = cur.fetchall()

    filas = []
    resueltos = set()
    for producto in pendientes:
        for patron, url, serie, descripcion in FAMILIAS:
            if patron.search(producto["nombre_producto"]):
                filas.append((
                    producto["codigo"], "meide.mx", url, descripcion, serie, None, None, "ok",
                    "Match por familia contra ficha técnica de meide.mx (meidegroup.com no "
                    "responde). Confirmado con búsqueda web + verificación de contenido del PDF.",
                ))
                resueltos.add(producto["codigo"])
                break

    with conexion, conexion.cursor() as cur:
        codigos = [f[0] for f in filas]
        if codigos:
            cur.execute("DELETE FROM scrapes WHERE dominio = 'meide.mx' AND codigo = ANY(%s)", (codigos,))
            cur.executemany("""
                INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, filas)

    conexion.close()
    print(f"MECH (meide.mx, segunda fuente): {len(filas)} matches de {len(pendientes)} códigos "
          f"que seguían pendientes tras fu-mech.com.")


if __name__ == "__main__":
    main()
