#!/usr/bin/env python3
"""
누락된 정책 적용 보충 스크립트 (일회성)

- 특정 정책 이름으로 정책을 찾아, 그 정책이 attached 된 모든 그룹(필터)을 대상으로
  applied_policy_id 가 비어있거나 다르거나 market_prices.default 가 비어있는 상품을 골라
  단순 마크업 가격(기존 propagation 로직과 동일)으로 채운다.
- 페이지네이션을 id 기준 cursor 로 수행 (10,000개 limit 제거).
- 기본은 dry-run. 실제 반영은 --apply 플래그.

사용:
  cd backend && .venv/Scripts/python.exe scripts/backfill_policy_to_missing_products.py --policy "가디정책"
  cd backend && .venv/Scripts/python.exe scripts/backfill_policy_to_missing_products.py --policy "가디정책" --apply
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from backend.db.orm import get_write_session


BATCH_SIZE = 1000


def calc_price(
    base: int, pricing: dict, source_site: str | None, is_point_restricted
) -> int:
    """기존 apply_policy_to_filter_products 와 동일한 단순 마크업 계산."""
    use_range = bool(pricing.get("useRangeMargin"))
    range_margins = pricing.get("rangeMargins") or []
    default_margin = pricing.get("marginRate", 15)
    shipping = pricing.get("shippingCost", 0) or 0
    extra = pricing.get("extraCharge", 0) or 0

    margin_rate = default_margin
    if use_range and range_margins:
        for r in range_margins:
            max_val = r.get("max") or 9999999999
            if base >= r.get("min", 0) and base < max_val:
                margin_rate = r.get("rate", 15)
                break

    source_margin = 0
    ssm_data = pricing.get("sourceSiteMargins") or {}
    if ssm_data and source_site:
        _ssm = ssm_data.get(source_site, {}) or {}
        _ss_rate = _ssm.get("marginRate", 0) or 0
        _ss_amount = _ssm.get("marginAmount", 0) or 0
        point_only = bool(_ssm.get("pointOnly"))
        apply_ssm = (not point_only) or (is_point_restricted is False)
        if apply_ssm:
            if _ss_rate > 0:
                source_margin += round(base * _ss_rate / 100)
            if _ss_amount > 0:
                source_margin += _ss_amount

    return int(base * (1 + margin_rate / 100) + source_margin + shipping + extra)


async def run(policy_name: str, apply: bool):
    async with get_write_session() as conn:
        # 1. 정책 조회
        res = await conn.execute(
            text("SELECT id, name, pricing FROM samba_policy WHERE name = :n"),
            {"n": policy_name},
        )
        rows = res.mappings().all()
        if not rows:
            print(f"[ERROR] '{policy_name}' 정책을 찾을 수 없음")
            return
        if len(rows) > 1:
            print(f"[WARN] 동명 정책 {len(rows)}건 — 첫 번째 사용")
        policy = rows[0]
        policy_id = policy["id"]
        pricing = policy["pricing"] or {}
        print(f"[OK] 정책: {policy['name']} (id={policy_id})")
        print(f"     pricing keys: {list(pricing.keys())}")

        # 2. 정책이 적용된 필터(그룹) 목록
        res = await conn.execute(
            text(
                "SELECT id, name FROM samba_search_filter "
                "WHERE applied_policy_id = :pid"
            ),
            {"pid": policy_id},
        )
        filters = res.mappings().all()
        print(f"[OK] 적용 그룹 수: {len(filters)}")
        if not filters:
            print("     적용된 그룹 없음 — 종료")
            return

        grand_total = 0
        grand_missing = 0
        grand_updated = 0
        grand_failed = 0

        for f in filters:
            filter_id = f["id"]
            filter_name = f["name"]

            # 그룹 전체 카운트
            res = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM samba_collected_product "
                    "WHERE search_filter_id = :fid"
                ),
                {"fid": filter_id},
            )
            total = res.scalar_one()

            # 누락 카운트 (applied_policy_id 다름 OR market_prices.default 비어있음)
            res = await conn.execute(
                text(
                    "SELECT COUNT(*) FROM samba_collected_product "
                    "WHERE search_filter_id = :fid "
                    "  AND ( applied_policy_id IS DISTINCT FROM :pid "
                    "       OR market_prices IS NULL "
                    "       OR market_prices->>'default' IS NULL "
                    "       OR market_prices->>'default' = '' )"
                ),
                {"fid": filter_id, "pid": policy_id},
            )
            missing = res.scalar_one()

            grand_total += total
            grand_missing += missing
            print(
                f"\n[GROUP] {filter_name} (id={filter_id})  total={total}  missing={missing}"
            )
            if missing == 0:
                continue

            # 누락 상품을 cursor 페이지네이션으로 처리 (id는 ULID 문자열)
            last_id = ""
            processed = 0
            while True:
                res = await conn.execute(
                    text(
                        "SELECT id, sale_price, original_price, source_site, "
                        "       is_point_restricted, applied_policy_id, market_prices "
                        "FROM samba_collected_product "
                        "WHERE search_filter_id = :fid AND id > :lid "
                        "  AND ( applied_policy_id IS DISTINCT FROM :pid "
                        "       OR market_prices IS NULL "
                        "       OR market_prices->>'default' IS NULL "
                        "       OR market_prices->>'default' = '' ) "
                        "ORDER BY id ASC LIMIT :lim"
                    ),
                    {
                        "fid": filter_id,
                        "lid": last_id,
                        "pid": policy_id,
                        "lim": BATCH_SIZE,
                    },
                )
                batch = res.mappings().all()
                if not batch:
                    break

                for p in batch:
                    last_id = p["id"]
                    base = p["sale_price"] or p["original_price"] or 0
                    if base <= 0:
                        grand_failed += 1
                        print(f"     [SKIP] id={p['id']} base price=0")
                        continue
                    try:
                        calc = calc_price(
                            base, pricing, p["source_site"], p["is_point_restricted"]
                        )
                        mp = dict(p["market_prices"] or {})
                        mp["default"] = calc

                        if apply:
                            # 별도 세션으로 row-level update (실패가 다른 상품에 영향 안 주도록)
                            async with get_write_session() as wconn:
                                await wconn.execute(
                                    text(
                                        "UPDATE samba_collected_product "
                                        "SET applied_policy_id = :pid, "
                                        "    market_prices = CAST(:mp AS jsonb) "
                                        "WHERE id = :id"
                                    ),
                                    {
                                        "pid": policy_id,
                                        "mp": _json_dumps(mp),
                                        "id": p["id"],
                                    },
                                )
                                await wconn.commit()
                        grand_updated += 1
                    except Exception as e:
                        grand_failed += 1
                        print(f"     [FAIL] id={p['id']} err={e}")

                processed += len(batch)
                print(f"     ...{processed}건 처리됨 (last_id={last_id})")

        print("\n" + "=" * 60)
        print(f"전체 그룹: {len(filters)}")
        print(f"전체 상품: {grand_total}")
        print(f"누락 상품: {grand_missing}")
        print(f"갱신 대상: {grand_updated}  ({'반영' if apply else 'dry-run'})")
        print(f"실패/스킵: {grand_failed}")
        print("=" * 60)


def _json_dumps(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, help="정책 이름 (예: 가디정책)")
    ap.add_argument(
        "--apply", action="store_true", help="실제 DB 반영 (기본은 dry-run)"
    )
    args = ap.parse_args()
    asyncio.run(run(args.policy, args.apply))


if __name__ == "__main__":
    main()
