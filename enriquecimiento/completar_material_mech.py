# =========================================================================
# completar_material_mech.py - completa productos_criticos.material para
# MECH, usando declaraciones de material CONFIRMADAS por catálogo/ficha,
# no adivinadas:
#
#   - " RAN " (ranurado/grooved) en el nombre -> "Ductile Iron Grooved
#     Fittings and Couplings" es el encabezado de sección real en
#     MECH-GROOVED-NEW-.pdf (pág. 11), Material: ASTM A536 GRADE 65-45-12
#     (pág. 12) -- aplica a todo ese rango de modelos (1N/1G/90/130/240/300...).
#   - "ACx300 LBS ROSC" en el nombre -> corresponde a la sección "American
#     Standard Class 300" de BMI-Catalogue-NEW-.pdf (pág. 30), Material:
#     ASTM A197/A197M (hierro maleable).
#   - "FIG. G3034" (beam clamp) -> ya lo dice el propio texto que guardó
#     meide_matcher.py: "Malleable Iron Wide-Mouth Top Beam Clamp".
#   - "TUB ROJA"/"TUBO AC" + ASTM A795/A53 (tubería) -> el propio texto de
#     meide_matcher.py dice "tubería de acero soldada negra/galvanizada".
#
# NO cubre (a propósito, sin fuente confirmada): SOPORTE TIPO PERA
# (PGSD9 -- la ficha de meide.mx no declara material del cuerpo, solo de
# los accesorios de conexión) ni STRAP/TE MEC (P3L/P3J -- no se encontró
# una declaración de material específica para esa familia). Mejor dejarlos
# NULL que asumir que son ductile iron como el resto del catálogo grooved.
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_material_mech.py
# =========================================================================

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


MATERIAL_DUCTIL = "Hierro dúctil (Ductile Iron), ASTM A536 Grade 65-45-12"
MATERIAL_MALEABLE = "Hierro maleable (Malleable Iron), ASTM A197/A197M"
MATERIAL_ACERO_SOLDADO = "Acero al carbono soldado (Welded Carbon Steel), ASTM A795/A53"

REGLAS = [
    # (condición SQL, material, fuente)
    (" RAN ", MATERIAL_DUCTIL,
     "fu-mech.com, MECH-GROOVED-NEW-.pdf pág. 11-12 (sección 'Ductile Iron Grooved Fittings and Couplings')"),
    ("ACx300 LBS ROSC", MATERIAL_MALEABLE,
     "fu-mech.com, BMI-Catalogue-NEW-.pdf pág. 30 (sección 'American Standard Class 300')"),
    ("FIG. G3034", MATERIAL_MALEABLE,
     "meide.mx, DS-1A7-3034-01-E-Mordaza.pdf (texto ya guardado en scrapes: 'Malleable Iron Wide-Mouth Top Beam Clamp')"),
    ("ASTM 795", MATERIAL_ACERO_SOLDADO,
     "meide.mx (texto ya guardado en scrapes: tubería de acero soldada)"),
    (" A53 ", MATERIAL_ACERO_SOLDADO,
     "meide.mx (texto ya guardado en scrapes: tubería de acero soldada)"),
]


def main():
    conexion = psycopg2.connect(**CONEXION)
    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for patron, material, fuente in REGLAS:
            cur.execute(
                """
                UPDATE productos_criticos
                SET material = %s,
                    specs_adicionales = COALESCE(specs_adicionales || ' | ', '') ||
                        'Material confirmado por: ' || %s
                WHERE marca = 'MECH' AND material IS NULL AND nombre_producto ILIKE %s
                """,
                (material, fuente, f"%{patron}%"),
            )
            print(f"  '{patron}': {cur.rowcount} códigos.")
            actualizados += cur.rowcount

    conexion.close()
    print(f"\nTotal: {actualizados} códigos MECH completados con material confirmado.")


if __name__ == "__main__":
    main()
