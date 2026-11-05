# =========================================================================
# simplex_matcher.py - SIMPLEX (marca de Johnson Controls, la misma
# empresa dueña de TYCO, pero unidad de Fire DETECTION en vez de Fire
# SUPPRESSION — otro catálogo, otro price book).
#
# El buscador real de johnsoncontrols.com (?q=...) SÍ funciona (devuelve
# "Results 1-4 of 4"), pero solo entrega páginas genéricas de la línea de
# negocio ("Fire Detection"), no fichas por código de producto: los
# dispositivos Simplex (bases, sensores direccionables) se venden a
# través de instaladores certificados, sin catálogo público por SKU.
# No se encontró un price book público equivalente al de TYCO.
#
# Uso:
#   docker compose exec scraper python matchers/simplex_matcher.py
# =========================================================================

import psycopg2

from scraper_precios.config import CONEXION


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor() as cur:
        cur.execute("SELECT codigo FROM productos_criticos WHERE marca = 'SIMPLEX'")
        codigos = [r[0] for r in cur.fetchall()]

    filas = [(
        codigo, "johnsoncontrols.com", None, None, None, None, None, "no_encontrado",
        "El buscador de johnsoncontrols.com funciona pero solo devuelve páginas "
        "genéricas de línea de negocio ('Fire Detection'), no fichas por código de "
        "producto. Los dispositivos Simplex se distribuyen vía instaladores "
        "certificados; no se encontró catálogo público por SKU ni price book.",
    ) for codigo in codigos]

    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas)

    conexion.close()
    print(f"SIMPLEX: 0 matches, {len(filas)} sin match (de {len(codigos)} códigos).")


if __name__ == "__main__":
    main()
