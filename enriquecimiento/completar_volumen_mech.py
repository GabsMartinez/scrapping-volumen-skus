# =========================================================================
# completar_volumen_mech.py - segunda pasada de volumen para los 105
# códigos MECH (fu-mech.com + meide.mx), aplicando el método validado en
# TYCO: renderizar cada PDF/página como imagen y leer las tablas de
# medidas pegadas a los diagramas técnicos (no solo texto plano).
#
# HALLAZGO CLAVE de esta ronda: fu-mech.com SÍ publica fichas técnicas PDF
# reales descargables (botón "Click Here To Download" en cada página de
# producto) que la primera ronda nunca siguió -- el print-to-pdf de la
# página solo capturaba un ícono roto donde iba ese botón. Se descargaron
# ~17 PDFs reales nuevos a data/capturas_fuentes/fu-mech.com/ficha_real_*.pdf
# (ver data/capturas_fuentes/manifiesto.csv). Además se encontraron y
# corrigieron varios casos donde el matcher original había linkeado el
# código a la página del modelo con sufijo "X"/"NX" (rango de tallas
# grandes) cuando el código real (sin sufijo en el campo `modelo`)
# correspondía a la página SIN sufijo (rango de tallas chicas) -- ver
# notas por familia abajo.
#
# Cada FAMILIA:
#   - fuente: (dominio, url, dimensiones_fuente_texto)
#   - material: string o None (solo se aplica si productos_criticos.material
#     está vacío)
#   - tabla: { talla_codigo: tupla de medidas en mm (según lo que espere calc) }
#   - codigos: { codigo_interno: talla_codigo }
#   - calc: función(talla, medidas) -> (volumen_cm3, metodo_texto, confianza_texto)
#
# Uso:
#   docker compose exec scraper python enriquecimiento/completar_volumen_mech.py [--familia <clave>]
#   docker compose exec scraper python enriquecimiento/completar_volumen_mech.py --listar
# =========================================================================
import argparse
import math

import psycopg2

from scraper_precios.config import CONEXION


def caja(*medidas_mm):
    v = 1.0
    for m in medidas_mm:
        v *= m
    return round(v / 1000, 2)


def cilindro(diametro_mm, largo_mm):
    r = diametro_mm / 2
    return round(math.pi * r * r * largo_mm / 1000, 2)


# Tabla de referencia O.D. de tubería (ASME B1.20.1 / ANSI, publicada en la
# MISMA ficha "Malleable Iron Pipe Fitting" pág. 33 -- no es un dato externo
# inventado, es la tabla "Basic Dimension for American Standard Pipe
# Threads" de la propia ficha) -- se usa como proxy del diámetro del cuerpo
# de los accesorios roscados BMI cuando la ficha no publica un ancho/OD de
# cuerpo aparte.
OD_TUBERIA_MM = {
    "1/8": 10.29, "1/4": 13.72, "3/8": 17.15, "1/2": 21.34, "3/4": 26.67,
    "1": 33.40, "1-1/4": 42.16, "1-1/2": 48.26, "2": 60.33, "2-1/2": 73.03,
    "3": 88.90,
}


# =========================================================================
# meide.mx - Support hanger / Ring hanger, modelo GSD9 (gancho tipo pera)
# =========================================================================
FAM_GSD9 = {
    "fuente": ("meide.mx",
        "https://www.meide.mx/wp-content/uploads/2026/05/Support-hanger-Ring-hanger-Pera.pdf",
        "Ficha PDF real 'Support hanger - Ring hanger' (Jinan Meide Casting Co.), "
        "sección '2. Size', modelo GSD9, tabla por talla A/B/C/D (mm) y Nut size."),
    "material": None,
    "tabla": {
        "1": (84.44, '3/8"-16UNC', 9.525), "1-1/4": (93.54, '3/8"-16UNC', 9.525),
        "1-1/2": (98.89, '3/8"-16UNC', 9.525), "2": (110.59, '3/8"-16UNC', 9.525),
        "2-1/2": (147.55, '3/8"-16UNC', 9.525), "3": (162.74, '3/8"-16UNC', 9.525),
        "4": (188.34, '3/8"-16UNC', 9.525),
    },
    "codigos": {
        "6A2SPMECH1": "1", "6A2SPME114": "1-1/4", "6A2SPME112": "1-1/2",
        "6A2SPMECH2": "2", "6A2SPME212": "2-1/2", "6A2SPMECH3": "3", "6A2SPMECH4": "4",
    },
}


def calc_gsd9(talla, m):
    d, nut_txt, rod = m
    v = caja(d, d, rod)
    metodo = (f"Caja envolvente aproximada (mismo método que PHD FIG141/ERICO FIG100 en "
              f"completar_volumen.py): D×D×RodSize = {d}×{d}×{rod} mm. D=altura total del aro "
              f"(tabla '2. Size' ficha GSD9), usada también como ancho por ser aro redondo. "
              f"Sin vista lateral con la profundidad real de la banda -- se aproxima con el "
              f"diámetro de la varilla/tuerca de sujeción ({nut_txt}={rod}mm). Supuesto explícito.")
    return v, metodo, "baja (falta eje de profundidad, aproximado con diámetro de varilla, igual que PHD/ERICO)"


# =========================================================================
# meide.mx - Malleable Iron Wide-Mouth Top Beam Clamp, Type 3034
# =========================================================================
FAM_3034 = {
    "fuente": ("meide.mx",
        "https://www.meide.mx/wp-content/uploads/2026/05/DS-1A7-3034-01-E-Mordaza.pdf",
        "Ficha PDF real 'Malleable Iron Wide-Mouth Top Beam Clamp' Type 3034, doc "
        "DS-1A7-3034-01-E, sección '3.0 Dimensions', tabla '3034 10' A/B1/B2/C/D (mm)."),
    "material": None,
    "tabla": {"10": (40.0, 49.0, 21.0)},
    "codigos": {"6D4BCMEC38": "10"},
}


def calc_3034(talla, m):
    a, b1, d = m
    v = caja(a, b1, d)
    metodo = (f"Caja envolvente real: A×B1×D = {a}×{b1}×{d} mm (frontal: A=ancho base, "
              "B1=altura total; lateral: D=profundidad). 3 medidas de dibujo técnico de 2 vistas.")
    return v, metodo, "media-alta (3 ejes reales de un dibujo técnico de 2 vistas: frontal + lateral)"


# =========================================================================
# fu-mech.com - Grooved Rigid Coupling 1G / 1GS (ficha_real_rigid-coupling-model-1g.pdf)
# tabla A/B/C (mm) por talla nominal + Pipe O.D., certificado UL/FM.
# Caja envolvente con 3 ejes reales (A=OD menor del cuerpo, B=ancho máx.
# sobre tornillos, C=largo end-to-end) -- sin ningún supuesto adicional.
# =========================================================================
FAM_1G = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/Rigid-Coupling1G.pdf",
        "Ficha PDF real descargada del botón 'Click Here To Download' en "
        "fu-mech.com/product/mech-grooved-rigid-coupling-model-1g/ (no capturada en la "
        "ronda anterior). Tablas '1G' y '1GS', columnas Nominal Size/Pipe O.D./"
        "Dimensions A,B,C/Bolt Size, certificado UL FM."),
    "material": None,
    # talla -> (A, B, C) mm
    "tabla": {
        "1": (59, 100, 44), "1-1/4": (66, 105, 45), "1-1/2": (72, 112, 45),
        "2": (85, 130, 45), "2-1/2": (98, 140, 52),
        "3": (114, 160, 45), "4": (140, 187, 50), "6": (200, 255, 50),
        "8": (255, 322, 58), "10": (318, 410, 63),
    },
    "codigos": {
        "3A10000001": "1", "3A10000114": "1-1/4", "3A10000112": "1-1/2",
        "3A10000002": "2", "3A10000212": "2-1/2",
        "3A10000003": "3", "3A10000004": "4", "3A10000006": "6",
        "3A10000008": "8", "3A10000010": "10",
    },
}


def calc_abc(talla, m):
    a, b, c = m
    v = caja(a, b, c)
    metodo = f"Caja envolvente real: A×B×C = {a}×{b}×{c} mm, tabla oficial UL/FM por talla nominal."
    return v, metodo, "alta (3 ejes reales de tabla oficial del fabricante, sin supuestos)"


# =========================================================================
# fu-mech.com - Mechanical Tee Grooved Outlet, modelo 3G (saddle/clamp)
# =========================================================================
FAM_3G = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/Mechanical-Tee.pdf",
        "Ficha PDF real (botón Download) fu-mech.com/product/mech-grooved-mech-tee-grvd-model-3g/. "
        "Tabla '3G', columnas Nominal Size/Pipe O.D./Hole Dia/Dimensions A,B,C,D/Bolt Size."),
    "material": None,
    # talla "run x branch" -> (A, B, C) mm
    "tabla": {
        "2x1-1/4": (116, 76, 69.5), "2x1-1/2": (116, 76, 69.5),
        "2-1/2x1-1/4": (144, 84.5, 75), "2-1/2x1-1/2": (144, 84.5, 73),
        "3x1-1/4": (152, 85.5, 84.5), "3x1-1/2": (152, 85.5, 84.5),
        "4x1-1/2": (188, 89, 102), "4x2-1/2": (188, 104.5, 102),
        "6x2-1/2": (247, 115, 134),
    },
    "codigos": {
        "3B31002114": "2x1-1/4", "3B31002112": "2x1-1/2",
        "3B31212114": "2-1/2x1-1/4", "3B31212112": "2-1/2x1-1/2",
        "3B31003114": "3x1-1/4", "3B31003112": "3x1-1/2",
        "3B31004112": "4x1-1/2", "3B31004212": "4x2-1/2",
        "3B31006212": "6x2-1/2",
    },
}

# =========================================================================
# fu-mech.com - Mechanical Tee Threaded Outlet, modelo 3J (saddle/clamp)
#
# RONDA "revisión MECH thumbnails" (2026-08-10): 3B32004212 (4x2-1/2) SÍ
# tiene fila real -- estaba mal diagnosticado como "falta en la tabla".
# La página impresa (mediabox 665.6pt de ancho) corta la tabla en la fila
# "100x32", pero el PDF descargado es en realidad el recorte de UNA página
# de un catálogo más ancho (spread a 2 páginas) y el contenido de texto de
# la página SIGUIENTE del catálogo (que continúa la MISMA tabla 3J hasta
# 150x65) quedó embebido en el mismo stream de texto, solo que posicionado
# fuera del mediabox visible (coordenadas x>665.6pt, invisible al imprimir
# o renderizar la página normalmente). Se extrajo con
# pdfplumber.extract_words() filtrando por x0>665.622 y agrupando por
# 'top' -- fila encontrada limpia, sin superposición de texto (verificado
# palabra por palabra, sin caracteres intercalados de otra fila): Nominal
# "100×65", Pipe O.D. "114.3×73.0" (coincide exacto con el código interno
# "P3JS 114X73"), Working Pressure 300psi/2.07MPa, Dimensions A=188 B=104.5
# C=102 D=70mm, Bolt 1/2×75, Certificado UL FM -- y la fila en pulgadas
# inmediatamente debajo confirma "4×2½ / 4.500×2.875" sin ambigüedad.
# =========================================================================
FAM_3J = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/Mechanical-Tee3JThreaded-Outlet.pdf",
        "Ficha PDF real (botón Download) fu-mech.com/product/mech-grooved-mech-tee-thd-model-3j/. "
        "Tabla '3J', columnas Nominal Size/Pipe O.D./Hole Dia/Dimensions A,B,C,D/Bolt Size. Fila "
        "100x65 (4x2-1/2) recuperada de texto embebido fuera del área visible de la página "
        "(continuación de la misma tabla en la página siguiente del catálogo original) -- ver "
        "nota de la ronda 'revisión MECH thumbnails' 2026-08-10."),
    "material": None,
    "tabla": {
        "2x1": (116, 68, 60), "3x1": (152, 72.5, 80), "2-1/2x1": (144, 71, 75),
        "3x1-1/2": (152, 85.5, 80), "2-1/2x3/4": (144, 71, 75), "2-1/2x1-1/2": (144, 84.5, 73),
        "4x2-1/2": (188, 104.5, 102),
    },
    "codigos": {
        "3B32000021": "2x1", "3B32000031": "3x1", "3B32002121": "2-1/2x1",
        "3B32003112": "3x1-1/2", "3B32021234": "2-1/2x3/4", "3B32212112": "2-1/2x1-1/2",
        "3B32004212": "4x2-1/2",
    },
}

# =========================================================================
# fu-mech.com - Grooved Elbow 45, modelo 120 (NO 120X -- ver nota abajo)
# CORRECCIÓN DE MAPEO: el matcher original había vinculado estos 6 códigos
# a la página "elbow-45-model-120x" (rango 3"-10"), pero el campo `modelo`
# de la BD dice "P120 <od>" (SIN sufijo X) y las tallas reales (1-1/4" a
# 4") caen fuera del rango de 120X (3"-10") -- la ficha correcta es la
# página/PDF "MECH GROOVED ElBOW 45-MODEL 120" (SIN X, rango 1"-12").
# Solo axisimétrico en un eje (L, center-to-end); se usa caja envolvente
# L×L×D (D=Pipe O.D. de la misma tabla) igual que el patrón BMI-elbow.
# =========================================================================
FAM_120 = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/%D9%83%D9%88%D8%B9-45.pdf",
        "Ficha PDF real (botón Download) en fu-mech.com/product/mech-grooved-elbow-45-model-120/ "
        "(SIN sufijo X -- corrección de mapeo, ver nota en el código). Tabla '120', columnas "
        "Nominal Size/Pipe O.D./Dimensions L."),
    "material": None,
    # talla -> (L, D) mm
    "tabla": {
        "1-1/4": (44.5, 42.4), "1-1/2": (44.5, 48.3), "2": (51, 60.3),
        "2-1/2": (57, 73.0), "3": (63.5, 88.9), "4": (76, 114.3),
    },
    "codigos": {
        "3C10000114": "1-1/4", "3C10000112": "1-1/2", "3C10000002": "2",
        "3C10000212": "2-1/2", "3C10000003": "3", "3C10000004": "4",
    },
}


def calc_l_d_codo(talla, m):
    l, d = m
    v = caja(l, l, d)
    metodo = (f"Caja envolvente: L×L×D = {l}×{l}×{d} mm. L=dimensión 'center-to-end' publicada "
              "(única, ambos tramos del codo se asumen iguales por ser simétrico); D=Pipe O.D. "
              "de la misma tabla, usado como proxy del diámetro del cuerpo del accesorio.")
    return v, metodo, "media (L real de tabla oficial + O.D. de tubería como proxy de profundidad)"


def calc_l_l_d_tee(talla, m):
    l, d = m
    v = caja(l, l, d)
    metodo = (f"Caja envolvente: L×L×D = {l}×{l}×{d} mm. L=dimensión end-to-end publicada "
              "(se usa también para el alcance de la rama, por falta de una segunda medida "
              "real); D=Pipe O.D. de la misma tabla, proxy del diámetro del cuerpo.")
    return v, metodo, "media (L real de tabla oficial + O.D. de tubería como proxy de profundidad/rama)"


# =========================================================================
# fu-mech.com - Grooved Tee, modelo 130 / 130S (NO 130X)
# CORRECCIÓN DE MAPEO igual que 120: el modelo real es "P130"/"P130S" (sin
# X), rango de tallas 1"-16" para 130 y 2"-8" para 130S -- la página
# correcta es "MECH GROOVED TEE -MODEL 130"/"130S", no "130X".
# =========================================================================
FAM_130 = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/tee-130tee130s.pdf",
        "Ficha PDF real (botón Download) en fu-mech.com/product/mech-grooved-tee-model-130/ y "
        "…-130s/ (SIN sufijo X -- corrección de mapeo). Tablas '130' y '130S', columnas "
        "Nominal Size/Pipe O.D./Dimensions L."),
    "material": None,
    "tabla": {
        "1-1/4": (70, 42.4), "1-1/2": (70, 48.3), "2": (70, 60.3),
        "2-1/2": (76, 73.0), "3": (85.5, 88.9), "4": (101, 114.3),
    },
    "codigos": {
        "3B10000114": "1-1/4", "3B10000112": "1-1/2", "3B10000002": "2",
        "3B10000212": "2-1/2", "3B10000003": "3", "3B10000004": "4",
    },
}

# =========================================================================
# fu-mech.com - MECH BMI Threaded Fittings (Malleable Iron, American
# Standard Class 150) -- catálogo único con TODAS las familias BMI, cada
# ficha_real_*.pdf descargada es la MISMA brochure completa (solo cambia
# qué producto viene circulado en el índice). Usa la tabla de O.D. de
# tubería (pág. 33 del mismo documento) como proxy del diámetro del cuerpo.
# =========================================================================
FUENTE_BMI = ("fu-mech.com",
    "https://fu-mech.com/wp-content/uploads/2023/01/MECH-BMI-ELBOW-90-MODEL-90.pdf",
    "Ficha PDF real 'Malleable Iron Pipe Fitting American Standard' (catálogo completo BMI, "
    "botón Download de varias páginas de fu-mech.com/product/american-standard-mech-bmi-*), "
    "tablas por modelo (90, 90R, 130, 220, 240, 241, 291) con dimensión 'A'/'B' (mm) por talla "
    "+ tabla pág. 33 'Basic Dimension for American Standard Pipe Threads' (O.D. of Pipe) "
    "usada como proxy del diámetro del cuerpo del accesorio.")

FAM_BMI_90 = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {"1": 38.1, "1-1/2": 49.3},  # talla -> A (mm)
    "codigos": {"3C2AC00001": "1", "3C2AC00112": "1-1/2"},
}


def calc_bmi_elbow90(talla, a):
    d = OD_TUBERIA_MM[talla]
    v = caja(a, a, d)
    metodo = (f"Caja envolvente: A×A×D = {a}×{a}×{d} mm. A=dimensión 'center-to-end' del "
              "modelo 90 (BMI, tabla oficial ASME B16.3/B16.14), D=O.D. de tubería (pág. 33 "
              "de la misma ficha) como proxy del diámetro del cuerpo.")
    return v, metodo, "media (A real de catálogo oficial + O.D. de tubería del mismo documento como proxy de profundidad)"


FAM_BMI_90R = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {"1x1/2": (32, 35.5, "1")},  # talla -> (A, B, talla_mayor_para_D)
    "codigos": {"3C2ACR0112": "1x1/2"},
}


def calc_bmi_elbow90r(talla, m):
    a, b, talla_mayor = m
    d = OD_TUBERIA_MM[talla_mayor]
    v = caja(a, b, d)
    metodo = (f"Caja envolvente: A×B×D = {a}×{b}×{d} mm. A y B son los 2 tramos (distintos, "
              "por ser codo reductor) de la tabla oficial modelo 90R; D=O.D. de tubería del "
              "lado mayor ({talla_mayor}\") como proxy del diámetro del cuerpo.")
    return v, metodo, "media (A y B reales de catálogo oficial + O.D. de tubería como proxy de profundidad)"


FAM_BMI_130 = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {"1": 38.1},
    "codigos": {"3B1AC00001": "1"},
}


def calc_bmi_tee130(talla, a):
    d = OD_TUBERIA_MM[talla]
    v = caja(2 * a, a, d)
    metodo = (f"Caja envolvente: (2×A)×A×D = {2*a}×{a}×{d} mm. A=dimensión 'center-to-end' "
              "del modelo 130 (BMI, misma tabla que el codo 90 -- estandarizado por ASME "
              "B16.3). Se usa 2×A para el largo del ramal recto (se extiende A a cada lado del "
              "centro) y A para el alcance de la salida lateral; D=O.D. de tubería como proxy "
              "del diámetro del cuerpo.")
    return v, metodo, "media (A real de catálogo oficial + O.D. de tubería como proxy de profundidad)"


FAM_BMI_291 = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {"1/2": 23.9, "3/4": 27.2, "1": 31.8},
    "codigos": {"3D2AC00012": "1/2", "3D2AC00034": "3/4", "3D2AC00001": "1"},
}


def calc_bmi_plug(talla, a):
    d = OD_TUBERIA_MM[talla]
    v = cilindro(d, a)
    metodo = (f"Cilindro real: π×(D/2)²×A = π×({d}/2)²×{a} mm. Pieza genuinamente axisimétrica "
              "(tapón macho roscado, modelo 291/291S -- mismos valores de A en ambas variantes "
              "para esta talla). D=O.D. de tubería (proxy del cuerpo roscado; subestima "
              "levemente porque no incluye la cabeza hex/cuadrada de maniobra, más ancha que "
              "el diámetro de rosca). A=longitud total de tabla oficial.")
    return v, metodo, "media (axisimétrico, D aproximado con O.D. de tubería -- subestima la cabeza de maniobra)"


FAM_BMI_241 = {
    "fuente": FUENTE_BMI, "material": None,
    # talla_menor x talla_mayor -> (A, talla_mayor)
    "tabla": {
        "1x1/2": (25.5, "1"), "1x3/4": (25.5, "1"), "1-1/4x1": (27.4, "1-1/4"),
    },
    "codigos": {
        "3FAC000112": "1x1/2", "3FAC000134": "1x3/4", "3FAC001141": "1-1/4x1",
    },
}


def calc_bmi_bushing(talla, m):
    a, talla_mayor = m
    d = OD_TUBERIA_MM[talla_mayor]
    v = cilindro(d, a)
    metodo = (f"Cilindro real: π×(D/2)²×A = π×({d}/2)²×{a} mm. Bushing reductor (modelo 241, "
              f"exterior roscado talla {talla_mayor}\"), tratado como axisimétrico usando el "
              "O.D. de tubería del lado MAYOR (roscado exterior) como diámetro y A=altura de "
              "tabla oficial. Subestima porque el exterior real es hexagonal (ancho entre "
              "caras > O.D. de tubería), no se publica esa medida.")
    return v, metodo, "media (axisimétrico aproximado, subestima por exterior hexagonal no publicado)"


FAM_BMI_240 = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {
        "1x1/2": (42.9, "1"), "1x3/4": (42.9, "1"), "1-1/4x1": (52.3, "1-1/4"),
    },
    "codigos": {
        "3E12AC0112": "1x1/2", "3E12AC0134": "1x3/4", "3E12AC1141": "1-1/4x1",
    },
}
# calc_bmi_bushing sirve igual para 240 (reducing coupling/socket) -- mismo patrón A + D lado mayor.

FAM_BMI_220 = {
    "fuente": FUENTE_BMI, "material": None,
    "tabla": {"1": (42.4, "1")},
    "codigos": {"3A1AC00001": "1"},
}
# calc_bmi_bushing también sirve para el coupling 220 (single-size, axisimétrico).

FAM_HOSE = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/03/01-Mech-Flexible-Hose-NEW-V8.pdf",
        "Ficha PDF real (botón Download) fu-mech.com/product/mech-stainless-steel-flexible-hose-"
        "for-sprinkler-connection/, pág. 9, 'Style: MDFB - Braided Hose with Straight Nipple', "
        "tabla cULus/FM: Hose Length 1200mm (48\"), 1/2\" thread, Hose Diameter O.D. 26.8mm."),
    "material": None,
    "tabla": {"1/2x48": (26.8, 1200)},  # (OD, largo) mm
    "codigos": {"1B1MFRM012": "1/2x48"},
}


def calc_hose(talla, m):
    od, largo = m
    v = cilindro(od, largo)
    metodo = (f"Cilindro real: π×(D/2)²×L = π×({od}/2)²×{largo} mm. Manguera flexible trenzada, "
              "genuinamente axisimétrica. Largo (1200mm=48\") y O.D. (26.8mm) coinciden "
              "exactamente con el nombre del producto (1/2\" X 48\") y la tabla oficial estilo "
              "MDFB (braided) de la ficha real. No incluye las boquillas/niples de conexión en "
              "los extremos (volumen adicional menor).")
    return v, metodo, "alta (medida exacta que coincide con el nombre del producto, tabla oficial del fabricante)"


# =========================================================================
# fu-mech.com - Flexible Coupling 1N (NO reductor -- modelo hermano del
# "Reducing Flexible Coupling 1N" ya usado en la ronda P1N, mismo número de
# modelo "1N" pero tabla DISTINTA: una talla nominal por fila en vez de un
# par talla_mayorxtalla_menor). Encontrada en la ronda "revisión MECH
# thumbnails" (2026-08-10) como texto embebido fuera del área visible del
# MISMO PDF ya descargado para el acople reductor (ficha_real_red-coupling
# -model-1n.pdf) -- confirma que el catálogo original tiene AMBAS tablas
# ("1N Flexible Coupling" no reductora Y "Reducing Flexible Coupling 1N")
# en páginas contiguas que quedaron fusionadas en el mismo stream de texto
# al recortar la página para el botón de descarga del sitio.
#
# HALLAZGO IMPORTANTE PARA REVISAR CON EL USUARIO: el patrón de nombre
# interno de LOS 7 códigos "P1N <numero>" (incluidos los 5 ya resueltos en
# la ronda P1N con el supuesto "reducción un paso hacia abajo") es
# IDÉNTICO al de esta tabla no-reductora (numero = O.D. de tubería de una
# SOLA talla, ej. "P1N 42"=OD 42.4mm=1-1/4"), lo que sugiere que los 5 ya
# cargados (3A20000002, 3A20000003, 3A20000004, 3A20000212 con confianza
# "baja", y posiblemente 3A20000006/1NS) podrían pertenecer en realidad a
# ESTA tabla no reductora en vez de a la reductora -- NO se tocan en esta
# ronda (fuera del alcance de los 32 códigos asignados) pero se deja
# documentado aquí para que el usuario decida si se re-abre esa parte.
#
# Solo se pudo leer con certeza la fila de 32mm/1-1/4" (texto limpio, sin
# superposición) -- la fila de 40mm/1-1/2" (necesaria para 3A20000112)
# aparece con caracteres de dos filas distintas intercalados en las mismas
# coordenadas (superposición real de dos páginas del catálogo original) y
# no se pudo leer con certeza suficiente; se deja sin volumen.
# =========================================================================
FAM_1N_FLEX_NOREDUCTOR = {
    "fuente": ("fu-mech.com",
        "https://fu-mech.com/wp-content/uploads/2023/01/Reducing-Flexible-Coupling1N-2.pdf",
        "Texto embebido fuera del área visible (x0<0, fuera del mediabox de 665.6pt) del mismo "
        "PDF 'ficha_real_red-coupling-model-1n.pdf' ya usado para el acople reductor -- tabla "
        "'1N Flexible Coupling' (NO reductora), columnas Nominal Size/Pipe O.D./Working Pressure/"
        "Dimensions A,B,C/Bolt Size. Fila 32mm/1-1/4' verificada limpia (sin superposición de "
        "texto de otra fila)."),
    "material": None,
    "tabla": {"1-1/4": (65, 104, 44)},  # talla -> (A, B, C) mm
    "codigos": {"3A20000114": "1-1/4"},
}


FAMILIAS = {
    "gsd9_pera": (FAM_GSD9, calc_gsd9),
    "beam_clamp_3034": (FAM_3034, calc_3034),
    "rigid_coupling_1g": (FAM_1G, calc_abc),
    "mech_tee_3g": (FAM_3G, calc_abc),
    "mech_tee_3j": (FAM_3J, calc_abc),
    "elbow_45_120": (FAM_120, calc_l_d_codo),
    "tee_130": (FAM_130, calc_l_l_d_tee),
    "bmi_elbow_90": (FAM_BMI_90, calc_bmi_elbow90),
    "bmi_elbow_90r": (FAM_BMI_90R, calc_bmi_elbow90r),
    "bmi_tee_130": (FAM_BMI_130, calc_bmi_tee130),
    "bmi_plug_291": (FAM_BMI_291, calc_bmi_plug),
    "bmi_red_bush_241": (FAM_BMI_241, calc_bmi_bushing),
    "bmi_red_socket_240": (FAM_BMI_240, calc_bmi_bushing),
    "bmi_sockets_220": (FAM_BMI_220, calc_bmi_bushing),
    "flexible_hose": (FAM_HOSE, calc_hose),
    "1n_flex_noreductor": (FAM_1N_FLEX_NOREDUCTOR, calc_abc),
}


def procesar_familia(cur, clave, fam, calc_fn):
    dominio, url, fuente_txt = fam["fuente"]
    n = 0
    for codigo, talla in fam["codigos"].items():
        medidas = fam["tabla"][talla]
        volumen_cm3, metodo, confianza = calc_fn(talla, medidas)
        dim_texto = f"Talla {talla}: medidas {medidas} mm (ver volumen_metodo)"

        cur.execute("SELECT material FROM productos_criticos WHERE codigo=%s", (codigo,))
        row = cur.fetchone()
        if row is None:
            print(f"  [{clave}] {codigo}: NO existe en productos_criticos, se omite.")
            continue
        material_actual = row[0]

        sets = ["dimensiones_texto=%s", "dimensiones_fuente=%s", "volumen_cm3=%s",
                "volumen_metodo=%s", "volumen_confianza=%s"]
        params = [dim_texto, fuente_txt, volumen_cm3, metodo, confianza]

        if fam.get("material") and not material_actual:
            sets.append("material=%s")
            params.append(fam["material"])

        params.append(codigo)
        cur.execute(f"UPDATE productos_criticos SET {', '.join(sets)} WHERE codigo=%s", params)
        print(f"  [{clave}] {codigo} (talla {talla}): {volumen_cm3} cm3 ({confianza})")
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--familia", default=None)
    ap.add_argument("--listar", action="store_true")
    args = ap.parse_args()

    if args.listar:
        for k in FAMILIAS:
            print(k)
        return

    conexion = psycopg2.connect(**CONEXION)
    total = 0
    with conexion, conexion.cursor() as cur:
        claves = [args.familia] if args.familia else list(FAMILIAS.keys())
        for clave in claves:
            if clave not in FAMILIAS:
                print(f"Familia desconocida: {clave}")
                continue
            fam, calc_fn = FAMILIAS[clave]
            total += procesar_familia(cur, clave, fam, calc_fn)
    conexion.close()
    print(f"\n{total} códigos actualizados.")


if __name__ == "__main__":
    main()
