"""SSG batch3."""

import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KR5BDFGX16NK8861EJWAB7D4": {
        "11st": "패션잡화 > 우산 > 장우산",
        "auction": "가방/잡화 > 우산/양산 > 장우산",
        "coupang": "패션의류잡화 > 유니섹스/남녀공용 패션 > 공용 잡화 > 우산 > 남녀공용장우산",
        "gmarket": "가방/잡화 > 우산/양산 > 장우산",
        "lotteon": "잡화 > 우산/양산 > 장우산",
        "smartstore": "패션잡화 > 패션소품 > 우산 > 자동우산",
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 우산/양산 > 장우산",
    },
    "cm_01KR5BDFH5PRYB2WBMC5R7E2SP": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 축구화"
    },
    "cm_01KR5BDSRPTKNRHK7EH96JEMF1": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 캐주얼가방 > 토트백"
    },
    "cm_01KQV693GTF17H1PXCHQJQJPJR": {
        "11st": "여성의류 > 티셔츠 > 반소매",
        "auction": "여성의류 > 마담의류 > 티셔츠",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 티셔츠 > 여성 반소매",
        "gmarket": "여성의류 > 티셔츠 > 브이넥티셔츠",
        "lotteon": "여성의류 > 티셔츠/맨투맨 > 맨투맨",
    },
    "cm_01KR5BDTX1HF4VKHHMF5AAYS33": {
        "11st": "남성의류 > 후드티 > 무지 후드티",
        "auction": "남성의류 > 긴팔티셔츠 > 후드티셔츠",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 남성 후드티",
        "gmarket": "남성의류 > 맨투맨/후드티 > 후드티셔츠",
        "lotteon": "남성의류 > 긴팔티/맨투맨 > 후드티셔츠",
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 남성 상의 > 후드티",
    },
    "cm_01KR5E6C5MYRNW22NCCVW0GGHY": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 사파리/야상"
    },
    "cm_01KR5E6C5NHGAJDE1EEVC0FQEB": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 슬리퍼/쪼리"
    },
    "cm_01KR5E6C5QBS4CC2DCZFHP22YX": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 반바지/스커트"
    },
    "cm_01KR5E6C5R3CK5C9DC2E9T3T10": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 남성가방 > 숄더백/토트백"
    },
    "cm_01KR5E6C5R3CK5C9DC2E9T3T11": {
        "ssg": "신세계몰메인매장 > 등산/아웃도어 > 등산화/트레킹화 > 등산화/트레킹화"
    },
    "cm_01KR5E6C5SPMF5ZQAQKHAF5Z7W": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 스니커즈/운동화 > 슬립온"
    },
    "cm_01KR5E6C5TESZQC1DM46XY7Z3Q": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 블루종/캐주얼점퍼"
    },
    "cm_01KR5E6C5V5M0ZXR877491NMB6": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 캐주얼/트레이닝팬츠"
    },
    "cm_01KR5BDHTRHK2JS2PH1SDHV70Q": {
        "ssg": "신세계몰메인매장 > 남성패션 > 자켓 > 캐주얼 자켓"
    },
    "cm_01KR5BD3GDMVWX1D26XYEVMR2Q": {
        "ssg": "신세계몰메인매장 > 남성패션 > 맨투맨/후드/티셔츠 > 브이넥 티셔츠"
    },
    "cm_01KR5BDCD4KT1VJPPMM337X7YB": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 스포츠 기능성 웨어"
    },
    "cm_01KR5BD5M56BXNVRKAP1Y5J7FK": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 사파리/야상"
    },
    "cm_01KR5BDFH3YM7A91MRP9ZR0TXP": {
        "ssg": "신세계몰메인매장 > 유아동신발/잡화 > 가방/지갑 > 책가방/백팩"
    },
    "cm_01KR5E6C5WPCR13KGQS5Q7JABW": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 핸드백 > 숄더백"
    },
    "cm_01KR5E6C5X2XG7JJCAW0CT7X9X": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 캐주얼가방 > 힙색/슬링백"
    },
    "cm_01KR5BDDEXS5KW1Y2BASP6R60R": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 슬리퍼/쪼리"
    },
    "cm_01KR5BD82KXAZATWZ70EEQ0R9N": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 남성가방 > 숄더백/토트백"
    },
    "cm_01KQV693HJ7TRGT2XBJJNND14W": {
        "11st": "등산/아웃도어 > 등산화 > 트레킹화",
        "coupang": "스포츠/레져 > 등산 > 등산/아웃도어 신발 > 남녀공용 > 트레킹화",
        "gmarket": "등산/아웃도어 > 등산화/트레킹화 > 트레킹화",
        "lotteon": "등산/아웃도어 > 등산화/트래킹화 > 트레킹화",
    },
    "cm_01KR5BD82GZJ995129ZFE3R8MJ": {
        "ssg": "신세계몰메인매장 > 유아동신발/잡화 > 가방/지갑 > 크로스백/숄더백"
    },
    "cm_01KR5BDFGRVWNS8DEZJHFXGA8W": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 아동신발 > 스니커즈"
    },
    "cm_01KR5E6C5YCEGX3WNRQH88RSDW": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 팬츠 > 면팬츠"
    },
    "cm_01KR5E6C60NX1BY45QFKTDB3BY": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 맨투맨/후드/티셔츠 > 맨투맨"
    },
    "cm_01KR5E6C60NX1BY45QFKTDB3BZ": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 맨투맨/후드/티셔츠 > 후드티"
    },
    "cm_01KR5E6C6100HX9C1CR9YBZB6N": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 맨투맨/후드/티셔츠 > 라운드넥 티셔츠"
    },
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
        print(f"SSG b3: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
