# Pull a few Daraz listings per category into seed JSON (image URLs only, hotlinked).
import json, re, sys, time, urllib.request, urllib.parse
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"
CATS = {"Mobiles": "smartphone", "Electronics": "bluetooth earbuds", "Fashion": "men polo shirt",
        "Home & Living": "bedsheet", "Beauty": "face wash", "Groceries": "rice 5kg"}
def num(s): return int(re.sub(r"[^\d]", "", s or "") or 0)
out = []
for cat, q in CATS.items():
    url = "https://www.daraz.com.bd/catalog/?ajax=true&q=" + urllib.parse.quote(q)
    data = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))
    n = 0
    for it in data["mods"]["listItems"]:
        price = round(float(it.get("price") or 0))
        if not it.get("image") or not price: continue
        orig = round(float(it.get("originalPrice") or 0)) or None
        out.append({"category": cat, "name": it["name"][:200], "price": price,
                    "original_price": orig if orig and orig > price else None,
                    "image": it["image"], "rating": round(float(it.get("ratingScore") or 0), 1),
                    "description": "\n".join(it.get("description") or [])[:2000],
                    "stock": 50, "reviews": int(it.get("review") or 0)})
        n += 1
        if n == 8: break
    time.sleep(1)
json.dump(out, open(sys.argv[1], "w"), indent=1, ensure_ascii=False)
print(len(out), "products")
