# =========================================================================
# globe_matcher.py - GLOBE. globefiresprinkler.com (el dominio de
# fabricantes.py) no resuelve: Globe Fire Sprinkler Corp fue adquirida
# por Victaulic en 2018 y su línea GL-xxxx pasó a venderse bajo el
# catálogo "FireLock™" de victaulic.com con nomenclatura V-xxxx.
#
# Cómo se resolvió la ambigüedad de la primera vuelta (varias series
# K5.6 candidatas, ninguna claramente "standard coverage"): el filtro
# real del catálogo (https://www.victaulic.com/vtc_product_categories/
# fire-sprinklers/, un widget FacetWP) estaba con display:none en el DOM
# hasta hacer clic en el header del acordeón ("Categories"/"K
# Factor"/"Deflector") — por eso no aparecía en un fetch estático.
# Automatizado con Playwright: clic en cada header + su checkbox
# (Standard Coverage -> data-value="standard-spray", K Factor 5.6 ->
# data-value="5-6", Deflector Upright/Pendent -> data-value="upright"/
# "pendent"), lo que devuelve exactamente las series FL-QR/FL-SR (sin
# sufijo /C, /SW, /CNV, /EUR = las variantes "plain", que son las que
# corresponden a nuestros códigos).
#
# GL5601 (Pendent, Quick Response) queda con AMBIGÜEDAD real de la
# fuente: la página FL-QR lista DOS modelos K5.6 para "Pendent and
# Recessed Pendent" (V2708 y V2762) sin distinguir cuál es cuál en el
# texto visible — no se pudo confirmar cuál es el pendent liso vs
# empotrado sin abrir el submittal PDF. Se deja V2708 (el primero
# listado) marcado explícitamente como sin confirmar al 100%.
#
# Las 2 ESCUDO (accesorio) no se investigaron — mismo patrón que en
# TYCO/RELIABLE.
#
# Uso:
#   docker compose exec scraper python matchers/globe_matcher.py
# =========================================================================

import psycopg2

from scraper_precios.config import CONEXION


# código -> (url, serie, descripción, confianza)
MATCHES = {
    "7AUPBR0012": (  # GL5615 UP QR BR K5.6
        "https://www.victaulic.com/products/firelock-series-fl-qr-sprinklers/",
        "FireLock™ Series FL-QR Sprinklers — Upright V2704, K5.6 | 8.1 SI",
        "Upright: V2815 K2.8 | V4215 K4.2 | V2704 K5.6 | V3402 K8.0 (disponible con "
        "acople FireLock IGS estilo V9).",
        "alta",
    ),
    "7AUPCRSR12": (  # GL5661 UP SR CR K5.6
        "https://www.victaulic.com/products/firelock-series-fl-sr-sprinklers/",
        "FireLock™ Series FL-SR Sprinklers — Upright V2703, K5.6 | 8.1 SI",
        "Upright: V2861 K2.8 | V4261 K4.2 | V2703 K5.6 | V3401 K8.0 (disponible con "
        "acople FireLock IGS estilo V9).",
        "alta",
    ),
    "7AUPBRSR12": (  # GL5661 UP SR BR K5.6 (mismo modelo que el anterior, distinto acabado)
        "https://www.victaulic.com/products/firelock-series-fl-sr-sprinklers/",
        "FireLock™ Series FL-SR Sprinklers — Upright V2703, K5.6 | 8.1 SI",
        "Upright: V2861 K2.8 | V4261 K4.2 | V2703 K5.6 | V3401 K8.0 (disponible con "
        "acople FireLock IGS estilo V9).",
        "alta",
    ),
    "7APDQRBR12": (  # GL5601 PD QR BR K5.6 -- AMBIGUO, ver nota arriba
        "https://www.victaulic.com/products/firelock-series-fl-qr-sprinklers/",
        "FireLock™ Series FL-QR Sprinklers — Pendent, K5.6 (V2708 o V2762, sin confirmar cuál)",
        "Pendent and Recessed Pendent: V2801 K2.8 | V4201 K4.2 | V2708 K5.6 | V2762 K5.6 "
        "| V3406 K8.0 | V3702 K8.0. La página lista DOS modelos K5.6 para pendent sin "
        "distinguir cuál es liso y cuál empotrado en el texto visible — habría que abrir "
        "el submittal PDF (41.01) para confirmar.",
        "media (V2708 vs V2762 sin confirmar)",
    ),
}


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor() as cur:
        cur.execute("SELECT codigo FROM productos_criticos WHERE marca = 'GLOBE'")
        codigos = [r[0] for r in cur.fetchall()]

    filas = []
    for codigo in codigos:
        if codigo in MATCHES:
            url, serie, descripcion, confianza = MATCHES[codigo]
            filas.append((
                codigo, "victaulic.com", url, descripcion, serie, None, None, "ok",
                f"Confianza {confianza}. Encontrado con el filtro real del catálogo "
                f"(Categories=Standard Coverage, K Factor=5.6, Deflector=Upright/Pendent).",
            ))
        else:
            filas.append((
                codigo, "victaulic.com", None, None, None, None, None, "no_encontrado",
                "Escudo/accesorio, no investigado (mismo patrón que TYCO/RELIABLE).",
            ))

    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas)

    conexion.close()
    ok = sum(1 for f in filas if f[7] == "ok")
    print(f"GLOBE: {ok} matches, {len(filas)-ok} sin match (de {len(filas)} códigos).")


if __name__ == "__main__":
    main()
