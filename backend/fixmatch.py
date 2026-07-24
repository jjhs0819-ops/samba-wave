"""오매칭 수정 — 크림945312(박스)를 팩742031서 떼고 박스742030에 매칭."""

import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


async def main():
    from sqlalchemy import text as T
    from backend.db.orm import get_write_session

    KID = "945312"
    PACK = "742031"
    BOX = "742030"
    box_opts = [
        {"name": "1個", "price": 39000, "stock": 3},
        {"name": "2個", "price": 93000, "stock": 1},
        {"name": "3個", "price": 140000, "stock": 1},
        {"name": "4個", "price": 170000, "stock": 1},
    ]
    box_name = 'UNION ARENA Booster Pack "Kagurabachi" Box'
    async with get_write_session() as s:
        # 0) 사전 상태
        r = (
            await s.execute(
                T(
                    "SELECT site_product_id, resell_matches->'kream'->>'product_id' FROM samba_collected_product WHERE site_product_id IN (:p,:b) AND source_site='SNKRDUNK'"
                ),
                {"p": PACK, "b": BOX},
            )
        ).all()
        print("사전:", r)
        # 1) 팩 매칭해제 + 거부등록
        await s.execute(
            T(
                """CREATE TABLE IF NOT EXISTS kream_snkr_rejected (snkr_id text NOT NULL, kream_pid text NOT NULL, reason text, rejected_at timestamptz DEFAULT now(), PRIMARY KEY (snkr_id, kream_pid))"""
            )
        )
        await s.execute(
            T(
                "INSERT INTO kream_snkr_rejected (snkr_id,kream_pid,reason) VALUES (:p,:k,'오매칭수정-팩→박스') ON CONFLICT DO NOTHING"
            ),
            {"p": PACK, "k": KID},
        )
        await s.execute(
            T(
                "UPDATE samba_collected_product SET resell_matches = resell_matches - 'kream' - 'kream_candidates', updated_at=NOW() WHERE source_site='SNKRDUNK' AND site_product_id=:p"
            ),
            {"p": PACK},
        )
        # 2) 742030 정상행 생성 — 742031(팩) 클론 후 덮어쓰기
        exists = (
            await s.execute(
                T(
                    "SELECT count(*) FROM samba_collected_product WHERE site_product_id=:b AND source_site='SNKRDUNK'"
                ),
                {"b": BOX},
            )
        ).scalar_one()
        if exists == 0:
            await s.execute(
                T("""
                INSERT INTO samba_collected_product
                SELECT * FROM samba_collected_product WHERE site_product_id=:p AND source_site='SNKRDUNK' LIMIT 1
            """),
                {"p": PACK},
            )
            # 클론된 새 행을 BOX 값으로 교정 (id는 클론돼 충돌 → 새 id 필요할 수 있음)
        # 위 INSERT는 PK(id) 충돌 위험 — 대신 명시 컬럼 INSERT
        await s.rollback()
    # 재시도: 명시 컬럼 방식
    async with get_write_session() as s2:
        # 팩 해제 재적용(롤백됐으므로)
        await s2.execute(
            T(
                "INSERT INTO kream_snkr_rejected (snkr_id,kream_pid,reason) VALUES (:p,:k,'오매칭수정-팩→박스') ON CONFLICT DO NOTHING"
            ),
            {"p": PACK, "k": KID},
        )
        await s2.execute(
            T(
                "UPDATE samba_collected_product SET resell_matches = resell_matches - 'kream' - 'kream_candidates', updated_at=NOW() WHERE source_site='SNKRDUNK' AND site_product_id=:p"
            ),
            {"p": PACK},
        )
        # 클론 컬럼 목록(자동생성/PK 제외)
        cols = (
            await s2.execute(
                T(
                    "SELECT string_agg(column_name,',') FROM information_schema.columns WHERE table_name='samba_collected_product' AND column_name NOT IN ('id')"
                )
            )
        ).scalar_one()
        exists = (
            await s2.execute(
                T(
                    "SELECT count(*) FROM samba_collected_product WHERE site_product_id=:b AND source_site='SNKRDUNK'"
                ),
                {"b": BOX},
            )
        ).scalar_one()
        if exists == 0:
            await s2.execute(
                T(
                    f"INSERT INTO samba_collected_product ({cols}) SELECT {cols} FROM samba_collected_product WHERE site_product_id=:p AND source_site='SNKRDUNK'"
                ),
                {"p": PACK},
            )
        # BOX 행 교정: site_product_id, name, options, cost, resell_matches(945312 매칭)
        km = (
            await s2.execute(
                T(
                    "SELECT resell_matches->'kream' FROM samba_collected_product WHERE site_product_id=:p AND source_site='SNKRDUNK'"
                ),
                {"p": PACK},
            )
        ).scalar_one_or_none()
        # 팩은 방금 해제됨 → km None. 945312 매칭 새로 구성
        new_km = {"product_id": KID, "style_code": "UA46BT"}
        await s2.execute(
            T("""
            UPDATE samba_collected_product
            SET site_product_id=:b, name=:nm, options=CAST(:opt AS jsonb), cost=39000, sale_price=39000,
                resell_matches=jsonb_build_object('kream', CAST(:km AS jsonb)), updated_at=NOW()
            WHERE site_product_id=:p AND source_site='SNKRDUNK' AND resell_matches IS NOT NULL AND site_product_id<>:b
        """),
            {
                "b": BOX,
                "nm": box_name,
                "opt": json.dumps(box_opts, ensure_ascii=False),
                "km": json.dumps(new_km),
                "p": PACK,
            },
        )
        await s2.commit()
        # 검증
        chk = (
            await s2.execute(
                T(
                    "SELECT site_product_id, resell_matches->'kream'->>'product_id', left(name,40), left(options::text,60) FROM samba_collected_product WHERE site_product_id IN (:p,:b) AND source_site='SNKRDUNK'"
                ),
                {"p": PACK, "b": BOX},
            )
        ).all()
        print("사후:", chk)


asyncio.run(main())
