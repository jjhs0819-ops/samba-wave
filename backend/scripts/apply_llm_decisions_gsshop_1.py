"""GSShop 1차 batch (29행) LLM 직접 매핑 결정 적용."""

import asyncio
import asyncpg
import json
from backend.core.config import settings


DECISIONS: dict[str, dict[str, str]] = {
    # 1) 텀블러
    "cm_01KQV6GVDWPZBFAQBDRG1RFDC8": {
        "11st": "주방용품 > 보온/보냉용품 > 보온컵/텀블러",
        "auction": "주방용품 > 컵/잔 > 텀블러",
        "coupang": "주방용품 > 수저/컵/식기 > 컵/머그/잔 > 텀블러 > 보온/보냉텀블러",
        "gmarket": "주방용품 > 컵/잔 > 텀블러",
        "lotteon": "주방용품 > 잔/컵 > 텀블러",
        "smartstore": "생활/건강 > 주방용품 > 잔/컵 > 텀블러",
    },
    # 2) 유아동 실내화/슬리퍼
    "cm_01KQV6GVMX1P4BS0NR8ZME65XJ": {
        "11st": "유아동신발 > 남아신발 > 실내화 > 실내화",
        "auction": "유아동신발/잡화 > 유아동신발 > 실내화",
        "gmarket": "유아동신발/잡화 > 유아동신발 > 실내화",
        "lotteon": "유아동신발/잡화 > 유아동신발 > 유아동실내화",
        "smartstore": "출산/육아 > 유아동잡화 > 신발 > 실내화",
    },
    # 3) 등산화/트레킹화 (롯데)
    "cm_01KQV6GVVN5YANMTYAK8HCWJFY": {
        "11st": "등산/아웃도어 > 등산화 > 트레킹화",
        "coupang": "스포츠/레져 > 등산 > 등산/아웃도어 신발 > 남녀공용 > 트레킹화",
        "gmarket": "등산/아웃도어 > 등산화/트레킹화 > 트레킹화",
        "lotteon": "등산/아웃도어 > 등산화/트래킹화 > 트레킹화",
    },
    # 4) 등산화/트레킹화 (현대)
    "cm_01KR5BBJRTH23H51ASRW68K576": {
        "11st": "등산/아웃도어 > 등산화 > 트레킹화",
        "coupang": "스포츠/레져 > 등산 > 등산/아웃도어 신발 > 남녀공용 > 트레킹화",
        "gmarket": "등산/아웃도어 > 등산화/트레킹화 > 트레킹화",
        "lotteon": "등산/아웃도어 > 등산화/트래킹화 > 트레킹화",
        "ssg": "신세계몰메인매장 > 등산/아웃도어 > 등산화/트레킹화 > 등산화/트레킹화",
    },
    # 5) 등산바지
    "cm_01KQV6GVKHVFNXHZ8XW7EN7824": {
        "11st": "등산/아웃도어 > 남성등산복 > 등산바지 > 긴바지",
        "auction": "등산/아웃도어 > 남성등산의류 > 남성등산바지",
        "gmarket": "등산/아웃도어 > 남성등산의류 > 남성등산바지",
    },
    # 6) 스포츠가방/아동책가방 (lotteon 후보 부적합 → SKIP 전체)
    # 7) 스포츠 액세서리 기타
    "cm_01KQV6GVFXYMNDH5QMTKBZH1Y9": {
        "auction": "스포츠의류/운동화 > 스포츠기타용품 > 기타스포츠용품",
        "gmarket": "스포츠의류/운동화 > 스포츠기타용품 > 기타스포츠용품",
        "smartstore": "스포츠/레저 > 기타스포츠용품",
    },
    # 8) 스포츠 모자/선캡
    "cm_01KR5BBD453M5EYH5GBC7W5GX5": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 스포츠모자/잡화 > 스포츠모자",
    },
    # 9) 아동화
    "cm_01KQV6GVR9WSR9KB9GT3N1X35J": {
        "11st": "스포츠 신발 > 운동화/스니커즈 > 아동화",
    },
    # 10) 슬리퍼/샌들 (롯데 스포츠슈즈)
    "cm_01KQV6GV970RQVJ02M95YSXS4D": {
        "11st": "스포츠 잡화 > 슬리퍼/샌들 > 성인 샌들",
        "auction": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "gmarket": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 샌들",
    },
    # 11) 슬리퍼/샌들 (현대 스포츠슈즈) - 동일
    "cm_01KQV6GV77N9YXH47D42HE4KWV": {
        "11st": "스포츠 잡화 > 슬리퍼/샌들 > 성인 샌들",
        "auction": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "gmarket": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 샌들",
    },
    # 12) 런닝화/워킹화
    "cm_01KR5BBC3KVMTGYSC3A8C6V316": {
        "ssg": "신세계몰메인매장 > 슈즈/운동화 > 스니커즈/운동화 > 런닝화/워킹화",
    },
    # 13) 반바지/스커트 (여성 스포츠)
    "cm_01KR5BBEAPYJ42YRDRMK6T9V5K": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 반바지/스커트",
    },
    # 14) 민소매/나시티셔츠 (여성)
    "cm_01KR5BBEAHYMC3QNRCN25N6GDH": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 여성스포츠의류 > 티셔츠",
    },
    # 15) 바람막이/자켓/점퍼 (남성)
    "cm_01KR5BBEAM912Z2QH7YC93KYZX": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 바람막이/자켓/점퍼",
    },
    # 16) 긴팔티셔츠 (남성)
    "cm_01KR5BBD49S910E22VF70R6P49": {
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 티셔츠",
    },
    # 17) 기타스포츠화 — 모든 후보 부적합 → 전체 SKIP
    # 18) 트레이닝상의 — ssg 후보 부적합 → SKIP
    # 19) 트레이닝하의 — ssg 후보 부적합 → SKIP
    # 20) 트레이닝복세트 (전체 빈)
    "cm_01KR5BBEAS0RMFMV98K7NTQP49": {
        "lotteon": "스포츠의류/운동화 > 남성스포츠의류 > 트레이닝복",
        "ssg": "신세계몰메인매장 > 스포츠웨어/용품 > 남성스포츠의류 > 트레이닝복세트",
    },
    # 21) 남성 샌들/슬리퍼 (롯데)
    "cm_01KQV6GVBX0KN0NE911PDXDDGM": {
        "11st": "수입명품 > 남성신발 > 샌들/슬리퍼",
        "auction": "브랜드 잡화 > 남성화 > 샌들",
        "coupang": "패션의류잡화 > 남성패션 > 남성화 > 샌들 > 남성캐주얼샌들",
        "gmarket": "브랜드 잡화 > 남성화 > 샌들/슬리퍼",
    },
    # 22) 남성 샌들/슬리퍼 (현대) - 동일
    "cm_01KQV6GVB8P88THWEBP0AKC534": {
        "11st": "수입명품 > 남성신발 > 샌들/슬리퍼",
        "auction": "브랜드 잡화 > 남성화 > 샌들",
        "coupang": "패션의류잡화 > 남성패션 > 남성화 > 샌들 > 남성캐주얼샌들",
        "gmarket": "브랜드 잡화 > 남성화 > 샌들/슬리퍼",
    },
    # 23) 여성 샌들/슬리퍼 (현대, 전체 빈)
    "cm_01KQV73T5Z22JB9VM1APGZSM68": {
        "11st": "수입명품 > 여성신발 > 샌들/슬리퍼/뮬",
        "auction": "브랜드 잡화 > 여성화 > 샌들/슬리퍼",
        "coupang": "패션의류잡화 > 여성패션 > 여성화 > 샌들 > 여성뮬/슬리퍼형샌들",
        "gmarket": "브랜드 잡화 > 여성화 > 샌들",
        "smartstore": "패션잡화 > 여성신발 > 슬리퍼",
    },
    # 24) 여성 부츠/앵클부츠/부티
    "cm_01KQV6GVJVD1GGKYB8YZEEQRHX": {
        "auction": "브랜드 잡화 > 여성화 > 부츠/앵클부츠/부티",
        "coupang": "패션의류잡화 > 여성패션 > 여성화 > 부츠 > 여성앵클부츠",
    },
    # 25) 남성 런닝 속옷
    "cm_01KR5BBGQM9N99VTRH950YGZ32": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 민소매 런닝",
    },
    # 26) 남성 팬티
    "cm_01KR5BBGQPRDJ3V3D9EQ0KDSMT": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성속옷 > 사각/드로즈 팬티",
    },
    # 27) 여성 브라
    "cm_01KR5BBHNZNKW9ZWNSEFF4MBV8": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 여성속옷 상의 > 브라렛",
    },
    # 28) 남성속옷 내의/잠옷/타이즈
    "cm_01KR5BBGQGS1QEV58G9SVY2TK5": {
        "ssg": "신세계몰메인매장 > 언더웨어 > 남성 잠옷/이지웨어 > 잠옷세트",
    },
    # 29) 여성 브라/팬티세트 — ssg 세트 leaf 없음 → SKIP
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
        print(f"✓ GSShop batch1: 행 {rows_updated}, 키 {keys_added}")
        if rejected:
            print(f"⚠ 트리 미일치 {len(rejected)}건:")
            for r in rejected[:10]:
                print(f"  {r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
