import re
import urllib.request

all_urls = []
for pg in [1,2,3]:
    url = f"https://www.reliablesprinkler.com/sitemap_type_product.xml?pg={pg}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    data = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', errors='replace')
    locs = re.findall(r'<loc>([^<]+)</loc>', data)
    all_urls.extend(locs)
    print(f"pg{pg}: {len(locs)} urls")

print("Total:", len(all_urls))
matches = [u for u in all_urls if '112' in u.lower()]
print("Matches with '112':")
for m in matches:
    print(" ", m)
