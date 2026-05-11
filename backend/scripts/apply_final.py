"""잔여 26 빈 칸 LLM 직접 결정."""

import asyncio
import asyncpg
import json
from backend.core.config import settings

D = {
    "cm_01KR5E6C6EVCC2AWBV8HV1S5NX": {
        "auction": "스포츠의류/운동화 > 스포츠화 > 런닝화"
    },
    "cm_01KPPTX18XVA5TXC5A27JS5Q2A": {"lotteon": "언더웨어 > 여성속옷소품 > 브라패드"},
    "cm_01KR5BBW39TZKGCMV7DQB03E4M": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 여행용가방 > 수화물용캐리어"
    },
    "cm_01KQV6GV51FDWEYAYSS95SCAQK": {
        "auction": "브랜드 잡화 > 패션잡화 > 양말",
        "gmarket": "브랜드 잡화 > 패션잡화 > 양말",
    },
    "cm_01KQV73T3P0BY535WNQR2CTNAM": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼"
    },
    "cm_01KR5BCAGSS95ZEQTQTR40F6CX": {
        "ssg": "신세계몰메인매장 > 남성패션 > 자켓 > 캐주얼 자켓"
    },
    "cm_01KR5BCWBCNNVW7ETZRA6KZCA2": {"smartstore": "패션의류 > 남성의류 > 점퍼"},
    "cm_01KQV73T57DGVA222AN4GKPKAT": {
        "coupang": "패션의류잡화 > 남성패션 > 해외직구 > 신발 > 남성구두",
        "lotteon": "신발 > 남성캐주얼화 > 스니커즈",
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼",
    },
    "cm_01KQV6GW97PM6E1EXPAPYDJ0GV": {"smartstore": "출산/육아 > 유아동의류 > 티셔츠"},
    "cm_01KQW2DYRSQK0BX3BA99HFJ99R": {
        "auction": "조명/인테리어 > 인테리어소품 > 캔들",
        "gmarket": "조명/인테리어 > 인테리어소품 > 캔들",
        "smartstore": "가구/인테리어 > 인테리어소품 > 캔들",
    },
    "cm_01KQV694XNV2WB85TMQA1DKE0Q": {"auction": "여성의류 > 마담의류 > 원피스"},
    "cm_01KQV73TKYB2QQZY9SYVKAAF6P": {"smartstore": "패션의류 > 여성의류 > 티셔츠"},
    "cm_01KNXGQKDB9Z29SSH1GREEG6JH": {"lotteon": "시계/주얼리 > 시계 > 남성쿼츠시계"},
    "cm_01KN9Q70HYF93AFXYVSRQ8YGZC": {"smartstore": "패션잡화 > 남성가방 > 크로스백"},
}


async def main():
    conn = await asyncpg.connect(
        host="172.18.0.2",
        port=5432,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
        ssl=False,
    )
    try:
        tree_rows = await conn.fetch(
            "SELECT site_name, cat1, cat2 FROM samba_category_tree"
        )
        mv = {}
        for r in tree_rows:
            c1, c2 = r["cat1"], r["cat2"]
            if isinstance(c1, str):
                c1 = json.loads(c1)
            if isinstance(c2, str):
                c2 = json.loads(c2)
            p = set()
            if isinstance(c1, list):
                p.update(x for x in c1 if isinstance(x, str))
            if isinstance(c2, dict):
                p.update(k for k in c2.keys() if isinstance(k, str))
            elif isinstance(c2, list):
                p.update(x for x in c2 if isinstance(x, str))
            mv[r["site_name"]] = p
        rows_u, keys_a, rej = 0, 0, []
        async with conn.transaction():
            for mid, add in D.items():
                rec = await conn.fetchrow(
                    "SELECT target_mappings FROM samba_category_mapping WHERE id=$1",
                    mid,
                )
                if not rec:
                    continue
                tm = rec["target_mappings"]
                if isinstance(tm, str):
                    tm = json.loads(tm)
                if not isinstance(tm, dict):
                    tm = {}
                merged = dict(tm)
                n = 0
                for mk, path in add.items():
                    if isinstance(merged.get(mk), str) and merged[mk].strip():
                        continue
                    if path not in mv.get(mk, set()):
                        rej.append(f"{mid} {mk}: {path}")
                        continue
                    merged[mk] = path
                    n += 1
                if n:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        mid,
                    )
                    rows_u += 1
                    keys_a += n
        print(f"final: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        for r in rej[:10]:
            print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
