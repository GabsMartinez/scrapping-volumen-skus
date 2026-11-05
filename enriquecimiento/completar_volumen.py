# =========================================================================
# completar_volumen.py - calcula un volumen APROXIMADO (caja envolvente,
# para planear espacio de bodega) para los códigos donde ya tenemos
# dimensiones reales del fabricante. Cada grupo de producto usa una
# lectura distinta de sus letras (A, B, C, D, E...) porque cada ficha las
# define distinto -- no hay una fórmula única. Todo queda documentado en
# volumen_metodo para poder auditar/corregir el supuesto.
#
# Grupos cubiertos:
#   1) PHD FIG 141 + ERICO FIG 100 (ganchos tipo pera, mismo diseño):
#      la ficha solo da el perfil frontal (E = altura total, que además
#      sirve de ancho porque el aro es redondo). NO hay dato de
#      profundidad (grosor de la banda de metal vista de lado) en
#      ninguna fuente pública revisada (fabricante, distribuidores).
#      Se usa Rod Size (el dato más chico disponible) como aproximación
#      conservadora de esa profundidad faltante -- es un supuesto
#      explícito, marcado con confianza "baja".
#   2) PHD FIG 353/360/363 (abrazadera de viga): la ficha SÍ trae 2
#      vistas (frontal + lateral), así que hay 3 ejes reales: D (alcance
#      de la mordaza), C (altura), B (ancho de la base, vista lateral).
#      Confianza "media" (son las 3 medidas más grandes de un dibujo
#      real de 2 vistas, no un supuesto).
#   3) Wilson & Cousins (válvulas angulares + boquilla): A, B, C ya
#      vienen como 3 medidas de un cuerpo compacto tipo válvula.
#      Confianza "media".
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_volumen.py
# =========================================================================
import re

import psycopg2
import psycopg2.extras

from scraper_precios.config import CONEXION


RE_MM = re.compile(r"\(([\d.]+)\s*mm\)")
RE_FRACCION_PULG = re.compile(r'(\d+)-(\d+)/(\d+)"?|(\d+)/(\d+)"?|(\d+)"')


def frac_a_mm(texto: str) -> float | None:
    """'4-1/4\"' o '3/8' o '2\"' -> mm (las comillas de pulgada son opcionales,
    'Rod Size' en las fichas PHD/ERICO viene sin comillas: '3/8')."""
    m = RE_FRACCION_PULG.search(texto)
    if not m:
        return None
    if m.group(1):
        pulgadas = int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    elif m.group(4):
        pulgadas = int(m.group(4)) / int(m.group(5))
    else:
        pulgadas = int(m.group(6))
    return round(pulgadas * 25.4, 2)


def valor_mm(texto: str, etiqueta: str) -> float | None:
    """Busca 'Etiqueta: ... (XX.XXmm)' y devuelve XX.XX; si no hay mm
    entre paréntesis, convierte la fracción en pulgadas que le sigue."""
    m = re.search(rf"{re.escape(etiqueta)}:\s*([^|]+)", texto)
    if not m:
        return None
    segmento = m.group(1)
    m_mm = RE_MM.search(segmento)
    if m_mm:
        return float(m_mm.group(1))
    return frac_a_mm(segmento)


def calc_anillo_ganchos(dim_texto: str) -> dict | None:
    # PHD llama a la altura total "E"; ERICO llama a la misma medida "H"
    # (mismo tipo de pieza, letras distintas en cada ficha).
    e = valor_mm(dim_texto, "E") or valor_mm(dim_texto, "H")
    rod = valor_mm(dim_texto, "Rod Size") or valor_mm(dim_texto, "RS")
    if e is None or rod is None:
        return None
    volumen_mm3 = e * e * rod
    return {
        "volumen_cm3": round(volumen_mm3 / 1000, 2),
        "metodo": (
            f"Caja envolvente aproximada: (E o H)×(E o H)×RodSize = {e}×{e}×{rod} mm. "
            "La altura total (E en PHD, H en ERICO) se usa también como ancho porque la pieza es un aro "
            "redondo. NO se encontró dato de profundidad/grosor de banda en ninguna "
            "fuente pública -- se usa Rod Size (el diámetro de la varilla, el dato "
            "más chico disponible) como aproximación conservadora de esa profundidad "
            "faltante. Es un supuesto explícito, no un dato confirmado."
        ),
        "confianza": "baja (falta eje de profundidad, aproximado con Rod Size)",
    }


def calc_abrazadera_viga(dim_texto: str) -> dict | None:
    d = valor_mm(dim_texto, "D")
    c = valor_mm(dim_texto, "C") or valor_mm(dim_texto, "Adj. C")
    b = valor_mm(dim_texto, "B")
    if None in (d, c, b):
        return None
    volumen_mm3 = d * c * b
    return {
        "volumen_cm3": round(volumen_mm3 / 1000, 2),
        "metodo": (
            f"Caja envolvente: D×C×B = {d}×{c}×{b} mm, tomado de una ficha con 2 "
            "vistas reales (frontal: D=alcance de la mordaza, C=altura; lateral: "
            "B=ancho de la base). Las 3 medidas vienen del dibujo técnico, no son "
            "un supuesto."
        ),
        "confianza": "media (3 ejes de un dibujo real de 2 vistas)",
    }


def calc_valvula_wc(dim_texto: str) -> dict | None:
    a = valor_mm(dim_texto, "A")
    b = valor_mm(dim_texto, "B")
    # usa 'C cerrado' (la posición compacta) si existe; si no, 'C'
    c = valor_mm(dim_texto, "C cerrado") or valor_mm(dim_texto, "C")
    if a is None or c is None:
        return None
    if b is None:
        # HN4LRED no trae B ("Subject to thread") -> usa A como proxy del ancho
        b = a
        confianza = "baja (sin ancho B publicado, se usa A como aproximación)"
    else:
        confianza = "media (3 medidas de cuerpo de válvula ya publicadas)"
    volumen_mm3 = a * b * c
    return {
        "volumen_cm3": round(volumen_mm3 / 1000, 2),
        "metodo": f"Caja envolvente: A×B×C = {a}×{b}×{c} mm (cuerpo tipo válvula/boquilla).",
        "confianza": confianza,
    }


GRUPOS = [
    (["6A2PHD"], calc_anillo_ganchos),      # PHD FIG 141
    (["6A10000002", "6A10000112", "6A10000114"], calc_anillo_ganchos),  # ERICO FIG 100
    (["6D4PHD"], calc_abrazadera_viga),     # PHD FIG 353/360/363
    (["23BOQP0112", "5A32VSRB212", "5A28BRSR112"], calc_valvula_wc),  # Wilson & Cousins
]


def pertenece(codigo: str, prefijos: list) -> bool:
    return any(codigo == p or codigo.startswith(p) for p in prefijos)


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT codigo, dimensiones_texto FROM productos_criticos WHERE dimensiones_texto IS NOT NULL")
        filas = cur.fetchall()

    actualizados = 0
    with conexion, conexion.cursor() as cur:
        for fila in filas:
            codigo, dim_texto = fila["codigo"], fila["dimensiones_texto"]
            funcion = next((f for prefijos, f in GRUPOS if pertenece(codigo, prefijos)), None)
            if funcion is None:
                print(f"  {codigo}: sin grupo de cálculo asignado, se deja sin volumen.")
                continue
            resultado = funcion(dim_texto)
            if resultado is None:
                print(f"  {codigo}: no se pudo parsear dimensiones para volumen.")
                continue
            cur.execute(
                "UPDATE productos_criticos SET volumen_cm3=%s, volumen_metodo=%s, volumen_confianza=%s WHERE codigo=%s",
                (resultado["volumen_cm3"], resultado["metodo"], resultado["confianza"], codigo),
            )
            print(f"  {codigo}: {resultado['volumen_cm3']} cm3 ({resultado['confianza']})")
            actualizados += 1

    conexion.close()
    print(f"\n{actualizados}/{len(filas)} códigos con volumen calculado.")


if __name__ == "__main__":
    main()
