# =========================================================================
# erico_matcher.py - ERICO. Los productos que nos importan (soportes tipo
# pera / beam clamps) ya NO se venden bajo la marca "ERICO" en el sitio
# actual: viven bajo "nVent CADDY" (erico.com redirige a nvent.com, que
# agrupa marcas). No hay crawl de catálogo acá: solo 4 números de figura
# distintos entre los 11 códigos, así que se resolvió cada uno a mano
# investigando el buscador real del sitio (Coveo, nvent.com/en-us/search)
# y navegando la página de categoría "loop-hangers".
#
# FIG 100 (3 códigos, "SOPORTE TIPO PERA") NO tiene página vigente en el
# catálogo actual de CADDY — se revisó la categoría "Loop Hangers"
# completa y solo existe "100T" (Heavy Duty Trapeze), no un "100" liso.
# Probablemente descontinuado/renombrado. Se deja como no_encontrado real,
# no por falta de búsqueda.
#
# Uso:
#   docker compose exec scraper python matchers/erico_matcher.py
# =========================================================================

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


# figura -> (url, título, descripción) ya confirmados a mano contra el
# sitio real (ver comentario arriba). Clave: la figura tal como aparece
# en Nombre Producto ("FIG 100", "FIG 115", etc.).
PAGINAS_CONFIRMADAS = {
    "FIG 115": (
        "https://www.nvent.com/en-us/caddy/products/115-standard-duty-loop-hanger-0",
        "115 Standard Duty Loop Hanger | nVent CADDY",
        "The 115 Standard Duty Loop Hanger is ideal for suspending stationary, "
        "non-insulated pipe lines, including CPVC pipes, in fire sprinkler systems. "
        "A knurled locknut secures the pipe.",
    ),
    "FIG 300": (
        "https://www.nvent.com/en-us/caddy/products/300-universal-beam-clamp-0",
        "300 Universal Beam Clamp | nVent CADDY",
        "Conforms with Federal Specification WW-H-171 (Type 23), Manufacturers "
        "Standardization Society (MSS) SP-58 (Type 19 and 23).",
    ),
    "FIG 310": (
        "https://www.nvent.com/en-us/caddy/products/310-universal-beam-clamp-thick-flange-0",
        "310 Universal Beam Clamp, Thick Flange | nVent CADDY",
        "Universal beam clamp for thick beams. Conforms with Federal Specification "
        "WW-H-171 (Type 23), Manufacturers Standardization Society (MSS) SP-58 "
        "(Type 19 and 23). Material: Cast Iron.",
    ),
}


def figura_de(nombre_producto: str) -> str | None:
    up = nombre_producto.upper()
    for figura in PAGINAS_CONFIRMADAS:
        if figura in up:
            return figura
    return None


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'ERICO'")
        productos = cur.fetchall()

    resultados = {"ok": 0, "no_encontrado": 0}
    filas_insertar = []

    for producto in productos:
        figura = figura_de(producto["nombre_producto"])
        if figura is None:
            filas_insertar.append((
                producto["codigo"], "erico.com", None, None, None, None, None,
                "no_encontrado",
                "FIG 100 (soporte tipo pera): no existe página vigente en el catálogo "
                "actual de nVent CADDY. Se revisó la categoría completa 'Loop Hangers' "
                "y solo existe la variante '100T', no un '100' liso — probablemente "
                "descontinuado o renombrado.",
            ))
            resultados["no_encontrado"] += 1
            continue

        url, titulo, descripcion = PAGINAS_CONFIRMADAS[figura]
        filas_insertar.append((
            producto["codigo"], "erico.com", url, descripcion, titulo, None, None,
            "ok", f"Match manual verificado: {figura} -> nVent CADDY (marca actual del producto).",
        ))
        resultados["ok"] += 1

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'erico.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    print(f"ERICO: {resultados['ok']} matches, {resultados['no_encontrado']} sin match (de {len(productos)} códigos).")


if __name__ == "__main__":
    main()
