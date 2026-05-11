"""유령상품 일괄 SOUT(판매중지) 처리.

입력: /tmp/lotteon_ghosts_<seller>.json (diagnose 결과)
배치: change_status(spdLst=[{spdNo, slStatCd:'SOUT'}, ...])
"""

import asyncio
import asyncpg
import json
import os
import sys
import time

sys.path.insert(0, "/app/backend")

from backend.core.config import settings
from backend.domain.samba.proxy.lotteon import LotteonClient
from backend.domain.samba.proxy.lotteon.api_client import LotteonApiError


BATCH_SIZE = 50
BATCH_DELAY = 0.5  # rate limit 회피


async def main():
    label = os.environ.get("LOTTEON_ACCOUNT_LABEL", "unclehg")
    ghosts_path = f"/tmp/lotteon_ghosts_{label}.json"
    if not os.path.exists(ghosts_path):
        print(f"[ERROR] {ghosts_path} 없음 — 먼저 diagnose_lotteon_ghost.py 실행")
        sys.exit(1)
    with open(ghosts_path, "r", encoding="utf-8") as f:
        diag = json.load(f)

    ghosts = diag.get("ghosts") or []
    print(f"[INFO] 입력 유령상품 = {len(ghosts):,}개")
    if not ghosts:
        print("[INFO] 처리할 항목 없음")
        return

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        database=settings.write_db_name,
        user=settings.write_db_user,
        password=settings.write_db_password,
    )
    row = await conn.fetchrow(
        """
    SELECT additional_fields FROM samba_market_account
    WHERE market_type='lotteon' AND seller_id=$1 LIMIT 1
    """,
        diag.get("seller_id") or "unclehg",
    )
    await conn.close()
    af = row["additional_fields"]
    if isinstance(af, str):
        af = json.loads(af)
    api_key = af["apiKey"]

    client = LotteonClient(api_key)
    await client.test_auth()

    spd_list = [g["spdNo"] for g in ghosts if g.get("spdNo")]
    success: list[str] = []
    failed: list[dict] = []

    start = time.time()
    for i in range(0, len(spd_list), BATCH_SIZE):
        batch = spd_list[i : i + BATCH_SIZE]
        payload = [{"spdNo": s, "slStatCd": "SOUT"} for s in batch]
        try:
            res = await client.change_status(payload)
            # data 배열 항목별 검증
            data = (res or {}).get("data") or []
            if not isinstance(data, list):
                data = []
            for j, item in enumerate(data):
                spd = batch[j] if j < len(batch) else item.get("spdNo", "?")
                rc = (item or {}).get("resultCode", "")
                if rc in ("", "0000", "00", "SUCCESS"):
                    success.append(spd)
                else:
                    failed.append(
                        {
                            "spdNo": spd,
                            "resultCode": rc,
                            "msg": item.get("resultMessage", ""),
                        }
                    )
            # data 응답 없으면 일괄 성공으로 간주
            if not data:
                success.extend(batch)
        except LotteonApiError as e:
            for s in batch:
                failed.append({"spdNo": s, "resultCode": "EXC", "msg": str(e)})
        except Exception as e:
            for s in batch:
                failed.append({"spdNo": s, "resultCode": "ERR", "msg": str(e)})

        elapsed = time.time() - start
        print(
            f"  batch {i // BATCH_SIZE + 1}/{(len(spd_list) + BATCH_SIZE - 1) // BATCH_SIZE} "
            f"({i + len(batch)}/{len(spd_list)}) 성공 누적={len(success):,} 실패={len(failed):,} "
            f"elapsed={elapsed:.1f}s"
        )
        await asyncio.sleep(BATCH_DELAY)

    await client.aclose()

    out_path = f"/tmp/lotteon_ghosts_{label}_result.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "total": len(spd_list),
                "success": len(success),
                "failed": len(failed),
                "failed_samples": failed[:30],
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("===== 처리 결과 =====")
    print(f"  total    : {len(spd_list):,}")
    print(f"  success  : {len(success):,}")
    print(f"  failed   : {len(failed):,}")
    print(f"  결과 파일 : {out_path}")


asyncio.run(main())
