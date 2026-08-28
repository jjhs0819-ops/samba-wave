"""바이마 등록 상품을 삼바 상품관리에 연결(백필).

5,003건은 삼바를 거치지 않고 스크립트로 바이마에 직접 올라갔다. 그래서
samba_collected_product 에 "이 상품이 바이마에 올라가 있다"는 기록이 없고,
상품관리 화면에도 안 뜬다. 오토튠도 registered_accounts 로 감시 대상을
고르기 때문에 이 연결이 없으면 재고 동기화가 아예 시작되지 않는다.

이 스크립트가 채우는 것:
  market_product_nos[account_id] = 바이마 상품ID
  registered_accounts           += account_id
  name_ja                        = 바이마에 실제로 올라간 일본어 상품명

name_ja 를 같이 넣는 이유는, 무신사에서 수집한 name 은 한국어라 상품관리에서
"이 상품이 바이마에 무슨 이름으로 올라가 있는지" 볼 방법이 없기 때문이다.
바이마 실등록명이 사실이므로 기존 값과 다르면 덮어쓴다(--skip-name-ja 로 끈다).

매칭은 무신사 goods_no(site_product_id) 로 한다. 등록 시 바이마
商品管理番号(reference_number)에 무신사 상품번호를 넣었기 때문에 1:1로 붙는다.

usage:
  python -m scripts.buyma_backfill --csv backfill_mapping.csv --account ma_xxx --dry-run
  python -m scripts.buyma_backfill --csv backfill_mapping.csv --account ma_xxx --apply
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select


async def _run(
    csv_path: Path, account_id: str, apply: bool, limit: int, name_ja: bool
) -> int:
    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import (
        SambaCollectedProduct,
        as_market_nos,
    )

    csv.field_size_limit(10**7)
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    if limit:
        rows = rows[:limit]
    print(
        f"[백필] 매핑 {len(rows):,}건 / account={account_id} / "
        f"{'적용' if apply else 'DRY-RUN'}",
        flush=True,
    )

    Session = get_write_sessionmaker()
    async with Session() as session:
        acc = (
            (
                await session.execute(
                    select(SambaMarketAccount).where(
                        SambaMarketAccount.id == account_id
                    )
                )
            )
            .scalars()
            .first()
        )
        if acc is None:
            print(f"  계정 없음: {account_id}")
            return 2
        if acc.market_type != "buyma":
            print(f"  market_type 가 buyma 가 아님: {acc.market_type}")
            return 2
        print(f"  계정 확인: {acc.account_label} (tenant={acc.tenant_id})")

        # 무신사 goods_no → 수집상품 (한 번에 로드, 건별 쿼리 5천번 방지)
        nos = [
            r["musinsa_goods_no"].strip() for r in rows if r["musinsa_goods_no"].strip()
        ]
        found: dict[str, SambaCollectedProduct] = {}
        CHUNK = 500
        for i in range(0, len(nos), CHUNK):
            part = nos[i : i + CHUNK]
            res = (
                (
                    await session.execute(
                        select(SambaCollectedProduct).where(
                            SambaCollectedProduct.site_product_id.in_(part)
                        )
                    )
                )
                .scalars()
                .all()
            )
            for p in res:
                found[str(p.site_product_id)] = p
        print(f"  수집상품 매칭: {len(found):,} / {len(nos):,}")

        stat = Counter()
        for r in rows:
            no = r["musinsa_goods_no"].strip()
            bid = r["buyma_product_id"].strip()
            if not no or not bid:
                stat["키없음"] += 1
                continue
            p = found.get(no)
            if p is None:
                stat["수집상품 없음"] += 1
                continue

            # dict 는 반드시 복사한다. as_market_nos 는 dict 를 그대로 돌려주는데,
            # 그걸 제자리 수정하고 같은 객체를 재할당하면 SQLAlchemy 가 변경으로
            # 보지 않아 UPDATE 가 나가지 않는다(로컬 검증에서 4건 중 2건이 조용히
            # 반영되지 않았다). 통계는 '연결'로 찍히므로 성공한 줄 알게 된다.
            nosmap = dict(as_market_nos(p.market_product_nos))
            accs = list(p.registered_accounts or [])
            before = (nosmap.get(account_id), account_id in accs)

            nosmap[account_id] = bid
            if account_id not in accs:
                accs.append(account_id)

            jp = (r.get("buyma_name") or "").strip() if name_ja else ""
            jp_changed = bool(jp) and (p.name_ja or "") != jp
            if jp_changed:
                stat["일문명 채움" if not p.name_ja else "일문명 갱신"] += 1

            if before == (bid, True) and not jp_changed:
                stat["이미 연결됨"] += 1
                continue
            if before == (bid, True):
                stat["연결됨(일문명만)"] += 1
            else:
                stat["연결"] += 1
            if apply:
                p.market_product_nos = nosmap
                p.registered_accounts = accs
                if jp_changed:
                    p.name_ja = jp
                session.add(p)

        if apply:
            await session.commit()
            print("  커밋 완료")

    print("\n" + "=" * 46)
    for k, v in stat.most_common():
        print(f"  {k:<16} {v:>7,}")
    print("=" * 46)
    if stat["수집상품 없음"]:
        print("\n  ※ '수집상품 없음' 은 무신사에서 수집된 적 없는 상품이다.")
        print("     상품관리에 띄우려면 먼저 수집이 필요하다(백필만으로는 안 뜬다).")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument(
        "--account", required=True, help="samba_market_account.id (market_type=buyma)"
    )
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--skip-name-ja",
        action="store_true",
        help="일문 상품명(name_ja) 은 건드리지 않는다",
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.csv.exists():
        print(f"CSV 없음: {a.csv}")
        return 2
    return asyncio.run(_run(a.csv, a.account, a.apply, a.limit, not a.skip_name_ja))


if __name__ == "__main__":
    sys.exit(main())
