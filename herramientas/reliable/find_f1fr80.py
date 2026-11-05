import urllib.request

urls = [
    "https://www.reliablesprinkler.com/product/f1fr80-series-quick-response-sprinklers/",
    "https://www.reliablesprinkler.com/product/f1-80-series-standard-response-sprinklers/",
    "https://www.reliablesprinkler.com/product/f1-80-series/",
    "https://www.reliablesprinkler.com/product/f1fr80/",
    "https://www.reliablesprinkler.com/product-category/sprinklers/",
    "https://www.reliablesprinkler.com/products/",
]
for url in urls:
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        r = urllib.request.urlopen(req, timeout=20)
        data = r.read()
        print(url, "->", r.status, len(data))
    except Exception as e:
        print(url, "-> FAIL", e)
