import asyncio
import sys
import httpx

sys.stdout.reconfigure(encoding="utf-8")


async def m():
    H = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "ja",
        "Referer": "https://snkrdunk.com/",
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get("https://snkrdunk.com/v1/apparels/742030", headers=H)
        d = r.json() or {}
        print("키:", [k for k in d.keys()][:20])
        print("name:", d.get("name") or d.get("localizedName"))
        print("minPrice:", d.get("minPrice"), "listingCount:", d.get("listingCount"))
        print("image:", (d.get("imageUrl") or d.get("thumbnailImageUrl") or "")[:70])
        # 수량옵션(sizes) 있나
        rs = await c.get("https://snkrdunk.com/v1/apparels/742030/sizes", headers=H)
        if rs.status_code == 200:
            for sp in (rs.json().get("sizePrices") or [])[:8]:
                sz = sp.get("size") or {}
                print(
                    "  옵션:",
                    sz.get("localizedName") or sz.get("name"),
                    "min",
                    sp.get("minListingPrice"),
                    "cnt",
                    sp.get("listingItemCount") or sp.get("listingCount"),
                )


asyncio.run(m())
