# =========================================================================
# capturar_fuentes_pdf.py - guarda un PDF de CADA página/documento fuente
# usado en el scraping, para que se pueda auditar a mano contra el
# original (pedido explícito: "dame un pdf de toda página de la que salió
# el scrapeo").
#
# - Si la url_fuente ya es un PDF (price book, fichas técnicas), se
#   descarga tal cual.
# - Si es una página web, se renderiza con Playwright y se imprime a PDF
#   (page.pdf()) -- esto captura la página TAL COMO la vio el scraper,
#   útil para ver qué había ahí además de lo que se guardó en la base.
#
# Salida: data/capturas_fuentes/<dominio>/<NN>_<slug>.pdf +
#         data/capturas_fuentes/manifiesto.csv (url, archivo, códigos que la usan)
#
# Uso:
#   docker compose exec scraper python herramientas/capturar_fuentes_pdf.py
# =========================================================================
import csv
import os
import re
import urllib.request

import psycopg2
import psycopg2.extras
from playwright.sync_api import sync_playwright

from scraper_precios.config import CAPTURAS_FUENTES, CONEXION


CARPETA_SALIDA = str(CAPTURAS_FUENTES)
HEADERS = {"User-Agent": "Mozilla/5.0"}


TEXTOS_COOKIES = [
    "Accept All Cookies", "Accept all cookies", "Aceptar todas", "Aceptar cookies",
    "Accept All", "I Accept", "Allow all", "Allow All",
]
TEXTOS_PESTANAS = ["Technical Data", "Product Description", "Resources", "Specifications", "Downloads"]


def _cerrar_cookies(page) -> None:
    """Sitios con banner de cookies (TrustArc, OneTrust, cookie consent
    genérico) tapan el contenido real en el PDF si no se cierra antes de
    imprimir -- ver hallazgo asc-es.com (2026-08-05)."""
    for texto in TEXTOS_COOKIES:
        try:
            page.get_by_text(texto, exact=False).first.click(timeout=2000)
            page.wait_for_timeout(500)
            return
        except Exception:
            continue


def _abrir_pestanas_de_specs(page) -> None:
    """Algunos sitios (asc-es.com, FacetWP de WordPress) esconden material/
    dimensiones detrás de una pestaña que hay que clickear -- si no, el PDF
    solo muestra la pestaña que carga por defecto."""
    for texto in TEXTOS_PESTANAS:
        try:
            page.get_by_text(texto, exact=False).first.click(timeout=1500)
            page.wait_for_timeout(400)
        except Exception:
            continue


def slug(texto: str) -> str:
    texto = re.sub(r"^https?://", "", texto)
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-")
    return texto[:80]


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT dominio, url_fuente, array_agg(DISTINCT codigo ORDER BY codigo) AS codigos
            FROM scrapes
            WHERE url_fuente IS NOT NULL AND estado = 'ok'
            GROUP BY dominio, url_fuente
            ORDER BY dominio, url_fuente
        """)
        fuentes = cur.fetchall()
    conexion.close()

    print(f"{len(fuentes)} páginas/documentos fuente únicos a capturar.")

    manifiesto = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.route("**/*", lambda r: r.abort() if r.request.resource_type in
                    ("image", "font", "media") else r.continue_())

        for i, fila in enumerate(fuentes, 1):
            dominio, url = fila["dominio"], fila["url_fuente"]
            carpeta_dominio = os.path.join(CARPETA_SALIDA, dominio)
            os.makedirs(carpeta_dominio, exist_ok=True)
            nombre_archivo = f"{i:03d}_{slug(url)}.pdf"
            ruta = os.path.join(carpeta_dominio, nombre_archivo)

            try:
                if url.lower().endswith(".pdf") or "/pdf/" in url.lower():
                    req = urllib.request.Request(url, headers=HEADERS)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        with open(ruta, "wb") as f:
                            f.write(resp.read())
                    metodo = "descarga directa (ya era PDF)"
                else:
                    page.goto(url, wait_until="commit", timeout=25000)
                    page.wait_for_timeout(2500)
                    _cerrar_cookies(page)
                    _abrir_pestanas_de_specs(page)
                    # algunos sitios (fu-mech.com) cargan la ficha real del
                    # producto recién con scroll -- sin esto, el PDF solo
                    # muestra el menú de navegación y queda "vacío" (ver
                    # hallazgo 2026-08-05, data/capturas_fuentes/fu-mech.com).
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(2000)
                    page.pdf(path=ruta, format="A4", print_background=True)
                    metodo = "renderizado de página (Playwright)"

                print(f"  [{i}/{len(fuentes)}] OK ({metodo}): {url}")
                manifiesto.append((dominio, url, os.path.join(dominio, nombre_archivo),
                                    ", ".join(fila["codigos"]), "ok", ""))
            except Exception as e:
                print(f"  [{i}/{len(fuentes)}] ERROR: {url} -> {e}")
                manifiesto.append((dominio, url, "", ", ".join(fila["codigos"]), "error", str(e)))

        browser.close()

    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    with open(os.path.join(CARPETA_SALIDA, "manifiesto.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["dominio", "url_fuente", "archivo_pdf", "codigos_que_la_usan", "estado", "detalle_error"])
        w.writerows(manifiesto)

    ok = sum(1 for m in manifiesto if m[4] == "ok")
    print(f"\nListo: {ok}/{len(fuentes)} capturadas. Ver data/capturas_fuentes/manifiesto.csv")


if __name__ == "__main__":
    main()
