# =========================================================================
# extraer_specs.py - enriquece scrapes.ok con columnas estructuradas
# (material, acabado, aprobaciones, funcion_texto, tamano, k_factor)
# parseando el texto YA CAPTURADO en scrapes.descripcion. No vuelve a
# scrapear ni cambia estado/match — solo estructura lo que ya existe.
#
# Cubre 2 dominios donde el texto capturado ya trae secciones o pares
# "Label: Valor" identificables sin ambigüedad:
#
#   - phd-mfg.com: la página trae bloques "FUNCTION:" / "MATERIAL:" /
#     "FINISH:" / "Approvals:" / "Ordering:" / "NOTE:" en texto plano
#     (ver crawlers/phd_crawler.py, corregido 2026-08-05 para capturar la
#     ficha completa en vez de cortarla a 500 caracteres).
#   - reliablesprinkler.com: reliable_crawler.py ya arma la descripción
#     como "Label: Valor | Label: Valor | ..." a partir de los pares que
#     WordPress imprime en la página (K Factor, Size, Nominal Size, Valve
#     Size, Style List, etc.) — solo hace falta separarlos y decodificar
#     entidades HTML (&#8243; = ″).
#
# El resto de los dominios (fu-mech.com, tyco-fire.com, erico.com,
# victaulic.com, ...) NO se tocan: sus descripciones capturadas son
# demasiado cortas/genéricas (fu-mech) o vienen de fichas armadas a mano
# en los matchers (no hay texto crudo de sobra para parsear). Ver README
# para el detalle de qué se necesitaría en cada caso.
#
# Uso:
#   docker compose exec scraper python enriquecimiento/extraer_specs.py
# =========================================================================
import html
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_LABEL_PHD = re.compile(r"(?:^|\n)([A-Z][A-Za-z ]{2,20}):\s*\n?", re.MULTILINE)


def parsear_phd(descripcion: str) -> dict:
    posiciones = list(RE_LABEL_PHD.finditer(descripcion))
    secciones = {}
    for i, m in enumerate(posiciones):
        etiqueta = m.group(1).strip().upper()
        inicio = m.end()
        fin = posiciones[i + 1].start() if i + 1 < len(posiciones) else len(descripcion)
        valor = descripcion[inicio:fin].strip()
        if valor:
            secciones[etiqueta] = valor

    extra = " | ".join(
        f"{k.title()}: {v}" for k, v in secciones.items()
        if k not in ("FUNCTION", "MATERIAL", "FINISH", "APPROVALS")
    )
    return {
        "funcion_texto": secciones.get("FUNCTION"),
        "material": secciones.get("MATERIAL"),
        "acabado": secciones.get("FINISH"),
        "aprobaciones": secciones.get("APPROVALS"),
        "tamano": None,
        "k_factor": None,
        "specs_adicionales": extra or None,
    }


def parsear_reliable(descripcion: str) -> dict:
    texto = html.unescape(descripcion)
    pares = {}
    for parte in texto.split(" | "):
        if ":" not in parte:
            continue
        etiqueta, valor = parte.split(":", 1)
        etiqueta, valor = etiqueta.strip(), valor.strip()
        if etiqueta and valor:
            pares[etiqueta] = valor

    tamano = next(
        (v for k, v in pares.items() if "size" in k.lower()), None
    )
    k_factor = pares.get("K Factor")

    extra = " | ".join(
        f"{k}: {v}" for k, v in pares.items()
        if "size" not in k.lower() and k != "K Factor"
    )
    return {
        "funcion_texto": None,
        "material": pares.get("Material"),
        "acabado": pares.get("Finish"),
        "aprobaciones": pares.get("Approvals"),
        "tamano": tamano,
        "k_factor": k_factor,
        "specs_adicionales": extra or None,
    }


PARSERS = {
    "phd-mfg.com": parsear_phd,
    "reliablesprinkler.com": parsear_reliable,
}


def main():
    conexion = psycopg2.connect(**CONEXION)
    total_actualizados = 0

    with conexion, conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        for dominio, parser in PARSERS.items():
            cur.execute(
                "SELECT id, codigo, descripcion FROM scrapes_ultimo "
                "WHERE dominio = %s AND estado = 'ok' AND descripcion IS NOT NULL",
                (dominio,),
            )
            filas = cur.fetchall()

            actualizados = 0
            for fila in filas:
                specs = parser(fila["descripcion"])
                if not any(specs.values()):
                    continue
                cur.execute(
                    """
                    UPDATE scrapes SET
                        material = %(material)s,
                        acabado = %(acabado)s,
                        aprobaciones = %(aprobaciones)s,
                        funcion_texto = %(funcion_texto)s,
                        tamano = %(tamano)s,
                        k_factor = %(k_factor)s,
                        specs_adicionales = %(specs_adicionales)s
                    WHERE id = %(id)s
                    """,
                    {**specs, "id": fila["id"]},
                )
                actualizados += 1

            print(f"{dominio}: {actualizados}/{len(filas)} filas con al menos un campo estructurado.")
            total_actualizados += actualizados

    conexion.close()
    print(f"Total: {total_actualizados} filas de scrapes enriquecidas con specs estructuradas.")


if __name__ == "__main__":
    main()
