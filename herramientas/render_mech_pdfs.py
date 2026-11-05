# =========================================================================
# render_mech_pdfs.py - renderiza cada PDF de data/capturas_fuentes/fu-mech.com
# y data/capturas_fuentes/meide.mx a PNG (una imagen por página) para poder
# revisar visualmente si hay tablas de medidas/peso pegadas a un diagrama
# que el texto plano no captura. Salida: data/capturas_fuentes/_render/<archivo>_pNN.png
#
# Uso:
#   docker compose exec scraper python herramientas/render_mech_pdfs.py [filtro_substring]
# =========================================================================
import os
import sys

import pdfplumber

from scraper_precios.config import CAPTURAS_FUENTES

CARPETA_BASE = str(CAPTURAS_FUENTES)
CARPETA_SALIDA = str(CAPTURAS_FUENTES / "_render")
RESOLUCION = 200  # dpi


def render_pdf(ruta_pdf, prefijo):
    with pdfplumber.open(ruta_pdf) as pdf:
        for i, pagina in enumerate(pdf.pages, 1):
            img = pagina.to_image(resolution=RESOLUCION)
            nombre = f"{prefijo}_p{i:02d}.png"
            ruta_salida = os.path.join(CARPETA_SALIDA, nombre)
            img.save(ruta_salida)
            print(f"    -> {nombre} ({pagina.width:.0f}x{pagina.height:.0f}pt)")


def main():
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    os.makedirs(CARPETA_SALIDA, exist_ok=True)
    for dominio in ("fu-mech.com", "meide.mx"):
        carpeta = os.path.join(CARPETA_BASE, dominio)
        for archivo in sorted(os.listdir(carpeta)):
            if not archivo.lower().endswith(".pdf"):
                continue
            if filtro and filtro not in archivo:
                continue
            ruta_pdf = os.path.join(carpeta, archivo)
            prefijo = archivo[:-4]
            print(f"{dominio}/{archivo}")
            try:
                render_pdf(ruta_pdf, prefijo)
            except Exception as e:
                print(f"  ERROR: {e}")


if __name__ == "__main__":
    main()
