#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlmodel import select

from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.playauto import PlayAutoApiError, PlayAutoClient


@dataclass
class TargetAccount:
    account_id: str
    label: str
    api_key: str


async def _load_accounts(account_id: str | None) -> list[TargetAccount]:
    async with get_read_session() as session:
        stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "playauto"
        )
        if account_id:
            stmt = stmt.where(SambaMarketAccount.id == account_id)
        rows = (await session.exec(stmt)).all()

    accounts: list[TargetAccount] = []
    for row in rows:
        extras = row.additional_fields or {}
        api_key = str(extras.get("apiKey", "") or row.api_key or "").strip()
        if not api_key:
            continue
        label = row.account_label or row.business_name or row.market_name or row.id
        accounts.append(
            TargetAccount(account_id=str(row.id), label=str(label), api_key=api_key)
        )
    return accounts


async def _run_one(name: str, coro) -> tuple[str, bool, str]:
    try:
        result = await coro
        summary = f"OK {type(result).__name__}"
        if isinstance(result, list):
            summary += f" len={len(result)}"
        elif isinstance(result, dict):
            summary += f" keys={list(result.keys())[:8]}"
        else:
            summary += f" value={result}"
        return name, True, summary
    except PlayAutoApiError as exc:
        return name, False, f"ERR status={exc.status} msg={exc.message}"
    except Exception as exc:
        return name, False, f"ERR {type(exc).__name__}: {exc}"


async def diagnose_account(account: TargetAccount, days: int) -> int:
    print(f"\n=== PLAYAUTO {account.label} ({account.account_id}) ===")
    client = PlayAutoClient(account.api_key)
    failures = 0
    try:
        checks = [
            ("common:getMarketList", client.get_market_list()),
            ("common:getDelivCode", client.get_deliv_codes()),
            ("common:getMatchCate", client.get_match_categories()),
            ("emp:getMallSite", client.get_mall_sites()),
            ("emp:getProducts", client.get_products(my_cate_name="SAMBA-WAVE")),
            ("emp:getOrders", client.get_orders(count=1)),
            ("emp:getOrderCount", client.get_order_count()),
        ]
        for name, coro in checks:
            check_name, ok, detail = await _run_one(name, coro)
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {check_name}: {detail}")
            if not ok:
                failures += 1

        if days > 0:
            from datetime import UTC, datetime, timedelta

            start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y%m%d")
            check_name, ok, detail = await _run_one(
                f"emp:getOrders(startDate={start_date})",
                client.get_orders(start_date=start_date, count=5),
            )
            status = "PASS" if ok else "FAIL"
            print(f"[{status}] {check_name}: {detail}")
            if not ok:
                failures += 1
    finally:
        await client.close()
    return failures


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose PlayAuto 404 issues by separating COMMON and EMP endpoints."
    )
    parser.add_argument("--account-id", help="Specific SambaMarketAccount.id to test")
    parser.add_argument("--api-key", help="Direct PlayAuto API key to test")
    parser.add_argument(
        "--label", default="direct", help="Label used with --api-key (default: direct)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Additional get_orders(startDate=YYYYMMDD) lookback days",
    )
    args = parser.parse_args()

    targets: list[TargetAccount] = []
    if args.api_key:
        targets.append(
            TargetAccount(account_id="direct", label=args.label, api_key=args.api_key)
        )
    else:
        targets = await _load_accounts(args.account_id)

    if not targets:
        print("No PlayAuto accounts with API key found.")
        return 1

    total_failures = 0
    for target in targets:
        total_failures += await diagnose_account(target, args.days)

    print(f"\nTotal failures: {total_failures}")
    return 1 if total_failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
