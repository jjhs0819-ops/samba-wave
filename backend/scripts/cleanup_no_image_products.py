"""이미지 없는 마켓 등록 상품 정리 스크립트.

실행 순서:
  1. images 없음 + registered_accounts 있음 조회
  2. 마켓별 삭제 API 호출
  3. DB에서 상품 삭제

실행:
  docker cp cleanup_no_image_products.py samba-samba-api-1:/tmp/
  docker exec samba-samba-api-1 /app/backend/.venv/bin/python3 /tmp/cleanup_no_image_products.py
"""

import asyncio
import json
import sys

import asyncpg
from sqlalchemy import text


async def get_db_url() -> str:
    from backend.core.config import settings

    return (
        f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}"
        f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
    )


async def main() -> None:
    sys.path.insert(0, "/app/backend")
    url = await get_db_url()

    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        ssl=False,
        database=None,
        user=None,
        password=None,
        dsn=url,
    )

    try:
        # 이미지 없음 + 마켓 등록된 상품 조회
        rows = await conn.fetch(
            """
            SELECT id, name, source_site, site_product_id,
                   registered_accounts, market_product_nos
            FROM samba_collected_product
            WHERE (images IS NULL OR images = '[]'::jsonb)
              AND registered_accounts IS NOT NULL
              AND jsonb_array_length(registered_accounts) > 0
            ORDER BY created_at
            """
        )

        if not rows:
            print("[완료] 이미지 없는 마켓 등록 상품 없음.")
            return

        print(f"\n[조회] 이미지 없는 등록 상품: {len(rows)}건\n")
        for r in rows:
            accs = (
                json.loads(r["registered_accounts"]) if r["registered_accounts"] else []
            )
            print(
                f"  - {r['id']} | {r['source_site']} | {r['name'][:50]} | 등록계정: {len(accs)}개"
            )

        print(f"\n상기 {len(rows)}건을 마켓삭제 후 DB 삭제합니다.")
        confirm = input("계속하려면 'DELETE' 입력: ").strip()
        if confirm != "DELETE":
            print("취소.")
            return

        # --- 마켓 삭제 ---
        # 각 상품의 등록 계정별로 마켓 삭제 API 호출
        from backend.db.orm import get_write_session
        from backend.domain.samba.shipment.service import SambaShipmentService
        from backend.domain.samba.shipment.repository import SambaShipmentRepository

        market_fail: list[str] = []
        market_ok: list[str] = []

        for row in rows:
            pid = row["id"]
            reg_accounts = (
                json.loads(row["registered_accounts"])
                if row["registered_accounts"]
                else []
            )
            if not reg_accounts:
                market_ok.append(pid)
                continue

            print(
                f"\n[마켓삭제] {pid} — {row['name'][:40]} ({len(reg_accounts)}개 계정)"
            )
            try:
                async with get_write_session() as session:
                    shipment_repo = SambaShipmentRepository(session)
                    svc = SambaShipmentService(shipment_repo, session)
                    result = await svc.delete_from_markets(
                        product_ids=[pid],
                        target_account_ids=reg_accounts,
                        log_to_buffer=False,
                    )
                    failed = [
                        r
                        for r in (result.get("results") or [])
                        if r.get("status") == "failed"
                    ]
                    if failed:
                        print(f"  ⚠ 마켓삭제 일부 실패: {failed}")
                        market_fail.append(pid)
                    else:
                        print("  ✓ 마켓삭제 성공")
                        market_ok.append(pid)
            except Exception as e:
                print(f"  ✗ 마켓삭제 예외: {e}")
                market_fail.append(pid)

        print(
            f"\n[마켓삭제 완료] 성공: {len(market_ok)}건 / 실패: {len(market_fail)}건"
        )

        # 마켓삭제 성공 상품만 DB 삭제
        to_delete = [pid for pid in market_ok]
        if not to_delete:
            print("[중단] 마켓삭제 성공 상품 없음 — DB 삭제 건너뜀.")
            return

        print(f"\n[DB삭제] {len(to_delete)}건 삭제 시작...")
        try:
            async with get_write_session() as session:
                result = await session.execute(
                    text("DELETE FROM samba_collected_product WHERE id = ANY(:ids)"),
                    {"ids": to_delete},
                )
                deleted = result.rowcount
                await session.commit()
            print(f"  ✓ DB 삭제 완료: {deleted}건")
        except Exception as e:
            print(f"  ✗ DB 삭제 실패: {e}")

        if market_fail:
            print(f"\n[미처리] 마켓삭제 실패 {len(market_fail)}건 — 수동 확인 필요:")
            for pid in market_fail:
                print(f"  - {pid}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
