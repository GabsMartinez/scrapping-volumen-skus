# =========================================================================
# completar_kfactor.py - completa productos_criticos.k_factor para los
# códigos que ya lo traen en su propio nombre_producto (ej. "K5.6",
# "K11.2") pero no lo trajeron de una página scrapeada. Misma lógica que
# completar_tamano.py: solo rellena donde sigue NULL, nunca sobreescribe
# un valor que vino de la fuente del fabricante.
#
# El patrón exige que "K" NO esté precedida de letra/dígito (para no
# capturar cosas como "PVCPK4004", donde la K es parte de un código de
# ítem, no un K-factor de rociador).
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_kfactor.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_K = re.compile(r"(?<![A-Z0-9])K\s?(\d{1,2}(?:\.\d+)?)\b")


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE k_factor IS NULL")
        pendientes = cur.fetchall()

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for producto in pendientes:
            m = RE_K.search(producto["nombre_producto"].upper())
            if not m:
                continue
            cur.execute(
                "UPDATE productos_criticos SET k_factor = %s, "
                "specs_adicionales = COALESCE(specs_adicionales || ' | ', '') || "
                "'K-factor derivado del propio código interno' WHERE codigo = %s",
                (m.group(1), producto["codigo"]),
            )
            actualizados += 1

    conexion.close()
    print(f"{actualizados}/{len(pendientes)} códigos completados con K-factor derivado del nombre interno.")


if __name__ == "__main__":
    main()
