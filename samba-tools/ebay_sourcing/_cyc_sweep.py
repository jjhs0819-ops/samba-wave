"""kv_products.json 기반 스윕 [호스트]. 품절/삭제 → problems.json 저장(다음 단계 매칭용)."""
import json
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import Whale, utf8_stdout  # noqa: E402

utf8_stdout()


def main():
    with open("kv_products.json", "r", encoding="utf-8") as f:
        rows = json.load(f)
    print(f"대상 {len(rows)}건 스캔...")

    w = Whale()
    alive = 0
    problems = []
    price_changed = []
    try:
        for i, r in enumerate(rows):
            m = re.search(r"products/(\d+)", r.get("source_url") or "")
            if not m:
                problems.append(
                    {"id": r["id"], "name": r["name"], "pid": None, "status": "NOPID"}
                )
                continue
            pid = m.group(1)
            try:
                p = w.product(pid)
            except Exception:
                w.reconnect()
                p = w.product(pid)
            st = p.get("saleStatus") or p.get("_err") or "?"
            if st == "SELLING":
                alive += 1
                bp = p.get("price")
                dc = r.get("cost")
                try:
                    bp, dc = float(bp), float(dc)
                    if dc > 0 and abs(bp - dc) / dc >= 0.05:
                        price_changed.append(
                            {
                                "id": r["id"],
                                "name": r["name"],
                                "pid": pid,
                                "db_cost": dc,
                                "bunjang_price": bp,
                            }
                        )
                except (TypeError, ValueError):
                    pass
            else:
                problems.append(
                    {"id": r["id"], "name": r["name"], "pid": pid, "status": st}
                )
            if (i + 1) % 50 == 0:
                print(f"  ...{i+1}/{len(rows)}")
    finally:
        w.close()

    print(f"\n=== SELLING {alive} / 품절·삭제 {len(problems)} / 가격변동 {len(price_changed)} ===")
    with open("problems.json", "w", encoding="utf-8") as f:
        json.dump(problems, f, ensure_ascii=False, indent=1)
    with open("price_changed.json", "w", encoding="utf-8") as f:
        json.dump(price_changed, f, ensure_ascii=False, indent=1)
    for p in problems:
        print(f"  [{p['status']}] {p['name'][:28]} pid={p['pid']} ({p['id']})")


if __name__ == "__main__":
    main()
