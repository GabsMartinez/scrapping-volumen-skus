# =========================================================================
# anvil_matcher.py - ANVIL (anvilintl.com -> asc-es.com, "ASC Engineered
# Solutions" tras la fusión). El sitio corre su buscador de productos con
# Algolia (índice "products", API key pública de solo-lectura, capturada
# inspeccionando el tráfico de red del sitio real con Playwright). Con
# eso alcanza consultar directo por HTTP sin abrir navegador.
#
# Solo hay 1 código con marca ANVIL en el grupo crítico (FIG 69, soporte
# tipo pera). Si en el futuro hay más códigos ANVIL, generalizar este
# matcher a la misma consulta Algolia por "Fig <n>" + tipo de pieza.
#
# Uso:
#   docker compose exec scraper python matchers/anvil_matcher.py
# =========================================================================
import json
import re
import urllib.request

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


ALGOLIA_URL = ("https://kdea1wzv4c-dsn.algolia.net/1/indexes/*/queries"
               "?x-algolia-application-id=KDEA1WZV4C"
               "&x-algolia-api-key=0c6c4b7c605514df995ccca05e846c37")
RE_FIG = re.compile(r"FIG\s*(\d+)", re.IGNORECASE)


def buscar_algolia(query: str, hits: int = 20) -> list:
    # restrictSearchableAttributes=figureNumber: la búsqueda de texto libre
    # (ej. "Fig 69") no rankea bien el número exacto entre miles de
    # productos: hay que buscar SOLO en el campo figureNumber.
    params = f"query={query}&restrictSearchableAttributes=figureNumber&hitsPerPage={hits}"
    body = json.dumps({"requests": [{"indexName": "products", "params": params}]}).encode()
    req = urllib.request.Request(ALGOLIA_URL, data=body, headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())["results"][0]["hits"]


def limpiar_html(texto: str) -> str:
    return re.sub(r"<[^>]+>", " ", texto or "").strip()


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'ANVIL'")
        productos = cur.fetchall()

    filas_insertar = []
    resultados = {"ok": 0, "no_encontrado": 0}

    for producto in productos:
        m = RE_FIG.search(producto["nombre_producto"])
        if not m:
            filas_insertar.append((
                producto["codigo"], "asc-es.com", None, None, None, None, None,
                "no_encontrado", "No se pudo leer número de figura del nombre.",
            ))
            resultados["no_encontrado"] += 1
            continue

        figura = m.group(1)
        hits = buscar_algolia(figura)
        candidato = next(
            (h for h in hits if figura in [t.strip() for t in h.get("figureNumber", "").split(",")]),
            None,
        )

        if not candidato:
            filas_insertar.append((
                producto["codigo"], "asc-es.com", None, None, None, None, None,
                "no_encontrado", f"Fig {figura}: sin match exacto en Algolia (mejor esfuerzo revisado a mano).",
            ))
            resultados["no_encontrado"] += 1
            continue

        url = "https://www.asc-es.com" + candidato.get("uri", "")
        filas_insertar.append((
            producto["codigo"], "asc-es.com", url, limpiar_html(candidato.get("description"))[:2000],
            candidato.get("title"), None, None, "ok",
            f"Match por número de figura (Fig {figura}) vía búsqueda Algolia del sitio.",
        ))
        resultados["ok"] += 1

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'asc-es.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    print(f"ANVIL: {resultados['ok']} matches, {resultados['no_encontrado']} sin match (de {len(productos)} códigos).")


if __name__ == "__main__":
    main()
