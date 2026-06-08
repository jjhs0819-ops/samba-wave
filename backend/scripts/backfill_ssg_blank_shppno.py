"""SSG 주문 shipment_id 가 shppNo 없는 "|seq" 로 깨진 건을 정상 "shppNo|shppSeq" 로 복구.

배경 (이슈 #382):
    SSG 취소신청 동기화가 shppNo 없는 "|ordItemSeq" 형식 shipment_id 를 만들고, 같은 주문이
    출고대기 목록과 취소신청 목록에 동시 존재하면 정상 "shppNo|shppSeq" 를 "|seq" 가 덮어썼다.
    이후 송장 전송이 "SSG shppNo/shppSeq 누락" 으로 전면 실패한다.
    저장루프 가드(order.py)로 신규 동기화는 차단되지만, 이미 깨진 누적분은 이 스크립트로 복구한다.

복구 방법:
    계정별로 SSG 출고처리(listWarehouseOut)·배송지시(listShppDirection) 목록을 다시 조회해
    order_number → "shppNo|shppSeq" 맵을 만들고, 깨진 주문의 order_number 로 매칭해 채운다.
    (취소/배송 단계가 지나 목록에 없는 건은 복구 불가 — unrecovered 로 보고)

사용법 (프로덕션 VM 컨테이너):
    # 1) DRY-RUN — 깨진 건 수 + 복구 가능 수 확인
    docker exec samba-samba-api-1 /app/backend/.venv/bin/python \
        -m backend.scripts.backfill_ssg_blank_shppno --dry-run

    # 2) 실제 UPDATE
    docker exec samba-samba-api-1 /app/backend/.venv/bin/python \
        -m backend.scripts.backfill_ssg_blank_shppno --apply

옵션:
    --days N   SSG 목록 재조회 기간(기본 180, SSG API 최대치)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from backend.db.orm import get_write_session


async def _build_recover_map(account, days: int) -> dict[str, str]:
    """계정 1개의 출고처리+배송지시 목록 → {order_number: "shppNo|shppSeq"} 맵.

    shppNo 가 빈 항목은 제외(복구 소스로 무의미).
    """
    from backend.domain.samba.proxy.ssg import SSGClient

    extras = account.additional_fields or {}
    if not isinstance(extras, dict):
        extras = {}
    api_key = extras.get("apiKey", "") or account.api_key or ""
    if not api_key:
        return {}

    client = SSGClient(api_key)
    mapping: dict[str, str] = {}
    try:
        raws: list[dict] = []
        try:
            raws += await client.get_warehouse_out_orders(days=days)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] get_warehouse_out_orders 실패: {e}")
        try:
            raws += await client.get_orders(days=days)
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] get_orders 실패: {e}")

        label = account.account_label or ""
        for ro in raws:
            parsed = client.parse_order(ro, account.id, label, fee_rate=0.0)
            sid = str(parsed.get("shipment_id") or "")
            onum = str(parsed.get("order_number") or "")
            # shppNo 가 비어있지 않은(=정상) 것만 채택
            if onum and sid and not sid.startswith("|") and sid.split("|")[0]:
                mapping[onum] = sid
    finally:
        await client.close()
    return mapping


async def _run(dry_run: bool, days: int) -> int:
    from backend.domain.samba.account.repository import SambaMarketAccountRepository

    async with get_write_session() as session:
        # 깨진 SSG 주문 조회 — shipment_id 가 "|" 로 시작(shppNo 빈값)
        result = await session.execute(
            text(
                """
                SELECT id, order_number, channel_id, channel_name,
                       shipment_id, status, shipping_status
                FROM samba_order
                WHERE source = 'ssg'
                  AND shipment_id LIKE '|%'
                ORDER BY channel_id
                """
            )
        )
        broken = result.fetchall()
        total = len(broken)
        print(f"[조회] 깨진 SSG 주문(shppNo 빈값): {total:,}건")
        if not total:
            return 0

        # 채널(계정)별 그룹화
        by_channel: dict[str, list] = {}
        for row in broken:
            by_channel.setdefault(str(row.channel_id or ""), []).append(row)

        repo = SambaMarketAccountRepository(session)
        recovered = 0
        unrecovered = 0
        no_account = 0

        for channel_id, rows in by_channel.items():
            if not channel_id:
                no_account += len(rows)
                print(f"  [skip] channel_id 없음: {len(rows):,}건")
                continue
            account = await repo.get_async(channel_id)
            if not account:
                no_account += len(rows)
                print(
                    f"  [skip] 계정 조회 실패 channel_id={channel_id}: {len(rows):,}건"
                )
                continue

            label = account.account_label or channel_id
            print(f"  [계정] {label} — 깨진 {len(rows):,}건, SSG 목록 재조회 중...")
            rmap = await _build_recover_map(account, days)
            print(f"    재조회 맵: {len(rmap):,}건 (shppNo 보유)")

            for row in rows:
                onum = str(row.order_number or "")
                new_sid = rmap.get(onum)
                if not new_sid:
                    unrecovered += 1
                    continue
                print(
                    f"    복구 order={onum} {row.shipment_id!r} → {new_sid!r}"
                    + (" [DRY]" if dry_run else "")
                )
                if not dry_run:
                    await session.execute(
                        text(
                            "UPDATE samba_order SET shipment_id = :sid WHERE id = :oid"
                        ),
                        {"sid": new_sid, "oid": row.id},
                    )
                recovered += 1

        if not dry_run:
            await session.commit()

        print("\n===== 결과 =====")
        print(f"  깨진 건:        {total:,}")
        print(
            f"  복구:           {recovered:,}"
            + (" (DRY-RUN, 미적용)" if dry_run else "")
        )
        print(f"  복구불가(목록無): {unrecovered:,}")
        print(f"  계정없음:       {no_account:,}")
        return recovered


def main() -> None:
    parser = argparse.ArgumentParser()
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="영향 범위만 확인(미적용)")
    g.add_argument("--apply", action="store_true", help="실제 UPDATE 실행")
    parser.add_argument(
        "--days", type=int, default=180, help="SSG 목록 재조회 기간(기본 180)"
    )
    args = parser.parse_args()

    dry_run = not args.apply
    recovered = asyncio.run(_run(dry_run, args.days))
    if dry_run:
        print("\n[DRY-RUN] 실제 적용하려면 --apply 로 재실행")
    sys.exit(0 if recovered >= 0 else 1)


if __name__ == "__main__":
    main()
