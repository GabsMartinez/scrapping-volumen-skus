import urllib.request

from scraper_precios.config import EXPLORACION

urls = [
    "https://www.reliablesprinkler.com/product/f1fr80-series/",
    "https://www.reliablesprinkler.com/product/f1fr80-quick-response-sprinklers/",
    "https://www.reliablesprinkler.com/product/f1fr-80-series-quick-response-sprinklers/",
    "https://www.reliablesprinkler.com/product/f1fr80-series-sprinklers/",
    "https://www.reliablesprinkler.com/product-sitemap.xml",
    "https://www.reliablesprinkler.com/sitemap.xml",
    "https://www.reliablesprinkler.com/sitemap_index.xml",
]
for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        r = urllib.request.urlopen(req, timeout=20)
        data = r.read()
        print(url, "->", r.status, len(data))
        if 'sitemap' in url:
            open(EXPLORACION / 'html' / url.rsplit('/', 1)[-1], 'wb').write(data)
    except Exception as e:
        print(url, "-> FAIL", e)
