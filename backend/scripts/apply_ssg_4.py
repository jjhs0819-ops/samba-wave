"""SSG batch4."""

import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KR5E6C62NW5HFYEZAZBGX7QF": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 맨투맨/후드/티셔츠 > 민소매티셔츠"
    },
    "cm_01KR5BD3GM20ZNNVY77ECJV1AE": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 블루종/캐주얼점퍼"
    },
    "cm_01KR5BDJZWZYXNY1FC19NS8Q41": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 캐주얼/트레이닝팬츠"
    },
    "cm_01KR5BCM53C9HEQG02ZHS325M2": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 벨트/ACC > 남성벨트"
    },
    "cm_01KR5BCN7DV2RC3Y48VFB0H2FE": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 지갑 > 남성지갑"
    },
    "cm_01KR5BCPZEWZSECEY8FMHFJDCX": {
        "ssg": "신세계몰메인매장 > 남성패션 > 자켓 > 데님자켓"
    },
    "cm_01KR5BCR1EDRP0JPRDXW080MRD": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 스커트 > 롱스커트"
    },
    "cm_01KR5BCWBCNNVW7ETZRA6KZCA2": {
        "11st": "남성의류 > 점퍼 > 바람막이점퍼",
        "auction": "남성의류 > 점퍼/야상/패딩 > 바람막이점퍼",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 점퍼 > 남성 바람막이 점퍼",
        "gmarket": "남성의류 > 점퍼/야상/패딩 > 바람막이 점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 바람막이점퍼",
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 바람막이",
    },
    "cm_01KR5BD6R3JK57C71PQW1FXSRH": {
        "ssg": "신세계몰메인매장 > 남성명품 > 선글라스/안경 > 선글라스"
    },
    "cm_01KR5BDA8RE2975PBQRGF76K2G": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 슈즈용품 > 슈즈ACC"
    },
    "cm_01KR5BDNQNGK0Q8125W8ZFMEXG": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 핸드백 > 크로스백"
    },
    "cm_01KR5E6C63T77RRC34K4VAS6B1": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 블라우스/셔츠 > 셔츠"
    },
    "cm_01KR5E6C64F2RZZT4RWHXX0GVR": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 바람막이/자켓/점퍼"
    },
    "cm_01KR5E6C65YGC20910VQZB7SPE": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 팬츠 > 슬랙스"
    },
    "cm_01KR5E6C65YGC20910VQZB7SPF": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 브래지어/팬티 세트"
    },
    "cm_01KR5E6C66ATT8MY6XSW47RX96": {
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 니트/베스트 > 베이직니트"
    },
    "cm_01KR6T7ZRWXKNQ6Y9R8ZEVQ5TY": {
        "ssg": "신세계몰메인매장 > 등산/아웃도어 > 남성 등산의류 > 등산조끼/베스트"
    },
    "cm_01KR5E6C677T55T913P205N7Y6": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 핸드백 > 클러치백/파우치"
    },
    "cm_01KR5E6C68KHEFV5X049GKRNKM": {
        "ssg": "신세계몰메인매장 > 남성패션 > 맨투맨/후드/티셔츠 > 카라/피케티셔츠"
    },
    "cm_01KR5E6C69HB4AY8XQV6B74ES2": {
        "ssg": "신세계몰메인매장 > 남성패션 > 맨투맨/후드/티셔츠 > 라운드넥 티셔츠"
    },
    "cm_01KQV693KQVR2V855HVJQS0NSD": {
        "11st": "수입명품 > 여성의류 > 블라우스/셔츠",
        "auction": "여성의류 > 마담의류 > 블라우스/셔츠",
        "gmarket": "여성의류 > 마담의류 > 블라우스/셔츠",
        "lotteon": "명품 > 명품여성의류 > 블라우스/셔츠",
    },
    "cm_01KQV693FBCCGHVYFGFSXD1E03": {
        "11st": "여성의류 > 티셔츠 > 라운드 티셔츠",
        "auction": "여성의류 > 티셔츠 > 라운드넥티셔츠",
        "gmarket": "여성의류 > 티셔츠 > 라운드넥티셔츠",
        "lotteon": "여성의류 > 티셔츠/맨투맨 > 라운드넥티셔츠",
    },
    "cm_01KR5BD3GJFG2NQHA251SRF8BC": {
        "lotteon": "명품 > 명품여성의류 > 블라우스/셔츠",
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 블라우스/셔츠 > 셔츠",
    },
    "cm_01KR5BD29TZFVASYY379GF4QPF": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 브래지어/팬티 세트"
    },
    "cm_01KQV693CAZ32AEVEHP25TWJE1": {
        "11st": "남성의류 > 점퍼 > 바람막이점퍼",
        "auction": "남성의류 > 점퍼/야상/패딩 > 바람막이점퍼",
        "coupang": "패션의류잡화 > 남성패션 > 남성의류 > 점퍼 > 남성 바람막이 점퍼",
        "gmarket": "남성의류 > 점퍼/야상/패딩 > 바람막이 점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 바람막이점퍼",
        "smartstore": "패션의류 > 남성의류 > 점퍼",
    },
    "cm_01KR5BDBCGFVH82W27ARTSPMCH": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 아동신발 > 스니커즈"
    },
    "cm_01KR5BDQWSNARCBFT26RHV4BEF": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 핸드백 > 클러치백/파우치"
    },
    "cm_01KR5BDTWZ66PXMV914KVVQTPJ": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 패딩부츠/털부츠"
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
        print(f"SSG b4: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
