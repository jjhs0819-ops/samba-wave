"""무신사 품절 + 원본 msscdn URL(404) + 마켓등록 상품 정리.

- 마켓 삭제 후 DB 삭제 자동 실행 (확인 없이)
- 대상: MUSINSA + sold_out + registered + msscdn 원본 URL(R2 미러 아님)

실행:
  docker cp cleanup_musinsa_404_images.py samba-samba-api-1:/tmp/
  docker exec samba-samba-api-1 /app/backend/.venv/bin/python3 /tmp/cleanup_musinsa_404_images.py
"""

import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")


async def main() -> None:
    import asyncpg
    from sqlalchemy import text

    from backend.core.config import settings
    from backend.db.orm import get_write_session
    from backend.domain.samba.shipment.repository import SambaShipmentRepository
    from backend.domain.samba.shipment.service import SambaShipmentService

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    try:
        rows = await conn.fetch(
            """
            SELECT id, name, registered_accounts
            FROM samba_collected_product
            WHERE source_site = 'MUSINSA'
              AND sale_status = 'sold_out'
              AND registered_accounts IS NOT NULL
              AND registered_accounts::text NOT IN ('[]', 'null', '')
              AND images IS NOT NULL
              AND images::text != '[]'
              AND images::text NOT LIKE '%samba-wave%'
              AND images::text NOT LIKE '%r2.cloudflarestorage%'
            ORDER BY updated_at DESC
            """
        )
    finally:
        await conn.close()

    if not rows:
        print("[완료] 대상 없음.")
        return

    print(f"[대상] {len(rows)}건\n")

    market_ok: list[str] = []
    market_fail: list[str] = []

    for row in rows:
        pid = row["id"]
        reg_accounts = (
            json.loads(row["registered_accounts"]) if row["registered_accounts"] else []
        )
        name = str(row["name"] or "")[:50]

        if not reg_accounts:
            market_ok.append(pid)
            continue

        print(f"[마켓삭제] {pid} | {name} | 계정:{len(reg_accounts)}개")
        try:
            async with get_write_session() as session:
                svc = SambaShipmentService(SambaShipmentRepository(session), session)
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
                    print(f"  ⚠ 일부 실패: {failed}")
                    market_fail.append(pid)
                else:
                    print("  ✓ 마켓삭제 성공")
                    market_ok.append(pid)
        except Exception as e:
            print(f"  ✗ 예외: {e}")
            market_fail.append(pid)

    print(f"\n[마켓삭제] 성공:{len(market_ok)} / 실패:{len(market_fail)}")

    if not market_ok:
        print("[중단] 마켓삭제 성공 없음 — DB 삭제 건너뜀.")
        return

    print(f"\n[DB삭제] {len(market_ok)}건...")
    try:
        async with get_write_session() as session:
            result = await session.execute(
                text("DELETE FROM samba_collected_product WHERE id = ANY(:ids)"),
                {"ids": market_ok},
            )
            deleted = result.rowcount
            await session.commit()
        print(f"  ✓ DB 삭제 완료: {deleted}건")
    except Exception as e:
        print(f"  ✗ DB 삭제 실패: {e}")

    if market_fail:
        print(f"\n[미처리] 마켓삭제 실패 {len(market_fail)}건:")
        for pid in market_fail:
            print(f"  - {pid}")


if __name__ == "__main__":
    asyncio.run(main())
