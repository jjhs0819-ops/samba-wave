"""SSG batch1."""

import asyncio
import asyncpg
import json
from backend.core.config import settings

D = {
    "cm_01KR5E6C53MBY0BT299NCJ4YRV": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 면/치노팬츠"
    },
    "cm_01KR5E6C54Y55AT13G99W9F65W": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 원피스 > 롱/맥시원피스"
    },
    "cm_01KR5BCTX8VF2J6QJ0KW9NK8ME": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 면/치노팬츠"
    },
    "cm_01KR5BCR1B5PJ6640PG27YCX0C": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 원피스 > 롱/맥시원피스"
    },
    "cm_01KR5BCP07AQBYXKTDV0HED495": {
        "ssg": "신세계몰메인매장 > 남성패션 > 팬츠 > 데님"
    },
    "cm_01KR5BD6R1P27P5Z0T900MNVJ0": {
        "11st": "여성신발 > 샌들 > 웨지샌들",
        "auction": "신발 > 여성샌들 > 웨지샌들",
        "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성웨지샌들",
        "lotteon": "신발 > 여성샌들 > 뮬",
        "smartstore": "패션잡화 > 남성신발 > 샌들",
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
    },
    "cm_01KR5E6C55YZJ43H1ZTSD351AM": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 슈즈용품 > 깔창/패드"
    },
    "cm_01KR5E6C563N65YPM5TMTKZJH0": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 패딩/다운점퍼"
    },
    "cm_01KR5E6C57AKYC21JK6SYRVZ0Z": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼"
    },
    "cm_01KR5E6C58KHEP1Q7S3XA3QSWF": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 부츠/워커"
    },
    "cm_01KR6T989KZ14E8PPS8FSHTYVC": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 장갑/ACC > 팔토시/워머"
    },
    "cm_01KR5E6C592M6MREW02D62KZAD": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 샌들/슬리퍼"
    },
    "cm_01KR5E6C5A7ADZXJGNPAA7ZH9P": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 아동신발 > 스니커즈"
    },
    "cm_01KR5E6C5BRZARQXNQZNNTERPN": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 사각/드로즈 팬티"
    },
    "cm_01KR5E6C5BRZARQXNQZNNTERPP": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 삼각/브리프 팬티"
    },
    "cm_01KR5E6C5CFVC95HAMWA6JYKVS": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 모자 > 볼캡/야구모자"
    },
    "cm_01KR5E6C5DEB1W01CTPS4BG87W": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 비옷/레인코트"
    },
    "cm_01KR5E6C5EJYCNWBBSYC9TCZWK": {
        "ssg": "신세계몰메인매장 > 남성패션 > 점퍼/패딩 > 패딩/다운점퍼"
    },
    "cm_01KR5E6C5FK6BWWNH4A6Z74D1Q": {
        "ssg": "신세계몰메인매장 > 남성패션 > 가디건 > 집업/후드가디건"
    },
    "cm_01KR5E6C5G5PSEEBF1XT9CKBQT": {
        "ssg": "신세계몰메인매장 > 남성패션 > 맨투맨/후드/티셔츠 > 카라/피케티셔츠"
    },
    "cm_01KR5BCJ2GVRX2K95HXE6TMGKT": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 기타 스포츠화"
    },
    "cm_01KR5BCJ2EZK9T2VDG43BDGSTK": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 기타 스포츠잡화"
    },
    "cm_01KR5BCK3XFAXZDD9T7GKGTX8Y": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 슈즈용품 > 깔창/패드"
    },
    "cm_01KR5BCR180KXM588GFP2APG1T": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼"
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
        print(f"SSG b1: 행 {rows_u}, 키 {keys_a}, 미일치 {len(rej)}")
        if rej:
            for r in rej[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


asyncio.run(main())
