"""빈 target_mappings={} 카테고리 매핑 채우기 + 신세계몰 기본값 적용."""
import asyncio
import json
import sys

sys.path.insert(0, '/app/backend')
from backend.core.config import settings

SSG_DEFAULT = "신세계몰메인매장 > 스포츠웨어/용품 > 러닝화/의류"

# (source_site, source_category) → 각 마켓 매핑
MAPPINGS = {
    ('ABCmart', '신발 > 스포츠 > 골프화'): {
        'smartstore': '스포츠/레저 > 골프 > 골프화',
        'lotteon': '골프의류 > 골프화',
        '11st': '스포츠 신발 > 골프화',
        'gmarket': '스포츠의류/운동화 > 스포츠신발 > 골프화',
        'auction': '스포츠의류/운동화 > 스포츠신발 > 골프화',
        'coupang': '스포츠/레져 > 골프 > 골프화',
        'lottehome': '스포츠/레저 > 골프용품 > 골프화',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('ABCmart', '신발 > 스포츠 > 등산화'): {
        'smartstore': '스포츠/레저 > 등산 > 등산화',
        'lotteon': '등산/아웃도어 > 등산화',
        '11st': '등산/아웃도어 > 등산화/샌들 > 등산화',
        'gmarket': '등산/아웃도어 > 등산화/샌들 > 등산화',
        'auction': '등산/아웃도어 > 등산화/샌들 > 등산화',
        'coupang': '스포츠/레져 > 아웃도어/등산 > 등산화',
        'lottehome': '스포츠/레저 > 아웃도어 > 등산화',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('ABCmart', '용품 > 스포츠 > 스윔'): {
        'smartstore': '스포츠/레저 > 수영 > 수영용품',
        'lotteon': '헬스/수영용품 > 수영용품',
        '11st': '헬스 > 수영용품',
        'gmarket': '휘트니스/수영 > 수영용품',
        'auction': '휘트니스/수영 > 수영용품',
        'coupang': '스포츠/레져 > 헬스/요가 > 수영용품',
        'lottehome': '스포츠/레저 > 수영용품',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('ABCmart', '용품 > 신발용품 > 인솔'): {
        'smartstore': '스포츠/레저 > 등산 > 등산잡화 > 깔창/인솔',
        'lotteon': '등산/아웃도어 > 등산배낭/잡화 > 깔창/인솔',
        '11st': '등산/아웃도어 > 등산잡화 > 깔창/인솔',
        'gmarket': '등산/아웃도어 > 등산잡화/배낭 > 깔창/인솔',
        'auction': '등산/아웃도어 > 등산잡화/배낭 > 깔창/인솔',
        'coupang': '스포츠/레져 > 아웃도어/등산 > 등산잡화 > 깔창/인솔',
        'lottehome': '스포츠/레저 > 아웃도어 > 등산용품',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('ABCmart', '의류 > 스포츠 > 스윔웨어'): {
        'smartstore': '스포츠/레저 > 수영 > 수영복',
        'lotteon': '스포츠의류/운동화 > 수영복/비치웨어',
        '11st': '스포츠 의류 > 수영복',
        'gmarket': '스포츠의류/운동화 > 수영복',
        'auction': '스포츠의류/운동화 > 수영복',
        'coupang': '스포츠/레져 > 헬스/요가 > 수영복',
        'lottehome': '스포츠/레저 > 수영용품 > 수영복',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('FashionPlus', '아웃도어/레저 > 등산화 > 아쿠아슈즈'): {
        'smartstore': '스포츠/레저 > 등산 > 등산화',
        'lotteon': '등산/아웃도어 > 등산화',
        '11st': '등산/아웃도어 > 등산화/샌들 > 아쿠아슈즈',
        'gmarket': '등산/아웃도어 > 등산화/샌들 > 아쿠아/워터슈즈',
        'auction': '등산/아웃도어 > 등산화/샌들 > 아쿠아/워터슈즈',
        'coupang': '스포츠/레져 > 아웃도어/등산 > 등산화',
        'lottehome': '스포츠/레저 > 아웃도어 > 등산화',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('LOTTEON', '스포츠/레저 > 의류 > 남성의류 > 니트/가디건'): {
        'smartstore': '패션의류 > 남성의류 > 니트/가디건',
        'lotteon': '남성패션 > 의류 > 니트/가디건 > 남성가디건',
        '11st': '남성의류 > 니트 > 니트/가디건',
        'gmarket': '남성의류 > 니트/스웨터 > 가디건',
        'auction': '남성의류 > 니트/스웨터 > 가디건',
        'coupang': '패션의류잡화 > 남성패션 > 남성의류 > 니트/스웨터/가디건 > 남성 가디건',
        'lottehome': '패션의류 > 남성의류 > 니트/가디건',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('MUSINSA', '신발 > 스포츠화 > 골프화'): {
        'smartstore': '스포츠/레저 > 골프 > 골프화',
        'lotteon': '골프의류 > 골프화',
        '11st': '스포츠 신발 > 골프화',
        'gmarket': '스포츠의류/운동화 > 스포츠신발 > 골프화',
        'auction': '스포츠의류/운동화 > 스포츠신발 > 골프화',
        'coupang': '스포츠/레져 > 골프 > 골프화',
        'lottehome': '스포츠/레저 > 골프용품 > 골프화',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('MUSINSA', '신발 > 신발용품 > 깔창'): {
        'smartstore': '스포츠/레저 > 등산 > 등산잡화 > 깔창/인솔',
        'lotteon': '등산/아웃도어 > 등산배낭/잡화 > 깔창/인솔',
        '11st': '등산/아웃도어 > 등산잡화 > 깔창/인솔',
        'gmarket': '등산/아웃도어 > 등산잡화/배낭 > 깔창/인솔',
        'auction': '등산/아웃도어 > 등산잡화/배낭 > 깔창/인솔',
        'coupang': '스포츠/레져 > 아웃도어/등산 > 등산잡화 > 깔창/인솔',
        'lottehome': '스포츠/레저 > 아웃도어 > 등산용품',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    # SSG 소싱처 카테고리 → 판매 마켓 매핑
    ('SSG', '가디건 > 니트웨어'): {
        # 이미 다른 마켓은 있고 smartstore만 없음
        'smartstore': '패션의류 > 여성의류 > 니트/가디건',
        'lotteon': '여성패션 > 의류 > 가디건',
        '11st': '여성의류 > 니트 > 가디건',
        'gmarket': '여성의류 > 니트/스웨터 > 가디건',
        'auction': '여성의류 > 니트/스웨터 > 가디건',
        'coupang': '패션의류잡화 > 여성패션 > 여성의류 > 니트/스웨터/가디건 > 여성 가디건',
        'lottehome': '패션의류 > 여성의류 > 니트/가디건',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('SSG', '남성팬츠'): {
        'smartstore': '패션의류 > 남성의류 > 바지',
        'lotteon': '남성패션 > 의류 > 긴바지 > 캐주얼팬츠',
        '11st': '남성의류 > 긴바지 > 캐주얼팬츠',
        'gmarket': '남성의류 > 바지 > 캐주얼팬츠',
        'auction': '남성의류 > 바지 > 캐주얼팬츠',
        'coupang': '패션의류잡화 > 남성패션 > 남성의류 > 바지 > 남성 긴바지',
        'lottehome': '패션의류 > 남성의류 > 바지',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('SSG', '영캐주얼 > 맨투맨/후드/티셔츠 > 라운드넥 티셔츠'): {
        'smartstore': '패션의류 > 남성의류 > 티셔츠',
        'lotteon': '브랜드진/캐주얼 > 반팔티셔츠/나시 > 라운드넥티셔츠',
        '11st': '남성의류 > 반팔티셔츠 > 라운드넥티셔츠',
        'gmarket': '남성의류 > 반팔티셔츠 > 라운드넥티셔츠',
        'auction': '남성의류 > 반팔티셔츠 > 라운드넥티셔츠',
        'coupang': '패션의류잡화 > 남성패션 > 남성의류 > 반팔 티셔츠 > 남성 라운드넥 반팔티셔츠',
        'lottehome': '패션의류 > 남성의류 > 티셔츠',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('SSG', '해외명품 > 잡화/ACC > 기타소품'): {
        'smartstore': '패션잡화 > 패션소품 > 기타소품',
        'lotteon': '여성패션 > 액세서리 > 패션소품 > 기타패션소품',
        '11st': '패션잡화 > 패션소품 > 기타',
        'gmarket': '패션잡화 > 패션소품 > 기타잡화',
        'auction': '패션잡화 > 패션소품 > 기타잡화',
        'coupang': '패션의류잡화 > 여성패션 > 여성잡화 > 패션소품 > 기타 여성패션소품',
        'lottehome': '패션의류 > 잡화 > 기타잡화',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
    ('SSG', '핸드백/지갑 > 여성가방 > 토트백'): {
        'smartstore': '패션잡화 > 여성가방 > 토트백',
        'lotteon': '가방/지갑 > 여성가방 > 토트백',
        '11st': '수입명품 > 여성가방 > 토트백',
        'gmarket': '가방/잡화 > 여성가방 > 토트백',
        'auction': '가방/잡화 > 여성가방 > 토트백',
        'coupang': '패션의류잡화 > 여성패션 > 여성잡화 > 가방 > 여성토트백',
        'lottehome': '패션의류 > 잡화 > 가방 > 토트백',
        'ssg': SSG_DEFAULT,
        'ssg_std': SSG_DEFAULT,
    },
}


async def main():
    import asyncpg  # noqa: F401

    conn = await asyncpg.connect(
        host=settings.write_db_host,
        port=settings.write_db_port,
        ssl=False,
        user=settings.write_db_user,
        password=settings.write_db_password,
        database=settings.write_db_name,
    )

    ok, err = 0, 0
    for (site, cat), new_vals in MAPPINGS.items():
        try:
            row = await conn.fetchrow(
                "SELECT id, target_mappings::text FROM samba_category_mapping"
                " WHERE source_site=$1 AND source_category=$2",
                site, cat,
            )
            if row:
                existing = json.loads(row['target_mappings']) if row['target_mappings'] else {}
                # 기존 값 보존 + 빈 것만 채움
                merged = {**new_vals}
                for k, v in existing.items():
                    if v and v.strip():
                        merged[k] = v
                await conn.execute(
                    "UPDATE samba_category_mapping SET target_mappings=CAST($1 AS jsonb) WHERE id=$2",
                    json.dumps(merged, ensure_ascii=False),
                    row['id'],
                )
                print(f"UPDATE: {site}|{cat}")
            else:
                await conn.execute(
                    "INSERT INTO samba_category_mapping (id, source_site, source_category, target_mappings)"
                    " VALUES (gen_random_uuid(), $1, $2, CAST($3 AS jsonb))",
                    site, cat, json.dumps(new_vals, ensure_ascii=False),
                )
                print(f"INSERT: {site}|{cat}")
            ok += 1
        except Exception as e:
            print(f"ERR: {site}|{cat} => {e}")
            err += 1

    print(f"\n완료: OK={ok}, ERR={err}")
    await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
