"""KREAM매칭 SNKR 21,618쌍 enrich — JP(영문명·일문명·엔가·옵션) + KREAM(한글명) 수집.

로컬 PC 전용(서버 메모리 0). 결과 → _matched_enrich.jsonl. 재개가능.
서버는 이 파일로 집 Postgres 일괄 업데이트(name=한글, name_en, name_ja, 엔가, currency JPY).
"""

import asyncio
import json
import os
import re
import urllib.request

from backend.domain.samba.proxy.snkrdunk import SnkrdunkClient

PAIRS = "C:/Users/canno/workspace/samba-wave/scripts/_matched_pairs.csv"
OUT = "C:/Users/canno/workspace/samba-wave/scripts/_matched_enrich.jsonl"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}


# 로컬 KREAM 카탈로그 한글명 사전(있으면 fetch 스킵 → 가속)
try:
    _CAT = json.load(
        open(
            "C:/Users/canno/workspace/samba-wave/scripts/_kream_cat_names.json",
            encoding="utf-8",
        )
    )
except Exception:
    _CAT = {}


def kream_korean(kid):
    """KREAM 상품 한글명 — 카탈로그(로컬, 즉시)만 사용. 미보유는 빈값(나중 백필)."""
    return _CAT.get(str(kid), "")


def _kream_korean_live(kid):
    try:
        html = (
            urllib.request.urlopen(
                urllib.request.Request(
                    f"https://kream.co.kr/products/{kid}", headers=UA
                ),
                timeout=5,
            )
            .read()
            .decode("utf-8", "ignore")
        )
        d = re.search(r'<meta name="description"[^>]*content="([^"]+)"', html)
        if not d:
            return ""
        desc = d.group(1)
        # KREAM desc 구조: "{모델} 포켓몬 TCG {한글명} Pokemon TCG {영문명} 상품"
        # 한글명 = '포켓몬 TCG' 와 'Pokemon TCG' 사이.
        m = re.search(r"포켓몬\s*TCG\s*(.+?)\s*Pok[eé]mon\s*TCG", desc)
        if m:
            return m.group(1).strip()[:120]
        # 폴백: 'Pokemon TCG' 앞 전체서 선행 모델코드 제거
        kor = re.split(r"Pok[eé]mon TCG", desc)[0].strip()
        kor = re.sub(r"^[A-Za-z0-9/\-]+\s+", "", kor)
        kor = re.sub(r"^포켓몬\s*TCG\s*", "", kor).strip()
        return kor[:120]
    except Exception:
        return ""


async def main():
    pairs = []
    for line in open(PAIRS, encoding="utf-8"):
        line = line.strip()
        if "," in line:
            s, k = line.split(",", 1)
            if s and k:
                pairs.append((s.strip(), k.strip()))
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            l = l.strip()
            if l:
                done.add(str(json.loads(l)["snkr_id"]))
    todo = [(s, k) for s, k in pairs if s not in done]
    print(f"매칭쌍 {len(pairs)} | 이미 {len(done)} | 이번 {len(todo)}", flush=True)
    client = SnkrdunkClient()
    cf = open(OUT, "a", encoding="utf-8")
    sem = asyncio.Semaphore(16)
    write_lock = asyncio.Lock()
    cnt = {"ok": 0, "fail": 0, "n": 0}

    def jp_light(sid):
        """가벼운 JP fetch — detail(name/localizedName/minPrice) + used p1(PSA10 최저엔).
        get_trading_card_detail의 다중페이지/내부sleep 없이 2콜로 enrich 가속.
        """
        import json as _j

        jh = {
            "User-Agent": UA["User-Agent"],
            "Accept": "application/json",
            "Accept-Language": "ja-JP,ja;q=0.9",
            "Referer": "https://snkrdunk.com/",
        }

        def get(u):
            return _j.loads(
                urllib.request.urlopen(
                    urllib.request.Request(u, headers=jh), timeout=8
                ).read()
            )

        d = get(f"https://snkrdunk.com/v1/apparels/{sid}")
        name_en = (d.get("name") or "").strip()
        name_ja = (d.get("localizedName") or "").strip()
        box_min = (
            d.get("minPrice") if isinstance(d.get("minPrice"), (int, float)) else 0
        )
        price = 0
        try:
            u = get(
                f"https://snkrdunk.com/v1/apparels/{sid}/used?perPage=100&page=1&sizeId=0&isSaleOnly=true"
            )
            mins = []
            for x in u.get("apparelUsedItems") or []:
                if x.get("isDisplaySold"):
                    continue
                cond = (
                    (x.get("displayShortConditionTitle") or "").upper().replace(" ", "")
                )
                if not cond.startswith("PSA10"):
                    continue
                p = x.get("price")
                if isinstance(p, (int, float)) and p > 0:
                    mins.append(int(p))
            if mins:
                price = min(mins)
        except Exception:
            pass
        if price == 0 and box_min:
            price = int(box_min)  # 박스/봉인: minPrice
        return name_en, name_ja, price

    async def one(sid, kid):
        rec = {"snkr_id": sid, "kream_id": kid}
        try:
            en, ja, price = await asyncio.to_thread(jp_light, sid)
            if en:
                rec["name_en"] = en
                rec["name_ja"] = ja
                rec["price"] = float(price)
                rec["options"] = []
                cnt["ok"] += 1
            else:
                rec["err"] = "no_name"
                cnt["fail"] += 1
        except Exception as e:
            rec["err"] = str(e)[:60]
            cnt["fail"] += 1
        rec["kor"] = kream_korean(kid)
        async with write_lock:
            cf.write(json.dumps(rec, ensure_ascii=False) + "\n")
            cf.flush()
            cnt["n"] += 1
            if cnt["n"] % 200 == 0:
                print(
                    f"  {cnt['n']}/{len(todo)} (ok {cnt['ok']} fail {cnt['fail']})",
                    flush=True,
                )

    async def guarded(sid, kid):
        async with sem:
            await one(sid, kid)

    await asyncio.gather(*[guarded(s, k) for s, k in todo])
    cf.close()
    print(f"완료 ok {cnt['ok']} / fail {cnt['fail']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
