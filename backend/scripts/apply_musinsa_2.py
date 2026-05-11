"""MUSINSA batch2."""
import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KQV6GW57C0E7QQR6E1R1MQ5K": {
        "auction": "신발 > 여성샌들 > 스트랩샌들",
        "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성스트랩샌들",
        "gmarket": "신발 > 여성샌들 > 스트랩샌들",
        "lotteon": "신발 > 여성샌들 > 스트랩샌들",
    },
    "cm_01KN9Q700TQVYGVYDPK5WJBSXJ": {"smartstore": "패션잡화 > 남성가방 > 숄더백"},
    "cm_01KN9Q70D3Z2SNCQMNZB7D35PZ": {"smartstore": "패션잡화 > 남성가방 > 에코백"},
    "cm_01KQ6BGFGCVSQ9CERGK0XX3EJW": {"smartstore": "패션잡화 > 여행용가방/소품 > 중대형 캐리어"},
    "cm_01KN9Q72WV6DEXX5H6WET3NJ15": {"smartstore": "패션잡화 > 남성가방 > 토트백"},
    "cm_01KR5BCGW4T1NBKHGR8RKD0X61": {"ssg": "신세계몰메인매장 > 키즈 > 의류 > 아우터"},
    "cm_01KQV6GVYD4HBJKZVFM8MSVC3Y": {
        "11st": "브랜드 주얼리 > 브랜드 여성주얼리 > 헤어액세서리 > 헤어소품",
        "auction": "쥬얼리/시계 > 헤어액세서리 > 헤어핀",
        "gmarket": "쥬얼리/시계 > 헤어액세서리 > 헤어집게",
        "lotteon": "시계/주얼리 > 헤어액세서리 > 헤어밴드",
        "smartstore": "패션잡화 > 헤어액세서리 > 헤어액세서리소품",
    },
    "cm_01KNXGQM3M8HC4W85AYT2NAJCS": {"lotteon": "시계/주얼리 > 귀걸이 > 금귀걸이"},
    "cm_01KR5BCGW68GARF0SCAK5EARRH": {"ssg": "신세계몰메인매장 > 키즈 > 의류 > 아우터"},
    "cm_01KNXGQMFBZ1MB85MCCVXNM60S": {"lotteon": "시계/주얼리 > 목걸이 > 은목걸이"},
    "cm_01KQV6GW77VYR54NQ0WCN83ZZ2": {
        "11st": "여성가방 > 클러치백 > 클러치백",
        "auction": "가방/잡화 > 여성가방 > 클러치백",
        "coupang": "패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성클러치",
        "gmarket": "가방/잡화 > 여성가방 > 클러치백",
        "lotteon": "가방/지갑 > 여성가방 > 클러치",
    },
    "cm_01KQV6GW14PT7WFBANKT9PE6C6": {"smartstore": "패션잡화 > 남성가방 > 브리프케이스"},
    "cm_01KQV6GVX1FSSQSBPCCNBJ0PKG": {
        "11st": "생활잡화 > 신발용품 > 기타 용품",
        "lotteon": "신발 > 신발용품 > 기타신발용품",
        "smartstore": "패션잡화 > 신발용품 > 기타신발용품",
    },
    "cm_01KNGVXW0ABV4F64JW20C1FRKN": {"lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 슬립온"},
    "cm_01KQ6BH9ADKDD866CVFWV7RE6P": {"lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 스니커즈"},
    "cm_01KNGVXVRP1MNTJNXPK3V3YDA2": {"lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 스니커즈"},
    "cm_01KNGVXVC1ETPWJ7DFMNATD7TZ": {"lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 스니커즈"},
    "cm_01KN1FK4XN47P4YXWG045HJAWX": {"lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 스니커즈"},
    "cm_01KR5BCGW7HAP9CWH13MH1NE42": {
        "11st": "유아동잡화 > 남아잡화 > 한복/소품 > 기타 액세서리",
        "coupang": "패션의류잡화 > 영유아동 신발/잡화/기타의류(0~17세) > 여아잡화 > 한복/신발/소품 > 여아 기타액세서리",
        "ssg": "신세계몰메인매장 > 키즈 > 액세서리 > 기타액세서리",
    },
    "cm_01KQV6GW1TFNJG93BGW50910NK": {
        "11st": "브랜드 잡화/소품 > 선글라스/안경테 > 선글라스",
        "gmarket": "브랜드 쥬얼리/시계 > 선글라스/안경테 > 공용 선글라스",
        "lotteon": "명품 > 명품선글라스/안경 > 선글라스",
    },
    "cm_01KQV6GWKCV7VM2W8TX17V5S4H": {"coupang": "뷰티 > 향수 > 액체향수 > 여성향수 > 퍼퓸"},
    "cm_01KN9Q7AE5ZX3YJHJMN7HK1M89": {"lotteon": "브랜드언더웨어 > 홈웨어/이지웨어 > 홈웨어상의 > 여성용"},
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
        print(f"MUSINSA b2: 행 {rows_u}, 키 {keys_a}")
        if rej:
            for r in rej[:5]: print(f"  미일치: {r}")
    finally:
        await conn.close()

asyncio.run(main())
