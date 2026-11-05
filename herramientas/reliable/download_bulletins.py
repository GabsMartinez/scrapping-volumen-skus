import urllib.request
import os

from scraper_precios.config import BOLETINES_RELIABLE

bulletins = {
    "203": "cover-plates",
    "204": "escutcheons",
    "071": "f1-56-series-standard-response",
    "074": "f1fr56-series-quick-response",
    "078": "f1fr80-300-series-quick-response",
    "132": "gl112-sprinkler",
    "205": "gl112-related-205",
    "208": "gl112-related-208",
    "019": "jl-14-jl-17-esfr",
    "070": "p25-esfr-pendent",
}

os.makedirs(BOLETINES_RELIABLE, exist_ok=True)

for num, name in bulletins.items():
    url = f"https://www.reliablesprinkler.com/files/bulletins/{num}.pdf"
    out = str(BOLETINES_RELIABLE / f"{num}_{name}.pdf")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=30).read()
        with open(out, 'wb') as f:
            f.write(data)
        print(f"OK {num} -> {len(data)} bytes -> {out}")
    except Exception as e:
        print(f"FAIL {num}: {e}")
