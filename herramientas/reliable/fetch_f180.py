import re
import urllib.request

from scraper_precios.config import EXPLORACION

url = "https://www.reliablesprinkler.com/product/f1-80-series/"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')

with open(EXPLORACION / "html" / "f1-80-series.html", "w", encoding="utf-8") as f:
    f.write(data)

bulletins = sorted(set(re.findall(r'href="([^"]*bulletin[^"]*)"', data)))
print("Bulletins:", bulletins)

# print title and K-factor / SIN mentions near text
idx = data.find("<title>")
print(data[idx:idx+150])

for kw in ["RA6322", "RA6312", "F1FR80", "F1-80", "K-Factor", "Style List"]:
    i = data.find(kw)
    print(kw, "found at", i)
