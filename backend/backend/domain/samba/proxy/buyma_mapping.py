"""무신사 수집상품 → BUYMA PS-API 등록 payload 매핑.

BUYMA 마스터데이터(buyma_master/*.csv)를 로드해 브랜드/카테고리/색/사이즈/배송/가격을
매핑한다. 샌드박스에서 상의·아우터·신발 전 카테고리 201 검증 완료된 로직.
"""

from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

_MD = Path(__file__).parent / "buyma_master"

# 한국 지역 ID (買付地/発送地)
KOREA_AREA_ID = "2002003000"

# 타겟 브랜드 (무신사 slug/name → BUYMA brand_id). 출품금지(5252/ASCLO) 제외됨.
TARGET_BRAND: dict[str, int] = {
    "covernat": 7738,
    "커버낫": 7738,
    "discoveryexpedition": 9810,
    "디스커버리익스페디션": 9810,
    "디스커버리": 9810,
    "nationalgeographic": 9737,
    "내셔널지오그래픽": 9737,
    "kodak": 14836,
    "코닥": 14836,
    "kangol": 643,
    "캉골": 643,
    "thisisneverthat": 6228,
    "디스이즈네버댓": 6228,
    "kirsh": 7984,
    "키르시": 7984,
    "acmedelavie": 10710,
    "아크메드라비": 10710,
    "lmc": 11283,
    "mahagrid": 13137,
    "마하그리드": 13137,
    "matinkim": 14188,
    "마뗑킴": 14188,
    "marithefrancoisgirbaud": 15634,
    "마리떼프랑소와저버": 15634,
    "마리떼": 15634,
}


@lru_cache(maxsize=1)
def _sizes() -> list[dict]:
    with open(_MD / "sizes.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _colors() -> dict[str, int]:
    with open(_MD / "colors.csv", encoding="utf-8-sig") as f:
        return {r["name"]: int(r["id"]) for r in csv.DictReader(f)}


def brand_id(brand: str) -> int:
    """무신사 브랜드명/slug → BUYMA brand_id (없으면 0)."""
    key = (brand or "").strip().lower().replace(" ", "")
    return TARGET_BRAND.get(key) or TARGET_BRAND.get((brand or "").strip(), 0)


# 무신사 카테고리 키워드(depth1~3) → BUYMA 레디스 category_id
_CATEGORY_RULES = [
    (("패딩", "다운"), 3062),
    (("코트",), 3060),
    (("플리스", "후리스"), 3257),
    (("재킷", "자켓", "점퍼", "블루종", "바람막이", "헤비 아우터", "야상"), 3061),
    (("반소매", "티셔츠", "긴소매"), 3001),
    (("후드", "후디"), 3005),
    (("맨투맨", "스웨트"), 3006),
    (("니트", "스웨터", "가디건"), 3004),
    (("셔츠", "블라우스"), 3007),
    (("스니커", "운동화", "신발"), 3081),
]


def map_category(depth1: str = "", depth2: str = "", depth3: str = "") -> int:
    t = (depth1 or "") + (depth2 or "") + (depth3 or "")
    for kws, cid in _CATEGORY_RULES:
        if any(k in t for k in kws):
            return cid
    if "아우터" in t:
        return 3061
    return 3010  # トップスその他


# 색상 문자열 → (계통 master_id, 일본어 색명)
_COLOR_RULES = [
    (("블랙", "black"), 2, "ブラック"),
    (("화이트", "white", "아이보리"), 1, "ホワイト"),
    (("그레이", "gray", "grey", "차콜"), 3, "グレー"),
    (("브라운", "brown", "카멜"), 4, "ブラウン"),
    (("베이지", "beige", "크림"), 5, "ベージュ"),
    (("카키",), 6, "カーキ"),
    (("그린", "green"), 6, "グリーン"),
    (("네이비", "navy"), 16, "ネイビー"),
    (("블루", "blue"), 7, "ブルー"),
    (("레드", "red"), 11, "レッド"),
    (("핑크", "pink"), 10, "ピンク"),
    (("퍼플", "purple"), 8, "パープル"),
    (("옐로", "yellow"), 9, "イエロー"),
    (("오렌지", "orange"), 12, "オレンジ"),
    (("실버",), 13, "シルバー"),
]


def map_color(text: str) -> tuple[int, str]:
    s = (text or "").lower()
    for kws, cid, jp in _COLOR_RULES:
        if any(k in s for k in kws):
            return cid, jp
    return 99, "マルチカラー"


# 한국 여성복 숫자사이즈 → 알파벳 (근사, 브랜드별 편차 있음)
_KR_NUM_SIZE = {
    "75": "XS",
    "80": "XS",
    "85": "S",
    "90": "M",
    "95": "L",
    "100": "XL",
    "105": "XL",
    "110": "XL",
    "44": "XS",
    "55": "S",
    "66": "M",
    "77": "L",
    "88": "XL",
}


def size_master(label: str, category_id: int) -> int | None:
    """무신사 사이즈 라벨 + BUYMA category_id → size master_id (없으면 None)."""
    lab = (label or "").strip().upper()
    cid = int(category_id)
    cands = [r for r in _sizes() if str(r["category_id"]) == str(category_id)]
    # 신발(3080~3088): 무신사 mm(230/23.5/24) → master id(=mm)
    if 3080 <= cid <= 3088:
        digits = lab.replace("CM", "").replace(".", "").strip()
        if digits.isdigit():
            mm = digits if len(digits) >= 3 else str(int(digits) * 10)
            for r in cands:
                if str(r["id"]) == mm:
                    return int(r["id"])
        return None
    # 의류: 한국 숫자사이즈 → 알파벳
    if lab.isdigit():
        lab = _KR_NUM_SIZE.get(lab, lab)
    # 정확매칭
    for r in cands:
        if r["name"].upper() == lab:
            return int(r["id"])
    # 以上/以下 제거 후 매칭 (XL→XL以上, XS→XS以下)
    for r in cands:
        nm = r["name"].upper().replace("以上", "").replace("以下", "").strip()
        if nm == lab:
            return int(r["id"])
    # XXL/2XL→XL계열, FREE→フリー
    if lab in ("XXL", "2XL", "3XL", "XXXL"):
        for r in cands:
            if r["name"].upper().startswith("XL"):
                return int(r["id"])
    if lab in ("F", "FREE", "ONESIZE", "ONE SIZE"):
        for r in cands:
            if "フリー" in r["name"] or "FREE" in r["name"].upper():
                return int(r["id"])
    return None


# 카테고리 → (배송방법ID, 배송비KRW, 라벨). K패킷 2kg상한 초과는 EMS.
def shipping_for_category(category_id: int) -> tuple[int, int, str]:
    cid = int(category_id)
    if cid in (3060, 3062, 4106):  # 코트·다운/패딩·무톤퍼 = >2kg
        return 650, 28000, "EMS"
    if 3080 <= cid <= 3088:  # 신발
        return 608, 13000, "K패킷"
    if cid in (3061, 3063, 3064, 3066, 3067, 3257, 4104, 4105, 4107):  # 자켓류
        return 608, 15000, "K패킷"
    if cid in (3004, 3005, 3006):  # 니트·후디·스웨트
        return 608, 11000, "K패킷"
    return 608, 9000, "K패킷"  # 티셔츠·기본


# 환율9 × (1 − 성약수수료 0.077)
_YEN_RATE = 8.307


def price_to_yen(
    sourcing_krw: int, ship_krw: int, settle_krw: int = 2000, margin_krw: int = 8000
) -> int:
    yen = (sourcing_krw + ship_krw + settle_krw + margin_krw) / _YEN_RATE
    return int(math.ceil(yen / 100) * 100)  # 100엔 올림
