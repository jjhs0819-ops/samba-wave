"""무신사(MUSINSA) 쿠팡 대량 등록 준비 스크립트.

무신사 수집 상품의 tenant_id NULL 보정 + 카테고리 매핑 INSERT.

GS샵과의 차이: 무신사 상품은 이미 "상의 > 반소매 티셔츠" 형식의 카테고리가 있으므로
상품명 기반 키워드 매핑 단계가 불필요함. 대신 _MUSINSA_SS_RULES 룩업 테이블 활용.

처리 흐름:
  1단계: 현황 진단 (카테고리 비어있는 상품, tenant_id NULL 상품)
  2단계: tenant_id NULL 보정
  3단계: samba_category_mapping INSERT
  4단계: 결과 리포트

실행:
  cd backend
  source .venv/bin/activate
  python scripts/prepare_musinsa_coupang.py
"""

import json
import sys
from datetime import datetime, timezone

import psycopg2
from ulid import ULID

# 무신사 카테고리 → 쿠팡 카테고리 경로 매핑 (category/service.py _MUSINSA_SS_RULES 참조)
MUSINSA_TO_COUPANG_PATH: dict[str, str] = {
    # ── 상의 ──
    "상의 > 반소매 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 긴소매 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 피케/카라 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 맨투맨/스웨트셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 후드 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 민소매 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "상의 > 니트/스웨터": "패션의류 > 남성의류 > 니트 > 풀오버",
    "상의 > 셔츠/블라우스": "패션의류 > 남성의류 > 셔츠/남방",
    "상의 > 기타 상의": "패션의류 > 남성의류 > 티셔츠",
    # ── 아우터 ──
    "아우터 > 후드 집업": "패션의류 > 남성의류 > 아우터 > 후드집업",
    "아우터 > 카디건": "패션의류 > 남성의류 > 니트 > 카디건",
    # "아우터 > 블루종/MA-1" → MUSINSA_DIRECT_CODES로 이동 (69529)
    "아우터 > 레더/라이더스 재킷": "패션의류 > 남성의류 > 아우터 > 레더재킷",
    "아우터 > 무스탕/퍼": "패션의류 > 남성의류 > 아우터 > 무스탕",
    "아우터 > 트러커 재킷": "패션의류 > 남성의류 > 아우터 > 재킷",
    "아우터 > 수트/블레이저 재킷": "패션의류 > 남성의류 > 아우터 > 재킷",
    # "아우터 > 나일론/코치 재킷" → MUSINSA_DIRECT_CODES로 이동 (79502)
    "아우터 > 트레이닝 재킷": "패션의류 > 남성의류 > 트레이닝복",
    "아우터 > 환절기 코트": "패션의류 > 남성의류 > 아우터 > 숏코트",
    "아우터 > 롱코트": "패션의류 > 남성의류 > 아우터 > 롱코트",
    "아우터 > 숏코트": "패션의류 > 남성의류 > 아우터 > 숏코트",
    "아우터 > 패딩": "패션의류 > 남성의류 > 아우터 > 패딩",
    "아우터 > 숏패딩/패딩조끼": "패션의류 > 남성의류 > 아우터 > 패딩",
    "아우터 > 롱패딩/패딩코트": "패션의류 > 남성의류 > 아우터 > 패딩",
    # "아우터 > 플리스/뽀글이" → MUSINSA_DIRECT_CODES로 이동 (79502)
    "아우터 > 사파리/헌팅 재킷": "패션의류 > 남성의류 > 아우터 > 재킷",
    # "아우터 > 기타 아우터" → MUSINSA_DIRECT_CODES로 이동 (79502)
    # "아우터 > 아노락 재킷" → MUSINSA_DIRECT_CODES로 이동 (79500)
    "아우터 > 베스트": "패션의류 > 남성의류 > 아우터 > 베스트",
    # ── 바지 ──
    "바지 > 데님 팬츠": "패션의류 > 남성의류 > 청바지",
    "바지 > 코튼 팬츠": "패션의류 > 남성의류 > 바지",
    "바지 > 슈트 팬츠/슬랙스": "패션의류 > 남성의류 > 바지",
    "바지 > 트레이닝/조거 팬츠": "패션의류 > 남성의류 > 트레이닝복",
    "바지 > 숏팬츠": "패션의류 > 남성의류 > 바지",
    "바지 > 레깅스": "패션의류 > 여성의류 > 레깅스",
    "바지 > 점프 슈트/오버올": "패션의류 > 남성의류 > 점프슈트",
    "바지 > 기타 바지": "패션의류 > 남성의류 > 바지",
    # ── 원피스/스커트 ──
    "원피스/스커트 > 미니원피스": "패션의류 > 여성의류 > 원피스",
    "원피스/스커트 > 미디원피스": "패션의류 > 여성의류 > 원피스",
    "원피스/스커트 > 맥시원피스": "패션의류 > 여성의류 > 원피스",
    "원피스/스커트 > 미니스커트": "패션의류 > 여성의류 > 스커트",
    "원피스/스커트 > 미디스커트": "패션의류 > 여성의류 > 스커트",
    "원피스/스커트 > 롱스커트": "패션의류 > 여성의류 > 스커트",
    # ── 신발 ──
    "신발 > 스니커즈": "패션잡화 > 남성신발 > 스니커즈",
    "신발 > 캔버스/단화": "패션잡화 > 남성신발 > 스니커즈",
    "신발 > 스포츠화 > 런닝화": "패션잡화 > 남성신발 > 운동화 > 러닝화",
    "신발 > 스포츠화 > 기타 운동화": "패션잡화 > 남성신발 > 운동화 > 워킹화",
    "신발 > 스포츠화 > 등산화": "스포츠/레저 > 등산 > 등산화",
    "신발 > 구두": "패션잡화 > 남성신발 > 구두",
    "신발 > 샌들/슬리퍼": "패션잡화 > 남성신발 > 샌들",
    "신발 > 부츠": "패션잡화 > 남성신발 > 부츠",
    "신발 > 기타 신발": "패션잡화 > 남성신발 > 스니커즈",
    # ── 가방 ──
    "가방 > 백팩": "패션잡화 > 가방 > 백팩",
    "가방 > 크로스백": "패션잡화 > 가방 > 크로스백",
    "가방 > 숄더백": "패션잡화 > 가방 > 숄더백",
    "가방 > 토트백": "패션잡화 > 가방 > 토트백",
    "가방 > 에코백": "패션잡화 > 가방 > 에코백/캔버스백",
    "가방 > 클러치 백": "패션잡화 > 가방 > 클러치/파우치",
    "가방 > 웨이스트 백": "패션잡화 > 가방 > 힙색/웨이스트백",
    "가방 > 캐리어": "패션잡화 > 가방 > 여행용 가방",
    # ── 모자 ──
    "모자 > 캡/야구 모자": "패션잡화 > 모자 > 캡모자",
    "모자 > 비니": "패션잡화 > 모자 > 비니",
    "모자 > 버킷/사파리햇": "패션잡화 > 모자 > 버킷햇",
    # ── 뷰티 ──
    "뷰티 > 베이스메이크업 > 블러셔": "화장품/미용 > 색조메이크업 > 블러셔",
    "뷰티 > 베이스메이크업 > 파운데이션": "화장품/미용 > 베이스메이크업 > 파운데이션",
    "뷰티 > 베이스메이크업 > 쿠션": "화장품/미용 > 베이스메이크업 > 쿠션",
    "뷰티 > 베이스메이크업 > 프라이머": "화장품/미용 > 베이스메이크업 > 프라이머",
    "뷰티 > 스킨케어 > 클렌징": "화장품/미용 > 스킨케어 > 클렌징",
    "뷰티 > 스킨케어 > 스킨/토너": "화장품/미용 > 스킨케어 > 스킨/토너",
    "뷰티 > 스킨케어 > 에센스/세럼": "화장품/미용 > 스킨케어 > 에센스/세럼/앰플",
    "뷰티 > 스킨케어 > 로션/크림": "화장품/미용 > 스킨케어 > 로션/크림",
    "뷰티 > 스킨케어 > 선크림": "화장품/미용 > 스킨케어 > 선케어",
    "뷰티 > 향수/탈취 > 향수": "화장품/미용 > 향수",
    "뷰티 > 뷰티 디바이스/소품 > 메이크업소품 > 기타 소품": "화장품/미용 > 뷰티소품 > 페이스소품 > 퍼프",
    # ── 스포츠/레저 ──
    "스포츠/레저 > 상의 > 반소매 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "스포츠/레저 > 상의 > 긴소매 티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "스포츠/레저 > 상의 > 반소매티셔츠": "패션의류 > 남성의류 > 티셔츠",
    "스포츠/레저 > 상의 > 나시/민소매": "패션의류 > 남성의류 > 티셔츠",
    "스포츠/레저 > 하의 > 숏팬츠": "패션의류 > 남성의류 > 바지",
    "스포츠/레저 > 하의 > 트레이닝팬츠": "패션의류 > 남성의류 > 트레이닝복",
    # "스포츠/레저 > 아우터 > 기타 점퍼/재킷" → MUSINSA_DIRECT_CODES로 이동 (79502)
    "스포츠/레저 > 아우터 > 트레이닝 재킷": "패션의류 > 남성의류 > 트레이닝복",
    # "스포츠/레저 > 아우터 > 바람막이" → MUSINSA_DIRECT_CODES로 이동 (79500)
    "스포츠/레저 > 신발 > 라이프스타일화": "패션잡화 > 남성신발 > 스니커즈",
    "스포츠/레저 > 신발 > 런닝화": "패션잡화 > 남성신발 > 운동화 > 러닝화",
    "스포츠/레저 > 신발 > 축구화": "스포츠/레저 > 축구 > 축구화",
    "스포츠/레저 > 신발 > 등산화": "스포츠/레저 > 등산 > 등산화",
}

# 경로 매칭으로 해결 불가한 카테고리 → 쿠팡 코드 직접 매핑
MUSINSA_DIRECT_CODES: dict[str, str] = {
    # ── 아우터 (패딩) ──
    "아우터 > 경량 패딩/패딩 베스트 > 경량 패딩": "69536",  # 남성 패딩/다운패딩점퍼
    "스포츠/레저 > 아우터 > 하프 패딩/하프 헤비 아우터": "69536",
    "스포츠/레저 > 아우터 > 롱 패딩/롱 헤비 아우터": "69536",
    "스포츠/레저 > 아우터 > 숏 패딩/숏 헤비 아우터": "69536",
    # ── 아우터 (재킷/점퍼) — "점퍼" 경로매칭 → 직접코드 (77284=점퍼루 버그 수정) ──
    "아우터 > 블루종/MA-1": "69529",  # 남성 항공점퍼/블루종
    "아우터 > 나일론/코치 재킷": "79502",  # 남성 기타 점퍼류
    "아우터 > 플리스/뽀글이": "79502",  # 남성 기타 점퍼류
    "아우터 > 기타 아우터": "79502",  # 남성 기타 점퍼류
    "아우터 > 아노락 재킷": "79500",  # 남성 바람막이 점퍼
    "스포츠/레저 > 아우터 > 나일론/코치 재킷": "79502",  # 남성 기타 점퍼류 (기존 77284 점퍼루 ❌)
    "스포츠/레저 > 아우터 > 기타 점퍼/재킷": "79502",  # 남성 기타 점퍼류
    "스포츠/레저 > 아우터 > 바람막이": "79500",  # 남성 바람막이 점퍼
    # ── 상의 ──
    "스포츠/레저 > 상의 > 기타상의": "111688",  # 남성 티셔츠
    "스포츠/레저 > 상의 > 맨투맨/스웨트": "111688",
    "스포츠/레저 > 상의 > 후드 티셔츠": "111688",
    "스포츠/레저 > 상의 > 피케/카라 티셔츠": "111688",
    # ── 하의 ──
    "스포츠/레저 > 하의 > 기타 바지": "69523",  # 남성 긴바지
    "스포츠/레저 > 하의 > 일자 팬츠": "69523",
    "스포츠/레저 > 하의 > 조거 팬츠": "70312",  # 트레이닝 팬츠
    "바지 > 숏 팬츠": "69972",  # 숏팬츠 (띄어쓰기 차이)
    # ── 가방 ──
    "스포츠/레저 > 가방 > 웨이스트 백": "69589",  # 남성힙색/허리색
    "스포츠/레저 > 가방 > 메신저/크로스 백": "69582",  # 남성크로스/메신저백
    "스포츠/레저 > 가방 > 보스턴/더플백": "81211",  # 팀백/더플백
    "스포츠/레저 > 가방 > 기타가방": "69582",  # 남성크로스/메신저백
    # ── 모자 ──
    "소품 > 모자 > 캡/야구모자": "69608",  # 남성야구모자/군모
    "소품 > 모자 > 버킷/사파리햇": "69611",  # 남성벙거지
    "소품 > 모자 > 헌팅캡/베레모": "69612",  # 남성베레모/헌팅캡
    "소품 > 모자 > 트루퍼": "69617",  # 남성귀달이 모자
    "소품 > 모자 > 기타 모자": "69608",  # 남성야구모자/군모
    # ── 신발 ──
    "신발 > 샌들/슬리퍼 > 스포츠/캐주얼 샌들": "67979",  # 남성캐주얼샌들
    "신발 > 부츠/워커 > 기타 부츠": "42626",  # 남성부츠
    "신발 > 부츠/워커 > 앵클/숏 부츠": "42626",
    # ── 잡화 ──
    "스포츠/레저 > 잡화 > 토시/슬리브": "81223",  # 팔토시/쿨토시
    # ── 기구/용품/장비 ──
    "스포츠/레저 > 기구/용품/장비 > 등산용품": "81747",  # 등산스틱 (일반 등산용품)
    "스포츠/레저 > 기구/용품/장비 > 캠핑용품": "81905",  # 캠핑소품
}

# 남성 코드 → 여성 코드 직접 매핑 (DB 조회 결과 하드코딩, 경로 부분매칭 버그 수정)
_MALE_TO_FEMALE_CODE: dict[str, str] = {
    # ── 점퍼류 ──
    "79502": "79404",  # 남성 기타 점퍼류 → 여성 기타점퍼
    "79500": "79403",  # 남성 바람막이 점퍼 → 여성 바람막이 점퍼
    "69529": "69207",  # 남성 항공점퍼/블루종 → 여성 항공점퍼/블루종
    "69536": "69214",  # 남성 패딩/다운패딩점퍼 → 여성 패딩/다운패딩점퍼
    "79501": "79402",  # 남성 패딩/다운패딩조끼 → 여성 패딩/다운패딩조끼
    "69530": "69208",  # 남성 야구점퍼/스타디움 → 여성 야구점퍼/스타디움
    "69531": "69209",  # 남성 야상/사파리 → 여성 야상/사파리
    # ── 티셔츠 ──
    "79488": "79381",  # 남성 긴소매 → 여성 긴소매
    "79489": "79382",  # 남성 반소매 → 여성 반소매
    "79490": "79383",  # 남성 민소매/나시 → 여성 민소매/나시
    "111688": "79382",  # (baby 코드, 범용 티셔츠로 사용) → 여성 반소매
    # ── 셔츠 ──
    "69516": "69187",  # 남성 캐주얼 셔츠 → 여성 블라우스
    "69517": "69188",  # 남성 와이셔츠 → 여성 셔츠(남방)
    # ── 니트/스웨터 ──
    "79491": "79387",  # 남성 라운드넥 → 여성 라운드넥
    "79492": "79388",  # 남성 브이넥 → 여성 브이넥
    "79493": "79389",  # 남성 터틀넥 → 여성 터틀넥
    "79494": "79390",  # 남성 카라넥 → 여성 카라넥
    "79495": "79391",  # 남성 후드 → 여성 후드
    # ── 후드집업 ──
    "69532": "69210",  # 남성 후드집업/집업류 → 여성 후드집업/집업류
    # ── 재킷 ──
    "79498": "79400",  # 남성 정장재킷 → 여성 정장재킷
    "79499": "79401",  # 남성 캐주얼재킷 → 여성 캐주얼재킷
    # ── 코트 ──
    "69534": "69212",  # 남성 봄가을 코트/트렌치 → 여성 봄가을 코트/트렌치
    "69535": "69213",  # 남성 겨울 코트 → 여성 겨울 코트
    # ── 베스트 ──
    "69520": "69198",  # 남성 베스트(조끼) → 여성 베스트(조끼)
    # ── 트레이닝복 ──
    "69538": "69216",  # 남성 트레이닝복 상의 → 여성 트레이닝복 상의
    "69539": "69217",  # 남성 트레이닝복 하의 → 여성 트레이닝복 하의
    "69540": "69218",  # 남성 트레이닝복 세트 → 여성 트레이닝복 세트
    "70312": "69217",  # (여아 트레이닝, 범용으로 사용) → 여성 트레이닝복 하의
    # ── 청바지 ──
    "69521": "69199",  # 남성 청바지 긴바지 → 여성 청바지 긴바지
    "69522": "69200",  # 남성 청바지 반바지 → 여성 청바지 반바지
    # ── 바지 ──
    "69523": "69201",  # 남성 긴바지 → 여성 긴바지
    "69524": "69202",  # 남성 반바지 → 여성 반바지
    "69972": "69202",  # (래쉬가드 반바지, 범용으로 사용) → 여성 반바지
    # ── 레깅스 ──
    "105917": "79398",  # 남성 레깅스 → 여성 레깅스
    "79398": "79398",  # 여성 레깅스 → 여성 레깅스 (이미 여성)
    # ── 셔츠 (해외직구) ──
    "69699": "69187",  # 남성 해외직구 셔츠/남방 → 여성 블라우스
    # ── 부분매칭으로 여성코드가 먼저 해석된 경우 (identity) ──
    "69216": "69216",  # 여성 트레이닝복 상의 (이미 여성)
    "69217": "69217",  # 여성 트레이닝복 하의 (이미 여성)
    "69198": "69198",  # 여성 베스트(조끼) (이미 여성)
    "111935": "111935",  # 여성 등산/아웃도어 플리스자켓 (이미 여성)
}

# 의류 카테고리 1단계 (성별 prefix 대상)
_CLOTHING_CAT1 = {"상의", "하의", "아우터", "바지", "원피스/스커트"}
_SPORT_CLOTHING_CAT2 = {"상의", "하의", "아우터"}


def _is_clothing_category(source_category: str) -> bool:
    """성별 prefix를 추가할 의류 카테고리인지 판별."""
    segments = [s.strip() for s in source_category.split(">")]
    cat1 = segments[0] if segments else ""
    if cat1 in _CLOTHING_CAT1:
        return True
    if cat1 == "스포츠/레저" and len(segments) > 1:
        return segments[1] in _SPORT_CLOTHING_CAT2
    return False


def _resolve_female_code(
    male_code: str,
    source_category: str,
    coupang_cat2: dict[str, str],
) -> str | None:
    """남성 코드 → 여성 코드 직접 변환 (경로 부분매칭 제거)."""
    female_code = _MALE_TO_FEMALE_CODE.get(male_code)
    if female_code:
        print(f"    [여성코드] {male_code} → {female_code}")
    return female_code


def find_coupang_code(
    source_category: str,
    coupang_cat2: dict[str, str],
) -> str | None:
    """source_category의 마지막 세그먼트를 쿠팡 cat2 경로에서 매칭."""
    if not source_category:
        return None

    # 0순위: 전체 경로 완전일치 (성별 구분이 필요한 경로에서 오매칭 방지)
    exact_code = coupang_cat2.get(source_category)
    if exact_code:
        print(f"  [경로일치] '{source_category}' -> (코드: {exact_code})")
        return str(exact_code)

    segments = [s.strip() for s in source_category.split(">")]
    keyword = segments[-1] if segments else ""
    if not keyword:
        return None

    # 1순위: 최하위 세그먼트 완전일치
    for path, code in coupang_cat2.items():
        path_segments = [s.strip() for s in path.split(">")]
        last_segment = path_segments[-1] if path_segments else ""
        if last_segment == keyword:
            print(f"  [완전일치] '{keyword}' -> {path} (코드: {code})")
            return str(code)

    # 2순위: 경로 내 부분일치
    candidates: list[tuple[str, str]] = []
    for path, code in coupang_cat2.items():
        if keyword in path:
            candidates.append((path, str(code)))

    if candidates:
        best = min(candidates, key=lambda x: len(x[0]))
        print(f"  [부분일치] '{keyword}' -> {best[0]} (코드: {best[1]})")
        return best[1]

    return None


def find_coupang_code_with_rules(
    musinsa_category: str,
    coupang_cat2: dict[str, str],
) -> str | None:
    """무신사 카테고리를 쿠팡 코드로 변환. 직접 코드 → 성별prefix → 룩업 → 경로 매칭."""
    # 0순위: 직접 코드 매핑 (경로 매칭 불가한 카테고리)
    direct_code = MUSINSA_DIRECT_CODES.get(musinsa_category)
    if direct_code:
        print(f"  [직접코드] '{musinsa_category}' -> {direct_code}")
        return direct_code

    # 0.5순위: 성별 prefix 처리 — prefix를 벗기고 base 코드 찾은 뒤 변환
    for prefix in ("남성의류 > ", "여성의류 > "):
        if musinsa_category.startswith(prefix):
            base_cat = musinsa_category[len(prefix) :]
            base_code = find_coupang_code_with_rules(base_cat, coupang_cat2)
            if not base_code:
                return None
            if prefix.startswith("남성"):
                return base_code  # 남성은 기존 코드 재사용
            # 여성은 남성코드 → 여성코드 변환
            return _resolve_female_code(base_code, base_cat, coupang_cat2)

    # 1순위: MUSINSA_TO_COUPANG_PATH 룩업
    coupang_path = MUSINSA_TO_COUPANG_PATH.get(musinsa_category)
    if coupang_path:
        print(f"  [룩업] '{musinsa_category}' -> '{coupang_path}'")
        code = find_coupang_code(coupang_path, coupang_cat2)
        if code:
            return code

    # 2순위: 원본 카테고리로 직접 매칭 (룩업에 없는 신규 카테고리)
    print(f"  [직접매칭] '{musinsa_category}'")
    return find_coupang_code(musinsa_category, coupang_cat2)


def main() -> None:
    conn = psycopg2.connect(
        host="localhost",
        port=5433,
        dbname="test_little_boy",
        user="test_user",
        password="test_password",
    )
    cur = conn.cursor()

    try:
        # ============================================================
        # 1단계: 현황 진단
        # ============================================================
        print("=" * 60)
        print("1단계: 현황 진단")
        print("=" * 60)

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'MUSINSA'
        """)
        total = cur.fetchone()[0]
        print(f"  전체 MUSINSA 상품: {total}건")

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'MUSINSA' AND (category IS NULL OR category = '')
        """)
        empty_cat = cur.fetchone()[0]
        print(f"  카테고리 비어있는 상품: {empty_cat}건")

        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'MUSINSA' AND tenant_id IS NULL
        """)
        null_tenant = cur.fetchone()[0]
        print(f"  tenant_id NULL 상품: {null_tenant}건")

        if total == 0:
            print("\nMUSINSA 수집 상품이 없습니다.")
            sys.exit(0)

        print()

        # ============================================================
        # 2단계: tenant_id NULL 보정
        # ============================================================
        print("=" * 60)
        print("2단계: tenant_id NULL 보정")
        print("=" * 60)

        if null_tenant > 0:
            # 기존 MUSINSA 상품 중 tenant_id가 있는 값 조회
            cur.execute("""
                SELECT DISTINCT tenant_id FROM samba_collected_product
                WHERE source_site = 'MUSINSA' AND tenant_id IS NOT NULL
                LIMIT 1
            """)
            row = cur.fetchone()

            if row and row[0]:
                ref_tenant_id = row[0]
                print(f"  참조 tenant_id: {ref_tenant_id}")

                cur.execute(
                    """
                    UPDATE samba_collected_product
                    SET tenant_id = %s, updated_at = NOW()
                    WHERE source_site = 'MUSINSA' AND tenant_id IS NULL
                """,
                    (ref_tenant_id,),
                )
                tenant_updated = cur.rowcount
                print(f"  tenant_id 보정: {tenant_updated}건")
            else:
                print("  WARNING: 참조할 tenant_id가 없습니다. 수동 지정 필요.")
        else:
            print("  tenant_id NULL 없음 — 보정 불필요")

        print()

        # ============================================================
        # 3단계: samba_category_mapping INSERT
        # ============================================================
        print("=" * 60)
        print("3단계: samba_category_mapping INSERT")
        print("=" * 60)

        # 기존 MUSINSA 매핑 삭제 후 재생성
        cur.execute("DELETE FROM samba_category_mapping WHERE source_site = 'MUSINSA'")
        deleted = cur.rowcount
        print(f"  기존 MUSINSA 매핑 {deleted}건 삭제")

        # 쿠팡 cat2 트리 로드
        cur.execute("SELECT cat2 FROM samba_category_tree WHERE site_name = 'coupang'")
        tree_row = cur.fetchone()
        if not tree_row or not tree_row[0]:
            print("  WARNING: 쿠팡 카테고리 트리(cat2)가 없습니다. 매핑 INSERT 스킵.")
        else:
            coupang_cat2: dict[str, str] = tree_row[0]
            if isinstance(coupang_cat2, str):
                coupang_cat2 = json.loads(coupang_cat2)
            print(f"  쿠팡 cat2 경로 {len(coupang_cat2)}건 로드")

            # MUSINSA 상품의 고유 카테고리 조회
            cur.execute("""
                SELECT DISTINCT category
                FROM samba_collected_product
                WHERE source_site = 'MUSINSA' AND category IS NOT NULL AND category != ''
            """)
            categories = [row[0] for row in cur.fetchall()]
            print(f"  MUSINSA 고유 카테고리 {len(categories)}건")

            inserted = 0
            skipped_nomatch = 0

            def _insert_mapping(cat: str, code: str) -> None:
                nonlocal inserted
                now = datetime.now(tz=timezone.utc)
                mapping_id = f"cm_{ULID()}"
                target_mappings = json.dumps({"coupang": code})
                cur.execute(
                    """
                    INSERT INTO samba_category_mapping
                    (id, source_site, source_category, target_mappings, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (mapping_id, "MUSINSA", cat, target_mappings, now, now),
                )
                print(f"    INSERT: id={mapping_id}, cat='{cat}', coupang={code}")
                inserted += 1

            for source_category in categories:
                print(f"\n  [{source_category}]")

                matched_code = find_coupang_code_with_rules(
                    source_category, coupang_cat2
                )
                if not matched_code:
                    print(f"    SKIP: 매칭 실패 — 수동 매핑 필요")
                    skipped_nomatch += 1
                    continue

                # 기존 매핑 INSERT
                _insert_mapping(source_category, matched_code)

                # 의류 카테고리 → 성별 prefix 매핑 추가
                if _is_clothing_category(source_category):
                    # 남성의류 prefix — 기존 남성 코드 재사용
                    male_cat = f"남성의류 > {source_category}"
                    _insert_mapping(male_cat, matched_code)

                    # 여성의류 prefix — 여성 코드 런타임 조회
                    female_cat = f"여성의류 > {source_category}"
                    female_code = _resolve_female_code(
                        matched_code, source_category, coupang_cat2
                    )
                    if female_code:
                        _insert_mapping(female_cat, female_code)
                    else:
                        print(f"    SKIP 여성: '{female_cat}' 여성 코드 조회 실패")

            print(f"\n  매핑 INSERT: {inserted}건, 매칭실패: {skipped_nomatch}건")

        # 커밋
        conn.commit()
        print("\n  DB 커밋 완료")
        print()

        # ============================================================
        # 4단계: 결과 리포트
        # ============================================================
        print("=" * 60)
        print("4단계: 결과 리포트")
        print("=" * 60)

        # 카테고리별 상품 수
        print("\n  [카테고리별 상품 수]")
        cur.execute("""
            SELECT category, COUNT(*) as cnt
            FROM samba_collected_product
            WHERE source_site = 'MUSINSA'
            GROUP BY category
            ORDER BY cnt DESC
        """)
        for cat, cnt in cur.fetchall():
            print(f"    {cat or '(빈값)'}: {cnt}건")

        # tenant_id 확인
        print("\n  [tenant_id NULL 잔존 확인]")
        cur.execute("""
            SELECT COUNT(*) FROM samba_collected_product
            WHERE source_site = 'MUSINSA' AND tenant_id IS NULL
        """)
        remaining_null = cur.fetchone()[0]
        print(f"    tenant_id NULL: {remaining_null}건")

        # 카테고리 매핑 확인
        print("\n  [MUSINSA 카테고리 매핑]")
        cur.execute("""
            SELECT source_category, target_mappings
            FROM samba_category_mapping
            WHERE source_site = 'MUSINSA'
            ORDER BY created_at
        """)
        for row in cur.fetchall():
            mappings = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            print(f"    {row[0]} -> coupang:{mappings.get('coupang', 'N/A')}")

        print("\n완료!")

    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
