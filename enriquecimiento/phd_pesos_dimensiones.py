# =========================================================================
# phd_pesos_dimensiones.py - PHD Manufacturing: peso y dimensiones desde
# las fichas técnicas en PDF ("View Data Sheet", enlazadas en cada página
# de producto). Las tablas traen columnas "Rod Size A", "B", "C", "D",
# "E", "Max. Pipe Size", "Max. Rec. Load", "Wt. Each" por número de
# figura — un mismo PDF suele cubrir varias figuras (ej. 350, 353-357).
#
# IMPORTANTE (para quien use estos datos para calcular espacio en
# bodega): A-E son medidas de INGENIERÍA (distancia entre tornillos,
# diámetro de varilla, etc.), NO el tamaño de la caja/empaque del
# producto — ningún fabricante publica eso en su web pública. Se guardan
# tal cual vienen, etiquetadas, para que quien las use decida cómo
# aplicarlas. El peso por unidad (Wt. Each) sí es directamente confiable.
#
# Estrategia:
#   1. Reabre cada página de producto (Playwright) y saca el/los link(s)
#      a PDF ("Data Sheet").
#   2. Descarga cada PDF único (varias páginas de producto comparten el
#      mismo PDF) y extrae su tabla de specs con pdfplumber.
#   3. Identifica la columna de número de figura y la de peso por fila,
#      arma un índice {figura -> (peso_lbs, peso_kg, dimensiones_texto)}.
#   4. Cruza contra productos_criticos (marca='PHD') por número de figura
#      (mismo patrón que matchers/phd_matcher.py) y actualiza scrapes.
#
# Si una tabla no tiene columna de peso reconocible, o una fila no trae
# figura clara, se descarta esa fila (mejor perder cobertura que inventar
# un peso).
#
# Uso:
#   docker compose exec scraper python enriquecimiento/phd_pesos_dimensiones.py
# =========================================================================
import io
import re
import urllib.request

import pdfplumber
import psycopg2
import psycopg2.extras
from playwright.sync_api import sync_playwright

from scraper_precios.config import CONEXION

HEADERS = {"User-Agent": "Mozilla/5.0"}
RE_FIGURA_TABLA = re.compile(r"^[*ΔΘ†‡]?\s*(\d{3}[A-Z]?)$")
RE_FIGURA_CODIGO = re.compile(r"FIG\.?\s*(\d{3}[A-Z]?)", re.IGNORECASE)


def obtener_urls_pdf(urls_producto: list) -> dict:
    """{url_producto: url_pdf} para las páginas que sí traen un link a PDF."""
    resultado = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.route("**/*", lambda r: r.abort() if r.request.resource_type in
                    ("image", "font", "media", "stylesheet") else r.continue_())
        for i, url in enumerate(urls_producto, 1):
            try:
                page.goto(url, wait_until="commit", timeout=20000)
                page.wait_for_timeout(2500)
                hrefs = page.eval_on_selector_all("a", "els => els.map(e => e.href)")
                pdfs = [h for h in hrefs if h.lower().endswith(".pdf")]
                if pdfs:
                    resultado[url] = pdfs[0]
                    print(f"  [{i}/{len(urls_producto)}] {url.split('/')[-2]} -> {pdfs[0].split('/')[-1]}")
                else:
                    print(f"  [{i}/{len(urls_producto)}] sin PDF")
            except Exception as e:
                print(f"  [{i}/{len(urls_producto)}] ERROR: {e}")
        browser.close()
    return resultado


def limpiar_celda(v) -> str:
    return (v or "").replace("\n", " ").strip()


def parsear_tabla_pdf(url_pdf: str) -> dict:
    """{figura -> {peso_lbs, peso_kg, dimensiones_texto}} desde un PDF."""
    req = urllib.request.Request(url_pdf, headers=HEADERS)
    data = urllib.request.urlopen(req, timeout=30).read()

    indice = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pagina in pdf.pages:
            for tabla in pagina.extract_tables():
                encabezado = [limpiar_celda(c) for c in (tabla[0] if tabla else [])]
                if not any("Figure" in c for c in encabezado):
                    continue

                idx_peso = next((i for i, c in enumerate(encabezado) if "Wt" in c or "Weight" in c), None)
                idx_figura = 0

                for fila in tabla[2:]:  # fila 0 = encabezado principal, fila 1 = subencabezado (lbs/kg)
                    celdas = [limpiar_celda(c) for c in fila]
                    if not celdas or not celdas[idx_figura]:
                        continue
                    m = RE_FIGURA_TABLA.match(celdas[idx_figura])
                    if not m:
                        continue
                    figura = m.group(1)

                    dims = []
                    for etiqueta, valor in zip(encabezado[1:], celdas[1:]):
                        if etiqueta and valor and etiqueta not in ("Wt. Each",):
                            dims.append(f"{etiqueta.replace(chr(10), ' ')}: {valor}")

                    peso_lbs = peso_kg = None
                    if idx_peso is not None and idx_peso + 1 < len(celdas):
                        try:
                            peso_lbs = float(celdas[idx_peso].replace(",", ""))
                        except ValueError:
                            pass
                        try:
                            peso_kg = float(celdas[idx_peso + 1].strip("()").replace(",", ""))
                        except ValueError:
                            pass

                    indice[figura] = {
                        "peso_lbs": peso_lbs,
                        "peso_kg": peso_kg,
                        "dimensiones_texto": " | ".join(dims) or None,
                    }
    return indice


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT DISTINCT url FROM catalogo_fabricante WHERE dominio = 'phd-mfg.com'")
        urls_producto = [f["url"] for f in cur.fetchall()]

        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'PHD'")
        productos = cur.fetchall()

    print(f"{len(urls_producto)} páginas de producto PHD a revisar por link de PDF.")
    mapa_pdfs = obtener_urls_pdf(urls_producto)
    pdfs_unicos = sorted(set(mapa_pdfs.values()))
    print(f"\n{len(pdfs_unicos)} PDFs únicos encontrados, extrayendo tablas...")

    indice_figuras = {}
    for url_pdf in pdfs_unicos:
        try:
            datos = parsear_tabla_pdf(url_pdf)
            for figura, specs in datos.items():
                indice_figuras[figura] = {**specs, "fuente": url_pdf}
            print(f"  {url_pdf.split('/')[-1]}: {len(datos)} figura(s) con datos.")
        except Exception as e:
            print(f"  ERROR en {url_pdf}: {e}")

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for producto in productos:
            m = RE_FIGURA_CODIGO.search(producto["nombre_producto"])
            if not m:
                continue
            specs = indice_figuras.get(m.group(1).upper())
            if not specs:
                continue
            cur.execute(
                """
                UPDATE scrapes SET peso_lbs = %s, peso_kg = %s,
                       dimensiones_texto = %s, dimensiones_fuente = %s
                WHERE codigo = %s AND dominio = 'phd-mfg.com' AND estado = 'ok'
                """,
                (specs["peso_lbs"], specs["peso_kg"], specs["dimensiones_texto"],
                 specs["fuente"], producto["codigo"]),
            )
            if cur.rowcount:
                actualizados += 1

    conexion.close()
    print(f"\nActualizados: {actualizados}/{len(productos)} códigos PHD con peso/dimensiones.")


if __name__ == "__main__":
    main()
