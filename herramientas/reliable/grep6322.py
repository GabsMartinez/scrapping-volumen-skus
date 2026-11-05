import os

import pdfplumber

from scraper_precios.config import BOLETINES_RELIABLE

files = sorted(f for f in os.listdir(BOLETINES_RELIABLE) if f.endswith('.pdf'))
for fname in files:
    path = BOLETINES_RELIABLE / fname
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if "6322" in text or "RA63" in text or "RA73" in text or "F1FR80" in text:
                idx = text.find("F1FR80")
                print(fname, i, "F1FR80 ctx:", text[max(0,idx-60):idx+60].replace("\n"," | ") if idx>=0 else "")
                for kw in ["6322","RA63","RA73"]:
                    if kw in text:
                        idx2 = text.find(kw)
                        print("   ", kw, text[max(0,idx2-60):idx2+60].replace("\n"," | "))
