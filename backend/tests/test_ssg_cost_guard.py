"""SSG 원가 오염 방어 회귀 테스트 (#625 보완).

2026-07-11 실사고: 데몬/확장앱 DOM 스크랩이 가격 앞뒤 숫자(할인율 "7%", 행사 문구)를
이어붙여 원가가 "7"+실원가+"370714" 형태의 조 단위로 오염 → 닥스 등 2,723건이
롯데홈/롯데ON/플레이오토에 조 단위 가격으로 전송됨.

- daemon_detail_fallback: 신규 수집 경로 방어 (RefreshResult 캡 미적용 구간)
- RefreshResult.__post_init__: 옵션 원가 캡 (필드 캡 우회 경로)
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.collector.refresher import RefreshResult
from backend.domain.samba.proxy.ssg_sourcing import daemon_detail_fallback
from backend.domain.samba.shipment.service import exceeds_price_cap

# 실사고 오염값: "7"(카드 7%) + 280,221(실제 카드혜택가) + "370714"(행사 문구 숫자)
CORRUPT_CARD = 7_280_221_370_714
REAL_SALE = 301_312
REAL_CARD = 280_221


def test_daemon_fallback_discards_corrupt_dom_card_price() -> None:
    detail = daemon_detail_fallback(
        {
            "name": "매장정품 닥스 DBWA2F718W3",
            "domSalePrice": REAL_SALE,
            "domCardPrice": CORRUPT_CARD,
        }
    )
    # 오염 카드가는 폐기하고 판매가로 폴백
    assert detail["salePrice"] == REAL_SALE
    assert detail["bestBenefitPrice"] == REAL_SALE
    assert detail["bestAmt"] == REAL_SALE


def test_daemon_fallback_keeps_normal_card_price() -> None:
    detail = daemon_detail_fallback(
        {
            "name": "매장정품 닥스 DBWA2F718W3",
            "domSalePrice": REAL_SALE,
            "domCardPrice": REAL_CARD,
        }
    )
    assert detail["salePrice"] == REAL_SALE
    assert detail["bestBenefitPrice"] == REAL_CARD


def test_daemon_fallback_discards_corrupt_sale_price() -> None:
    # domSalePrice 자체가 오염된 경우 → sale_price 필드로 폴백
    detail = daemon_detail_fallback(
        {
            "name": "매장정품 닥스",
            "domSalePrice": 10_677_658_010_400,
            "sale_price": REAL_SALE,
            "domCardPrice": REAL_CARD,
        }
    )
    assert detail["salePrice"] == REAL_SALE
    assert detail["bestBenefitPrice"] == REAL_CARD


def test_daemon_fallback_benefit_over_3x_sale_discarded() -> None:
    # 1천만 미만이라도 판매가 3배 초과 혜택가는 오염으로 폐기 (#625 캡과 동일 기준)
    detail = daemon_detail_fallback(
        {
            "name": "테스트",
            "domSalePrice": 80_000,
            "domCardPrice": 500_000,
        }
    )
    assert detail["bestBenefitPrice"] == 80_000


def test_refresh_result_caps_corrupt_field_costs() -> None:
    # 기존 #625 필드 캡 동작 확인
    r = RefreshResult(
        product_id="cp_test",
        new_sale_price=float(REAL_SALE),
        new_cost=float(CORRUPT_CARD),
        new_benefit_cost=float(CORRUPT_CARD),
    )
    assert r.new_cost == float(REAL_SALE)
    assert r.new_benefit_cost == float(REAL_SALE)


def test_refresh_result_caps_corrupt_option_costs() -> None:
    # 오염 혜택가 ÷ 판매가 비율이 옵션 cost에 곱해진 경우 — 옵션 price로 캡
    ratio = CORRUPT_CARD / REAL_SALE
    r = RefreshResult(
        product_id="cp_test",
        new_sale_price=float(REAL_SALE),
        new_cost=float(CORRUPT_CARD),
        new_options=[
            {"name": "FREE", "price": REAL_SALE, "cost": round(REAL_SALE * ratio)},
            {"name": "정상", "price": 100_000, "cost": 93_000},
        ],
    )
    assert r.new_options[0]["cost"] == REAL_SALE
    # 정상 옵션 원가는 보존
    assert r.new_options[1]["cost"] == 93_000


def test_refresh_result_option_cost_capped_without_option_price() -> None:
    # 옵션에 price가 없으면 상품 판매가로 캡
    r = RefreshResult(
        product_id="cp_test",
        new_sale_price=float(REAL_SALE),
        new_options=[{"name": "FREE", "cost": CORRUPT_CARD}],
    )
    assert r.new_options[0]["cost"] == float(REAL_SALE)


def test_exceeds_price_cap_blocks_incident_values() -> None:
    # 실사고 값(원가 7.28조, 전송가 10.7조)은 반드시 차단
    assert exceeds_price_cap(CORRUPT_CARD)
    assert exceeds_price_cap(10_677_658_010_400)
    assert exceeds_price_cap(REAL_SALE, CORRUPT_CARD)  # 하나라도 초과면 차단
    assert exceeds_price_cap(100_000_000)  # 경계값(1억)도 차단


def test_exceeds_price_cap_allows_normal_values() -> None:
    assert not exceeds_price_cap(REAL_SALE, REAL_CARD)
    assert not exceeds_price_cap(99_999_999)  # 상한 미만 허용
    assert not exceeds_price_cap(0, None)  # 빈 값은 판단 제외
    assert not exceeds_price_cap("잘못된값")  # 숫자 아님 → 판단 제외


def test_refresh_result_normal_reverse_margin_preserved() -> None:
    # 정상 역마진(원가 > 판매가, 3배 이내)은 캡하지 않음
    r = RefreshResult(
        product_id="cp_test",
        new_sale_price=100_000.0,
        new_cost=150_000.0,
        new_options=[{"name": "FREE", "price": 100_000, "cost": 150_000}],
    )
    assert r.new_cost == 150_000.0
    assert r.new_options[0]["cost"] == 150_000
