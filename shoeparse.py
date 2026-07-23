import asyncio, re, sys
import httpx
sys.stdout.reconfigure(encoding='utf-8')
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36"
RE=re.compile(r'"sizeName":"([^"]+)"[^}]*\},"minNewListingPrice":(\d+)')
def to_mm(s):
    m=re.match(r'^(\d+(?:\.\d+)?)\s*cm$',(s or '').strip(),re.I)
    if not m: return None
    v=float(m.group(1))*10
    return str(int(v)) if v==int(v) else str(v)
async def fetch(c,style):
    r=await c.get(f"https://snkrdunk.com/products/{style}")
    if r.status_code!=200: return None
    h=r.text.replace("\\","")
    out={}
    for sz,pr in RE.findall(h):
        mm=to_mm(sz); p=int(pr)
        if mm and p>0: out[mm]={"price":p,"stock":1}
    return out
async def m():
    tests=[("1178630-BBNB",{"265":50095}),("MS1300TB",{"275":49094}),("EG6860",{"280":66127}),
           ("VN0A4BV99RB1",{"280":15028}),("JS2630",{"280":11021})]
    async with httpx.AsyncClient(headers={"User-Agent":UA,"Accept-Language":"ja"},timeout=30,follow_redirects=True) as c:
        for style,dbmap in tests:
            live=await fetch(c,style)
            if live is None: print(f"{style}: fetch 실패"); continue
            for mm,dbp in dbmap.items():
                lv=live.get(mm)
                if lv:
                    d=(lv['price']-dbp)/dbp*100
                    print(f"{style:14} {mm}: DB ¥{dbp:,} vs 라이브 ¥{lv['price']:,}  ({d:+.1f}%)  [사이즈 {len(live)}개 파싱]")
                else:
                    print(f"{style:14} {mm}: DB ¥{dbp:,} vs 라이브 매물없음  [사이즈 {len(live)}개 파싱]")
            await asyncio.sleep(0.4)
asyncio.run(m())
