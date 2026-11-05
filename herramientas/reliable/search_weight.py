import pdfplumber
import os

from scraper_precios.config import BOLETINES_RELIABLE

files = sorted(f for f in os.listdir(BOLETINES_RELIABLE) if f.endswith('.pdf'))
for fname in files:
    path = BOLETINES_RELIABLE / fname
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            for kw in ["Weight", "weight", "WEIGHT", " lb", "lbs", " kg", "Kg", "oz."]:
                if kw in text:
                    # print context
                    idx = text.find(kw)
                    ctx = text[max(0,idx-80):idx+80].replace("\n"," | ")
                    print(f"{fname} p{i} [{kw}]: ...{ctx}...")
