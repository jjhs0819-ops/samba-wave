"""GSShop 3차 batch (행 63-90) LLM 직접 매핑 결정 적용."""

import asyncio
import asyncpg
import json
from backend.core.config import settings


DECISIONS: dict[str, dict[str, str]] = {
    "cm_01KPC7S4CYHC3SDW7NCH0RNFP2": {
        "lotteon": "스포츠의류/운동화 > 스포츠가방 > 크로스백 > 남성용",
    },
    "cm_01KQV6GV9XWABZZNXNNF83TSAP": {
        "11st": "수영/수상레저 > 아쿠아슈즈 > 성인 아쿠아슈즈",
        "auction": "스포츠의류/운동화 > 스포츠화 > 아쿠아슈즈",
        "gmarket": "스포츠의류/운동화 > 스포츠화 > 아쿠아슈즈",
        "lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 아쿠아슈즈",
    },
    "cm_01KQV6GV8J01E3C1D1A4X0KVEQ": {
        "auction": "스포츠의류/운동화 > 스포츠잡화 > 스포츠양말",
        "gmarket": "스포츠의류/운동화 > 스포츠잡화 > 스포츠양말",
    },
    "cm_01KQV6GV4B53KR6MGVQP7FQXGY": {
        "auction": "스포츠의류/운동화 > 스포츠잡화 > 스포츠장갑",
        "gmarket": "스포츠의류/운동화 > 스포츠잡화 > 스포츠장갑",
    },
    # 67 두건/헤어밴드 - SKIP / 68 기타스포츠화 - SKIP
    "cm_01KQV6GVM7TVD1262FYH9MSB10": {
        "11st": "스포츠 잡화 > 스포츠 용품 > 넥워머/바라클라바",
        "auction": "스포츠의류/운동화 > 스포츠잡화 > 스포츠마스크/바라클라바",
        "coupang": "스포츠/레져 > 스포츠 잡화 > 스카프/넥워머/아이스머플러",
        "gmarket": "스포츠의류/운동화 > 스포츠잡화 > 스포츠마스크/바라클라바",
        "smartstore": "스포츠/레저 > 스포츠액세서리 > 스포츠넥워머",
    },
    # 70 남성스포츠 레깅스 - ssg SKIP
    "cm_01KPPV4HDSC12R0DGWB30KGSSE": {
        "lotteon": "노트북/PC/태블릿 > 노트북액세서리 > 노트북가방/케이스",
    },
    "cm_01KQV6GV2ZQ4WWRVCTMB2E5GGJ": {
        "11st": "남성신발 > 샌들 > 캐쥬얼샌들",
        "auction": "신발 > 남성샌들 > 쪼리/슬리퍼",
        "gmarket": "신발 > 남성캐주얼화 > 샌들/슬리퍼",
        "lotteon": "브랜드신발 > 남성신발 > 샌들",
    },
    "cm_01KQV6GV2ANDAWAZKPEPQ7N7DA": {
        "11st": "수입명품 > 여성신발 > 샌들/슬리퍼/뮬",
        "auction": "신발 > 여성샌들 > 슬리퍼",
        "gmarket": "신발 > 여성샌들 > 슬리퍼샌들",
        "lotteon": "브랜드신발 > 여성신발 > 샌들 > 뮬",
    },
    # 74 남성신발 로퍼/단화 - SKIP
    "cm_01KQV6GVD71D2344CPPY8ZSKVZ": {
        "11st": "여성신발 > 부츠 > 롱부츠",
        "auction": "신발 > 여성부츠/워커 > 부티",
        "gmarket": "신발 > 여성부츠/워커 > 부티",
        "lotteon": "신발 > 여성부츠/워커 > 부티",
    },
    "cm_01KQV6GVEJ5EET4RRRGJR9VKAX": {
        "11st": "브랜드 여성신발 > 로퍼 > 로퍼",
    },
    "cm_01KQV6GVP7PSFM32BJQQ33J4AV": {
        "11st": "남성신발 > 기능화 > 안전화/작업화",
        "smartstore": "패션잡화 > 남성신발 > 기능화 > 작업화/안전화",
    },
    "cm_01KR5BBRXE9XX3KT3ZG06TMR4P": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 남성신발 > 스니커즈",
    },
    "cm_01KQV6GVPWNPZEE46BX1P0XNXV": {
        "smartstore": "패션잡화 > 여성신발 > 단화 > 스니커즈",
    },
    "cm_01KR5BBRXC62X77M3RJPQSRYY1": {
        "ssg": "신세계몰메인매장 > 가방/지갑 > 남성가방 > 크로스백",
    },
    "cm_01KQV6GV51FDWEYAYSS95SCAQK": {
        "lotteon": "잡화 > 기타패션소품 > 기타패션소품",
        "smartstore": "패션잡화 > 패션소품 > 기타패션소품",
    },
    "cm_01KR5BBPZXXWMSC5FNKVQNVMGW": {
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 원피스 > 미디원피스",
    },
    "cm_01KR5BBPZQTT8B5RSP5M1FDZK6": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 여성속옷 하의 > 거들/속바지",
    },
    # 84 여성속옷 브래지어 - lotteon 부적합 SKIP
    "cm_01KR5BBPZTD8EZWD2ZTBMD4DE8": {
        "11st": "수입명품 > 여성의류 > 블라우스/셔츠",
        "auction": "여성의류 > 셔츠/블라우스 > 솔리드셔츠",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 여성 셔츠(남방)",
        "gmarket": "여성의류 > 마담의류 > 블라우스/셔츠",
        "lotteon": "여성의류 > 블라우스/셔츠 > 솔리드셔츠",
        "ssg": "신세계몰메인매장 > 여성브랜드패션 > 블라우스/셔츠 > 셔츠",
    },
    "cm_01KQV6GVV095923VHBDMB3WGEE": {
        "11st": "수입명품 > 여성의류 > 블라우스/셔츠",
        "auction": "여성의류 > 마담의류 > 블라우스/셔츠",
        "coupang": "패션의류잡화 > 여성패션 > 여성의류 > 여성 블라우스",
        "gmarket": "여성의류 > 마담의류 > 블라우스/셔츠",
        "lotteon": "명품 > 명품여성의류 > 블라우스/셔츠",
    },
    "cm_01KR5BBRX8N0P8V799VPVBTPXB": {
        "ssg": "신세계몰메인매장 > 침구/커튼/카페트 > 패브릭소품/커버 > 쿠션/방석",
    },
    # 88 유니섹스 청바지 - ssg SKIP
    "cm_01KQV6GVCJG9AQ3NT95ZW9J0SB": {
        "lotteon": "브랜드진/캐주얼 > 아우터 > 레인코트 > 남성용",
        "smartstore": "패션의류 > 남성의류 > 아우터 > 레인코트",
    },
    "cm_01KR5BBQY0PP9BJJ6P3JV02JGA": {
        "11st": "스포츠 의류 > 반팔/민소매티셔츠 > 남성 민소매/나시",
        "lotteon": "남성의류 > 반팔티셔츠 > 민소매티셔츠",
        "ssg": "신세계몰메인매장 > 캐주얼/유니섹스 > 맨투맨/후드/티셔츠 > 민소매티셔츠",
    },
}


async def main() -> None:
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
        market_valid: dict[str, set[str]] = {}
        for r in tree_rows:
            cat1 = r["cat1"]
            cat2 = r["cat2"]
            if isinstance(cat1, str):
                cat1 = json.loads(cat1)
            if isinstance(cat2, str):
                cat2 = json.loads(cat2)
            paths: set[str] = set()
            if isinstance(cat1, list):
                paths.update(c for c in cat1 if isinstance(c, str))
            if isinstance(cat2, dict):
                paths.update(k for k in cat2.keys() if isinstance(k, str))
            elif isinstance(cat2, list):
                paths.update(c for c in cat2 if isinstance(c, str))
            market_valid[r["site_name"]] = paths

        rows_updated = 0
        keys_added = 0
        rejected: list[str] = []
        async with conn.transaction():
            for mid, additions in DECISIONS.items():
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
                added = 0
                merged = dict(tm)
                for mk, path in additions.items():
                    if isinstance(merged.get(mk), str) and merged.get(mk).strip():
                        continue
                    if path not in market_valid.get(mk, set()):
                        rejected.append(f"{mid} {mk}: {path}")
                        continue
                    merged[mk] = path
                    added += 1
                if added:
                    await conn.execute(
                        "UPDATE samba_category_mapping SET target_mappings=$1::jsonb, updated_at=NOW() WHERE id=$2",
                        json.dumps(merged, ensure_ascii=False),
                        mid,
                    )
                    rows_updated += 1
                    keys_added += added
        print(f"✓ GSShop batch3: 행 {rows_updated}, 키 {keys_added}")
        if rejected:
            print(f"⚠ 트리 미일치 {len(rejected)}건:")
            for r in rejected[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
