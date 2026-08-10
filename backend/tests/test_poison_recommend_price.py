"""POIZON 추천가 응답 파싱 테스트 (2026-08-10).

문서(참고가 반환 필드 표3)상 minPrice/averagePrice/maxPrice 는 '최근 30일 거래가'라
거래 이력이 없는 SKU 에서는 응답에 아예 없다. 라이브 확인 결과 대다수 상품이 이 경우라,
폴백 없이 payload.get("minPrice") 만 읽으면 시세가 항상 None 이 되어 가격 정책이
조용히 실패한다. 폴백은 시장 최저 호가(global/asia/local)와 백분위 구간을 쓴다.
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import PoisonClient

parse = PoisonClient.parse_recommend_payload

# 라이브 실측 응답 (아디다스 삼바 B75806, biddingType=20, KRW)
LIVE_NO_TRADE = {
    "leakInfos": [{"leakPrice": 72000, "buyerRegion": "CN"}],
    "priceRangeItems": [
        {"percentValue": 10, "price": 65000},
        {"percentValue": 30, "price": 81000},
        {"percentValue": 50, "price": 92000},
        {"percentValue": 70, "price": 92000},
        {"percentValue": 90, "price": 144000},
    ],
    "asiaMinPrice": 72000,
    "effectiveExposurePrice": 64000,
    "globalMinPrice": 72000,
}


def test_30일_거래가_없으면_시장최저호가로_채운다():
    r = parse(LIVE_NO_TRADE)
    assert r["minPrice"] == 72000  # globalMinPrice
    assert r["averagePrice"] == 92000  # 백분위 중간값(50%)
    assert r["maxPrice"] == 144000  # 백분위 상위(90%)


def test_원본_스펙_필드를_그대로_노출한다():
    r = parse(LIVE_NO_TRADE)
    assert r["globalMinPrice"] == 72000
    assert r["asiaMinPrice"] == 72000
    assert r["effectiveExposurePrice"] == 64000
    assert r["priceRanges"] == {10: 65000, 30: 81000, 50: 92000, 70: 92000, 90: 144000}


def test_30일_거래가가_오면_평균최고는_그것을_쓴다():
    # 문서 응답 예시 형태 (거래 이력이 있는 SKU)
    payload = {
        "minPrice": 13200,
        "maxPrice": 13200,
        "averagePrice": 13200,
        "globalMinPrice": 71000,
        "localMinPrice": 76000,
        "asiaMinPrice": 71000,
        "priceRangeItems": [
            {"price": 13300, "percentValue": 10},
            {"price": 28600, "percentValue": 90},
        ],
    }
    r = parse(payload)
    # 경쟁 입찰 기준가는 실거래가가 아니라 '이겨야 할 호가' → globalMinPrice 우선
    assert r["minPrice"] == 71000
    assert r["averagePrice"] == 13200
    assert r["maxPrice"] == 13200


def test_백분위만_있으면_백분위로_채운다():
    payload = {"priceRangeItems": [{"percentValue": 10, "price": 238000}]}
    r = parse(payload)
    assert r["minPrice"] == 238000
    assert r["averagePrice"] == 238000
    assert r["maxPrice"] == 238000


def test_빈_응답이면_전부_None():
    r = parse({"priceRangeItems": []})
    assert r["minPrice"] is None
    assert r["averagePrice"] is None
    assert r["maxPrice"] is None
    assert r["priceRanges"] == {}


def test_local만_있으면_local로_폴백():
    r = parse({"localMinPrice": 99000})
    assert r["minPrice"] == 99000
