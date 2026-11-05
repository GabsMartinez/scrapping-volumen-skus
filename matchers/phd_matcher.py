# =========================================================================
# phd_matcher.py - PHD Manufacturing (phd-mfg.com). Cruza productos_
# criticos (marca PHD) contra catalogo_fabricante (crawlers/phd_crawler.py)
# por número de figura ("FIG 141", "FIG. 015", etc.).
#
# La mayoría matchea 1:1 exacto contra el "Figure: ###" principal de cada
# página. Excepción: FIG 353 no es la figura principal de ninguna página
# (la principal de "Domestic Beam Clamp" es 350) — el sitio la menciona
# solo dentro del texto ("el diseño universal del 3/8" Fig. 353..."), así
# que para esos casos se busca el número de figura DENTRO de la
# descripción completa, no solo en el campo modelo_detectado.
#
# Uso:
#   docker compose exec scraper python matchers/phd_matcher.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_FIGURA_CODIGO = re.compile(r"FIG\.?\s*(\d{3}[A-Z]?)", re.IGNORECASE)
RE_FIGURA_TEXTO = re.compile(r"Fig\.?\s*(\d{3}[A-Z]?)", re.IGNORECASE)


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'PHD'")
        productos = cur.fetchall()

        cur.execute("""
            SELECT url, titulo, modelo_detectado, descripcion FROM catalogo_fabricante
            WHERE dominio = 'phd-mfg.com'
        """)
        catalogo = cur.fetchall()

    indice_principal = {}
    for fila in catalogo:
        indice_principal.setdefault(fila["modelo_detectado"].upper(), []).append(fila)

    resultados = {"ok": 0, "ok_texto": 0, "no_encontrado": 0}
    filas_insertar = []

    for producto in productos:
        m = RE_FIGURA_CODIGO.search(producto["nombre_producto"])
        if not m:
            filas_insertar.append((
                producto["codigo"], "phd-mfg.com", None, None, None, None, None,
                "no_encontrado", "No se pudo leer número de figura del nombre.",
            ))
            resultados["no_encontrado"] += 1
            continue

        figura = m.group(1).upper()
        candidatos = indice_principal.get(figura, [])
        via_texto = False

        if not candidatos:
            # buscar la figura mencionada dentro del texto de cada página
            # (ej. FIG 353 dentro de la página de "Domestic Beam Clamp",
            # cuya figura principal es 350).
            for fila in catalogo:
                if RE_FIGURA_TEXTO.search(fila["descripcion"] or ""):
                    if figura in [g.upper() for g in RE_FIGURA_TEXTO.findall(fila["descripcion"])]:
                        candidatos.append(fila)
            via_texto = True

        if not candidatos:
            filas_insertar.append((
                producto["codigo"], "phd-mfg.com", None, None, None, None, None,
                "no_encontrado", f"Figura {figura} no encontrada ni como figura principal ni mencionada en ninguna página.",
            ))
            resultados["no_encontrado"] += 1
            continue

        mejor = candidatos[0]
        detalle = (
            f"Match por número de figura {figura} " +
            ("(mencionada dentro del texto de la página, no es la figura principal)."
             if via_texto else "(figura principal de la página).")
        )
        filas_insertar.append((
            producto["codigo"], "phd-mfg.com", mejor["url"], mejor["descripcion"], mejor["titulo"],
            None, None, "ok", detalle,
        ))
        resultados["ok_texto" if via_texto else "ok"] += 1

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'phd-mfg.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    total_ok = resultados["ok"] + resultados["ok_texto"]
    print(f"PHD: {total_ok} matches ({resultados['ok']} figura principal + {resultados['ok_texto']} mencionada en texto), "
          f"{resultados['no_encontrado']} sin match (de {len(productos)} códigos).")


if __name__ == "__main__":
    main()
