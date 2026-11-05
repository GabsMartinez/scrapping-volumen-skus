# =========================================================================
# tyco_matcher.py - TYCO (tyco-fire.com). A diferencia de MECH, acá NO se
# crawlea el sitio: tyco-fire.com no publica páginas por SKU, pero SÍ
# publica un price book oficial en PDF con precio de lista por variante
# exacta (acabado, temperatura, orientación) — mejor fuente posible.
#
# Cómo se consiguió el PDF real (no el visor): la página
# /americas-price-book linkea a un visor de Widen (tyco.widen.net/view/pdf/...)
# que devuelve HTML (pdf.js), no el PDF. El PDF real lo pide ese visor a
# previews.us-east-1.widencdn.net/preview/.../<slug>?sig...&sig.expires=...
# (URL firmada, se ve en Network al abrir el visor con Playwright). Esa sí
# devuelve el binario. El sig.expires es un timestamp unix: si esta URL ya
# expiró, hay que volver a abrir /americas-price-book con Playwright y
# capturar la URL firmada nueva desde el evento 'request'.
#
# Nuestro código interno YA trae, dentro de Nombre Producto, el SIN
# (Sprinkler Identification Number, ej. "TY323"), la temperatura
# ("155°F"), y el acabado en un código de 2 letras (CR=Chrome, BR=Brass,
# etc.) — todo lo que hace falta para ubicar la fila exacta en el PDF.
#
# Uso:
#   docker compose exec scraper python matchers/tyco_matcher.py
# =========================================================================
import os
import re

import pdfplumber
import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION, FUENTES

RUTA_PDF = str(FUENTES / "tyco_pricebook_2026-01-05.pdf")

# url_fuente debe ser algo accesible fuera del contenedor (va a Supabase);
# el PDF local queda solo para reprocesar, el número de página va en detalle.
URL_PUBLICA_PRICEBOOK = "https://www.tyco-fire.com/americas-price-book"


RE_SIN = re.compile(r"\bTY\s?(\d{3,4}[A-Z]?)\b")
RE_TEMP_F = re.compile(r"(\d{2,3})\s?°?\s?F")
RE_PRECIO = re.compile(r"\$[\d,]+\.\d{2}")
RE_ORIENTACION_CODIGO = re.compile(r"\b(UP|PD)\b")
RE_PARTE = re.compile(r"^[\d][\d\-]*[\d]$")

# Código de acabado (2 letras, tal como viene en Nombre Producto) ->
# palabra que aparece en la columna "Finish" del price book.
ACABADOS = {
    "CR": "Chrome",
    "BR": "Brass",
    "BL": "White",       # BLANCO
    "BLA": "White",
    "NG": "Black",       # NEGRO
    "NAT": "Natural",
}


def extraer_texto_paginas(ruta_pdf: str) -> list:
    with pdfplumber.open(ruta_pdf) as pdf:
        return [pagina.extract_text() or "" for pagina in pdf.pages]


def detectar_acabado(nombre_producto: str) -> str | None:
    up = nombre_producto.upper()
    for codigo, palabra in ACABADOS.items():
        if re.search(rf"\b{codigo}\b", up):
            return palabra
    return None


def orientacion_esperada(nombre_producto: str) -> str | None:
    m = RE_ORIENTACION_CODIGO.search(nombre_producto.upper())
    if not m:
        return None
    return "PENDENT" if m.group(1) == "PD" else "UPRIGHT"


def orientacion_de_fila(linea: str) -> str:
    """El price book lista 'Upright  Pendent  Finish  Temp  Price' por
    fila. Cuando una de las dos primeras columnas es un guion ('–') y la
    otra es un número de parte real, esa fila es SOLO para esa
    orientación (aunque comparta SIN/temp/acabado con la otra). Si
    ninguna es guion (mismo precio para ambas) o el formato no calza
    (otras tablas del PDF, ej. válvulas), se trata como válida para
    cualquier orientación."""
    tokens = linea.strip().split()
    if tokens and tokens[0] == "w":
        tokens = tokens[1:]
    if len(tokens) < 2:
        return "AMBAS"
    t0, t1 = tokens[0], tokens[1]
    es_dash = t0 in ("–", "-", "—")
    es_dash1 = t1 in ("–", "-", "—")
    if es_dash and RE_PARTE.match(t1):
        return "PENDENT"
    if es_dash1 and RE_PARTE.match(t0):
        return "UPRIGHT"
    return "AMBAS"


def main():
    paginas = extraer_texto_paginas(RUTA_PDF)
    print(f"PDF cargado: {len(paginas)} páginas.")

    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'TYCO'")
        productos = cur.fetchall()

    filas_insertar = []
    resultados = {"ok": 0, "no_encontrado": 0}

    for producto in productos:
        nombre = producto["nombre_producto"]
        m_sin = RE_SIN.search(nombre.upper())
        m_temp = RE_TEMP_F.search(nombre)
        acabado = detectar_acabado(nombre)

        if not (m_sin and m_temp and acabado):
            filas_insertar.append((
                producto["codigo"], "tyco-fire.com", None, None, None, None, None,
                "no_encontrado",
                f"No se pudo leer SIN/temperatura/acabado desde el nombre "
                f"(sin={bool(m_sin)}, temp={bool(m_temp)}, acabado={acabado}).",
            ))
            resultados["no_encontrado"] += 1
            continue

        sin = "TY" + m_sin.group(1)
        temp = m_temp.group(1)
        orientacion = orientacion_esperada(nombre)

        candidatos = []
        for num_pagina, texto in enumerate(paginas):
            if sin not in texto.upper():
                continue
            for linea in texto.split("\n"):
                if temp in linea and acabado.lower() in linea.lower() and RE_PRECIO.search(linea):
                    candidatos.append((num_pagina, linea))

        if orientacion:
            # Filtra filas que son claramente de la OTRA orientación (ej.
            # nuestro código es Pendent pero la fila es la fila
            # Upright-only del mismo SIN/temp/acabado — mismo SIN/temp/
            # acabado, precio distinto). Si el filtro deja la lista
            # vacía, se reporta no_encontrado en vez de aceptar una fila
            # de la orientación equivocada (más vale perder el match que
            # guardar un precio que no es).
            candidatos = [
                (np, l) for np, l in candidatos if orientacion_de_fila(l) in ("AMBAS", orientacion)
            ]

        if not candidatos:
            filas_insertar.append((
                producto["codigo"], "tyco-fire.com", None, None, sin, None, None,
                "no_encontrado",
                f"SIN {sin} encontrado en el PDF pero ninguna fila coincide con "
                f"temperatura {temp}°F + acabado {acabado}"
                + (f" + orientación {orientacion}" if orientacion else "") + ".",
            ))
            resultados["no_encontrado"] += 1
            continue

        num_pagina, linea = candidatos[0]
        precio = RE_PRECIO.findall(linea)[-1].replace("$", "").replace(",", "")

        filas_insertar.append((
            producto["codigo"], "tyco-fire.com",
            URL_PUBLICA_PRICEBOOK, linea.strip(), sin, precio, "USD",
            "ok",
            f"Price book {os.path.basename(RUTA_PDF)}, página {num_pagina + 1}. "
            f"{len(candidatos)} fila(s) candidata(s); se tomó la primera.",
        ))
        resultados["ok"] += 1

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'tyco-fire.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    print(f"TYCO: {resultados['ok']} matches, {resultados['no_encontrado']} sin match (de {len(productos)} códigos).")


if __name__ == "__main__":
    main()
