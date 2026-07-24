"""오매칭 수정 — 크림945312(박스)를 팩742031 해제 후 박스742030에 매칭."""

import asyncio
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")


async def main():
    from sqlalchemy import text as T
    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import generate_collected_product_id

    KID, PACK, BOX = "945312", "742031", "742030"
    box_opts = [
        {"name": "1個", "price": 39000, "stock": 3},
        {"name": "2個", "price": 93000, "stock": 1},
        {"name": "3個", "price": 140000, "stock": 1},
        {"name": "4個", "price": 170000, "stock": 1},
    ]
    box_name = 'UNION ARENA Booster Pack "Kagurabachi" Box'
    km = json.dumps({"product_id": KID, "style_code": "UA46BT"}, ensure_ascii=False)
    async with get_write_session() as s:
        print(
            "사전:",
            (
                await s.execute(
                    T(
                        "SELECT site_product_id, resell_matches->'kream'->>'product_id' FROM samba_collected_product WHERE site_product_id IN (:p,:b) AND source_site='SNKRDUNK'"
                    ),
                    {"p": PACK, "b": BOX},
                )
            ).all(),
        )
        # 1) 팩 매칭해제 + 거부등록
        await s.execute(
            T(
                "CREATE TABLE IF NOT EXISTS kream_snkr_rejected (snkr_id text NOT NULL, kream_pid text NOT NULL, reason text, rejected_at timestamptz DEFAULT now(), PRIMARY KEY (snkr_id, kream_pid))"
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
        # 2) 742030 정상행 — 팩행 클론(새 id) 후 박스값 덮어쓰기. 컬럼 명시(id 제외).
        exists = (
            await s.execute(
                T(
                    "SELECT count(*) FROM samba_collected_product WHERE site_product_id=:b AND source_site='SNKRDUNK'"
                ),
                {"b": BOX},
            )
        ).scalar_one()
        if exists == 0:
            cols = (
                await s.execute(
                    T(
                        "SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='samba_collected_product' AND column_name<>'id'"
                    )
                )
            ).scalar_one()
            nid = generate_collected_product_id()
            await s.execute(
                T(
                    f"INSERT INTO samba_collected_product (id,{cols}) SELECT :nid,{cols} FROM samba_collected_product WHERE site_product_id=:p AND source_site='SNKRDUNK' LIMIT 1"
                ),
                {"nid": nid, "p": PACK},
            )
            await s.execute(
                T("""UPDATE samba_collected_product SET site_product_id=:b, name=:nm,
                options=CAST(:opt AS jsonb), cost=39000, sale_price=39000, original_price=39000,
                resell_matches=jsonb_build_object('kream', CAST(:km AS jsonb)), updated_at=NOW()
                WHERE id=:nid"""),
                {
                    "b": BOX,
                    "nm": box_name,
                    "opt": json.dumps(box_opts, ensure_ascii=False),
                    "km": km,
                    "nid": nid,
                },
            )
        await s.commit()
        print(
            "사후:",
            (
                await s.execute(
                    T(
                        "SELECT site_product_id, resell_matches->'kream'->>'product_id', left(name,40), left(options::text,55) FROM samba_collected_product WHERE site_product_id IN (:p,:b) AND source_site='SNKRDUNK'"
                    ),
                    {"p": PACK, "b": BOX},
                )
            ).all(),
        )


asyncio.run(main())
