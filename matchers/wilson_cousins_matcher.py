# =========================================================================
# wilson_cousins_matcher.py - WILSON & COUSINS.
#
# El dominio de fabricantes.py ("wilsoncousins.com") no resuelve — el
# real es wilsonandcousins.com ("and" completo, no "&"). Solo 3 códigos,
# cada uno encontrado a mano navegando categoría -> subcategoría por
# talla (el sitio SÍ tiene URLs limpias por producto, sin necesitar
# buscador ni crawl completo).
#
# Uso:
#   docker compose exec scraper python matchers/wilson_cousins_matcher.py
# =========================================================================

import psycopg2

from scraper_precios.config import CONEXION


# código -> (url, título/SKU, descripción) verificados a mano contra el sitio real.
MATCHES = {
    "5A28BRSR112": (
        "https://wilsonandcousins.com/product/ie25h-m-brass/",
        "IE25H-M-BRASS",
        "1.5\" Brass Angle Valve with hydrolator Female NPT Inlet x Male Hose Outlet.",
    ),
    "5A32VSRB212": (
        # nuestro código es "IE23E" (con tapa/cadena); el sitio solo lista
        # variantes IE23-BRASS/CP/FF/HPCP e IE23G-*, sin sufijo "E" — se
        # toma IE23-BRASS (misma familia/talla) como el más cercano.
        "https://wilsonandcousins.com/product/ie23-brass/",
        "IE23-BRASS (familia; nuestro código es la variante IE23E con tapa/cadena, no listada por separado)",
        "2.5\" Standard Angle Hose Valve. 2.5\" Female Inlet x 2.5\" Male Hose Thread Outlet.",
    ),
    "23BOQP0112": (
        "https://wilsonandcousins.com/product/hn4lred/",
        "HN4LRED",
        "1.5\" Red Plastic combination fog nozzle",
    ),
}


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor() as cur:
        cur.execute("SELECT codigo FROM productos_criticos WHERE marca = 'WILSON & COUSINS'")
        codigos = [r[0] for r in cur.fetchall()]

    filas = []
    for codigo in codigos:
        if codigo in MATCHES:
            url, titulo, descripcion = MATCHES[codigo]
            filas.append((codigo, "wilsonandcousins.com", url, descripcion, titulo, None, None,
                          "ok", "Match verificado a mano navegando categoría -> subcategoría por talla."))
        else:
            filas.append((codigo, "wilsonandcousins.com", None, None, None, None, None,
                          "no_encontrado", "No revisado."))

    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'wilsonandcousins.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas)

    conexion.close()
    ok = sum(1 for f in filas if f[7] == "ok")
    print(f"WILSON & COUSINS: {ok} matches, {len(filas)-ok} sin match (de {len(filas)} códigos).")


if __name__ == "__main__":
    main()
