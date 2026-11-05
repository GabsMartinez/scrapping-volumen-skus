import re
import urllib.request

from scraper_precios.config import EXPLORACION

url = "https://www.reliablesprinkler.com/product/f1fr80-series/"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')

with open(EXPLORACION / "html" / "f1fr80-series.html", "w", encoding="utf-8") as f:
    f.write(data)

bulletins = sorted(set(re.findall(r'href="([^"]*bulletin[^"]*)"', data)))
print("Bulletins:", bulletins)

idx = data.find("<title>")
print(data[idx:idx+150])

for kw in ["RA6322", "RA6312", "K-Factor", "Style List"]:
    i = data.find(kw)
    print(kw, "found at", i, data[max(0,i-100):i+50].replace("\n"," ") if i>=0 else "")
