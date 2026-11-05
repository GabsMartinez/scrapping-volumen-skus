# =========================================================================
# seed_productos.py - carga data/entrada/codigos_criticos_dominios.xlsx
# (hojas Con_Dominio + Sin_Dominio) a la tabla productos_criticos.
# Se puede correr las veces que haga falta: hace upsert por Código.
#
# Uso (desde el contenedor 'scraper'):
#   python main.py seed
#   (o directo: docker compose exec scraper python db/seed_productos.py)
# =========================================================================

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from scraper_precios.config import CONEXION, EXCEL_CODIGOS_CRITICOS

RUTA_EXCEL = EXCEL_CODIGOS_CRITICOS


COLUMNAS = ["Código", "Nombre Producto", "Marca", "Modelo", "Familia",
            "movimiento_total", "pct_acum", "Dominios_Oficiales", "Tiene_Dominio"]


def cargar_filas() -> list[tuple]:
    con_dominio = pd.read_excel(RUTA_EXCEL, sheet_name="Con_Dominio")
    sin_dominio = pd.read_excel(RUTA_EXCEL, sheet_name="Sin_Dominio")
    todo = pd.concat([con_dominio, sin_dominio], ignore_index=True)
    todo["Dominios_Oficiales"] = todo["Dominios_Oficiales"].fillna("")
    todo["Tiene_Dominio"] = todo["Tiene_Dominio"].fillna(False)
    return list(todo[COLUMNAS].itertuples(index=False, name=None))


def main():
    filas = cargar_filas()
    print(f"Cargando {len(filas)} códigos a productos_criticos...")

    conexion = psycopg2.connect(**CONEXION)
    with conexion, conexion.cursor() as cur:
        execute_values(cur, """
            INSERT INTO productos_criticos
                (codigo, nombre_producto, marca, modelo, familia,
                 movimiento_total, pct_acum, dominios_oficiales, tiene_dominio)
            VALUES %s
            ON CONFLICT (codigo) DO UPDATE SET
                nombre_producto = EXCLUDED.nombre_producto,
                marca = EXCLUDED.marca,
                modelo = EXCLUDED.modelo,
                familia = EXCLUDED.familia,
                movimiento_total = EXCLUDED.movimiento_total,
                pct_acum = EXCLUDED.pct_acum,
                dominios_oficiales = EXCLUDED.dominios_oficiales,
                tiene_dominio = EXCLUDED.tiene_dominio
        """, filas)

    print("Listo.")


if __name__ == "__main__":
    main()
