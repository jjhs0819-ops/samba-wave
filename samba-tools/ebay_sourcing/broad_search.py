"""번장 '포켓몬카드' 키워드 전체목록을 페이지네이션으로 훑어 단일카드 대량 수집 [호스트].

특정 몬 키워드(batch_search) 대신 카테고리 전체를 페이지 넘기며 긁는다.
링크: m.bunjang.co.kr/keywords/포켓몬카드?without=[구매,매입,삽니다,교환,구해요]
  → find_v2 q='포켓몬카드' 페이지네이션. 구매글은 BAD_KW/EXTRA_BAD로 client 제외.

출력: scratchpad/cands.json {"pokemon":[{bpid,price,name,img}]}
실행: backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/broad_search.py <out.json> [--want 80] [--pages 40]
"""

import json
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import BAD_KW, Whale, utf8_stdout  # noqa: E402
from batch_search import (  # noqa: E402
    EXTRA_BAD,
    MAX_COST,
    MIN_COST,
    MULTI_BAD,
    POKE_SPECIFIC,
    RARITY,
    _norm,
    _safe,
)

# utf8_stdout 은 batch_search import 시 이미 호출됨(중복 호출하면 stdout 이중래핑으로 깨짐).
_ = utf8_stdout  # noqa: F401 — import 유지용

KEYWORD = "포켓몬카드"


def main():
    out_path = sys.argv[1]
    want = int(sys.argv[sys.argv.index("--want") + 1]) if "--want" in sys.argv else 80
    pages = int(sys.argv[sys.argv.index("--pages") + 1]) if "--pages" in sys.argv else 40
    start = int(sys.argv[sys.argv.index("--start") + 1]) if "--start" in sys.argv else 0
    prev = {}
    try:
        prev = json.load(open(out_path, encoding="utf-8"))
    except Exception:
        pass
    result = {"ateez": prev.get("ateez", []), "pokemon": [], "skz": prev.get("skz", [])}

    w = Whale()
    seen_pid, seen_name, out = set(), set(), []
    try:
        for pg in range(start, start + pages):
            if len(out) >= want:
                break
            items = _safe(w, "search", KEYWORD, 100, pg) or []
            if not items:
                print(f"  page {pg}: 결과없음 — 중단")
                break
            for it in items:
                if len(out) >= want:
                    break
                pid = it.get("pid")
                nm = it.get("name", "") or ""
                low = nm.lower()
                if not pid or pid in seen_pid:
                    continue
                if any(b in low for b in BAD_KW) or any(b in low for b in EXTRA_BAD):
                    continue
                if any(b in low for b in MULTI_BAD):
                    continue
                # 단일 식별 가능한 카드만 — 레어도 토큰 1개(2개면 여러장 나열), 이름 짧게
                rar = len(re.findall(r"(?<![a-z])(sar|ar|sr|ur|rr|hr)(?![a-z])", low))
                if rar >= 2 or len(nm) > 34:
                    continue
                if not any(rt in low for rt in RARITY):
                    continue
                # 어떤 카드인지 특정 가능해야(포켓몬명/레어도 포함)
                if not any(s in nm for s in POKE_SPECIFIC):
                    continue
                key = _norm(nm)[:24]
                if key in seen_name:
                    continue
                p = _safe(w, "product", str(pid))
                if not p or p.get("_err") or p.get("saleStatus") != "SELLING":
                    continue
                price = int(p.get("price") or 0)
                if not (MIN_COST <= price <= MAX_COST):
                    continue
                if int(p.get("imageCount") or 0) < 1:
                    continue
                seen_pid.add(pid)
                seen_name.add(key)
                out.append(
                    {
                        "bpid": str(pid),
                        "price": price,
                        "name": p.get("name") or nm,
                        "img": int(p.get("imageCount") or 1),
                    }
                )
                print(f"  [{len(out):3d}] p{pg} {pid} | {price:,}원 | {(p.get('name') or nm)[:32]}")
    finally:
        w.close()
    result["pokemon"] = out
    json.dump(result, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n수집 포켓몬 {len(out)} → {out_path}")


if __name__ == "__main__":
    main()
