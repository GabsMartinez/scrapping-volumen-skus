# =========================================================================
# mech_matcher.py - cruza productos_criticos (marca MECH) contra
# catalogo_fabricante (fu-mech.com, ya crawleado por mech_catalogo_spider)
# e inserta los matches encontrados en 'scrapes'.
#
# Por qué existe esto en vez de buscar directo en el sitio: nuestro
# código interno del producto (ej. "B240", "P1G73") NO es el modelo real
# del fabricante (ej. "MODEL 240") — es un alias de catálogo interno de
# la distribuidora. El único texto en común es el NÚMERO embebido, más
# el tipo de pieza (codo, copa, unión...). Por eso el cruce es:
#   1) mismo número de modelo (2-4 dígitos, con o sin sufijo de letra)
#   2) si hay más de un candidato con ese número, se desempata por
#      palabra clave del tipo de pieza (ES -> EN) compartida en el título
#
# SEGUNDA PASADA (familias sin página por talla, ej. "ACOPLE RIG" P1G73/
# P1G42/...): fu-mech NO publica una página por cada talla de estos
# acoples/tees mecánicas — publica UNA página por familia completa (ej.
# "MODEL 1G" cubre todas las tallas del acople rígido). Nuestro código
# trae el patrón "P<familia> <talla>" (ej. "P1G 73", "P3G 60X42"): para
# los que la primera pasada no resolvió, se busca "P" + el modelo exacto
# del catálogo como token completo (con \b para no confundir "P1G" con
# "P1GS"). Si el código trae un sufijo "S" que el catálogo no tiene como
# variante propia (ej. "P1NS", pero el catálogo solo tiene "1N"/"1NX"),
# se cae al modelo base sin "S" — es la misma familia, solo que fu-mech
# no distingue esa variante en su sitio.
#
# Uso:
#   docker compose exec scraper python matchers/mech_matcher.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


# SIN \b antes del dígito a propósito: nuestros códigos internos suelen
# venir pegados a un prefijo de letra sin separador (ej. "B240", "P1G73"),
# así que un \b ahí nunca matchea (letra y dígito son ambos \w). Se busca
# la corrida de dígitos donde sea, y aparte se guarda si viene con sufijo
# de letra pegado (ej. "180R") porque el catálogo también usa ese patrón.
RE_TOKEN_MODELO = re.compile(r"(\d{2,4})([A-Z]{0,2})\b")

# Palabra clave (ES, en Nombre Producto) -> palabras que deberían aparecer
# en el título en inglés del fabricante si es el mismo tipo de pieza.
# No es exhaustivo: es una señal de desempate, no la única fuente de verdad.
TRADUCCIONES = {
    "CODO": ["ELBOW"],
    "TE ": ["TEE"],
    # "TE MEC" (Tee MECánica, tipo silla de montar) es un producto
    # DISTINTO de una tee roscada normal (BMI TEE) — sin esto, "TE MEC
    # SAL ROS" empataba en puntaje contra 8+ tees BMI/grooved normales.
    "TE MEC": ["MECH TEE"],
    "COPA": ["SOCKET", "REDUC"],
    "RED ": ["REDUC"],
    "ACOPLE": ["COUPLING"],
    "UNION": ["UNION"],
    "TAPON": ["CAP", "PLUG"],
    "TAPA": ["CAP", "PLUG"],
    # "TAPON MACHO" (macho=rosca que entra) es específicamente un PLUG,
    # no un CAP (que cubre por fuera) — sin esto, CAP y PLUG empataban en
    # puntaje (ambos son BMI) y la tercera pasada quedaba ambigua a propósito.
    "TAPON MACHO": ["PLUG"],
    "BRIDA": ["FLANGE"],
    "VALV": ["VALVE"],
    "CHEQUE": ["CHECK"],
    "COMPUERTA": ["GATE"],
    "MARIPOSA": ["BUTTERFLY"],
    "NIPLE": ["NIPPLE"],
    "SOPORTE": ["HANGER", "CLAMP", "SUPPORT"],
    "COLLAR": ["CLAMP"],
    "CRUZ": ["CROSS"],
    "MANGUERA": ["HOSE"],
    # "RED BUSHING" (buje reductor): la página real dice "Red BUSH", no
    # "REDUCING" — sin esto, TAPON/CAP quedaba con el mismo puntaje que
    # el buje reductor real y la tercera pasada no podía desempatar.
    "BUSHING": ["BUSH"],
    # tipo de conexión: sin esto, "CODO RAN" (ranurado=grooved) empataba
    # igual contra la línea roscada (BMI) y la ranurada (GROOVED) del
    # mismo número de modelo, y el desempate quedaba en manos de max()
    # (arbitrario en empates). Esto es lo que más ambigüedad causaba.
    "RAN": ["GROOVED"],
    "ROSC": ["BMI", "THREADED"],
    # "SAL ROS" (salida roscada, abreviado SIN la "C" de "ROSC") no
    # matcheaba con la clave "ROSC" de arriba — substring exacto, no
    # prefijo. Clave compuesta y específica a propósito (no solo "ROS"
    # suelto, que chocaría con "CROSS"). El target "THD" queda SOLO acá
    # (no en "ROSC" general): agregarlo ahí generaba empates falsos con
    # reductores concéntricos ranurados que igual dicen "(THD)" en el
    # título por su sub-variante de salida, sin ser roscados de verdad.
    "SAL ROS": ["BMI", "THREADED", "THD"],
}


# Clase de presión (ej. "ACx300 LBS", "150 LBS"): es un número de
# catálogo real (ANSI class), pero NO es el modelo del fabricante, y
# lamentablemente coincide seguido con números de modelo reales de
# fu-mech (ej. "300" = clase de presión Y también "MECH BMI CAP MODEL
# 300"). Sin filtrar esto, cosas como "UNION ACx300 LBS...B220" matchean
# mal contra el tapón (CAP) modelo 300 en vez de la unión real B220.
RE_CLASE_PRESION = re.compile(r"\d+\s*LBS", re.IGNORECASE)


def extraer_tokens(texto: str) -> set:
    """Devuelve el número solo (ej. '240') Y el número+sufijo (ej. '180R')
    como tokens válidos, para que un lado con sufijo (catálogo) matchee
    contra el otro sin sufijo (nuestro código) y viceversa. Se quita antes
    la clase de presión (ver RE_CLASE_PRESION) para no confundirla con un
    número de modelo real."""
    texto_limpio = RE_CLASE_PRESION.sub(" ", texto.upper())
    tokens = set()
    for digitos, sufijo in RE_TOKEN_MODELO.findall(texto_limpio):
        tokens.add(digitos)
        if sufijo:
            tokens.add(digitos + sufijo)
    return tokens


def puntaje_palabra_clave(nombre_producto: str, titulo_catalogo: str) -> int:
    nombre_up = nombre_producto.upper()
    titulo_up = titulo_catalogo.upper()
    puntaje = 0
    for clave_es, claves_en in TRADUCCIONES.items():
        if clave_es in nombre_up and any(c in titulo_up for c in claves_en):
            puntaje += 1
    return puntaje


# "P" + letras/dígitos + espacio, ej. "P1G 73", "P3GS 114X73", "P1N 60".
RE_PREFIJO_FAMILIA = re.compile(r"\bP([0-9][A-Z0-9]{0,3})\s")


def buscar_por_prefijo(nombre_producto: str, indice_modelo: dict):
    """Segunda pasada: familia completa por prefijo 'P<modelo>', con
    fallback al modelo base si el código trae un sufijo 'S' que el
    catálogo no distingue como variante propia. Devuelve
    (candidatos, es_fallback_base)."""
    m = RE_PREFIJO_FAMILIA.search(nombre_producto.upper())
    if not m:
        return [], False

    modelo = m.group(1)
    if modelo in indice_modelo:
        return indice_modelo[modelo], False

    if modelo.endswith("S") and modelo[:-1] in indice_modelo:
        return indice_modelo[modelo[:-1]], True

    return [], False


def buscar_por_texto_familia(nombre_producto: str, catalogo: list):
    """TERCERA pasada: para códigos sin NINGÚN número de modelo utilizable
    (ej. "TAPON MACHO ACx300 LBS ROSC" — tras quitar la clase de presión
    no queda ningún dígito), se busca por palabra clave del tipo de pieza
    en TODO el catálogo. No basta con "puntaje > 0" (ej. "TAPON" solo ya
    matchea 5 páginas de tapón/plug distintas): se necesita que UN
    candidato tenga el puntaje MÁS ALTO de forma única (ej. "TAPON" +
    "ROSC" juntos solo empatan en la página BMI, que además tiene "BMI"
    en el título) — si hay empate en el máximo, queda ambiguo a propósito
    y no se fuerza nada."""
    puntuados = [(puntaje_palabra_clave(nombre_producto, c["titulo"]), c) for c in catalogo]
    puntuados = [(p, c) for p, c in puntuados if p > 0]
    if not puntuados:
        return []
    maximo = max(p for p, c in puntuados)
    ganadores = [c for p, c in puntuados if p == maximo]
    return ganadores if len(ganadores) == 1 else []


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT codigo, nombre_producto, modelo FROM productos_criticos
            WHERE marca = 'MECH' AND tiene_dominio = TRUE
        """)
        productos = cur.fetchall()

        cur.execute("""
            SELECT url, titulo, modelo_detectado, descripcion FROM catalogo_fabricante
            WHERE dominio = 'fu-mech.com' AND modelo_detectado <> ''
        """)
        catalogo = cur.fetchall()

        # sin filtrar modelo_detectado: la tercera pasada (por texto) no
        # depende de tener un modelo detectado, así que también debe
        # poder usar páginas como la de manguera flex (sin número de modelo).
        cur.execute("SELECT url, titulo, modelo_detectado, descripcion FROM catalogo_fabricante WHERE dominio = 'fu-mech.com'")
        catalogo_completo = cur.fetchall()

    # índice 1: token de modelo (dígitos ± sufijo) -> filas de catálogo
    indice = {}
    # índice 2: modelo EXACTO del catálogo (ej. "1G", "3JX") -> filas
    indice_modelo = {}
    for fila in catalogo:
        for token in extraer_tokens(fila["modelo_detectado"]):
            indice.setdefault(token, []).append(fila)
        indice_modelo.setdefault(fila["modelo_detectado"].upper(), []).append(fila)

    resultados = {"ok": 0, "ok_familia": 0, "ok_texto": 0, "no_encontrado": 0}
    filas_insertar = []

    for producto in productos:
        tokens_producto = extraer_tokens(producto["nombre_producto"])
        candidatos = []
        for token in tokens_producto:
            candidatos.extend(indice.get(token, []))
        es_fallback_base = False
        es_texto = False

        if not candidatos:
            candidatos, es_fallback_base = buscar_por_prefijo(producto["nombre_producto"], indice_modelo)

        if not candidatos:
            candidatos = buscar_por_texto_familia(producto["nombre_producto"], catalogo_completo)
            es_texto = bool(candidatos)

        if es_texto:
            mejor = candidatos[0]
            filas_insertar.append((
                producto["codigo"], "fu-mech.com", mejor["url"], mejor["descripcion"], mejor["titulo"],
                None, None, "ok",
                f"Match por palabra clave del tipo de pieza (sin número de modelo utilizable en "
                f"el nombre): único candidato en todo el catálogo con esa palabra clave.",
            ))
            resultados["ok_texto"] += 1
            continue

        if not candidatos:
            filas_insertar.append((
                producto["codigo"], "fu-mech.com", None, None, None, None, None,
                "no_encontrado", "Ningún producto del catálogo comparte número de modelo, familia, ni palabra clave única.",
            ))
            resultados["no_encontrado"] += 1
            continue

        # desempate: mayor puntaje de palabra clave compartida
        mejor = max(candidatos, key=lambda c: puntaje_palabra_clave(producto["nombre_producto"], c["titulo"]))
        puntaje = puntaje_palabra_clave(producto["nombre_producto"], mejor["titulo"])

        if not es_fallback_base and puntaje == 0:
            # Un solo candidato NO es garantía de que el número sea
            # realmente un modelo: puede ser una segunda medida de talla
            # (ej. "48X21" en un STRAP) o cualquier otro número de 2-4
            # dígitos que coincida por casualidad con un modelo real de
            # otra pieza. Sin ninguna palabra clave que confirme el tipo
            # de pieza, es más seguro no dar el match por bueno (mejor
            # perder cobertura que meter una descripción/precio de un
            # producto distinto).
            filas_insertar.append((
                producto["codigo"], "fu-mech.com", None, None, None, None, None,
                "no_encontrado",
                f"Se encontró el número pero sin ninguna palabra clave del tipo de pieza que lo "
                f"confirme (candidato más cercano: '{mejor['titulo']}') — no se acepta el match "
                f"para evitar un falso positivo.",
            ))
            resultados["no_encontrado"] += 1
            continue

        if es_fallback_base:
            detalle = (
                f"Match por FAMILIA (fu-mech no publica página por talla): la página "
                f"cubre el modelo base '{mejor['modelo_detectado']}', nuestro código trae "
                f"una variante 'S' que el sitio no distingue por separado."
            )
            resultados["ok_familia"] += 1
        else:
            detalle = (
                f"Confianza alta: {len(candidatos)} candidato(s) con el mismo número de modelo, "
                f"puntaje de palabra clave {puntaje}."
            )
            resultados["ok"] += 1

        filas_insertar.append((
            producto["codigo"], "fu-mech.com", mejor["url"], mejor["descripcion"], mejor["titulo"],
            None, None, "ok", detalle,
        ))

    codigos = [p["codigo"] for p in productos]
    with conexion, conexion.cursor() as cur:
        # idempotente: si se vuelve a correr, no duplica intentos anteriores
        cur.execute("DELETE FROM scrapes WHERE dominio = 'fu-mech.com' AND codigo = ANY(%s)", (codigos,))
        cur.executemany("""
            INSERT INTO scrapes (codigo, dominio, url_fuente, descripcion, serie, precio, moneda, estado, detalle)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, filas_insertar)

    conexion.close()
    total_ok = resultados["ok"] + resultados["ok_familia"] + resultados["ok_texto"]
    print(f"MECH: {total_ok} matches ({resultados['ok']} por talla exacta + "
          f"{resultados['ok_familia']} por familia + {resultados['ok_texto']} por palabra clave única), "
          f"{resultados['no_encontrado']} sin match "
          f"(de {len(productos)} códigos, contra {len(catalogo)} productos del catálogo fu-mech.com).")


if __name__ == "__main__":
    main()
