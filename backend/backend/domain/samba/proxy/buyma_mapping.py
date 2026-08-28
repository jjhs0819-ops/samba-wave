"""무신사 수집상품 → BUYMA PS-API 등록 payload 매핑.

BUYMA 마스터데이터(buyma_master/*.csv)를 로드해 브랜드/카테고리/색/사이즈/배송/가격을
매핑한다. 샌드박스에서 상의·아우터·신발 전 카테고리 201 검증 완료된 로직.
"""

from __future__ import annotations

import csv
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

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
    "엘엠씨": 11283,
    "mahagrid": 13137,
    "마하그리드": 13137,
    "matinkim": 14188,
    "마뗑킴": 14188,
    "marithefrancoisgirbaud": 15634,
    "마리떼프랑소와저버": 15634,
    "마리떼": 15634,
    # 누락돼 있던 브랜드 — 없으면 brand_id=0 이 나가고, 그 상태로 올라간
    # 243건이 전부 POLO RALPH LAUREN(5918)으로 붙어버렸다. 바이마는 브랜드
    # 오등록을 삭제·경고 사유로 보므로 매핑 누락 자체가 사고다.
    "uniformbridge": 20051,
    "유니폼브릿지": 20051,
    "sculptor": 6590,
    "스칼프터": 6590,
    "스컬프터": 6590,
    "anderssonbell": 6642,
    "adsbanderssonbell": 6642,
    "안데르손벨": 6642,
    "emis": 16226,
    "이미스": 16226,
}


@lru_cache(maxsize=1)
def _sizes() -> list[dict]:
    with open(_MD / "sizes.csv", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


@lru_cache(maxsize=1)
def _colors() -> dict[str, int]:
    with open(_MD / "colors.csv", encoding="utf-8-sig") as f:
        return {r["name"]: int(r["id"]) for r in csv.DictReader(f)}


class UnknownBrandError(ValueError):
    """매핑에 없는 브랜드 — 0 을 흘려보내지 않고 등록을 멈춘다."""


def brand_id(brand: str, *, strict: bool = True) -> int:
    """무신사 브랜드명/slug → BUYMA brand_id.

    매핑에 없으면 예외를 던진다. 이전에는 0 을 반환했는데, 0 이 그대로 나간
    상품 243건이 엉뚱한 브랜드로 등록됐다(UNIFORM BRIDGE → POLO RALPH LAUREN).
    조용히 0 을 넘기느니 등록을 실패시키는 편이 훨씬 싸다.

    브랜드ID는 바이마 '일괄 출품 편집 → ID표'의 brands.csv 기준이다.
    """
    raw = (brand or "").strip()
    key = raw.lower().replace(" ", "")
    bid = TARGET_BRAND.get(key) or TARGET_BRAND.get(raw, 0)
    if not bid and strict:
        raise UnknownBrandError(
            f"BUYMA 브랜드 매핑 없음: {raw!r} — TARGET_BRAND 에 추가 후 등록할 것"
        )
    return bid


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
    # 하의 (순서 중요: 반바지·데님이 팬츠보다 먼저)
    (("데님", "청바지", "denim", "jean"), 3024),
    (("스커트", "치마"), 3020),
    (("반바지", "숏팬츠", "숏 팬츠", "쇼트팬츠", "하프팬츠", "쇼츠"), 3023),
    (
        (
            "슬랙스",
            "팬츠",
            "바지",
            "조거",
            "카고",
            "와이드",
            "치노",
            "레깅스",
            "pants",
            "trouser",
        ),
        3022,
    ),
]


def map_category(depth1: str = "", depth2: str = "", depth3: str = "") -> int:
    t = (depth1 or "") + (depth2 or "") + (depth3 or "")
    for kws, cid in _CATEGORY_RULES:
        if any(k in t for k in kws):
            return cid
    if "아우터" in t:
        return 3061
    if any(k in t for k in ("바지", "팬츠", "스커트", "치마", "하의")):
        return 3025  # ボトムスその他
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
    # 아래가 없으면 マルチカラー(99)로 떨어져 등록 대상에서 제외된다.
    (("버건디", "burgundy", "와인", "wine"), 11, "レッド"),
    (("라벤더", "lavender"), 8, "パープル"),
    (("민트", "mint"), 6, "グリーン"),
    (("올리브", "olive"), 6, "カーキ"),
    # F/W 후보 249건 중 72건(29%)이 マルチカラー 로 빠지던 표기들.
    # 색이 안 잡히면 바이마 색상 필터에서 누락돼 검색에 안 걸린다.
    # 계통ID는 바이마 ID표(colors.csv) 기준 — 추측으로 넣었다가 오트밀을
    # 블랙(2)으로 보낼 뻔했다. 1=ホワイト 2=ブラック 3=グレー 4=ブラウン
    # 5=ベージュ 6=グリーン 9=イエロー 16=ネイビー
    (("오트밀", "oatmeal"), 5, "オートミール"),
    (("아이보리", "ivory"), 1, "アイボリー"),
    (("차콜", "charcoal"), 3, "チャコール"),
    (("카키", "khaki"), 6, "カーキ"),
    (("머스타드", "mustard"), 9, "マスタード"),
    (("골드", "gold"), 14, "ゴールド"),
]


# 색 계통(master_id)은 BUYMA가 16종으로 고정돼 있어 차콜·아이보리 등은 상위
# 계통으로 흡수되지만, 색명(자유 입력)까지 계통명으로 덮으면 원본 색이 사라진다
# (무신사 '차콜' → 'グレー'로 등록되는 문제). 매칭된 키워드에 세부 색명이 있으면
# 그것을 쓰고, 없을 때만 계통 기본명으로 폴백한다.
_COLOR_NAME_JP = {
    "차콜": "チャコール",
    "charcoal": "チャコール",
    "아이보리": "アイボリー",
    "ivory": "アイボリー",
    "카멜": "キャメル",
    "camel": "キャメル",
    "크림": "クリーム",
    "cream": "クリーム",
    "버건디": "バーガンディ",
    "burgundy": "バーガンディ",
    "와인": "ワイン",
    "wine": "ワイン",
    "민트": "ミント",
    "mint": "ミント",
    "라벤더": "ラベンダー",
    "lavender": "ラベンダー",
    "olive": "オリーブ",
    "올리브": "オリーブ",
    "오트밀": "オートミール",
    "oatmeal": "オートミール",
    "카키": "カーキ",
    "khaki": "カーキ",
    "머스타드": "マスタード",
    "mustard": "マスタード",
}


def map_color(text: str) -> tuple[int, str]:
    s = (text or "").lower()
    for kws, cid, jp in _COLOR_RULES:
        for k in kws:
            if k in s:
                return cid, _COLOR_NAME_JP.get(k, jp)
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
    "115": "XL",
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
    # 조합 라벨(예: "XS_85", "M(95)", "L/100") → 구분자로 쪼개 각 토큰 시도
    if not (3080 <= cid <= 3088):
        tokens = re.split(r"[_()/ ]+", lab)
        if len([t for t in tokens if t]) > 1:
            for part in tokens:
                if part and part != lab:
                    mid = size_master(part, category_id)
                    if mid is not None:
                        return mid
    # 신발(3080~3088): 무신사 mm(230/23.5/24) → master id(=mm)
    if 3080 <= cid <= 3088:
        digits = lab.replace("CM", "").replace(".", "").strip()
        if digits.isdigit():
            mm = digits if len(digits) >= 3 else str(int(digits) * 10)
            for r in cands:
                if str(r["id"]) == mm:
                    return int(r["id"])
        return None
    # 하의 허리치수(인치, 24~38) → 알파벳 (여성복 44~88과 안 겹치는 범위)
    if 3020 <= cid <= 3025 and lab.isdigit() and 24 <= int(lab) <= 38:
        w = int(lab)
        lab = "S" if w <= 26 else "M" if w <= 28 else "L" if w <= 30 else "XL"
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


# ---------------------------------------------------------------------------
# 배송비 — 일본행 K-Packet / EMS
# ---------------------------------------------------------------------------
# 카테고리마다 고정값(9,000/11,000/13,000/15,000원)을 쓰던 것을 실제 요금표로
# 교체한다. 고정값은 실제 요금과 최대 6,610원까지 벌어져 있었고, 방향도 제각각
# 이었다 — 티셔츠는 2,070원 과대(가격이 불필요하게 비쌌고), 신발은 3,610원 과소
# (팔릴 때마다 마진의 45%가 사라졌다).
#
# 요금표와 카테고리 추정중량은 코드가 아니라 buyma_master/ 의 CSV 에 둔다.
# 우체국이 요금을 개정하면 CSV 만 갈아끼우면 되고 배포가 필요 없다. 실제로
# EMS 값이 28,000원으로 낡아 있어 7,500원이 비어 있었다.
#   shipping_jp.csv      우정사업본부 K-Packet/EMS 요금표(일본)
#                        https://www.koreapost.go.kr/kpost/subIndex/236.do?pSiteIdx=125
#   category_weight.csv  카테고리 → 추정 포장중량(g)


@lru_cache(maxsize=1)
def _shipping_jp() -> dict[str, Any]:
    """shipping_jp.csv → {kpacket: {중량: 요금}, max_g, ems_base, ems_per_kg}"""
    kpacket: dict[int, int] = {}
    conf: dict[str, Any] = {"max_g": 2000, "ems_base": 0, "ems_per_kg": 0}
    with open(_MD / "shipping_jp.csv", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            kind, key, val = r["kind"].strip(), r["key"].strip(), int(r["value"])
            if kind == "kpacket":
                kpacket[int(key)] = val
            elif kind == "kpacket_max_g":
                conf["max_g"] = val
            elif kind == "ems_base_2kg":
                conf["ems_base"] = val
            elif kind == "ems_per_kg":
                conf["ems_per_kg"] = val
    if not kpacket:
        raise ValueError("shipping_jp.csv 에 kpacket 구간이 없다")
    return {"kpacket": kpacket, **conf}


@lru_cache(maxsize=1)
def _category_weight() -> dict[str, int]:
    """category_weight.csv → {카테고리ID(str): 중량g}. _shoe/_default 포함."""
    with open(_MD / "category_weight.csv", encoding="utf-8-sig") as f:
        return {r["category_id"].strip(): int(r["weight_g"]) for r in csv.DictReader(f)}


# 신발은 신발상자를 포함해 보낸다 — 상자를 빼면 900g 대이지만 구매자가 상자를
# 기대하므로 포함 기준으로 잡는다. 상자 없이 보내면 3,480원이 남는데, 그 판단은
# 발송 정책이 정해진 뒤에.
_SHOE_CATEGORIES = range(3080, 3089)

# 배송수단 ID — K패킷 608 / EMS 650
_SHIP_ID_KPACKET = 608
_SHIP_ID_EMS = 650


def clean_style_no(style: str) -> str:
    """무신사 styleNo → 바이마가 받는 품번 형태로 정제.

    무신사는 색상을 품번에 괄호로 붙여 내려주는 경우가 있다
    (예: atb1619m(WHITE/WHITE STRIPE)). 바이마는 이걸 거부한다 —
    "ブランド品番は不正な値です". 실제로 176건이 이 형태였다.

    괄호부터 뒤를 잘라내고, 남는 것도 영숫자·하이픈 계열이 아니면 버린다.
    품번은 검색 노출용이라 틀린 값을 넣느니 비우는 게 낫다.
    """
    s = (style or "").strip()
    if not s:
        return ""
    s = re.split(r"[(（\[{]", s, maxsplit=1)[0].strip()
    s = s.rstrip("-_/. ")
    return s if re.fullmatch(r"[A-Za-z0-9\-_./]{2,50}", s) else ""


def weight_for_category(category_id: int) -> int:
    """카테고리 추정 포장중량(g)."""
    w = _category_weight()
    cid = int(category_id)
    if cid in _SHOE_CATEGORIES:
        return w["_shoe"]
    return w.get(str(cid), w["_default"])


def kpacket_fee(weight_g: int) -> int:
    """중량(g) → 일본행 K-Packet 요금(원). 2kg 초과면 EMS 요금을 돌려준다."""
    sh = _shipping_jp()
    if weight_g > sh["max_g"]:
        over_kg = math.ceil((weight_g - sh["max_g"]) / 1000)
        return sh["ems_base"] + sh["ems_per_kg"] * over_kg
    table = sh["kpacket"]
    bracket = min(b for b in table if b >= max(weight_g, 1))
    return table[bracket]


def shipping_for_category(category_id: int) -> tuple[int, int, str]:
    """카테고리 → (배송수단ID, 배송비원, 표시명)."""
    w = weight_for_category(category_id)
    fee = kpacket_fee(w)
    if w > _shipping_jp()["max_g"]:
        return _SHIP_ID_EMS, fee, "EMS"
    return _SHIP_ID_KPACKET, fee, "K패킷"


# 환율9 × (1 − 성약수수료 0.077)
_YEN_RATE = 8.307

# 부가가치세 환급 — 수출은 영세율이라 매입세액(구매가의 1/11)을 돌려받는다.
# 즉 실질 소싱원가는 구매가의 10/11 이다. 법인이라 일반과세자이고(간이과세는
# 개인사업자 전용), 소싱처 세금계산서를 매입증빙으로 갖추면 공제 요건이 선다.
# 환급을 못 받게 되면 이 값만 False 로 돌리면 원래 가격 체계로 복귀한다.
_VAT_DIVISOR = 11


def net_sourcing_krw(sourcing_krw: int, *, vat_refund: bool = True) -> int:
    """부가세 환급을 반영한 실질 소싱원가."""
    if not vat_refund:
        return int(sourcing_krw)
    return int(round(sourcing_krw * (_VAT_DIVISOR - 1) / _VAT_DIVISOR))


def price_to_yen(
    sourcing_krw: int,
    ship_krw: int,
    settle_krw: int = 2000,
    margin_krw: int = 8000,
    *,
    vat_refund: bool = True,
) -> int:
    """소싱가·배송비·정산비·목표마진 → 엔 판매가(100엔 올림).

    vat_refund 는 매입세액 환급분(구매가의 1/11)만큼 원가를 낮춰 그만큼
    가격을 내린다. 평균 ¥1,218 인하 효과이며, 시장가보다 비쌌던 구간의
    경쟁력을 되찾는 데 쓴다.
    """
    src = net_sourcing_krw(sourcing_krw, vat_refund=vat_refund)
    yen = (src + ship_krw + settle_krw + margin_krw) / _YEN_RATE
    return int(math.ceil(yen / 100) * 100)
