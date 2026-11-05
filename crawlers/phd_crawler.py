# =========================================================================
# phd_crawler.py - PHD Manufacturing (phd-mfg.com). No estaba en
# fabricantes.py original (quedó en Sin_Dominio) — es el fabricante real
# de soportes tipo pera FIG 141, beam clamps FIG 3xx, y bracing sísmico
# FIG 0xx que aparecen en nuestros 21 códigos marca "PHD".
#
# El sitio es WordPress + WooCommerce/ShopEngine, HTTP simple funciona
# bien (sin WAF), PERO el número de "Figure: ###" se renderiza vía JS en
# varias páginas (no todas) — por eso este crawler sí usa Playwright en
# vez de urllib, a diferencia de reliable_crawler.py.
#
# Solo se crawlean 3 categorías (las que aplican a nuestros códigos):
# band-hangers, beam-clamps (dos ubicaciones: pipe-hangers-devices Y
# fire-protection-seismic, con productos distintos en cada una), y
# seismic-bracing.
#
# NOTA (2026-08-05): la primera versión cortaba la descripción a 500
# caracteres desde "FUNCTION:" — eso alcanzaba para el texto de función
# pero cortaba MATERIAL/FINISH/Approvals/Ordering/NOTE, que vienen después
# en la misma página. Ahora captura hasta el footer real ("Copyright ©"),
# así queda toda la ficha completa disponible para parsear specs
# estructuradas (ver enriquecimiento/extraer_specs.py).
#
# Uso:
#   docker compose exec scraper python crawlers/phd_crawler.py
# =========================================================================
import re
import urllib.request

import psycopg2
import psycopg2.extras
from playwright.sync_api import sync_playwright

from scraper_precios.config import CONEXION

DOMINIO = "phd-mfg.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
RE_FIGURA = re.compile(r"Figure:\s*([A-Z0-9\-]+)", re.IGNORECASE)

CATEGORIAS = [
    "https://www.phd-mfg.com/product-category/pipe-hangers-devices/band-hangers/",
    "https://www.phd-mfg.com/product-category/pipe-hangers-devices/beam-clamps/",
    "https://www.phd-mfg.com/product-category/fire-protection-seismic/beam-clamps-fire-protection-seismic/",
    "https://www.phd-mfg.com/product-category/pipe-hangers-devices/seismic-bracing-pipe-hangers-devices/",
    "https://www.phd-mfg.com/product-category/fire-protection-seismic/seismic-bracing/",
]


def get(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=35).read().decode("utf-8", errors="ignore")


def listar_urls_producto() -> list:
    urls = set()
    for cat in CATEGORIAS:
        try:
            html = get(cat)
        except Exception as e:
            print(f"  no se pudo leer categoría {cat}: {e}")
            continue
        for href in re.findall(r'href="([^"]+)"', html):
            if "/products/" in href and href.count("/") > 6 and "selection-guide" not in href:
                urls.add(href.split("?")[0])
    return sorted(urls)


def main():
    urls = listar_urls_producto()
    print(f"{len(urls)} páginas de producto encontradas en las categorías relevantes.")

    filas = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=HEADERS["User-Agent"])
        page.route("**/*", lambda r: r.abort() if r.request.resource_type in
                    ("image", "font", "media", "stylesheet") else r.continue_())

        for i, url in enumerate(urls, 1):
            try:
                page.goto(url, wait_until="commit", timeout=20000)
                page.wait_for_timeout(3000)
                titulo = (page.locator("h1").first.text_content() or "").strip()
                texto = page.inner_text("body")
                m = RE_FIGURA.search(texto)
                figura = m.group(1) if m else ""
                idx = texto.find("FUNCTION:")
                if idx >= 0:
                    fin = texto.find("Copyright ©", idx)
                    descripcion = texto[idx:fin if fin > idx else idx + 3000]
                    descripcion = descripcion.replace("🔍", "").strip()
                else:
                    descripcion = titulo
                filas.append((DOMINIO, url, titulo, figura, descripcion))
                print(f"  [{i}/{len(urls)}] {titulo} -> Figure {figura or '(no encontrada)'}")
            except Exception as e:
                print(f"  [{i}/{len(urls)}] ERROR en {url}: {e}")

        browser.close()

    conexion = psycopg2.connect(**CONEXION)
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM catalogo_fabricante WHERE dominio = %s", (DOMINIO,))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO catalogo_fabricante (dominio, url, titulo, modelo_detectado, descripcion)
            VALUES %s
        """, filas)
    conexion.close()

    print(f"Listo: {len(filas)} productos guardados en catalogo_fabricante.")


if __name__ == "__main__":
    main()
