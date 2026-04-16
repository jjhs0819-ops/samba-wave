from backend.domain.samba.proxy.musinsa import MusinsaClient


def test_calculate_display_benefit_price_matches_v2k_screen_price():
    grade_discount, point_usage, display_price = (
        MusinsaClient._calculate_display_benefit_price(
            benefit_base=134100,
            grade_discount_rate=4.0,
            is_point_restricted=False,
            point_rate_pct=7.0,
        )
    )

    assert grade_discount == 5360
    assert point_usage == 9010
    assert display_price == 119730


def test_display_benefit_price_excludes_pre_point_accrual_values():
    _, _, display_price = MusinsaClient._calculate_display_benefit_price(
        benefit_base=134100,
        grade_discount_rate=4.0,
        is_point_restricted=False,
        point_rate_pct=7.0,
    )

    pre_point_accrual = 4780 + 4780

    assert display_price == 119730
    assert display_price - pre_point_accrual == 110170
    assert display_price != display_price - pre_point_accrual
