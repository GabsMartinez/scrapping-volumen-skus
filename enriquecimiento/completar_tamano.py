# =========================================================================
# completar_tamano.py - completa productos_criticos.tamano para los
# códigos que NO lo trajeron desde la página del fabricante (extraer_specs.py),
# parseando el tamaño de tubería/varilla directo desde nuestro propio
# nombre_producto (ej. 'SOP ANTIS LONG 2" PHD' -> tamano='2"').
#
# Es una fuente distinta y más débil que el scraping (viene de cómo el
# proveedor nombró el código en su propio sistema, no de una ficha técnica
# del fabricante), pero es texto real que ya teníamos, no un dato
# inventado -- por eso solo rellena donde tamano sigue NULL, nunca
# sobreescribe un valor que ya vino de una fuente scrapeada.
#
# Cobertura: 191/194 (los 3 restantes genuinemente no traen tamaño en su
# nombre -- 2 son dispositivos electrónicos sin tamaño de tubería, 1 es un
# escudo/cover plate sin tamaño especificado en el nombre).
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_tamano.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_CON_COMILLA = re.compile(r'(\d+(?:-\d+/\d+)?|\d+/\d+)"')
RE_FRACCION_SUELTA = re.compile(r"(\d+-\d+/\d+|\d+/\d+)")


def extraer_tamano(nombre: str) -> str | None:
    valores = RE_CON_COMILLA.findall(nombre)
    unidad = '"' if valores else ""
    if not valores:
        valores = RE_FRACCION_SUELTA.findall(nombre)
    if not valores:
        return None
    vistos = list(dict.fromkeys(valores))  # preserva orden, sin duplicados
    return " x ".join(f"{v}{unidad}" for v in vistos)


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT codigo, nombre_producto FROM productos_criticos WHERE tamano IS NULL"
        )
        pendientes = cur.fetchall()

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for producto in pendientes:
            tamano = extraer_tamano(producto["nombre_producto"])
            if not tamano:
                continue
            cur.execute(
                "UPDATE productos_criticos SET tamano = %s, "
                "specs_adicionales = COALESCE(specs_adicionales || ' | ', '') || "
                "'Tamaño derivado del propio código interno, no de ficha del fabricante' "
                "WHERE codigo = %s",
                (tamano, producto["codigo"]),
            )
            actualizados += 1

    conexion.close()
    print(f"{actualizados}/{len(pendientes)} códigos completados con tamaño derivado del nombre interno.")


if __name__ == "__main__":
    main()
