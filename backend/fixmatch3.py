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
    OVR = {
        "id",
        "source_site",
        "site_product_id",
        "name",
        "options",
        "cost",
        "sale_price",
        "original_price",
        "resell_matches",
        "updated_at",
    }
    async with get_write_session() as s:
        # 팩 매칭해제 + 거부
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
                "UPDATE samba_collected_product SET resell_matches=resell_matches-'kream'-'kream_candidates', updated_at=NOW() WHERE source_site='SNKRDUNK' AND site_product_id=:p"
            ),
            {"p": PACK},
        )
        # 742030 신규행 — 덮어쓸 컬럼 제외 클론
        exists = (
            await s.execute(
                T(
                    "SELECT count(*) FROM samba_collected_product WHERE site_product_id=:b AND source_site='SNKRDUNK'"
                ),
                {"b": BOX},
            )
        ).scalar_one()
        if exists == 0:
            rest = (
                await s.execute(
                    T(
                        "SELECT array_agg(column_name ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='samba_collected_product'"
                    )
                )
            ).scalar_one()
            rest = [c for c in rest if c not in OVR]
            rc = ",".join(f'"{c}"' for c in rest)
            nid = generate_collected_product_id()
            sql = f"""INSERT INTO samba_collected_product
                (id,source_site,site_product_id,name,options,cost,sale_price,original_price,resell_matches,updated_at,{rc})
                SELECT :nid,'SNKRDUNK',:b,:nm,CAST(:opt AS jsonb),39000,39000,39000,
                       jsonb_build_object('kream',CAST(:km AS jsonb)),NOW(),{rc}
                FROM samba_collected_product WHERE site_product_id=:p AND source_site='SNKRDUNK' LIMIT 1"""
            await s.execute(
                T(sql),
                {
                    "nid": nid,
                    "b": BOX,
                    "nm": box_name,
                    "opt": json.dumps(box_opts, ensure_ascii=False),
                    "km": km,
                    "p": PACK,
                },
            )
        await s.commit()
        print(
            "사후:",
            (
                await s.execute(
                    T(
                        "SELECT site_product_id, resell_matches->'kream'->>'product_id' 크림, left(name,42), left(options::text,55) FROM samba_collected_product WHERE site_product_id IN (:p,:b) AND source_site='SNKRDUNK'"
                    ),
                    {"p": PACK, "b": BOX},
                )
            ).all(),
        )
        print(
            "거부등록:",
            (
                await s.execute(
                    T(
                        "SELECT snkr_id,kream_pid FROM kream_snkr_rejected WHERE snkr_id=:p"
                    ),
                    {"p": PACK},
                )
            ).all(),
        )


asyncio.run(main())
