# -*- coding: utf-8 -*-
"""#434 — 롯데홈 유령상품 goods_no 자기기록(주문) 역복구.

롯데홈 API 무호출(searchStockList=33MB·IP차단 위험 회피). 유령상품
(registered_accounts 에 롯데홈 계정 있으나 market_product_nos[계정] 없음)을
①같은 style_code 형제 row 의 goods_no ②우리 자체 롯데홈 주문(samba_order:
source=lottehome, product_id=SiteGoodsNo, product_name=GoodsName) 의 상품명 매칭
으로 goods_no 단일후보 복구.

MODE: scan(기본·집계만) / fix(복구 UPDATE)
실행: /app/backend/.venv/bin/python3 /tmp/repair_lh.py [scan|fix]
"""

import asyncio
import json
import re
import sys
import traceback

from sqlalchemy import text

from backend.db.orm import get_write_session


def _norm(s: str) -> str:
    """상품명 정규화 — 공백/특수문자 제거 소문자."""
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


async def run(mode: str) -> None:
    async with get_write_session() as session:
        # 롯데홈 계정 id 목록
        accts = (
            await session.execute(
                text(
                    "SELECT id FROM samba_market_account "
                    "WHERE market_type = 'lottehome'"
                )
            )
        ).fetchall()
        acc_ids = [str(r[0]) for r in accts]
        print(f"롯데홈 계정 {len(acc_ids)}개: {acc_ids}", flush=True)
        if not acc_ids:
            return

        total_ghost = 0
        rec_sibling = 0
        rec_order = 0
        unrec = 0
        updated = 0
        samples: list[str] = []

        for acc_id in acc_ids:
            # 유령: registered_accounts 에 이 계정 있으나 market_product_nos[계정] 없음
            ghosts = (
                await session.execute(
                    text(
                        "SELECT id, name, style_code, "
                        "       COALESCE(market_names->>:k,'') AS mname "
                        "FROM samba_collected_product "
                        "WHERE registered_accounts @> CAST(:a AS jsonb) "
                        "AND NOT jsonb_exists(COALESCE(market_product_nos,'{}'::jsonb), :k)"
                    ),
                    {"k": acc_id, "a": json.dumps([acc_id])},
                )
            ).fetchall()
            if not ghosts:
                continue
            print(f"[{acc_id}] 유령 {len(ghosts)}개", flush=True)

            # 이 계정 롯데홈 주문 상품명→goods_no 맵 (단일후보만)
            orows = (
                await session.execute(
                    text(
                        "SELECT product_name, product_id FROM samba_order "
                        "WHERE source = 'lottehome' AND channel_id = :c "
                        "AND product_id IS NOT NULL AND product_id <> ''"
                    ),
                    {"c": acc_id},
                )
            ).fetchall()
            name2gno: dict[str, set] = {}
            for pn, pid in orows:
                _k = _norm(pn)
                if not _k or not str(pid).isdigit():
                    continue
                name2gno.setdefault(_k, set()).add(str(pid))

            for gid, gname, gstyle, gmname in ghosts:
                total_ghost += 1
                gno = ""
                src = ""
                # ① 같은 style_code 형제 row 의 goods_no
                if gstyle:
                    sib = (
                        await session.execute(
                            text(
                                "SELECT DISTINCT market_product_nos->>:k FROM "
                                "samba_collected_product WHERE style_code = :s "
                                "AND jsonb_exists(market_product_nos, :k) AND id <> :i"
                            ),
                            {"k": acc_id, "s": gstyle, "i": gid},
                        )
                    ).fetchall()
                    sset = {str(r[0]) for r in sib if r[0]}
                    if len(sset) == 1:
                        gno, src = next(iter(sset)), "sibling"
                        rec_sibling += 1
                # ② 주문 상품명 매칭 (단일후보)
                if not gno:
                    cand = name2gno.get(_norm(gmname)) or name2gno.get(_norm(gname))
                    if cand and len(cand) == 1:
                        gno, src = next(iter(cand)), "order"
                        rec_order += 1
                if not gno:
                    unrec += 1
                    continue
                if len(samples) < 20:
                    samples.append(
                        f"  [{src}] {gid} '{str(gname)[:30]}' → goods_no={gno}"
                    )
                if mode == "fix":
                    await session.execute(
                        text(
                            "UPDATE samba_collected_product SET market_product_nos = "
                            "COALESCE(market_product_nos,'{}'::jsonb) || "
                            "jsonb_build_object(CAST(:k AS text), to_jsonb(CAST(:v AS text))) "
                            "WHERE id = :i"
                        ),
                        {"k": acc_id, "v": gno, "i": gid},
                    )
                    updated += 1
            if mode == "fix":
                await session.commit()

        print("\n===== 결과 =====", flush=True)
        print(f"MODE: {mode}", flush=True)
        print(f"유령 총: {total_ghost}", flush=True)
        print(f"복구가능(형제 style): {rec_sibling}", flush=True)
        print(f"복구가능(주문 이름매칭): {rec_order}", flush=True)
        print(f"복구불가(단서없음/다중): {unrec}", flush=True)
        if mode == "fix":
            print(f"실제 UPDATE: {updated}", flush=True)
        print("\n--- 샘플(최대 20) ---", flush=True)
        for s in samples:
            print(s, flush=True)


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode not in ("scan", "fix"):
        print("MODE 는 scan|fix", flush=True)
        return
    try:
        await run(mode)
    except Exception:
        print(traceback.format_exc(), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
