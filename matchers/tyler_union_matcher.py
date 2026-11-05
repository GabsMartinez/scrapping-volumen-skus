# =========================================================================
# tyler_union_matcher.py - TYLER UNION. Solo 1 código: un restrictor de
# junta para tubería de hierro dúctil ("TUF GRIP" en nuestro nombre, que
# es como la distribuidora tradujo/renombró el "Tufgrip(TM) Restraint for
# Ductile Iron Pipe" real de Tyler Union - Series 1000). Confirmado a
# mano navegando tylerunion.com/products/catalog/restraints/.
#
# Uso:
#   docker compose exec scraper python matchers/tyler_union_matcher.py
# =========================================================================

import psycopg2

from scraper_precios.config import CONEXION


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor() as cur:
        cur.execute("SELECT codigo FROM productos_criticos WHERE marca = 'TYLER UNION'")
        codigos = [r[0] for r in cur.fetchall()]

    filas = [(
        codigo, "tylerunion.com",
        "https://www.tylerunion.com/products/catalog/restraints/",
        "Tufgrip™ Restraint for Ductile Iron Pipe (Series 1000). Nuestro código no "
        "especifica cuál de las variantes exactas (1000 TLD, 1000S) — se referencia "
        "la familia; el submittal PDF con specs detalladas está en la misma página.",
        "Tufgrip™ Restraint for Ductile Iron Pipe", None, None, "ok",
        "Match por familia de producto (no hay página por talla individual en el sitio).",
    ) for codigo in codigos]

    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'tylerunion.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas)

    conexion.close()
    print(f"TYLER UNION: {len(filas)} matches (de {len(codigos)} códigos).")


if __name__ == "__main__":
    main()
