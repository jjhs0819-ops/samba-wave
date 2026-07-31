"""45개(K-TCG Vault 등록) 번장 소스 품절·가격 스캔 [읽기전용, 호스트 실행].

각 상품의 번장 source_url pid → saleStatus/price 확인.
품절(SOLD_OUT/RESERVED/삭제) 목록 출력 → resource.py로 대체.

실행(호스트): backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/sweep.py
"""

import asyncio
import re
import sys

sys.path.insert(0, __file__.rsplit("ebay_sourcing", 1)[0] + "ebay_sourcing")
from common import DB_DSN, KV, Whale, utf8_stdout  # noqa: E402

utf8_stdout()


async def main():
    import asyncpg

    conn = await asyncpg.connect(DB_DSN)
    rows = await conn.fetch(
        "SELECT id,name,source_url,cost FROM samba_collected_product "
        "WHERE registered_accounts::text LIKE $1 ORDER BY id",
        f"%{KV}%",
    )
    await conn.close()
    print(f"대상 {len(rows)}건 스캔...")

    w = Whale()
    alive = 0
    problems = []  # 품절/삭제
    price_changed = []  # SELLING인데 원가 변동
    try:
        for r in rows:
            m = re.search(r"products/(\d+)", r["source_url"] or "")
            if not m:
                problems.append((r["id"], r["name"][:28], "?", "NOPID"))
                continue
            pid = m.group(1)
            p = w.product(pid)
            st = p.get("saleStatus") or p.get("_err") or "?"
            if st == "SELLING":
                alive += 1
                # 가격 변동 체크 (번장 현재가 vs DB 원가, 5% 이상 차이)
                bp = p.get("price")
                dc = r["cost"]
                try:
                    bp, dc = float(bp), float(dc)
                    if dc > 0 and abs(bp - dc) / dc >= 0.05:
                        price_changed.append(
                            (r["id"], r["name"][:28], pid, int(dc), int(bp))
                        )
                except (TypeError, ValueError):
                    pass
            else:
                problems.append((r["id"], r["name"][:28], pid, st))
    finally:
        w.close()

    print(
        f"\n=== SELLING {alive} / 품절·삭제 {len(problems)} / 가격변동 {len(price_changed)} ==="
    )
    print("── 품절·삭제(대체 필요) ──")
    for pid_id, name, pid, st in problems:
        print(f"  [{st}] {name} pid={pid} ({pid_id})")
    print("── 가격변동(원가 갱신 필요, DB→번장현재) ──")
    for pid_id, name, pid, dc, bp in price_changed:
        print(f"  {name} {dc:,}→{bp:,}원 pid={pid} ({pid_id})")


if __name__ == "__main__":
    asyncio.run(main())
