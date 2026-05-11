"""GSShop 2차 batch (행 30~62) LLM 직접 매핑 결정 적용."""

import asyncio
import asyncpg
import json
from backend.core.config import settings


DECISIONS: dict[str, dict[str, str]] = {
    # 30) 바람막이점퍼 (남성)
    "cm_01KQV6GVJ11QF4CEEJNFVCNWRD": {
        "11st": "남성의류 > 점퍼 > 바람막이점퍼",
        "auction": "남성의류 > 점퍼/야상/패딩 > 바람막이점퍼",
        "coupang": "패션의류잡화 > 유니섹스/남녀공용 패션 > 캐주얼 의류 > 점퍼 > 공용 바람막이 점퍼",
        "lotteon": "남성의류 > 점퍼/패딩/야상 > 바람막이점퍼",
        "smartstore": "패션의류 > 남성의류 > 점퍼",
    },
    # 31) 액세서리 모자
    "cm_01KR5BBJRXETHVQYQEQ17VY9A2": {
        "ssg": "신세계몰메인매장 > 모자/장갑/ACC > 모자 > 비니",
    },
    # 32) 헬스 보호대
    "cm_01KR5BBNV19EZM53SA1HFVYHH9": {
        "ssg": "신세계몰메인매장 > 헬스/요가/격투기 > 헬스소품/보호대",
    },
    # 33) 수영가방
    "cm_01KQV6GVRZPJMAX1X0XKD5N5RS": {
        "auction": "휘트니스/수영 > 수영용품 > 수영가방",
        "gmarket": "휘트니스/수영 > 수영용품 > 수영가방",
        "lotteon": "헬스/수영용품 > 수영용품 > 수영가방",
        "smartstore": "스포츠/레저 > 수영 > 수영용품 > 수영가방",
    },
    # 34) 아이젠/스패츠
    "cm_01KQV6GVTAQPX0T8KB8KETJV6Q": {
        "11st": "등산/아웃도어 > 등산용품 > 아이젠",
        "auction": "등산/아웃도어 > 등산장비 > 아이젠",
        "gmarket": "등산/아웃도어 > 등산장비 > 아이젠",
        "lotteon": "등산/아웃도어 > 등산용품/장비 > 아이젠",
        "smartstore": "스포츠/레저 > 등산 > 등산장비 > 아이젠",
    },
    # 35) 경등산화
    "cm_01KPC7S0T5Q716T1K5QBRNHMVN": {
        "smartstore": "스포츠/레저 > 등산 > 등산화",
    },
    # 36) 중등산화
    "cm_01KQV6GV5PBJNC4P8Z50B8TZQG": {
        "11st": "등산/아웃도어 > 등산화 > 중등산화",
        "auction": "등산/아웃도어 > 등산화/트레킹화 > 등산화",
        "coupang": "스포츠/레져 > 등산 > 등산/아웃도어 신발 > 남녀공용 > 트레킹화",
        "gmarket": "등산/아웃도어 > 등산화/트레킹화 > 등산화",
        "lotteon": "등산/아웃도어 > 등산화/트래킹화 > 등산화",
    },
    # 37) 트레킹화
    "cm_01KPC7S11MD7K3PGA8PZGBG7JW": {
        "smartstore": "스포츠/레저 > 등산 > 등산화",
    },
    # 38) 트레킹샌들
    "cm_01KQV6GV6BFDZ8ZP2CKNZF7NMD": {
        "11st": "등산/아웃도어 > 등산화 > 트레킹화",
        "coupang": "스포츠/레져 > 등산 > 등산/아웃도어 신발 > 남녀공용 > 트레킹화",
        "gmarket": "등산/아웃도어 > 등산화/트레킹화 > 트레킹화",
        "lotteon": "등산/아웃도어 > 등산화/트래킹화 > 트레킹화",
        "smartstore": "스포츠/레저 > 등산 > 등산화",
    },
    # 39) 등산가방 - lotteon SKIP
    # 40) 등산스틱
    "cm_01KQV6GV3N933ZB8ZJYBN66PWC": {
        "11st": "등산/아웃도어 > 등산스틱 > T자형",
        "auction": "등산/아웃도어 > 등산장비 > 등산스틱",
        "gmarket": "등산/아웃도어 > 등산장비 > 등산스틱",
        "lotteon": "등산/아웃도어 > 등산용품/장비 > 등산스틱/폴",
        "smartstore": "스포츠/레저 > 등산 > 기타등산장비",
    },
    # 41) 등산양말 - smartstore SKIP
    # 42) 등산장갑
    "cm_01KQV6GV7WQ7VW6389M1961YYF": {
        "auction": "등산/아웃도어 > 등산잡화/배낭 > 등산장갑",
        "gmarket": "등산/아웃도어 > 등산잡화/배낭 > 등산장갑",
    },
    # 43) 기타등산용품
    "cm_01KPC7RZYMVJWPY1RGXCMSTGD8": {
        "smartstore": "스포츠/레저 > 등산 > 기타등산장비",
    },
    # 44) 남성등산 다운/패딩 - smartstore SKIP
    # 45) 여성등산 다운/패딩 - smartstore SKIP
    # 46) 남성등산 자켓/플리스
    "cm_01KPC7RZ1GS20BYMF24JXMV7AV": {
        "smartstore": "스포츠/레저 > 등산 > 등산의류 > 재킷",
    },
    # 47) 여성등산 바지/스커트
    "cm_01KPC7S1WH4DME5MX9QTR88MW1": {
        "lotteon": "등산/아웃도어 > 여성등산의류 > 긴바지",
    },
    # 48) 여성등산 자켓/플리스
    "cm_01KPC7S24VQASMP4AJMN7TATVA": {
        "lotteon": "등산/아웃도어 > 여성등산의류 > 점퍼",
        "smartstore": "스포츠/레저 > 등산 > 등산의류 > 재킷",
    },
    # 49) 남성등산 티셔츠
    "cm_01KPC7RZKN7DNPP8QYETYXR47P": {
        "lotteon": "등산/아웃도어 > 남성등산의류 > 티셔츠 > 반팔티셔츠",
    },
    # 50) 여성등산 티셔츠
    "cm_01KPC7S2R608A89AJ9E0M94KNX": {
        "lotteon": "등산/아웃도어 > 여성등산의류 > 티셔츠 > 반팔티셔츠",
    },
    # 51) 남성등산 바람막이/아노락
    "cm_01KPC7RYGAESHG883E08ND58QM": {
        "smartstore": "스포츠/레저 > 등산 > 등산의류 > 재킷",
    },
    # 52) 여성등산 바람막이/아노락
    "cm_01KPC7S1MF794HGZ2JF7A5E1QT": {
        "smartstore": "스포츠/레저 > 등산 > 등산의류 > 재킷",
    },
    # 53) 캠핑 랜턴/조명
    "cm_01KR5BBMTZD998ZKWQBECEAVAP": {
        "ssg": "신세계몰메인매장 > 캠핑/낚시 > 랜턴/조명/공구 > 랜턴/램프/후레쉬",
    },
    # 54) 남성골프화
    "cm_01KQV6GVSMSMZ5SDVPRH5T6KAY": {
        "11st": "수입명품 > 골프 > 남성골프화",
        "auction": "골프 > 골프화 > 남성골프화",
        "coupang": "스포츠/레져 > 골프 > 골프신발 > 남성용 > 골프화",
        "gmarket": "골프 > 골프화 > 남성골프화",
        "lotteon": "골프용품 > 골프화 > 남성골프화",
    },
    # 55) 여성골프 바지
    "cm_01KR5BBJRZ1FXWBDE9S7MG49VZ": {
        "ssg": "신세계몰메인매장 > 골프 > 여성 골프의류 > 긴바지",
    },
    # 56) 여성골프 스커트
    "cm_01KPPTM5F627RBMZJZV3GW6GBS": {
        "lotteon": "골프의류 > 여성골프의류 > 스커트/큐롯 > 스커트",
    },
    # 57) 남성골프 반팔티셔츠
    "cm_01KQV6GVF7VZF9YEAA992FYD50": {
        "lotteon": "골프의류 > 남성골프의류 > 티셔츠 > 반팔티셔츠",
        "smartstore": "스포츠/레저 > 골프 > 골프의류 > 티셔츠",
    },
    # 58) 수영복/래쉬가드 - smartstore SKIP
    # 59) 스포츠가방 백팩
    "cm_01KPPTM6JTC77YXY90DWTDCJCB": {
        "lotteon": "스포츠의류/운동화 > 스포츠가방 > 백팩 > 남성용",
    },
    # 60) 스포츠신발 샌들
    "cm_01KQV6GV03Q7R9YGMH763VC7QV": {
        "11st": "스포츠 잡화 > 슬리퍼/샌들 > 성인 샌들",
        "auction": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "gmarket": "스포츠의류/운동화 > 스포츠화 > 스포츠샌들",
        "lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 샌들",
    },
    # 61) 스포츠신발 방한화/부츠
    "cm_01KQV6GVGJJ5J49N634BPV9V4K": {
        "11st": "스포츠 신발 > 운동화/스니커즈 > 방한화/부츠",
        "auction": "신발 > 남성캐주얼화 > 방한화/털부츠",
        "gmarket": "신발 > 남성워커/부츠 > 부츠/방한화",
        "lotteon": "스포츠의류/운동화 > 남성스포츠신발 > 방한화",
    },
    # 62) 스포츠신발 운동화/스니커즈 - smartstore SKIP
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
        print(f"✓ GSShop batch2: 행 {rows_updated}, 키 {keys_added}")
        if rejected:
            print(f"⚠ 트리 미일치 {len(rejected)}건 (위 5건):")
            for r in rejected[:5]:
                print(f"  {r}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
