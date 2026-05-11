"""MUSINSA batch1 (행 1-30)."""
import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KN9Q6XR1YKHKKMPXBVK91550": {"smartstore": "패션잡화 > 남성가방 > 백팩"},
    "cm_01KQV6GW2GY686WTHKB0KWS2R4": {"smartstore": "패션잡화 > 남성신발 > 구두"},
    "cm_01KQV73TS04B9ZNWMF2MTK5W30": {
        "11st": "남성신발 > 정장구두 > 정장구두",
        "auction": "신발 > 남성정장화 > 정장구두-기본",
        "gmarket": "신발 > 남성정장화 > 남성구두",
        "smartstore": "패션잡화 > 남성신발 > 구두",
    },
    "cm_01KQV73TSR58BWWTBTECT4V5AC": {"smartstore": "패션잡화 > 남성신발 > 구두"},
    "cm_01KR5BCCQ5J9ZSX8930EJCP26V": {"ssg": "신세계몰메인매장 > 키즈 > 액세서리 > 모자"},
    "cm_01KR5BCCQ75PS8VVWDQ3EFWWEN": {"ssg": "신세계몰메인매장 > 키즈 > 의류 > 하의"},
    "cm_01KR5BCCQARCTA3EPVYYH871EJ": {"ssg": "신세계몰메인매장 > 아동/주니어패션 > 바지/레깅스 > 조거/캐주얼팬츠"},
    "cm_01KNXGQKRT0WSS4HV251GAJQEP": {"lotteon": "시계/주얼리 > 시계 > 남성쿼츠시계"},
    "cm_01KQV6GVZR1S32YTZTTGMTXSNS": {
        "coupang": "패션의류잡화 > 영유아동 신발/잡화/기타의류(0~17세) > 남아신발 > 운동화/스니커즈 > 남아 운동화",
    },
    "cm_01KQV6GWAJ4KBCR7M2GSPZSA5J": {
        "11st": "키즈의류 (3~8세) > 남녀공용의류 > 티셔츠 > 맨투맨",
        "coupang": "패션의류잡화 > 키즈 의류(3~8세) > 남아의류 > 티셔츠 > 남아 맨투맨",
    },
    "cm_01KQV6GW97PM6E1EXPAPYDJ0GV": {
        "11st": "키즈의류 (3~8세) > 남녀공용의류 > 티셔츠 > 맨투맨",
        "coupang": "패션의류잡화 > 키즈 의류(3~8세) > 남녀공용의류 > 티셔츠 > 공용 맨투맨",
    },
    "cm_01KQV6GW36KB6GHWNA6AK8B6V0": {"lotteon": "가방/지갑 > 가방소품 > 가방끈"},
    "cm_01KQV6GW7Q0AVEMQGD90Y72Z37": {
        "11st": "키즈의류 (3~8세) > 남녀공용의류 > 상하복 세트",
        "auction": "유아동의류 > 유아동공용의류 > 유아동상하복세트",
        "coupang": "패션의류잡화 > 키즈 의류(3~8세) > 여아의류 > 상하복 세트 > 여아 상하 바지세트",
        "gmarket": "유아동의류 > 유아동공용의류 > 유아동상하복세트",
        "lotteon": "유아동의류 > 유아동공용의류 > 유아동상하복세트",
    },
    "cm_01KQV73TTF8E7TGR02ZM5S4EDB": {
        "gmarket": "신발 > 여성부츠/워커 > 롱부츠",
        "lotteon": "신발 > 여성부츠/워커 > 롱부츠",
        "smartstore": "패션잡화 > 여성신발 > 부츠 > 롱부츠",
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 부츠",
    },
    "cm_01KQV73TV5PGT7KFCPFR3E2A0K": {
        "11st": "브랜드 남성신발 > 워커/부츠 > 워커/부츠",
        "auction": "신발 > 여성부츠/워커 > 워커힐",
        "gmarket": "신발 > 남성워커/부츠 > 워커",
        "smartstore": "패션잡화 > 남성신발 > 워커",
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 부츠/워커",
    },
    "cm_01KMY4GCBDFRSGDPHRTBXJD5FD": {"auction": "신발 > 여성부츠/워커 > 부티"},
    "cm_01KMY3MQG70FGRPG2EQ9B6CWK6": {"auction": "신발 > 여성부츠/워커 > 부티"},
    "cm_01KN9Q7FHVR463VFQ1H7SH07AH": {"auction": "신발 > 여성부츠/워커 > 부티"},
    "cm_01KR5BCCPTKW490DAEXE73WWA6": {"ssg": "신세계몰메인매장 > 유아동신발/잡화 > 가방/지갑 > 크로스백/숄더백"},
    "cm_01KQV6GW5W13D5VPZ8KH97G40V": {
        "11st": "남성신발 > 슬리퍼 > 털실내화/슬리퍼",
        "auction": "신발 > 실내화/슬리퍼 > 털슬리퍼",
        "gmarket": "신발 > 실내화/슬리퍼 > 일반슬리퍼",
        "lotteon": "신발 > 슬리퍼/실내화 > 일반슬리퍼 > 남성용",
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
        print(f"MUSINSA b1: 행 {rows_u}, 키 {keys_a}")
        if rej:
            print(f"미일치 {len(rej)}:")
            for r in rej[:5]: print(f"  {r}")
    finally:
        await conn.close()

asyncio.run(main())
