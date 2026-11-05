# =========================================================================
# phd_pesos_extra.py - completa peso/dimensiones para las 2 familias PHD
# que el extractor genérico (phd_pesos_dimensiones.py) no pudo cubrir
# porque su tabla NO tiene columna "Figure Numbers" (cubre una sola
# figura por PDF, indexada por tamaño de tubería o de varilla en vez de
# por número de figura):
#
#   - FIG 141 (8 códigos): tabla indexada por "Pipe Size" (tamaño de
#     tubería) — 141141F_5-29-18.pdf.
#   - FIG 360 (1 código): tabla indexada por "Rod Size A" (tamaño de
#     varilla) — 360_11-12-25.pdf.
#
# Los otros 10 códigos PHD que quedan sin peso (FIG 010/015/030/031,
# soportes antisísmicos) NO se cubren a propósito: sus PDFs solo traen
# tablas de CAPACIDAD DE CARGA (lbs. de carga que resiste) y el peso del
# tubo de arriostramiento genérico (que es un insumo aparte, no la pieza
# PHD en sí) — no hay una fila "peso de este accesorio" confiable para
# extraer sin arriesgar asignar el número equivocado.
#
# Uso:
#   docker compose exec scraper python enriquecimiento/phd_pesos_extra.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


# Tabla FIG 141 (141141F_5-29-18.pdf): Pipe Size -> (Rod, B, Adj.C, D, E, Max Load, Wt lbs, Wt kg)
TABLA_141 = {
    0.5:  dict(peso_lbs=.10, peso_kg=.05, dims="Rod Size: 3/8 | B: 1-7/8 (47.63mm) | Adj. C: 1-7/16 (36.51mm) | D: 2-3/4 (69.85mm) | E: 3-1/16 (77.79mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    0.75: dict(peso_lbs=.10, peso_kg=.05, dims="Rod Size: 3/8 | B: 1-11/16 (42.86mm) | Adj. C: 1-1/8 (28.58mm) | D: 2-1/2 (63.50mm) | E: 3-1/16 (77.79mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    1.0:  dict(peso_lbs=.10, peso_kg=.05, dims="Rod Size: 3/8 | B: 1-5/8 (41.28mm) | Adj. C: 1 (25.40mm) | D: 2-1/2 (63.50mm) | E: 3-3/16 (80.96mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    1.25: dict(peso_lbs=.11, peso_kg=.05, dims="Rod Size: 3/8 | B: 1-15/16 (49.21mm) | Adj. C: 1-1/16 (26.99mm) | D: 2-13/16 (71.44mm) | E: 3-9/16 (90.49mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    1.5:  dict(peso_lbs=.11, peso_kg=.05, dims="Rod Size: 3/8 | B: 2-1/8 (53.98mm) | Adj. C: 1-1/16 (26.99mm) | D: 3-1/8 (79.38mm) | E: 3-7/8 (98.43mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    2.0:  dict(peso_lbs=.14, peso_kg=.06, dims="Rod Size: 3/8 | B: 2-7/16 (61.91mm) | Adj. C: 1-1/8 (28.58mm) | D: 3-5/16 (84.14mm) | E: 4-3/8 (111.13mm) | Max. Rec. Load: 300 lbs (1.33kN)"),
    2.5:  dict(peso_lbs=.19, peso_kg=.09, dims="Rod Size: 3/8 | B: 3-1/16 (77.79mm) | Adj. C: 1-5/8 (41.28mm) | D: 3-15/16 (100.01mm) | E: 5-3/8 (136.53mm) | Max. Rec. Load: 525 lbs (2.34kN)"),
    3.0:  dict(peso_lbs=.23, peso_kg=.10, dims="Rod Size: 3/8 | B: 3-11/16 (93.66mm) | Adj. C: 1-7/8 (47.63mm) | D: 4-9/16 (115.89mm) | E: 6-5/16 (160.34mm) | Max. Rec. Load: 525 lbs (2.34kN)"),
    3.5:  dict(peso_lbs=.25, peso_kg=.11, dims="Rod Size: 3/8 | B: 3-3/4 (95.25mm) | Adj. C: 1-7/8 (47.63mm) | D: 4-5/8 (117.48mm) | E: 6-5/8 (168.28mm) | Max. Rec. Load: 525 lbs (2.34kN)"),
    4.0:  dict(peso_lbs=.30, peso_kg=.14, dims="Rod Size: 3/8 | B: 4-3/16 (106.36mm) | Adj. C: 1-7/8 (47.63mm) | D: 5-1/16 (128.59mm) | E: 7-5/16 (185.74mm) | Max. Rec. Load: 650 lbs (2.89kN)"),
    5.0:  dict(peso_lbs=.50, peso_kg=.23, dims="Rod Size: 1/2 | B: 4-5/8 (117.48mm) | Adj. C: 1-5/8 (41.28mm) | D: 5-5/8 (142.88mm) | E: 8-3/8 (212.73mm) | Max. Rec. Load: 1000 lbs (4.45kN)"),
    6.0:  dict(peso_lbs=.58, peso_kg=.26, dims="Rod Size: 1/2 | B: 5-5/8 (142.88mm) | Adj. C: 2-1/4 (57.15mm) | D: 6-1/2 (165.10mm) | E: 9-13/16 (249.24mm) | Max. Rec. Load: 1000 lbs (4.45kN)"),
    8.0:  dict(peso_lbs=.90, peso_kg=.41, dims="Rod Size: 1/2 | B: 6-13/16 (173.04mm) | Adj. C: 2-7/16 (61.91mm) | D: 7-15/16 (201.61mm) | E: 12-1/4 (311.15mm) | Max. Rec. Load: 1000 lbs (4.45kN)"),
}
URL_141 = "https://www.phd-mfg.com/wp-content/uploads/2018/05/141141F_5-29-18.pdf"

# Tabla FIG 360 (360_11-12-25.pdf): Rod Size A -> (B, C, D, E, Max Load, Wt lbs, Wt kg)
TABLA_360 = {
    0.375: dict(peso_lbs=.37, peso_kg=.17, dims="Rod Size A: 3/8 | B: 1 (25.40mm) | C: 1-7/8 (47.63mm) | D: 1-5/8 (41.28mm) | E: 1/2 (12.70mm) | Max. Pipe Size: 4 | Max. Rec. Load: 400 lbs (1.78kN)"),
    0.5:   dict(peso_lbs=.35, peso_kg=.16, dims="Rod Size A: 1/2 | B: 1 (25.40mm) | C: 1-7/8 (47.63mm) | D: 1-5/8 (41.28mm) | E: 1/2 (12.70mm) | Max. Pipe Size: 8 | Max. Rec. Load: 500 lbs (2.22kN)"),
    0.625: dict(peso_lbs=.74, peso_kg=.34, dims="Rod Size A: 5/8 | B: 1-3/8 (34.93mm) | C: 2-5/16 (58.74mm) | D: 2-1/4 (57.15mm) | E: 3/4 (19.05mm) | Max. Pipe Size: 8 | Max. Rec. Load: 850 lbs (3.78kN)"),
    0.75:  dict(peso_lbs=.87, peso_kg=.39, dims="Rod Size A: 3/4 | B: 1-1/2 (38.10mm) | C: 2-3/8 (60.33mm) | D: 2-3/8 (60.33mm) | E: 3/4 (19.05mm) | Max. Pipe Size: 8 | Max. Rec. Load: 900 lbs (4.00kN)"),
}
URL_360 = "https://www.phd-mfg.com/wp-content/uploads/2025/12/360_11-12-25.pdf"

RE_FRACCION_MIXTA = re.compile(r'(\d+)\s+(\d+)/(\d+)"')
RE_FRACCION_PURA = re.compile(r'(?<!\d)(\d+)/(\d+)"')
RE_ENTERO = re.compile(r'(\d+)"')


def tamano_a_decimal(texto: str):
    m = RE_FRACCION_MIXTA.search(texto)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = RE_FRACCION_PURA.search(texto)
    if m:
        return int(m.group(1)) / int(m.group(2))
    m = RE_ENTERO.search(texto)
    if m:
        return float(m.group(1))
    return None


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'PHD'")
        productos = cur.fetchall()

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for producto in productos:
            nombre = producto["nombre_producto"].upper()
            if "FIG 141" in nombre or "FIG. 141" in nombre:
                tabla, url = TABLA_141, URL_141
            elif "FIG 360" in nombre or "FIG. 360" in nombre:
                tabla, url = TABLA_360, URL_360
            else:
                continue

            # quitar el número de figura antes de buscar el tamaño: en casos
            # como "FIG 360 1/2\"" el propio "360" calzaba con el patrón de
            # fracción mixta ("360 1/2" -> 360.5) y arruinaba el match.
            nombre_sin_figura = re.sub(r'FIG\.?\s*\d+', '', nombre, count=1)
            tamano = tamano_a_decimal(nombre_sin_figura)
            specs = tabla.get(tamano)
            if not specs:
                print(f"  {producto['codigo']}: tamaño {tamano} no encontrado en la tabla, se deja sin datos.")
                continue

            cur.execute(
                """
                UPDATE scrapes SET peso_lbs = %s, peso_kg = %s,
                       dimensiones_texto = %s, dimensiones_fuente = %s
                WHERE codigo = %s AND dominio = 'phd-mfg.com' AND estado = 'ok'
                """,
                (specs["peso_lbs"], specs["peso_kg"], specs["dims"], url, producto["codigo"]),
            )
            if cur.rowcount:
                actualizados += 1
                print(f"  {producto['codigo']}: {specs['peso_lbs']} lbs / {specs['peso_kg']} kg")

    conexion.close()
    print(f"\nActualizados: {actualizados} códigos PHD adicionales (FIG 141 + FIG 360).")


if __name__ == "__main__":
    main()
