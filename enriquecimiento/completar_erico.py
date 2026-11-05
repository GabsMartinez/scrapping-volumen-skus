# =========================================================================
# completar_erico.py - completa specs de ERICO desde el texto que YA está
# guardado en scrapes.descripcion (no vuelve a scrapear):
#
#   - FIG 100 (3 códigos): la ficha Ferguson que se usó para resolver
#     estos códigos (ver README, sección ERICO) ya trae dimensiones H/CL/
#     RS/A, carga máxima y acabado en texto plano -- solo hay que
#     parsearlas.
#   - FIG 300 y FIG 310 (4 códigos): "310 Universal Beam Clamp, Thick
#     Flange" declara "Material: Cast Iron" explícito. FIG 300 es la
#     MISMA familia de producto ("Universal Beam Clamp", misma norma
#     WW-H-171 Type 23 / MSS SP-58 Type 19&23) y solo difiere en grosor
#     de ala -- se aplica el mismo material por identidad de familia, no
#     por adivinanza entre productos distintos.
#   - FIG 115 (4 códigos): no queda nada confirmado -- la ficha es solo
#     texto de marketing sin material/dimensión, se deja sin tocar.
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_erico.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_FIG100 = re.compile(
    r"H=([\d/\-]+)\".*?CL=([\d/\-]+)\".*?RS=([\d/\-]+)\".*?A=([\d/\-]+)\".*?"
    r"Max Recom Load=(\d+) lbs, Finish=(\w+)"
)


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT p.codigo, p.nombre_producto, s.descripcion FROM productos_criticos p "
            "JOIN scrapes_ultimo s ON s.codigo = p.codigo "
            "WHERE p.marca = 'ERICO' AND s.estado = 'ok'"
        )
        filas = cur.fetchall()

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for fila in filas:
            nombre = fila["nombre_producto"].upper()
            desc = fila["descripcion"] or ""

            if "FIG 100" in nombre:
                m = RE_FIG100.search(desc)
                if not m:
                    continue
                h, cl, rs, a, carga, acabado = m.groups()
                dims = f"H: {h}\" | CL: {cl}\" | RS: {rs}\" | A: {a}\" | Max. Rec. Load: {carga} lbs"
                cur.execute(
                    "UPDATE productos_criticos SET dimensiones_texto=%s, acabado=%s, "
                    "aprobaciones=%s, dimensiones_fuente=%s WHERE codigo=%s",
                    (dims, acabado, "Conforms WW-H-171 Type 10, ANSI/MSS-SP-58 Type 10",
                     "erico.com (ficha original Ferguson, ver README)", fila["codigo"]),
                )
                actualizados += 1

            elif "FIG 300" in nombre or "FIG 310" in nombre:
                cur.execute(
                    "UPDATE productos_criticos SET material=%s, aprobaciones=%s, "
                    "specs_adicionales = COALESCE(specs_adicionales || ' | ', '') || %s "
                    "WHERE codigo=%s",
                    ("Hierro fundido (Cast Iron)",
                     "Conforms WW-H-171 (Type 23), MSS SP-58 (Type 19 and 23)",
                     "Material confirmado en ficha de FIG 310 (misma familia 'Universal Beam Clamp' que FIG 300)",
                     fila["codigo"]),
                )
                actualizados += 1

    conexion.close()
    print(f"{actualizados}/{len(filas)} códigos ERICO completados.")


if __name__ == "__main__":
    main()
