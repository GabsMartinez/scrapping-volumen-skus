import re
import urllib.request

from scraper_precios.config import EXPLORACION

urls = [
    "https://www.reliablesprinkler.com/product/j112/",
    "https://www.reliablesprinkler.com/product/j112-series/",
    "https://www.reliablesprinkler.com/product/model-j112/",
    "https://www.reliablesprinkler.com/product/j-112/",
]
for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        r = urllib.request.urlopen(req, timeout=20)
        data = r.read()
        print(url, "->", r.status, len(data))
        txt = data.decode('utf-8', errors='replace')
        bulletins = sorted(set(re.findall(r'href="([^"]*bulletin[^"]*)"', txt)))
        print("  Bulletins:", bulletins)
        idx = txt.find("<title>")
        print("  ", txt[idx:idx+100])
        if 'j112' in url.lower() and r.status==200:
            with open(EXPLORACION / 'html' / 'j112.html', 'w', encoding='utf-8') as f:
                f.write(txt)
    except Exception as e:
        print(url, "-> FAIL", e)
