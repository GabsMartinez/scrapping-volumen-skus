# =========================================================================
# star_pipe_matcher.py - STAR PIPE. Solo 1 código: mismo tipo de pieza que
# TYLER UNION (restrictor de junta), pero acá el producto real de Star
# Pipe se llama "Stargrip®" (no "Tuf Grip" — nombre genérico de la
# distribuidora). El código embebido "PVCPK4004" y el sufijo "HD" del
# nombre apuntan a la línea PVC Stargrip Series 4000HD.
#
# Uso:
#   docker compose exec scraper python matchers/star_pipe_matcher.py
# =========================================================================

import psycopg2

from scraper_precios.config import CONEXION


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor() as cur:
        cur.execute("SELECT codigo FROM productos_criticos WHERE marca = 'STAR PIPE'")
        codigos = [r[0] for r in cur.fetchall()]

    filas = [(
        codigo, "starpipeproducts.com",
        "https://www.starpipeproducts.com/product/pvc-stargrip-series-4000hd",
        "PVC Stargrip® Series 4000HD: restrictor de junta mecánica (MJ) para "
        "tubería PVC, línea heavy duty (HD). Nuestro código incluye el ítem real "
        "PVCPK4004, consistente con esta serie.",
        "PVC Stargrip® Series 4000HD", None, None, "ok",
        "Match por número de ítem embebido (PVCPK4004) + sufijo HD del nombre.",
    ) for codigo in codigos]

    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'starpipeproducts.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas)

    conexion.close()
    print(f"STAR PIPE: {len(filas)} matches (de {len(codigos)} códigos).")


if __name__ == "__main__":
    main()
