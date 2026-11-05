# =========================================================================
# completar_ronda2.py - segunda pasada sobre los 12 codigos que quedaban
# "por revisar de nuevo" en FALTANTES.md (8 ERICO nVent CADDY + 4 TYCO
# escudos), siguiendo la metodologia de PDF real + verificacion de
# modelo/SIN + diagrama renderizado como imagen cuando el texto solo no
# alcanza.
#
# Fuentes reales encontradas esta ronda (todas descargadas via curl con
# User-Agent de navegador -- Playwright chocaba con el bot-check de
# Cloudflare en nvent.com, pero el endpoint /pdf del propio sitio SI
# responde el PDF real si se le pide directo):
#
#   - ERICO FIG 115 (Standard Duty Loop Hanger): nvent.com publica una
#     ficha tecnica "system-generated" con tabla de medidas por tamano Y
#     diagrama con letras OD (diametro del aro), A (altura total), B
#     (altura del aro sin el collar), C (altura del collar), RS (diametro
#     de varilla). A diferencia del calculo previo para PHD FIG141/ERICO
#     FIG100 (que no tenian diametro real y usaban la altura tambien como
#     ancho), aqui SI hay un diametro real (OD) -- mejor dato, confianza
#     mas alta.
#   - ERICO FIG 300/310 (Universal Beam Clamp): la ficha real SI tiene
#     diagrama, pero solo publica UNA medida real del cuerpo (A, ancho del
#     cuello donde entra la varilla) mas RS (varilla) y FT (espesor MAXIMO
#     de ala que acepta la mordaza -- una capacidad, no una medida fija de
#     la pieza). Verificado tambien contra una ficha alterna
#     (alldataresource.com, mismo fabricante) -- mismos 3 valores, ningun
#     dato adicional. Falta por completo el eje de profundidad/largo a lo
#     largo de la viga: NO se calcula volumen, se documenta el motivo.
#   - TYCO escudos: los 4 codigos traen el P/N real de TYCO embebido en
#     nombre_producto (ej. "567154010" = P/N 56-715-4-010 sin guiones) --
#     se verifico contra el price book real (data/fuentes/tyco_pricebook_2026-01-05.pdf)
#     y contra las fichas TFP770 (Two-Piece Recessed Escutcheons, estilos
#     10/15/20/30/40/50/70) y TFP181 (Series RFII Concealed Sprinklers,
#     ya estaba descargada de una ronda anterior) para encontrar el estilo
#     exacto de cada P/N:
#       72ESBLI012 = 56-792-4-135 = "Cover Plate" Signal White, usado con
#         varios rociadores ocultos (RFII, DS-C, DS-ECC...) -- ficha TFP181
#         trae "COVER PLATE DIAMETER DIMENSION A: 3-1/4in" y "COVER PLATE
#         PROFILE DEPTH DIMENSION B: 3/16in" EXPLICITAMENTE etiquetados
#         para el escudo (no para el rociador) -- cilindro real, confianza alta.
#       7A2T000012 = 56-715-4-010 = Style 15 Recessed Escutcheon, Signal White
#       7A10000012 = 56-715-9-010 = Style 15 Recessed Escutcheon, Chrome Plated
#       7A10000034 = 56-700-9-010 = Style 40 Recessed Escutcheon, Chrome Plated
#     TFP770 tiene diagrama con "CLOSURE" (diametro visible del escudo) y
#     la altura total del conjunto (mounting plate + closure) -- cilindro
#     real, confianza alta.
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_ronda2.py
# =========================================================================
import math

import psycopg2

from scraper_precios.config import CONEXION


IN_A_MM = 25.4


def cilindro_cm3(diametro_mm: float, alto_mm: float) -> float:
    r = diametro_mm / 2
    return round(math.pi * r * r * alto_mm / 1000, 2)


def caja_cm3(a_mm: float, b_mm: float, c_mm: float) -> float:
    return round(a_mm * b_mm * c_mm / 1000, 2)


# -------------------------------------------------------------------------
# ERICO FIG 115 -- Standard Duty Loop Hanger
# Ficha: https://www.nvent.com/en-us/caddy/products/115-standard-duty-loop-hanger-0/pdf
# (ficha tecnica real "system-generated" de nVent, tabla + diagrama)
# Formula: caja envolvente OD (ancho, diametro real del aro) x A (altura
# total real, base a tope del colllar) x RS (profundidad, sin dato
# publicado -- se usa el diametro de varilla como aproximacion
# conservadora, mismo supuesto explicito que en PHD FIG141/ERICO FIG100).
# -------------------------------------------------------------------------
FIG115 = {
    # codigo: (catalogo, pipe_size, OD_in_texto, RS_in, A_in, B_in, C_in)
    "6A10000003": ("1150300EG", '3"', "3 1/2", "3/8", "6 9/16", "3 1/2", "1 15/16"),
    "6A10000004": ("1150400EG", '4"', "4 1/2", "3/8", "7 9/16", "4", "1 15/16"),
    "6A10000006": ("1150600EG", '6"', "6 5/8", "1/2", "11 5/16", "6 5/16", "3 5/16"),
    "6A10000212": ("1150250EG", '2 1/2"', "2 7/8", "3/8", "5 15/16", "3 7/16", "2"),
}


def frac_a_mm(txt: str) -> float:
    txt = txt.strip()
    if " " in txt:
        entero, frac = txt.split(" ", 1)
        n, d = frac.split("/")
        val = int(entero) + int(n) / int(d)
    elif "/" in txt:
        n, d = txt.split("/")
        val = int(n) / int(d)
    else:
        val = float(txt)
    return round(val * IN_A_MM, 3)


def actualizar_fig115(cur):
    n = 0
    for codigo, (cat, pipe, od, rs, a, b, c) in FIG115.items():
        od_mm, rs_mm, a_mm, b_mm, c_mm = (frac_a_mm(x) for x in (od, rs, a, b, c))
        dims = (
            f'Catalog {cat} | Pipe Size: {pipe} | OD (diametro del aro): {od}" ({od_mm}mm) | '
            f'RS (varilla): {rs}" ({rs_mm}mm) | A (altura total): {a}" ({a_mm}mm) | '
            f'B (altura del aro sin collar): {b}" ({b_mm}mm) | C (altura del collar): {c}" ({c_mm}mm)'
        )
        vol = caja_cm3(od_mm, a_mm, rs_mm)
        metodo = (
            f"Caja envolvente: OD x A x RS = {od_mm} x {a_mm} x {rs_mm} mm. OD (diametro real del "
            "aro) y A (altura total real, de la ficha con diagrama de nVent) son datos confirmados; "
            "NO hay dato de profundidad/grosor de banda publicado en ninguna fuente revisada -- se usa "
            "Rod Size (RS, el diametro de la varilla) como aproximacion conservadora de esa profundidad "
            "faltante, mismo supuesto ya usado en PHD FIG141/ERICO FIG100 (calc_anillo_ganchos), pero "
            "aqui con un ancho (OD) real en vez de asumido."
        )
        confianza = "media (2 de 3 ejes reales: OD y A de ficha nVent; profundidad aproximada con Rod Size)"
        cur.execute(
            "UPDATE productos_criticos SET material=%s, acabado=%s, dimensiones_texto=%s, "
            "dimensiones_fuente=%s, volumen_cm3=%s, volumen_metodo=%s, volumen_confianza=%s "
            "WHERE codigo=%s",
            (
                "Acero (Steel)",
                "Pregalvanized (Pregalvanizado)",
                dims,
                "nvent.com/en-us/caddy/products/115-standard-duty-loop-hanger-0/pdf "
                "(ficha tecnica real, tabla+diagrama, verificada contra catalogo " + cat + ")",
                vol,
                metodo,
                confianza,
                codigo,
            ),
        )
        print(f"  {codigo}: material+dimensiones+volumen={vol}cm3 ({confianza})")
        n += 1
    return n


# -------------------------------------------------------------------------
# ERICO FIG 300 / FIG 310 -- Universal Beam Clamp
# Ficha real SI tiene diagrama (renderizado y revisado visualmente), pero
# solo publica A (ancho del cuello, una medida real) + RS (varilla) + FT
# (espesor MAXIMO de ala que acepta -- capacidad, no medida fija de la
# pieza) -- falta por completo el eje de profundidad/largo a lo largo de
# la viga. Verificado tambien contra ficha alterna
# (alldataresource.com/.../Nvent_Caddy_3000050EG_Beam_Clamp_Spec_Sheet.pdf,
# mismos 3 valores, sin dato adicional). NO se calcula volumen -- se deja
# NULL y se documenta el motivo, siguiendo la regla del proyecto (mas vale
# perder cobertura que meter un dato equivocado con un eje inventado).
# -------------------------------------------------------------------------
FIG300_310 = {
    "6D10000012": ("300", "3000050EG", "1/2", "1 1/8", '3/4" Max'),
    "6D10000038": ("300", "3000037EG", "3/8", "1 1/8", '3/4" Max'),
    "6D30000012": ("310", "3100050EG", "1/2", "1", '1 1/4" Max'),
    "6D30000038": ("310", "3100037EG", "3/8", "1", '1 1/4" Max'),
}


def actualizar_fig300_310(cur):
    n = 0
    for codigo, (fig, cat, rs, a, ft) in FIG300_310.items():
        nota = (
            f"Ficha tecnica real de nVent (fig {fig}, catalogo {cat}) revisada con diagrama renderizado "
            f"como imagen (no solo texto): publica Rod Size (RS)={rs}\", A (ancho del cuello donde entra "
            f"la varilla)={a}\", y Flange Thickness (FT)={ft} -- este ultimo es la capacidad MAXIMA de "
            "espesor de ala que acepta la mordaza, no una medida fija de la pieza. Verificado tambien "
            "contra ficha alterna del mismo fabricante (alldataresource.com), mismos 3 valores, sin dato "
            "adicional. Falta por completo el eje de altura total del cuerpo y el eje de largo a lo largo "
            "de la viga (no estan en ningun diagrama publicado) -- no se calcula volumen para no inventar "
            "un eje. Mas vale perder cobertura que meter un dato equivocado."
        )
        cur.execute(
            "SELECT dimensiones_texto FROM productos_criticos WHERE codigo=%s", (codigo,)
        )
        dims = f'Catalog {cat} | RS: {rs}" | A: {a}" | FT: {ft}'
        cur.execute(
            "UPDATE productos_criticos SET dimensiones_texto=%s, dimensiones_fuente=%s, "
            "specs_adicionales = COALESCE(specs_adicionales || ' | ', '') || %s WHERE codigo=%s",
            (
                dims,
                f"nvent.com/en-us/caddy/products/{'300-universal-beam-clamp-0' if fig=='300' else '310-universal-beam-clamp-thick-flange-0'}/pdf",
                nota,
                codigo,
            ),
        )
        print(f"  {codigo}: dimensiones parciales guardadas, SIN volumen (eje de profundidad/largo faltante)")
        n += 1
    return n


# -------------------------------------------------------------------------
# TYCO -- 4 escudos (accesorios, no rociadores)
# -------------------------------------------------------------------------
TYCO_ESCUDOS = {
    # codigo: (pn, descripcion_estilo, material, diametro_mm, alto_mm, fuente)
    "72ESBLI012": (
        "56-792-4-135",
        "Cover Plate (Signal White RAL9003) para rociadores ocultos Series RFII/DS-C/DS-ECC, "
        "150-165F según variante -- mismo P/N y forma física en todas las series que lo usan.",
        "Latón (Brass)",
        82.6,  # 3-1/4" COVER PLATE DIAMETER DIMENSION A (TFP181)
        4.8,   # 3/16" COVER PLATE PROFILE DEPTH DIMENSION B (TFP181)
        "TFP181 (Series RFII Concealed Pendent Sprinklers) pag.3, Figura 2: 'COVER PLATE DIAMETER "
        "DIMENSION A: 3-1/4 in (82,6mm)' y 'COVER PLATE PROFILE DEPTH DIMENSION B: 3/16 in (4,8mm)', "
        "etiquetas explicitas para el escudo (no el cuerpo del rociador). P/N 56-792-4-135 verificado "
        "contra data/fuentes/tyco_pricebook_2026-01-05.pdf (p.28-29, Cover Plate Signal White).",
    ),
    "7A2T000012": (
        "56-715-4-010",
        "Style 15 Recessed Escutcheon (dos piezas), Signal White RAL9003, 1/2in NPT",
        "Acero al carbono recubierto blanco (Carbon steel, white coated)",
        73.0,  # 2-7/8" CLOSURE DIA (TFP770 fig.2 style 15)
        25.4,  # 1" altura total (TFP770 fig.2 style 15)
        "TFP770 (Two-Piece Recessed Escutcheons) pag.2, Figura 2 Style 15: CLOSURE 2-7/8in DIA "
        "(73,0mm), altura total 1in (25,4mm). P/N 56-715-4-010 verificado en pag.4 de la misma ficha "
        "(Style 15, Signal White).",
    ),
    "7A10000012": (
        "56-715-9-010",
        "Style 15 Recessed Escutcheon (dos piezas), Chrome Plated, 1/2in NPT",
        "Acero al carbono cromado (Carbon steel, chrome plated)",
        73.0,
        25.4,
        "TFP770 pag.2, Figura 2 Style 15: CLOSURE 2-7/8in DIA (73,0mm), altura total 1in (25,4mm). "
        "P/N 56-715-9-010 verificado en pag.4 (Style 15, Chrome plated).",
    ),
    "7A10000034": (
        "56-700-9-010",
        "Style 40 Recessed Escutcheon (dos piezas), Chrome Plated, 3/4in NPT",
        "Acero al carbono cromado (Carbon steel, chrome plated)",
        73.0,  # 2-7/8" CLOSURE DIA (TFP770 fig.5 style 40)
        28.6,  # 1-1/8" altura total (TFP770 fig.5 style 40)
        "TFP770 pag.2, Figura 5 Style 40: CLOSURE 2-7/8in DIA (73,0mm), altura total 1-1/8in "
        "(28,6mm). P/N 56-700-9-010 verificado en pag.4 (Style 40, Chrome Plated).",
    ),
}


def actualizar_tyco(cur):
    n = 0
    for codigo, (pn, desc_estilo, material, diam, alto, fuente) in TYCO_ESCUDOS.items():
        vol = cilindro_cm3(diam, alto)
        dims = f"P/N {pn} | {desc_estilo} | Diametro: {diam}mm | Espesor/profundidad: {alto}mm"
        metodo = (
            f"Cilindro real: pi x r^2 x h, diametro={diam}mm, altura={alto}mm -- ambas medidas "
            "etiquetadas explicitamente en el diagrama de la ficha TFP real (diametro del escudo "
            "visible + espesor/profundidad total del ensamble), no un supuesto."
        )
        cur.execute(
            "UPDATE productos_criticos SET material=%s, dimensiones_texto=%s, dimensiones_fuente=%s, "
            "volumen_cm3=%s, volumen_metodo=%s, volumen_confianza=%s WHERE codigo=%s",
            (material, dims, fuente, vol, metodo, "alta (diametro y profundidad reales, etiquetados en diagrama de ficha TFP)", codigo),
        )
        print(f"  {codigo}: material+dimensiones+volumen={vol}cm3 (alta)")
        n += 1
    return n


def main():
    conexion = psycopg2.connect(**CONEXION)
    with conexion, conexion.cursor() as cur:
        print("ERICO FIG 115 (loop hanger):")
        n1 = actualizar_fig115(cur)
        print("\nERICO FIG 300/310 (beam clamp) -- solo dimensiones parciales, sin volumen:")
        n2 = actualizar_fig300_310(cur)
        print("\nTYCO escudos:")
        n3 = actualizar_tyco(cur)
    conexion.close()
    print(f"\nTotal actualizados: {n1 + n2 + n3} (con volumen: {n1 + n3}/12, sin volumen documentado: {n2}/12)")


if __name__ == "__main__":
    main()
