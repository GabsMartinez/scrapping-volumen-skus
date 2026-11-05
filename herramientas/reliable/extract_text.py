import pdfplumber
import sys

from scraper_precios.config import BOLETINES_RELIABLE

fname = sys.argv[1]
path = BOLETINES_RELIABLE / fname

with pdfplumber.open(path) as pdf:
    print(f"=== {fname} === {len(pdf.pages)} pages")
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        print(f"--- page {i} ---")
        print(text)
        print()
