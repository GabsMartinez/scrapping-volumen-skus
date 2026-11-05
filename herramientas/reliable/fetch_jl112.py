import re
import urllib.request

from scraper_precios.config import EXPLORACION

url = "https://www.reliablesprinkler.com/product/jl112-and-j112-upright-pendent-recessed/"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')

with open(EXPLORACION / "html" / "jl112-j112.html", "w", encoding="utf-8") as f:
    f.write(data)

bulletins = sorted(set(re.findall(r'href="([^"]*bulletin[^"]*)"', data)))
print("Bulletins:", bulletins)

idx = data.find("<title>")
print(data[idx:idx+150])

for kw in ["RA7326", "RA7216", "K-Factor", "Style List"]:
    i = data.find(kw)
    print(kw, "found at", i, data[max(0,i-100):i+80].replace("\n"," ") if i>=0 else "")
