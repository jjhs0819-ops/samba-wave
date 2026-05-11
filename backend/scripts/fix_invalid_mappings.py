"""트리에 없는 매핑 경로를 NULL로 비우기 (옵션 A).

audit_invalid_mappings.py의 결과(/tmp/invalid_mappings.json)를 읽어서
잘못된 (mapping_id, market) 키만 target_mappings에서 제거.
사이드이펙트: 해당 마켓 등록 시 '미매핑' 표시 → 사용자 재매핑 유도.
"""

import asyncio
import asyncpg
import json
from backend.core.config import settings


async def main() -> None:
    with open("/tmp/invalid_mappings.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    invalid_rows = data["rows"]
    print(f"수정 대상: {len(invalid_rows)}행")

    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        async with conn.transaction():
            updated = 0
            removed_keys = 0
            for row in invalid_rows:
                mid = row["id"]
                invalid_markets = list(row["invalid"].keys())
                if not invalid_markets:
                    continue
                # 현재 target_mappings 다시 읽기 (audit 이후 변동 가능성 대비)
                rec = await conn.fetchrow(
                    "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
                    mid,
                )
                if not rec:
                    continue
                tm = rec["target_mappings"]
                if isinstance(tm, str):
                    try:
                        tm = json.loads(tm)
                    except Exception:
                        tm = None
                if not isinstance(tm, dict):
                    continue
                changed = False
                for mk in invalid_markets:
                    if mk in tm:
                        del tm[mk]
                        removed_keys += 1
                        changed = True
                if changed:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(tm, ensure_ascii=False),
                        mid,
                    )
                    updated += 1
            print(f"수정 완료: {updated}행, 제거된 마켓 키: {removed_keys}개")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
