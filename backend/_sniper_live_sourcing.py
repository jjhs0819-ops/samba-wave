"""2세대 스나이퍼 — 멀티소싱 라이브 검색 (삼바 20플러그인 네이티브).

크림 수요상품(거래≥N, _gold_candidates.jsonl)을 삼바 소싱 플러그인 search()로 라이브 조회해
저장분에 없던 상품의 원가를 확보한다. 병목이던 소싱매칭률을 끌어올리는 핵심 엔진.

플러그인 검색키:
  - 무신사/GS/SSG/ABC/나이키/아디다스 = style_code(품번)
  - 롯데온 = 한글명(품번검색 미지원)
매칭: 결과 style_code(있으면) 정확일치 / 없으면 이름에 품번포함. 최저 sale_price 채택.

실행(backend venv): .venv/Scripts/python.exe _sniper_live_sourcing.py
  환경: MIN_SALES(기본100) LIMIT(기본200) SITES(기본 musinsa,gsshop,ssg,abcmart)
출력: _sniper_live_out.csv (style, kream_pid, 최저소싱처, 원가, 크림명)
"""

import asyncio
import csv
import io
import json
import os
import re
import sys

sys.stdout = io.TextIOWrapper(
    sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
)
sys.path.insert(0, ".")

GOLD = r"C:\Users\canno\samba-tools\kream\_gold_candidates.jsonl"
OUT = r"C:\Users\canno\samba-tools\kream\_sniper_live_out.csv"
MIN_SALES = int(os.environ.get("MIN_SALES", "100"))
LIMIT = int(os.environ.get("LIMIT", "200"))
SITES = os.environ.get("SITES", "musinsa,gsshop,ssg,abcmart").split(",")


def ns(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


async def _plugins():
    from backend.domain.samba.plugins.sourcing.abcmart import AbcMartPlugin
    from backend.domain.samba.plugins.sourcing.gsshop import GsShopSourcingPlugin
    from backend.domain.samba.plugins.sourcing.lotteon import LotteonSourcingPlugin
    from backend.domain.samba.plugins.sourcing.musinsa import MusinsaPlugin
    from backend.domain.samba.plugins.sourcing.ssg import SSGPlugin

    reg = {
        "musinsa": MusinsaPlugin(),
        "gsshop": GsShopSourcingPlugin(),
        "ssg": SSGPlugin(),
        "abcmart": AbcMartPlugin(),
        "lotteon": LotteonSourcingPlugin(),
    }
    return {k: reg[k] for k in SITES if k in reg}


def _cost_of(item):
    """플러그인 결과 dict → (cost, style_code, name). cost=sale_price 우선."""
    c = item.get("sale_price") or item.get("cost") or item.get("price") or 0
    try:
        c = int(float(c))
    except Exception:
        c = 0
    return c, item.get("style_code") or "", item.get("name") or ""


async def live_cost(plugins, style, kname):
    """전 사이트 라이브검색 → 품번정확일치 최저원가 (site, cost, name)."""
    nstyle = ns(style)
    best = None
    for site, pg in plugins.items():
        kw = kname if site == "lotteon" else style
        if not kw:
            continue
        try:
            res = await asyncio.wait_for(pg.search(kw), timeout=25)
        except Exception:
            continue
        for it in res or []:
            if not isinstance(it, dict):
                continue
            cost, sc, nm = _cost_of(it)
            if cost <= 100:  # 1원 등 무효
                continue
            # 정확매칭: 결과 style_code 일치 or 이름에 품번 포함
            ok = (ns(sc) == nstyle) or (nstyle and nstyle in ns(nm))
            if not ok:
                continue
            if best is None or cost < best[1]:
                best = (site, cost, nm)
    return best


async def main():
    # 크림 수요상품 로드 (거래≥MIN_SALES, style 有)
    prods = []
    seen = set()
    for line in open(GOLD, encoding="utf-8"):
        d = json.loads(line)
        st = ns(d.get("style"))
        if not st or st in seen or int(d.get("sales") or 0) < MIN_SALES:
            continue
        seen.add(st)
        prods.append(d)
    prods.sort(key=lambda d: -int(d.get("sales") or 0))
    prods = prods[:LIMIT]
    print(
        f"대상 수요상품(거래≥{MIN_SALES}) {len(prods)}개 × 소싱처 {list(SITES)}",
        flush=True,
    )

    plugins = await _plugins()
    rows = []
    hit = 0
    for i, d in enumerate(prods, 1):
        b = await live_cost(plugins, d.get("style"), d.get("name"))
        if b:
            rows.append(
                {
                    "style": d.get("style"),
                    "kream_pid": d.get("pid"),
                    "cat": d.get("cat"),
                    "크림명": (d.get("name") or "")[:38],
                    "최저소싱처": b[0],
                    "원가": b[1],
                    "소싱명": b[2][:34],
                    "sales": d.get("sales"),
                    "wish": d.get("wish"),
                    "highest_bid": d.get("highest_bid"),
                    "lowest_ask": d.get("lowest_ask"),
                    "kream_url": f"https://kream.co.kr/products/{d.get('pid')}",
                }
            )
            hit += 1
        if i % 20 == 0:
            print(f"  [{i}/{len(prods)}] 라이브매칭 {hit}", flush=True)

    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    print(f"\n라이브 소싱매칭 {hit}/{len(prods)} → {OUT}", flush=True)
    for r in sorted(rows, key=lambda r: -(int(r.get("highest_bid") or 0) - r["원가"]))[
        :12
    ]:
        gap = int(r.get("highest_bid") or 0) - r["원가"]
        print(
            f"  마진~{gap:>8,} | {r['최저소싱처']:8}{r['원가']:>8,}→bid{int(r.get('highest_bid') or 0):>8,} 거래{r['sales']} | {r['크림명'][:26]}"
        )


if __name__ == "__main__":
    asyncio.run(main())
