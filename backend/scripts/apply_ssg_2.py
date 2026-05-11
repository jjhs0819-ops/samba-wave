"""SSG batch2."""

import asyncio, asyncpg, json
from backend.core.config import settings

D = {
    "cm_01KR5BD0ZFHGWKY98BVXF5QRC5": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 부츠/워커"
    },
    "cm_01KQV693D3ZHPTT6QJPWG0H2C1": {
        "11st": "여성의류 > 셔츠/남방 > 기본/무지 셔츠",
        "auction": "브랜드 캐주얼의류 > 티셔츠/셔츠 > 셔츠/남방",
        "coupang": "패션의류잡화 > 유니섹스/남녀공용 패션 > 캐주얼 의류 > 공용 셔츠/남방",
        "gmarket": "브랜드 캐주얼의류 > 티셔츠/셔츠 > 셔츠/남방",
        "smartstore": "패션의류 > 남성의류 > 셔츠/남방",
    },
    "cm_01KR5BDFGZBF5G3Z14VY34W5YC": {
        "ssg": "신세계몰메인매장 > 남성패션 > 니트/베스트 > 니트조끼"
    },
    "cm_01KR5BDTX3795HK4EPKKXCK6JM": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 캐주얼가방 > 힙색/슬링백"
    },
    "cm_01KR5E6C5HBD5SHNDFVRE4PJQ0": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼"
    },
    "cm_01KR5E6C5J1YJ0D8PAJC6WG0HQ": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들"
    },
    "cm_01KR5BD5M2ERCWC5X4QF90KGF8": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 사각/드로즈 팬티"
    },
    "cm_01KR5BD6QY1BZ5DHQS29WDHJZP": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 삼각/브리프 팬티"
    },
    "cm_01KR5BCZZSCJT4D6CYJEYDS2PG": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 모자 > 볼캡/야구모자"
    },
    "cm_01KR5BD4QNTRVAAWYW26NTCC1G": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 비옷/레인코트"
    },
    "cm_01KR5BDTWXVR75W3N1YT8KVQAA": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 패딩/다운점퍼"
    },
    "cm_01KR5E6C5KXNJMSGMWJ29X7N5H": {
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 여성 상의 > 가디건"
    },
    "cm_01KR5BDFH1EYJX2F0RN62W9FX8": {
        "11st": "남성의류 > 니트/스웨터 > 집업/후드",
        "auction": "남성의류 > 가디건 > 집업가디건",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 여성 후드집업/집업류",
        "gmarket": "브랜드 캐주얼의류 > 니트/가디건 > 가디건/집업/베스트",
        "lotteon": "남성의류 > 가디건/조끼 > 집업가디건",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 후드집업",
        "ssg": "신세계몰메인매장 > 남성패션 > 가디건 > 집업/후드가디건",
    },
    "cm_01KQV693BJWK3VSH1556DWKNT0": {
        "auction": "브랜드 남성의류 > 티셔츠 > 피케/카라 티셔츠",
        "gmarket": "브랜드 남성의류 > 티셔츠 > 피케/카라 티셔츠",
        "lotteon": "남성의류 > 반팔티셔츠 > 카라반팔티",
    },
    "cm_01KQV693MGC4HERSFKJQGN7JM9": {
        "11st": "스포츠 의류 > 긴바지 > 남성 긴바지",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 바지 > 여성 긴바지",
        "lotteon": "등산/아웃도어 > 남성등산의류 > 긴바지",
    },
    "cm_01KR5BCPZKNN1FHY2FGJGW1CPS": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 스니커즈/운동화 > 런닝화/워킹화"
    },
    "cm_01KR5BCSB01GDNBZJH8791NN88": {
        "ssg": "신세계몰메인매장 > 남성패션 > 코트 > 롱코트"
    },
    "cm_01KR5BCSB3N0CSQ4BVS3WM4EDS": {
        "ssg": "신세계몰메인매장 > 명품/수입의류 > 남성 상의 > 맨투맨"
    },
    "cm_01KQV693G34Q0QFCV4CXH6V3VY": {
        "11st": "여성의류 > 바지/팬츠 > 면팬츠",
        "auction": "브랜드 여성의류 > 팬츠 > 면팬츠",
        "gmarket": "브랜드 남성의류 > 팬츠 > 면팬츠/치노팬츠",
    },
    "cm_01KR5BCWBDKDBPH9K7RXZKCHAB": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 반바지/7부"
    },
    "cm_01KR5BCYH64RBRH0BCYSD53X24": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 모자 > 버킷햇"
    },
    "cm_01KR5BDCCZW2KEHB8CADCJXM3M": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 머플러/스카프 > 스카프"
    },
    "cm_01KR5BDCD27V2HG86S2C8Q7HVD": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 스커트 > 롱스커트"
    },
    "cm_01KQV693N7D7AWXKRY7J0XN0Y8": {
        "11st": "여성의류 > 바지/팬츠 > 슬랙스",
        "auction": "여성의류 > 바지 > 슬랙스",
        "gmarket": "남성의류 > 캐주얼바지 > 슬랙스",
        "lotteon": "남성의류 > 바지 > 슬랙스",
    },
    "cm_01KR5BDFGVC97QY1ECZV9P54HT": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 워킹화"
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
        print(f"SSG b2: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
