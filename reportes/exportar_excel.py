# =========================================================================
# exportar_excel.py - genera el reporte Excel a partir de Postgres.
#
# Hojas:
#   Resumen     avance por marca: códigos, % del movimiento, cuántos tienen
#               match, material, peso, volumen y precio.
#   Productos   1 fila por código crítico: datos del código + mejor scrape
#               (scrapes_ultimo) + specs, peso y volumen.
#   Pendientes  códigos sin volumen todavía, con qué más les falta y las
#               notas de por qué no se pudo calcular.
#   Scrapes     historial completo de intentos de scrape.
#   Catalogo    catálogo crudo crawleado de cada fabricante.
#   Columnas    diccionario: qué significa cada columna.
#
# Solo LEE la base, no modifica nada.
#
# Uso:
#   python main.py excel
#   python main.py excel --salida salidas/excel/otro_nombre.xlsx
# =========================================================================
import argparse
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from scraper_precios.config import CONEXION, RAIZ, SALIDAS_EXCEL, conectar

ARCHIVO_POR_DEFECTO = SALIDAS_EXCEL / "reporte_scraper_precios.xlsx"

# Excel no acepta más de 32.767 caracteres por celda ni caracteres de control.
MAX_CARACTERES_CELDA = 32_000
RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

SQL_PRODUCTOS = """
SELECT p.codigo, p.nombre_producto, p.marca, p.modelo, p.familia,
       p.movimiento_total, p.pct_acum,
       s.estado, s.dominio, s.url_fuente, s.serie, s.precio, s.moneda,
       p.material, p.acabado, p.tamano, p.k_factor, p.aprobaciones,
       p.peso_kg, p.peso_lbs, p.dimensiones_texto, p.dimensiones_fuente,
       p.volumen_cm3,
       NULLIF(split_part(p.volumen_confianza, ' ', 1), '') AS confianza_volumen,
       p.volumen_confianza, p.volumen_metodo,
       s.descripcion, p.funcion_texto, p.specs_adicionales, s.detalle
FROM productos_criticos p
LEFT JOIN scrapes_ultimo s ON s.codigo = p.codigo
ORDER BY p.movimiento_total DESC NULLS LAST, p.codigo
"""

SQL_SCRAPES = """
SELECT id, codigo, dominio, estado, url_fuente, serie, precio, moneda,
       material, acabado, aprobaciones, tamano, k_factor, peso_kg, peso_lbs,
       dimensiones_texto, dimensiones_fuente, descripcion, funcion_texto,
       specs_adicionales, detalle, scrapeado_en
FROM scrapes
ORDER BY codigo, scrapeado_en
"""

SQL_CATALOGO = """
SELECT id, dominio, url, titulo, modelo_detectado, descripcion, scrapeado_en
FROM catalogo_fabricante
ORDER BY dominio, titulo
"""

# columna de la base -> (encabezado en Excel, descripción para la hoja Columnas)
COLUMNAS = {
    "codigo": ("Código", "Código interno del producto (distribuidora)."),
    "nombre_producto": ("Nombre producto", "Nombre del producto en el sistema interno."),
    "marca": ("Marca", "Marca / fabricante."),
    "modelo": ("Modelo", "Denominación-Modelo del Excel de proveedores."),
    "familia": ("Familia", "Denominación-Familia del Excel de proveedores."),
    "movimiento_total": ("Movimiento", "Movimiento total del código (unidades) en el ranking."),
    "pct_acum": ("% acumulado", "Porcentaje acumulado del movimiento en el ranking (Pareto)."),
    "estado": ("Estado scrape", "Resultado del mejor scrape: ok / no_encontrado / error."),
    "dominio": ("Dominio fuente", "Sitio del fabricante de donde salió el dato."),
    "url_fuente": ("URL fuente", "Página o documento exacto usado como fuente."),
    "url": ("URL", "Página del catálogo del fabricante."),
    "serie": ("Serie / modelo fabricante", "Serie o modelo real según el fabricante."),
    "precio": ("Precio lista", "Precio de lista público (solo TYCO lo publica)."),
    "moneda": ("Moneda", "Moneda del precio."),
    "material": ("Material", "Material según ficha del fabricante."),
    "acabado": ("Acabado", "Acabado / recubrimiento."),
    "tamano": ("Tamaño", "Tamaño de tubería / varilla."),
    "k_factor": ("K-factor", "Factor K del rociador (sprinklers)."),
    "aprobaciones": ("Aprobaciones", "Listados / aprobaciones (UL, FM, ...)."),
    "peso_kg": ("Peso (kg)", "Peso por unidad publicado por el fabricante."),
    "peso_lbs": ("Peso (lbs)", "Peso por unidad en libras, tal como lo publica el fabricante."),
    "dimensiones_texto": ("Dimensiones", "Medidas de INGENIERÍA de la ficha (no del empaque)."),
    "dimensiones_fuente": ("Fuente dimensiones", "Documento / página / tabla de donde salen las medidas."),
    "volumen_cm3": ("Volumen (cm³)", "Volumen APROXIMADO de la pieza (cilindro o caja envolvente)."),
    "confianza_volumen": ("Confianza vol.", "alta / media / baja: resumen de la confianza del volumen."),
    "volumen_confianza": ("Confianza volumen (detalle)", "Motivo completo de la confianza asignada."),
    "volumen_metodo": ("Método volumen", "Fórmula y supuestos usados para calcular el volumen."),
    "descripcion": ("Descripción", "Texto capturado de la fuente."),
    "funcion_texto": ("Función", "Para qué sirve la pieza, según el fabricante."),
    "specs_adicionales": ("Notas / specs adicionales", "Specs extra y notas de origen de cada dato."),
    "detalle": ("Detalle del match", "Cómo se hizo el cruce código <-> fabricante y su confianza."),
    "modelo_detectado": ("Modelo detectado", "Modelo/figura detectado en la página del catálogo."),
    "titulo": ("Título", "Título de la página del catálogo."),
    "id": ("ID", "Identificador interno de la fila."),
    "scrapeado_en": ("Scrapeado en (UTC)", "Fecha y hora del scrape."),
}

FORMATOS_NUMERO = {
    "Movimiento": "#,##0",
    "% acumulado": "0.0%",
    "% del movimiento": "0.0%",
    "% con volumen": "0%",
    "Precio lista": "#,##0.00",
    "Peso (kg)": "0.000",
    "Peso (lbs)": "0.000",
    "Volumen (cm³)": "#,##0.00",
    "Scrapeado en (UTC)": "yyyy-mm-dd hh:mm",
}

COLUMNAS_NUMERICAS = ["movimiento_total", "pct_acum", "precio", "peso_kg", "peso_lbs", "volumen_cm3"]

ESTILO_ENCABEZADO = dict(
    font=Font(bold=True, color="FFFFFF"),
    fill=PatternFill("solid", fgColor="1F4E78"),
    alignment=Alignment(wrap_text=True, vertical="center"),
)


# --- lectura -----------------------------------------------------------------
def consultar(cur, sql: str) -> pd.DataFrame:
    cur.execute(sql)
    columnas = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columnas)


def limpiar(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el DataFrame listo para Excel: números como float, fechas sin
    zona horaria y texto sin caracteres de control ni celdas gigantes."""
    df = df.copy()
    for col in df.columns:
        serie = df[col]
        if col in COLUMNAS_NUMERICAS:
            df[col] = _a_numero(serie)
        elif isinstance(serie.dtype, pd.DatetimeTZDtype):
            df[col] = serie.dt.tz_convert("UTC").dt.tz_localize(None)
        elif serie.dtype == object and serie.map(lambda v: isinstance(v, datetime)).any():
            df[col] = pd.to_datetime(serie, utc=True).dt.tz_localize(None)
        elif serie.dtype == object or pd.api.types.is_string_dtype(serie):
            # pandas 2 guarda texto como object; pandas 3 como dtype "str"
            df[col] = serie.map(_limpiar_texto)
    return df


def _a_numero(serie: pd.Series) -> pd.Series:
    """Convierte a float (Decimal de Postgres, o texto tipo '66.01'). Si
    algún valor no vacío no es número (ej. un precio 'consultar'), deja la
    columna como texto para no perder ese dato."""
    valores = serie.map(lambda v: float(v) if isinstance(v, Decimal) else v)
    valores = valores.map(lambda v: None if isinstance(v, str) and not v.strip() else v)
    numeros = pd.to_numeric(valores, errors="coerce")
    if numeros.notna().sum() < valores.notna().sum():
        return serie.map(_limpiar_texto)
    return numeros


def _limpiar_texto(valor):
    if not isinstance(valor, str):
        return valor
    valor = RE_CONTROL.sub("", valor)
    if len(valor) > MAX_CARACTERES_CELDA:
        valor = valor[:MAX_CARACTERES_CELDA] + " …[recortado]"
    return valor


def renombrar(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={c: COLUMNAS[c][0] for c in df.columns if c in COLUMNAS})


# --- hojas derivadas ---------------------------------------------------------
def armar_resumen(productos: pd.DataFrame) -> pd.DataFrame:
    p = productos.assign(
        con_match=productos["estado"].eq("ok"),
        con_material=productos["material"].notna(),
        con_peso=productos["peso_kg"].notna() | productos["peso_lbs"].notna(),
        con_volumen=productos["volumen_cm3"].notna(),
        con_precio=productos["precio"].notna(),
    )
    resumen = (
        p.groupby("marca", dropna=False)
        .agg(
            codigos=("codigo", "count"),
            movimiento=("movimiento_total", "sum"),
            con_match=("con_match", "sum"),
            con_material=("con_material", "sum"),
            con_peso=("con_peso", "sum"),
            con_volumen=("con_volumen", "sum"),
            con_precio=("con_precio", "sum"),
        )
        .sort_values("movimiento", ascending=False)
        .reset_index()
    )
    conteos = ["codigos", "con_match", "con_material", "con_peso", "con_volumen", "con_precio"]
    total = resumen.drop(columns="marca").sum().to_frame().T
    total.insert(0, "marca", "TOTAL")
    resumen = pd.concat([resumen, total], ignore_index=True)
    resumen[conteos] = resumen[conteos].astype(int)
    resumen["movimiento"] = resumen["movimiento"].astype(float)

    mov_total = productos["movimiento_total"].sum()
    resumen.insert(3, "pct_mov", resumen["movimiento"] / mov_total if mov_total else 0)
    resumen["pct_vol"] = resumen["con_volumen"] / resumen["codigos"]
    return resumen.rename(columns={
        "marca": "Marca", "codigos": "Códigos", "movimiento": "Movimiento",
        "pct_mov": "% del movimiento", "con_match": "Con match", "con_material": "Con material",
        "con_peso": "Con peso", "con_volumen": "Con volumen", "con_precio": "Con precio",
        "pct_vol": "% con volumen",
    })


def armar_pendientes(productos: pd.DataFrame) -> pd.DataFrame:
    falta = productos[productos["volumen_cm3"].isna()].copy()
    si_no = {True: "Falta", False: "OK"}
    falta["falta_material"] = falta["material"].isna().map(si_no)
    falta["falta_peso"] = (falta["peso_kg"].isna() & falta["peso_lbs"].isna()).map(si_no)
    falta["falta_dimensiones"] = falta["dimensiones_texto"].isna().map(si_no)
    columnas = ["codigo", "nombre_producto", "marca", "movimiento_total", "pct_acum", "dominio",
                "url_fuente", "falta_dimensiones", "falta_material", "falta_peso",
                "dimensiones_texto", "specs_adicionales"]
    return renombrar(falta[columnas]).rename(columns={
        "falta_dimensiones": "Dimensiones", "falta_material": "Material", "falta_peso": "Peso",
    })


def armar_diccionario() -> pd.DataFrame:
    filas = [(enc, col, desc) for col, (enc, desc) in COLUMNAS.items()]
    return pd.DataFrame(filas, columns=["Columna en Excel", "Columna en la base", "Qué significa"])


# --- formato -----------------------------------------------------------------
def dar_formato(hoja, df: pd.DataFrame, fila_encabezado: int = 1, congelar: str = "A2"):
    n_filas = len(df) + fila_encabezado
    for celda in hoja[fila_encabezado]:
        for atributo, valor in ESTILO_ENCABEZADO.items():
            setattr(celda, atributo, valor)
    hoja.row_dimensions[fila_encabezado].height = 32
    hoja.freeze_panes = congelar
    if len(df.columns):
        ultima = get_column_letter(len(df.columns))
        hoja.auto_filter.ref = f"A{fila_encabezado}:{ultima}{max(n_filas, fila_encabezado)}"

    for i, nombre in enumerate(df.columns, start=1):
        letra = get_column_letter(i)
        muestra = [len(str(v)) for v in df[nombre].head(300) if not pd.isna(v)]
        ancho = max([len(str(nombre))] + muestra) + 2
        hoja.column_dimensions[letra].width = max(9, min(ancho, 55))

        formato = FORMATOS_NUMERO.get(nombre)
        es_url = nombre in ("URL fuente", "URL")
        if not (formato or es_url):
            continue
        for fila in range(fila_encabezado + 1, n_filas + 1):
            celda = hoja.cell(row=fila, column=i)
            if formato:
                celda.number_format = formato
            if es_url and isinstance(celda.value, str) and celda.value.startswith("http"):
                celda.hyperlink = celda.value
                celda.style = "Hyperlink"


def escribir(destino: Path, productos, scrapes, catalogo):
    resumen = armar_resumen(productos)
    pendientes = armar_pendientes(productos)
    hojas = [
        ("Productos", renombrar(productos), "C2"),
        ("Pendientes", pendientes, "C2"),
        ("Scrapes", renombrar(scrapes), "C2"),
        ("Catalogo", renombrar(catalogo), "B2"),
        ("Columnas", armar_diccionario(), "A2"),
    ]

    destino.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(destino, engine="openpyxl") as writer:
        # Resumen: título + tabla desde la fila 5
        resumen.to_excel(writer, sheet_name="Resumen", index=False, startrow=4)
        hoja = writer.sheets["Resumen"]
        hoja["A1"] = "Reporte scraper de precios"
        hoja["A1"].font = Font(bold=True, size=14)
        hoja["A2"] = (f"Generado {datetime.now():%Y-%m-%d %H:%M} desde Postgres "
                      f"({CONEXION['dbname']}@{CONEXION['host']}). "
                      f"{len(productos)} códigos críticos, {len(pendientes)} sin volumen.")
        hoja["A3"] = ("Volumen = aproximación de la pieza desde medidas de ingeniería del fabricante, "
                      "no tamaño de empaque. Ver hoja 'Columnas'.")
        hoja["A3"].font = Font(italic=True, color="666666")
        dar_formato(hoja, resumen, fila_encabezado=5, congelar="B6")
        ultima_fila = 5 + len(resumen)
        for celda in hoja[ultima_fila]:
            celda.font = Font(bold=True)
        col_pct = get_column_letter(resumen.columns.get_loc("% con volumen") + 1)
        hoja.conditional_formatting.add(
            f"{col_pct}6:{col_pct}{ultima_fila - 1}",
            DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="5B9BD5"),
        )

        for nombre, df, congelar in hojas:
            df.to_excel(writer, sheet_name=nombre, index=False)
            dar_formato(writer.sheets[nombre], df, congelar=congelar)

    return resumen, pendientes


def main(argv=None):
    parser = argparse.ArgumentParser(description="Genera el reporte Excel desde Postgres.")
    parser.add_argument("--salida", type=Path, default=ARCHIVO_POR_DEFECTO,
                        help=f"ruta del .xlsx (default: {ARCHIVO_POR_DEFECTO.relative_to(RAIZ)})")
    args = parser.parse_args(argv)

    conexion = conectar()
    try:
        with conexion.cursor() as cur:
            productos = limpiar(consultar(cur, SQL_PRODUCTOS))
            scrapes = limpiar(consultar(cur, SQL_SCRAPES))
            catalogo = limpiar(consultar(cur, SQL_CATALOGO))
    finally:
        conexion.close()

    try:
        resumen, pendientes = escribir(args.salida, productos, scrapes, catalogo)
    except PermissionError:
        raise SystemExit(f"No se pudo escribir {args.salida}: ¿está abierto en Excel? Ciérralo y repite.")

    total = resumen.iloc[-1]
    print(f"Excel generado: {args.salida}")
    print(f"  {int(total['Códigos'])} códigos | con match {int(total['Con match'])} | "
          f"material {int(total['Con material'])} | peso {int(total['Con peso'])} | "
          f"volumen {int(total['Con volumen'])} | precio {int(total['Con precio'])}")
    print(f"  Hojas: Resumen, Productos ({len(productos)}), Pendientes ({len(pendientes)}), "
          f"Scrapes ({len(scrapes)}), Catalogo ({len(catalogo)}), Columnas")


if __name__ == "__main__":
    main()
