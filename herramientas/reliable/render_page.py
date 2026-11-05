import pdfplumber
import sys

from scraper_precios.config import BOLETINES_RELIABLE, EXPLORACION

fname = sys.argv[1]
page_num = int(sys.argv[2])
out = sys.argv[3]

with pdfplumber.open(BOLETINES_RELIABLE / fname) as pdf:
    im = pdf.pages[page_num].to_image(resolution=200)
    im.save(EXPLORACION / "imagenes" / out)
    print("saved", out)
