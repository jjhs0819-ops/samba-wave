"""미확인 브랜드를 쿠팡 브랜드 API로 판별해 samba_brand_restriction 에 기록.

소명 대상 브랜드는 마켓이 계속 추가하고, 우리는 계속 새 브랜드를 수집한다.
목록에 없는 브랜드는 안전상 전부 차단되므로, 주기적으로 이걸 돌려
"팔아도 되는 브랜드"를 풀어줘야 한다.

대상: 수집 상품(samba_collected_product)의 브랜드 중 아직 판정이 없거나
      unknown 인 것. 이미 blocked/allowed 로 확정된 브랜드는 건너뛴다.

사용법:
    python -m backend.scripts.resolve_unknown_brands --dry-run
    python -m backend.scripts.resolve_unknown_brands --apply
    python -m backend.scripts.resolve_unknown_brands --apply --limit 20
"""

import argparse
import asyncio
import logging
import sys
import warnings
from collections import Counter

warnings.filterwarnings("ignore", category=DeprecationWarning)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# 쿠팡 API 예의 — 브랜드 검색을 몰아치지 않도록 호출 간 간격(초)
CALL_INTERVAL = 0.3


async def main(apply: bool, limit: int) -> int:
    from sqlalchemy import text
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.brand.model import (
        SambaBrandRestriction,
        normalize_brand,
    )
    from backend.domain.samba.brand.service import BrandGuardService
    from backend.domain.samba.proxy.coupang import CoupangClient

    async with get_write_session() as session:
        # 활성 쿠팡 계정
        acct = (
            (
                await session.execute(
                    select(SambaMarketAccount).where(
                        SambaMarketAccount.market_type == "coupang",
                        SambaMarketAccount.is_active == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        if not acct or not acct.api_key or not acct.api_secret:
            logger.error("활성 쿠팡 계정(api_key/secret)이 없습니다.")
            return 1
        logger.info(f"쿠팡 계정: {acct.seller_id}")

        # 수집 상품의 브랜드 목록
        rows = (
            await session.execute(
                text(
                    "SELECT brand, count(*) FROM samba_collected_product "
                    "WHERE brand IS NOT NULL AND btrim(brand) <> '' "
                    "GROUP BY brand ORDER BY count(*) DESC"
                )
            )
        ).fetchall()

        # 이미 확정된 브랜드는 제외
        known = {
            r.brand_key: r.verdict
            for r in (await session.execute(select(SambaBrandRestriction)))
            .scalars()
            .all()
        }
        targets: list[tuple[str, int]] = []
        seen: set[str] = set()
        for brand, cnt in rows:
            key = normalize_brand(brand)
            if not key or key in seen:
                continue
            seen.add(key)
            if known.get(key) in ("blocked", "allowed"):
                continue
            targets.append((brand, cnt))

        if limit:
            targets = targets[:limit]
        if not targets:
            logger.info("판별할 미확인 브랜드가 없습니다.")
            return 0

        logger.info(f"미확인 브랜드 {len(targets)}종 조회 시작\n")

        client = CoupangClient(acct.api_key, acct.api_secret, acct.seller_id or "")
        guard = BrandGuardService(session)
        results: list[tuple[str, int, str, str]] = []
        dist: Counter[str] = Counter()

        for i, (brand, cnt) in enumerate(targets, start=1):
            # tenant_id=None(전역)으로 기록한다. 브랜드 소명 여부는 어느 계정으로
            # 팔든 동일하므로 계정별로 쪼개면 목록이 갈라져 서로 안 보이게 된다.
            r = await guard.check(
                brand,
                coupang_client=client,
                tenant_id=None,
                record=apply,
            )
            dist[r.verdict] += 1
            results.append((brand, cnt, r.verdict, r.reason))
            mark = {"allowed": "허용", "blocked": "차단", "unknown": "미확인"}[
                r.verdict
            ]
            logger.info(
                f"  {i:3d}/{len(targets)}  {mark}  {brand[:24]:24s} "
                f"(상품 {cnt:2d}개)  {r.reason[:44]}"
            )
            if CALL_INTERVAL:
                await asyncio.sleep(CALL_INTERVAL)

        logger.info("")
        logger.info("=== 판별 결과 ===")
        for v, label in (
            ("allowed", "허용"),
            ("blocked", "차단"),
            ("unknown", "미확인"),
        ):
            logger.info(f"  {label:4s} {dist.get(v, 0):3d}종")

        freed = [r for r in results if r[2] == "allowed"]
        if freed:
            logger.info("")
            logger.info(
                f"=== 새로 풀린 브랜드 {len(freed)}종 (상품 {sum(r[1] for r in freed)}개) ==="
            )
            for brand, cnt, _, _ in sorted(freed, key=lambda x: -x[1]):
                logger.info(f"  {brand[:28]:28s} 상품 {cnt}개")

        newly_blocked = [r for r in results if r[2] == "blocked"]
        if newly_blocked:
            logger.info("")
            logger.info(f"=== 소명 대상으로 확인된 브랜드 {len(newly_blocked)}종 ===")
            for brand, cnt, _, reason in sorted(newly_blocked, key=lambda x: -x[1]):
                logger.info(f"  {brand[:28]:28s} 상품 {cnt}개  {reason[:40]}")

        if not apply:
            logger.info("\n[dry-run] 기록하지 않았습니다. --apply 로 실행하세요.")
        else:
            logger.info("\n기록 완료 (source='coupang_api').")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="판별 결과를 DB에 기록")
    ap.add_argument("--dry-run", action="store_true", help="조회만 (기본값)")
    ap.add_argument(
        "--limit", type=int, default=0, help="조회할 브랜드 수 제한(0=전체)"
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(main(apply=args.apply, limit=args.limit)))
