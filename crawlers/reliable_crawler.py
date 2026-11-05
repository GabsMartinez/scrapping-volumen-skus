# =========================================================================
# reliable_crawler.py - RELIABLE (reliablesprinkler.com).
#
# NO usa Scrapy a propósito: el WAF del sitio deja pasar una petición HTTP
# simple (urllib/curl) pero bloquea con 403 tanto a Playwright (fingerprint
# de navegador automatizado) COMO al downloader HTTP de Scrapy/Twisted
# (probablemente por el orden/set de headers que arma Twisted, distinto al
# de urllib). En vez de pelear con el WAF, se usa lo que sí funciona: un
# crawler chiquito con urllib + hilos, escribiendo directo a Postgres.
#
# El sitio es WordPress con sitemap real (wp-sitemap.xml ->
# sitemap_type_product.xml?pg=1..3, ~258 productos). Cada página trae
# specs como pares "Label:" / "Valor" (K Factor, Style List, Size...) en
# vez de descripción larga.
#
# Uso:
#   docker compose exec scraper python crawlers/reliable_crawler.py
# =========================================================================
import concurrent.futures
import re
import time
import urllib.request

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION

DOMINIO = "reliablesprinkler.com"
HEADERS = {"User-Agent": "Mozilla/5.0"}
RE_LABEL = re.compile(r"^[A-Za-z][A-Za-z /]*:$")


def get(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="ignore")


def listar_urls_producto() -> list:
    indice = get("https://www.reliablesprinkler.com/wp-sitemap.xml")
    paginas = re.findall(
        r"<loc>(https://www\.reliablesprinkler\.com/sitemap_type_product\.xml\?pg=\d+)</loc>", indice
    )
    urls = []
    for pagina in paginas:
        urls.extend(re.findall(r"<loc>(.*?)</loc>", get(pagina)))
    return urls


def extraer_producto(url: str) -> dict:
    html = get(url)
    titulo_m = re.search(r"<title>(.*?)</title>", html, re.S)
    titulo = re.sub(r"\s+", " ", titulo_m.group(1)).strip() if titulo_m else ""

    sin_script = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    sin_script = re.sub(r"<style.*?</style>", " ", sin_script, flags=re.S)
    texto = re.sub(r"<[^>]+>", "\n", sin_script)
    lineas = [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n") if l.strip()]

    specs = {}
    for i, linea in enumerate(lineas):
        if RE_LABEL.match(linea) and i + 1 < len(lineas):
            specs[linea.rstrip(":")] = lineas[i + 1]

    descripcion = " | ".join(f"{k}: {v}" for k, v in specs.items()) or titulo
    m_kfactor = re.search(r"[\d.]+", specs.get("K Factor", ""))
    modelo_detectado = f"K{m_kfactor.group(0)}" if m_kfactor else ""

    return {"url": url, "titulo": titulo, "modelo_detectado": modelo_detectado, "descripcion": descripcion}


def main():
    urls = listar_urls_producto()
    print(f"{len(urls)} páginas de producto encontradas.")

    filas = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futuros = {pool.submit(extraer_producto, u): u for u in urls}
        for i, futuro in enumerate(concurrent.futures.as_completed(futuros), 1):
            url = futuros[futuro]
            try:
                filas.append(futuro.result())
            except Exception as e:
                print(f"  [{i}/{len(urls)}] ERROR en {url}: {e}")
            if i % 50 == 0:
                print(f"  [{i}/{len(urls)}] procesados...")
            time.sleep(0.05)  # cortesía: no reventar el sitio con 6 hilos a la vez

    conexion = psycopg2.connect(**CONEXION)
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM catalogo_fabricante WHERE dominio = %s", (DOMINIO,))
        psycopg2.extras.execute_values(cur, """
            INSERT INTO catalogo_fabricante (dominio, url, titulo, modelo_detectado, descripcion)
            VALUES %s
        """, [(DOMINIO, f["url"], f["titulo"], f["modelo_detectado"], f["descripcion"]) for f in filas])
    conexion.close()

    print(f"Listo: {len(filas)} productos guardados en catalogo_fabricante.")


if __name__ == "__main__":
    main()
