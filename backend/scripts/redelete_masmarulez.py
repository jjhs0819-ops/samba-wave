"""마스마룰즈 잔존 415건 마켓삭제 재시도.

이전 풀 고갈로 실패한 건들을 service.delete_from_markets 직접 호출로 재시도.
프로덕션 컨테이너에서 실행: /app/backend/.venv/bin/python /tmp/redelete_masmarulez.py
"""

import asyncio
import logging
import sys
from sqlalchemy import select, func

from backend.db.orm import get_write_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP
from backend.domain.samba.shipment.service import SambaShipmentService
from backend.domain.samba.shipment.repository import SambaShipmentRepository

ACCOUNT_ID = "ma_01KQRRXMFD9W4WG81MGRME9YBP"  # 스마트스토어 차놀

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)


async def main() -> None:
    # 1) 잔존 상품 조회
    target_ids: list[str] = []
    async with get_write_session() as session:
        like = func.btrim(CP.brand).ilike("%마스마룰즈%") | func.btrim(CP.brand).ilike(
            "%masmarulez%"
        )
        stmt = select(CP.id, CP.registered_accounts).where(like)
        rows = (await session.execute(stmt)).all()
        for r in rows:
            ra = r.registered_accounts
            if isinstance(ra, list) and ACCOUNT_ID in ra:
                target_ids.append(r.id)

    print(f"[재삭제] 대상 {len(target_ids)}건", flush=True)
    if not target_ids:
        print("[재삭제] 대상 없음 — 종료")
        return

    ok = 0
    fail = 0
    fail_msgs: dict[str, int] = {}

    # 2) 100건씩 청크로 service 호출 (한 번에 너무 큰 트랜잭션 방지)
    CHUNK = 50
    for i in range(0, len(target_ids), CHUNK):
        chunk = target_ids[i : i + CHUNK]
        async with get_write_session() as session:
            svc = SambaShipmentService(SambaShipmentRepository(session), session)
            try:
                result = await svc.delete_from_markets(chunk, [ACCOUNT_ID])
            except Exception as e:
                fail += len(chunk)
                fail_msgs[f"chunk_exception:{type(e).__name__}"] = fail_msgs.get(
                    f"chunk_exception:{type(e).__name__}", 0
                ) + len(chunk)
                print(f"  [chunk {i // CHUNK + 1}] 전체 예외: {e!r}", flush=True)
                continue

            for entry in result.get("results", []):
                drs = entry.get("delete_results", {})
                if not drs:
                    fail += 1
                    fail_msgs["no_delete_results"] = (
                        fail_msgs.get("no_delete_results", 0) + 1
                    )
                    continue
                status = drs.get(ACCOUNT_ID, "")
                if status == "success":
                    ok += 1
                elif status == "soldout_fallback":
                    fail += 1
                    fail_msgs["soldout_fallback"] = (
                        fail_msgs.get("soldout_fallback", 0) + 1
                    )
                else:
                    fail += 1
                    msg = (status or "")[:60]
                    fail_msgs[msg] = fail_msgs.get(msg, 0) + 1

        print(
            f"  [chunk {i // CHUNK + 1}/{(len(target_ids) + CHUNK - 1) // CHUNK}] 누적 OK={ok}, FAIL={fail}",
            flush=True,
        )

    print(f"\n[재삭제 완료] 성공 {ok}건 / 실패 {fail}건")
    if fail_msgs:
        print("[실패 메시지 분포]")
        for msg, c in sorted(fail_msgs.items(), key=lambda x: -x[1]):
            print(f"  {c:>4}건 :: {msg}")


if __name__ == "__main__":
    asyncio.run(main())
