"""미매핑 카테고리 14건을 일괄 INSERT (프로덕션 DB).

사전 조건: cloud-sql-proxy --port 15432 fresh-sanctuary-489804-v4:asia-northeast3:samba-wave-db
"""

import asyncio
import json
import sys

import asyncpg

# 미매핑 카테고리별 마켓 매핑값 (기존 매핑 패턴 참고)
MAPPINGS = [
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 운동화/스니커즈 > 슬립온",
        "target_mappings": {
            "11st": "여성신발 > 슬립온 > 슬립온",
            "auction": "신발 > 스니커즈/슬립온 > 슬립온",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 여성슬립온",
            "gmarket": "신발 > 스니커즈/슬립온 > 여성슬립온",
            "lotteon": "신발 > 여성캐주얼화 > 슬립온",
            "smartstore": "패션잡화 > 여성신발 > 단화 > 슬립온",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 슬립온",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "남성패션 > 신발 > 운동화/스니커즈 > 슬립온",
        "target_mappings": {
            "11st": "남성신발 > 슬립온 > 슬립온",
            "auction": "신발 > 스니커즈/슬립온 > 슬립온",
            "coupang": "패션의류잡화 > 남성패션 > 남성화 > 남성슬립온",
            "gmarket": "신발 > 스니커즈/슬립온 > 남성슬립온",
            "lotteon": "신발 > 남성캐주얼화 > 슬립온",
            "smartstore": "패션잡화 > 남성신발 > 단화 > 슬립온",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 슬립온",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 플랫/로퍼 > 플랫",
        "target_mappings": {
            "11st": "여성신발 > 플랫슈즈 > 플랫슈즈",
            "auction": "신발 > 여성단화 > 플랫슈즈",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 단화/플랫 > 여성플랫슈즈",
            "gmarket": "신발 > 여성단화 > 플랫슈즈",
            "lotteon": "신발 > 여성캐주얼화 > 플랫슈즈",
            "smartstore": "패션잡화 > 여성신발 > 단화 > 플랫",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 플랫/로퍼",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "스포츠/레저 > 신발 > 여성스포츠신발 > 슬립온",
        "target_mappings": {
            "11st": "여성신발 > 슬립온 > 슬립온",
            "auction": "신발 > 스니커즈/슬립온 > 슬립온",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 여성슬립온",
            "gmarket": "신발 > 스니커즈/슬립온 > 여성슬립온",
            "lotteon": "스포츠의류/운동화 > 여성스포츠신발 > 슬립온",
            "smartstore": "스포츠/레저 > 스포츠화 > 여성스포츠화",
            "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 슬립온",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 샌들 > 스트랩샌들",
        "target_mappings": {
            "11st": "여성신발 > 샌들 > 샌들",
            "auction": "신발 > 여성샌들 > 스트랩샌들",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성스트랩샌들",
            "gmarket": "신발 > 여성샌들 > 스트랩샌들",
            "lotteon": "신발 > 여성샌들 > 스트랩샌들",
            "smartstore": "패션잡화 > 여성신발 > 샌들 > 스트랩샌들",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 플랫/로퍼 > 로퍼",
        "target_mappings": {
            "11st": "여성신발 > 로퍼 > 로퍼",
            "auction": "신발 > 여성단화 > 로퍼",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 단화/플랫 > 여성로퍼",
            "gmarket": "신발 > 여성단화 > 로퍼",
            "lotteon": "신발 > 여성캐주얼화 > 로퍼",
            "smartstore": "패션잡화 > 여성신발 > 단화 > 로퍼",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 플랫/로퍼",
        },
    },
    {
        "source_site": "ABCmart",
        "source_category": "신발 > 스니커즈 > 라이트닝",
        "target_mappings": {
            "11st": "남성신발 > 스니커즈 > 스니커즈",
            "auction": "신발 > 스니커즈/슬립온 > 스니커즈",
            "coupang": "패션의류잡화 > 유니섹스/남녀공용 패션 > 공용화 > 남녀공용스니커즈",
            "gmarket": "신발 > 스니커즈/슬립온 > 남성스니커즈",
            "lotteon": "신발 > 남성캐주얼화 > 스니커즈",
            "smartstore": "패션잡화 > 남성신발 > 스니커즈",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 스니커즈/운동화 > 스니커즈",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "남성패션 > 신발 > 로퍼",
        "target_mappings": {
            "11st": "남성신발 > 로퍼 > 로퍼",
            "auction": "신발 > 남성캐주얼화 > 로퍼/옥스포드화",
            "coupang": "패션의류잡화 > 남성패션 > 남성화 > 남성로퍼",
            "gmarket": "신발 > 남성캐주얼화 > 로퍼/옥스포드화",
            "lotteon": "신발 > 남성캐주얼화 > 로퍼",
            "smartstore": "패션잡화 > 남성신발 > 단화 > 로퍼",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 로퍼",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 샌들 > 슬링백샌들",
        "target_mappings": {
            "11st": "여성신발 > 샌들 > 샌들",
            "auction": "신발 > 여성샌들 > 기타샌들",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성캐주얼샌들",
            "gmarket": "신발 > 여성샌들 > 슬링백",
            "lotteon": "신발 > 여성샌들 > 슬링백",
            "smartstore": "패션잡화 > 여성신발 > 샌들 > 슬링백샌들",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 샌들 > 웨지샌들",
        "target_mappings": {
            "11st": "여성신발 > 샌들 > 웨지샌들",
            "auction": "신발 > 여성샌들 > 웨지샌들",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성웨지샌들",
            "gmarket": "신발 > 여성샌들 > 웨지샌들",
            "lotteon": "신발 > 여성샌들 > 웨지",
            "smartstore": "패션잡화 > 여성신발 > 샌들 > 웨지샌들",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "남성패션 > 신발 > 운동화/스니커즈 > 컴포트화",
        "target_mappings": {
            "11st": "남성신발 > 캐주얼화 > 컴포트화",
            "auction": "신발 > 남성캐주얼화 > 캐주얼화",
            "coupang": "패션의류잡화 > 남성패션 > 남성화 > 캐주얼화 > 남성캐주얼화",
            "gmarket": "신발 > 남성캐주얼화 > 캐주얼화",
            "lotteon": "신발 > 남성캐주얼화 > 캐주얼화",
            "smartstore": "패션잡화 > 남성신발 > 단화 > 컴포트화",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 캐주얼화",
        },
    },
    {
        "source_site": "ABCmart",
        "source_category": "신발 > 부츠 > 털부츠",
        "target_mappings": {
            "11st": "여성신발 > 부츠 > 패딩부츠",
            "auction": "신발 > 여성부츠/워커 > 패딩부츠",
            "coupang": "패션의류잡화 > 유니섹스/남녀공용 패션 > 공용화 > 워커/부츠/방한화 > 남녀공용 패딩/방한화",
            "gmarket": "신발 > 여성부츠/워커 > 패딩부츠",
            "lotteon": "신발 > 여성부츠/워커 > 방한부츠",
            "smartstore": "패션잡화 > 여성신발 > 부츠",
            "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠신발/샌들 > 패딩부츠/털부츠",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 의류 > 스커트 > 롱스커트",
        "target_mappings": {
            "11st": "여성의류 > 스커트/치마 > 롱 스커트",
            "auction": "여성의류 > 스커트 > 롱스커트",
            "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 스커트 > 여성 롱(발목길이)스커트",
            "gmarket": "여성의류 > 스커트 > 롱스커트",
            "lotteon": "여성의류 > 스커트 > 롱스커트",
            "smartstore": "패션의류 > 여성의류 > 스커트",
            "ssg": "신세계몰메인매장 > 여성브랜드패션 > 스커트 > 롱스커트",
        },
    },
    {
        "source_site": "LOTTEON",
        "source_category": "여성패션 > 신발 > 샌들 > 글래디에이터샌들",
        "target_mappings": {
            "11st": "여성신발 > 샌들 > 샌들",
            "auction": "신발 > 여성샌들 > 스트랩샌들",
            "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성캐주얼샌들",
            "gmarket": "신발 > 여성샌들 > 스트랩샌들",
            "lotteon": "신발 > 여성샌들 > 스트랩샌들",
            "smartstore": "패션잡화 > 여성신발 > 샌들",
            "ssg": "신세계몰메인매장 > 슈즈/운동화 > 여성신발 > 샌들",
        },
    },
]


async def main():
    sys.stdout.reconfigure(encoding="utf-8")
    conn = await asyncpg.connect(
        user="postgres",
        password="gemini0674@@",
        host="127.0.0.1",
        port=15432,
        database="railway",
    )
    inserted = 0
    skipped = 0
    for m in MAPPINGS:
        # 중복 방지 — 이미 존재하면 스킵
        existing = await conn.fetchval(
            "SELECT id FROM samba_category_mapping WHERE source_site=$1 AND source_category=$2",
            m["source_site"],
            m["source_category"],
        )
        if existing:
            print(f"[skip] 이미 존재: {m['source_site']} | {m['source_category']}")
            skipped += 1
            continue
        # ULID는 함수가 generate, 여기선 단순화 — uuid 사용
        from ulid import ULID

        new_id = f"cm_{ULID()}"
        await conn.execute(
            """INSERT INTO samba_category_mapping
            (id, source_site, source_category, target_mappings, created_at, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, NOW(), NOW())""",
            new_id,
            m["source_site"],
            m["source_category"],
            json.dumps(m["target_mappings"], ensure_ascii=False),
        )
        print(f"[OK]   {m['source_site']} | {m['source_category']}")
        inserted += 1
    print(f"\n=== 결과: 신규 INSERT {inserted}건, 중복스킵 {skipped}건 ===")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
