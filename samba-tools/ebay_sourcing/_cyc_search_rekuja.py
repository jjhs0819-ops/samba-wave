"""레쿠쟈(Rayquaza) 신규 후보 검색 [호스트]. 기존 등록 4건 pid 제외."""
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import BAD_KW, Whale, utf8_stdout  # noqa: E402

utf8_stdout()

EXIST_PID = {"398130335", "422612310", "421975256", "403971908"}
KW = ["레쿠쟈 ex", "레쿠쟈 vmax", "레쿠쟈 v", "레쿠쟈 sar", "레쿠쟈 vstar", "메가 레쿠쟈"]


def main():
    w = Whale()
    seen = {}
    try:
        for kw in KW:
            for it in w.search(kw, n=40):
                pid = str(it.get("pid") or "")
                nm = it.get("name", "") or ""
                if not pid or pid in EXIST_PID or pid in seen:
                    continue
                if any(b in nm.lower() for b in BAD_KW):
                    continue
                if "레쿠" not in nm:
                    continue
                rar = len(re.findall(r"(?<![a-z])(sar|csr|hr|rr|ur|sr|ar|vmax|vstar)(?![a-z])", nm.lower()))
                if rar >= 2 or len(nm) > 40:
                    continue
                try:
                    pr = int(it.get("price", 0))
                except Exception:
                    continue
                if pr < 3000 or pr > 300000:
                    continue
                p = w.product(pid)
                if p.get("saleStatus") != "SELLING":
                    continue
                seen[pid] = {
                    "pid": pid,
                    "name": nm,
                    "price": p.get("price"),
                    "imageUrl": p.get("imageUrl"),
                    "imageCount": p.get("imageCount"),
                }
                print(f"  {pid} | {p.get('price')}원 | {nm}")
    finally:
        w.close()
    with open("rekuja_cands.json", "w", encoding="utf-8") as f:
        json.dump(list(seen.values()), f, ensure_ascii=False, indent=1)
    print(f"\n=== 신규후보 {len(seen)}건 ===")


if __name__ == "__main__":
    main()
