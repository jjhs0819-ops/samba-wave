"""저재고 캡 → 신규등록 보류 판정 테스트.

2026-08-14 에잇세컨즈 실사고: 저재고 오버셀 방지 캡(#703, 재고 2개 이하 → 전송 0)이
적용된 뒤 전 옵션이 0이 되는데도 신규등록이 그대로 나가, 쿠팡에 '품절 상품'이 등록됐다.
신규등록 가드는 캡 '이전' 값을 보므로 통과해버린다 — 캡 직후 재판정이 필요하다.
"""

from backend.domain.samba.shipment.service import (
    _LOW_STOCK_SEND_CAP_TH,
    available_stock,
)


def _apply_cap(options):
    """service._dispatch_one 의 캡 로직과 동일 규칙."""
    out = []
    for o in options:
        c = dict(o)
        if int(c.get("stock") or 0) <= _LOW_STOCK_SEND_CAP_TH:
            c["stock"] = 0
        out.append(c)
    return out


def _should_hold(options, is_update):
    capped = _apply_cap(options)
    return (
        not is_update and available_stock(capped) <= 0 and available_stock(options) > 0
    )


def test_low_stock_only_new_registration_is_held():
    # 재고 1~2개뿐 — 캡 적용하면 전량 0 → 신규등록 보류
    opts = [
        {"name": "S", "stock": 0, "isSoldOut": True},
        {"name": "M", "stock": 1, "isSoldOut": False},
        {"name": "L", "stock": 2, "isSoldOut": False},
    ]
    assert available_stock(opts) == 3  # 원본엔 재고 있음
    assert available_stock(_apply_cap(opts)) == 0  # 전송값은 전량 0
    assert _should_hold(opts, is_update=False) is True


def test_update_is_not_held():
    # 갱신은 통과 — 기존 등록의 품절 전파는 오버셀 방지에 필수
    opts = [{"name": "M", "stock": 1, "isSoldOut": False}]
    assert _should_hold(opts, is_update=True) is False


def test_sufficient_stock_not_held():
    opts = [
        {"name": "M", "stock": 1, "isSoldOut": False},
        {"name": "L", "stock": 3, "isSoldOut": False},
    ]
    assert available_stock(_apply_cap(opts)) == 3
    assert _should_hold(opts, is_update=False) is False


def test_all_soldout_not_this_guard():
    # 원본부터 재고 0 — 이건 기존 전량품절 가드(#732)가 처리, 중복 보류 아님
    opts = [{"name": "M", "stock": 0, "isSoldOut": True}]
    assert _should_hold(opts, is_update=False) is False


def test_threshold_boundary():
    assert _apply_cap([{"stock": _LOW_STOCK_SEND_CAP_TH}])[0]["stock"] == 0
    assert (
        _apply_cap([{"stock": _LOW_STOCK_SEND_CAP_TH + 1}])[0]["stock"]
        == _LOW_STOCK_SEND_CAP_TH + 1
    )
