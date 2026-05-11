"""MUSINSA batch3."""
import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KPN11JA2797P1KF0B4A6G8W2": {"lotteon": "브랜드언더웨어 > 홈웨어/이지웨어 > 홈웨어하의 > 여성용"},
    "cm_01KN0QA0D1BGXD4SEQREQE29VV": {"lotteon": "스포츠의류/운동화 > 스포츠잡화 > 기타"},
    "cm_01KQV6GWB70BTNZYZZ5EREHMJ4": {
        "11st": "여성의류 > 바지/팬츠 > 점프슈트",
        "lotteon": "여성의류 > 원피스 > 점프슈트",
    },
    "cm_01KMY3TMF2YSA2VP4F5G739ARK": {"lotteon": "스포츠의류/운동화 > 스포츠가방 > 토트백 > 남성용"},
    "cm_01KMY3MJCXQRPV9VFW74NT0TSB": {"lotteon": "스포츠의류/운동화 > 스포츠잡화 > 마스크/버프"},
    "cm_01KMY3MFB11HHXBC1EBKKTWF8A": {"lotteon": "스포츠의류/운동화 > 기능성웨어 > 상의 > 남성용"},
    "cm_01KQV6GWBWMG5KY3D4K3GH7R3E": {
        "11st": "재활운동용품 > 스포츠테이프 > 스포츠테이프",
        "coupang": "스포츠/레져 > 헬스/요가 > 헬스기구/용품 > 스포츠테이프",
        "smartstore": "스포츠/레저 > 보호용품 > 스포츠테이프",
    },
    "cm_01KQV6GW0FR45GK8735DVRWYYR": {
        "11st": "전동레저/인라인/킥보드 > 보드 용품/잡화 > 보호대",
        "auction": "스포츠의류/운동화 > 스포츠보호용품 > 무릎보호대",
        "coupang": "스포츠/레져 > 헬스/요가 > 헬스기구/용품 > 헬스보호대",
        "gmarket": "스포츠의류/운동화 > 스포츠보호용품 > 손목보호대",
        "lotteon": "스포츠의류/운동화 > 스포츠보호용품 > 무릎보호대",
        "smartstore": "스포츠/레저 > 보호용품 > 머리보호대",
    },
    "cm_01KQV6GW4JJT1X7H2PK98A0ZHX": {
        "11st": "수영/수상레저 > 비치수영복 > 여성비치웨어 > 비치웨어",
        "auction": "여성의류 > 수영복/비치웨어 > 수영복",
        "coupang": "스포츠/레져 > 수영/수상스포츠 > 수영복 > 여성용 > 커버업/비치웨어",
        "gmarket": "여성의류 > 수영복/비치웨어 > 수영복",
        "lotteon": "브랜드진/캐주얼 > 시즌웨어 > 수영복/비치웨어 > 여성수영복",
        "smartstore": "스포츠/레저 > 수영 > 비치웨어 > 원피스",
    },
    "cm_01KQW2DZN2TJX0R6KZKXN3FSX3": {
        "11st": "주방용품 > 주방수납용품 > 수납바구니/정리함",
        "coupang": "생활용품 > 수납/정리 > 행거 > 일반형행거",
        "lotteon": "주방용품 > 주방수납용품 > 주방정리소품",
        "smartstore": "생활/건강 > 주방용품 > 주방수납용품 > 주방정리소품",
    },
}

async def main():
    conn = await asyncpg.connect(host="172.18.0.2", port=5432, user=settings.write_db_user, password=settings.write_db_password, database=settings.write_db_name, ssl=False)
    try:
        tree_rows = await conn.fetch("SELECT site_name, cat1, cat2 FROM samba_category_tree")
        mv = {}
        for r in tree_rows:
            c1, c2 = r["cat1"], r["cat2"]
            if isinstance(c1, str): c1 = json.loads(c1)
            if isinstance(c2, str): c2 = json.loads(c2)
            p = set()
            if isinstance(c1, list): p.update(x for x in c1 if isinstance(x, str))
            if isinstance(c2, dict): p.update(k for k in c2.keys() if isinstance(k, str))
            elif isinstance(c2, list): p.update(x for x in c2 if isinstance(x, str))
            mv[r["site_name"]] = p
        rows_u, keys_a, rej = 0, 0, []
        async with conn.transaction():
            for mid, add in D.items():
                rec = await conn.fetchrow("SELECT target_mappings FROM samba_category_mapping WHERE id=$1", mid)
                if not rec: continue
                tm = rec["target_mappings"]
                if isinstance(tm, str): tm = json.loads(tm)
                if not isinstance(tm, dict): tm = {}
                merged = dict(tm); n = 0
                for mk, path in add.items():
                    if isinstance(merged.get(mk), str) and merged[mk].strip(): continue
                    if path not in mv.get(mk, set()):
                        rej.append(f"{mid} {mk}: {path}"); continue
                    merged[mk] = path; n += 1
                if n:
                    await conn.execute("UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2", json.dumps(merged, ensure_ascii=False), mid)
                    rows_u += 1; keys_a += n
        print(f"MUSINSA b3: 행 {rows_u}, 키 {keys_a}")
        if rej:
            for r in rej[:5]: print(f"  미일치: {r}")
    finally:
        await conn.close()

asyncio.run(main())
