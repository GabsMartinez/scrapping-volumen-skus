# =========================================================================
# reliable_matcher.py - cruza productos_criticos (marca RELIABLE) contra
# catalogo_fabricante (reliablesprinkler.com, crawler.reliable_crawler).
#
# Reliable no numera sus páginas por nuestro "MOD." (esos son códigos
# internos RASCO/distribuidor) — pero SÍ publica el K-factor de cada
# rociador, que también viene en nuestro Nombre Producto ("K5.6",
# "K11.2"...). El cruce es: mismo K-factor + mismo tipo (orientación +
# respuesta), igual que MECH usa número de modelo + tipo de pieza.
#
# Uso:
#   docker compose exec scraper python matchers/reliable_matcher.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_KFACTOR = re.compile(r"K\s*(\d{1,2}\.\d)", re.IGNORECASE)

# código en Nombre Producto -> palabra que debería aparecer en el
# título/specs del catálogo si es el mismo tipo de rociador.
TIPO = {
    "PD": ["PENDENT"],
    "UP": ["UPRIGHT"],
    "ESFR": ["ESFR"],
    "QR": ["QUICK RESPONSE"],
    "SR": ["STANDARD RESPONSE"],
    "STD": ["STANDARD RESPONSE", "STANDARD"],
}


def extraer_kfactor(texto: str) -> str | None:
    m = RE_KFACTOR.search(texto.upper())
    return f"K{m.group(1)}" if m else None


def puntaje_tipo(nombre_producto: str, texto_catalogo: str) -> int:
    nombre_up = nombre_producto.upper()
    texto_up = texto_catalogo.upper()
    puntaje = 0
    for codigo, palabras in TIPO.items():
        if re.search(rf"\b{codigo}\b", nombre_up) and any(p in texto_up for p in palabras):
            puntaje += 1
    return puntaje


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, nombre_producto FROM productos_criticos WHERE marca = 'RELIABLE'")
        productos = cur.fetchall()

        cur.execute("""
            SELECT url, titulo, modelo_detectado, descripcion FROM catalogo_fabricante
            WHERE dominio = 'reliablesprinkler.com' AND modelo_detectado <> ''
        """)
        catalogo = cur.fetchall()

    indice = {}
    for fila in catalogo:
        indice.setdefault(fila["modelo_detectado"], []).append(fila)

    resultados = {"ok": 0, "no_encontrado": 0}
    filas_insertar = []

    for producto in productos:
        kfactor = extraer_kfactor(producto["nombre_producto"])
        candidatos = indice.get(kfactor, []) if kfactor else []

        if not candidatos:
            filas_insertar.append((
                producto["codigo"], "reliablesprinkler.com", None, None, None, None, None,
                "no_encontrado",
                f"K-factor detectado: {kfactor or 'ninguno'}. Sin candidatos en el catálogo." if kfactor
                else "No se pudo leer K-factor del nombre (probablemente un accesorio, no un rociador).",
            ))
            resultados["no_encontrado"] += 1
            continue

        mejor = max(candidatos, key=lambda c: puntaje_tipo(producto["nombre_producto"], c["titulo"] + " " + c["descripcion"]))
        puntaje = puntaje_tipo(producto["nombre_producto"], mejor["titulo"] + " " + mejor["descripcion"])

        if puntaje == 0:
            # Mismo K-factor no basta: un solo candidato con ese K-factor
            # puede ser la orientación/respuesta equivocada (ej. "PD ESFR"
            # cayendo sobre un "Upright" solo porque comparten K16.8). Sin
            # ninguna palabra de tipo confirmada, no se acepta el match.
            filas_insertar.append((
                producto["codigo"], "reliablesprinkler.com", None, None, None, None, None,
                "no_encontrado",
                f"K-factor {kfactor} encontrado pero sin confirmar orientación/respuesta "
                f"(candidato más cercano: '{mejor['titulo']}') — no se acepta para evitar "
                f"un falso positivo.",
            ))
            resultados["no_encontrado"] += 1
            continue

        filas_insertar.append((
            producto["codigo"], "reliablesprinkler.com", mejor["url"], mejor["descripcion"], mejor["titulo"],
            None, None, "ok",
            f"Confianza alta: K-factor {kfactor}, {len(candidatos)} candidato(s), puntaje tipo {puntaje}.",
        ))
        resultados["ok"] += 1

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        cur.execute("DELETE FROM scrapes WHERE dominio = 'reliablesprinkler.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    print(f"RELIABLE: {resultados['ok']} matches, {resultados['no_encontrado']} sin match (de {len(productos)} códigos).")


if __name__ == "__main__":
    main()
