"""쿠팡 반품sync 의 취소/반품 분류 회귀 테스트 (2026-07 버그).

쿠팡 returnRequests 엔드포인트는 출고중지요청(상품준비중 단계 취소)을 실제 반품과 같은
응답에 담아 내려준다. 이 건은 receiptType='RETURN' 이지만 receiptStatus 가
RELEASE_STOP_*(출고중지요청, 예: RELEASE_STOP_UNCHECKED) 이다 — 실측 확인(손성아/조미혜
2026-07). returns.py 의 _sync_coupang_items 가 이를 무시하고 전부 type='return' 으로
저장하던 버그 → 출고전 취소가 반품으로 둔갑, 주문상태가 반품요청으로 덮여 취소가 반품에 갇힘.

이 테스트는 returns.py 의 분류식·종결 가드식을 그대로 복제해 회귀를 고정한다.
"""

from __future__ import annotations


def _effective_type(
    return_type: str, receipt_type: str = "", receipt_status: str = ""
) -> str:
    """returns.py _sync_coupang_items 의 effective_type 표현식 동일.

    출고중지요청(receiptStatus=RELEASE_STOP_*/RU) 또는 CANCEL 카테고리
    (receiptType=CANCEL)는 취소로 분류.
    """
    rt = (receipt_type or "").upper()
    rs = (receipt_status or "").upper()
    is_cancel_claim = rt == "CANCEL" or rs.startswith("RELEASE_STOP") or rs == "RU"
    return "cancel" if return_type == "return" and is_cancel_claim else return_type


def _status_label(effective_type: str) -> str:
    return {
        "return": "반품요청",
        "exchange": "교환요청",
        "cancel": "취소요청",
    }.get(effective_type, "반품요청")


def _new_order_status(effective_type: str) -> str:
    return {
        "exchange": "exchange_requested",
        "cancel": "cancel_requested",
    }.get(effective_type, "return_requested")


def _should_overwrite_order(cur_status: str) -> bool:
    """종결(취소완료/반품완료/교환완료) 주문은 새 '요청' 상태로 하향 덮어쓰지 않는다."""
    return (cur_status or "").strip().lower() not in (
        "cancelled",
        "returned",
        "exchanged",
    )


def _promote_cancel_if_prior(
    return_type: str, is_cancel_claim: bool, prior_cancel_statuses: list[str]
) -> bool:
    """완료단계 모호성 보정: 취소승인 후 쿠팡이 취소완료를 RETURNS_COMPLETED 로 내려
    반품과 구분 불가할 때, 살아있는(거부 아님) 취소 클레임이 있으면 취소로 귀속.

    returns.py _sync_coupang_items 의 prior-cancel 승격 로직 동일.
    """
    if return_type == "return" and not is_cancel_claim:
        if any((s or "").lower() != "rejected" for s in prior_cancel_statuses):
            return True
    return is_cancel_claim


def _market_status_label(effective_type: str, status: str) -> str:
    """요청/완료/거부 상태를 반영한 반품행 market_order_status. 완료 하향 방지."""
    if status == "completed":
        return {"exchange": "교환완료", "cancel": "취소완료"}.get(
            effective_type, "반품완료"
        )
    if status == "rejected":
        return {"exchange": "교환거부", "cancel": "취소거부"}.get(
            effective_type, "반품거부"
        )
    return {"exchange": "교환요청", "cancel": "취소요청"}.get(
        effective_type, "반품요청"
    )


# ── receiptType 분류 ──────────────────────────────────────────────


def test_release_stop_unchecked_is_classified_cancel():
    """출고중지요청(receiptType=RETURN, receiptStatus=RELEASE_STOP_UNCHECKED)은 취소로 분류.

    실측 데이터: 손성아/조미혜 건이 정확히 이 형태로 내려옴(cancelReasonCategory1='고객변심').
    """
    et = _effective_type("return", "RETURN", "RELEASE_STOP_UNCHECKED")
    assert et == "cancel"
    assert _status_label(et) == "취소요청"
    assert _new_order_status(et) == "cancel_requested"


def test_short_ru_code_is_classified_cancel():
    assert _effective_type("return", "RETURN", "RU") == "cancel"


def test_cancel_category_receipt_type_is_classified_cancel():
    """결제완료 단계 취소(CANCEL 카테고리, receiptType=CANCEL)도 취소로 분류."""
    et = _effective_type("return", "CANCEL", "")
    assert et == "cancel"
    assert _status_label(et) == "취소요청"


def test_real_return_receipt_stays_return():
    """반품접수(RETURNS_UNCHECKED)는 반품 유지."""
    et = _effective_type("return", "RETURN", "RETURNS_UNCHECKED")
    assert et == "return"
    assert _status_label(et) == "반품요청"
    assert _new_order_status(et) == "return_requested"


def test_missing_status_defaults_to_return():
    """receiptType/receiptStatus 누락 시 기존 동작(반품) 유지 — 회귀 안전."""
    assert _effective_type("return", "", "") == "return"
    assert _effective_type("return", None, None) == "return"  # type: ignore[arg-type]


def test_release_stop_lowercase_normalized():
    assert _effective_type("return", "return", "release_stop_unchecked") == "cancel"


def test_exchange_endpoint_never_becomes_cancel():
    """교환 sync 는 receiptStatus 과 무관하게 교환 유지."""
    assert _effective_type("exchange", "RETURN", "RELEASE_STOP_UNCHECKED") == "exchange"
    assert _effective_type("exchange", "CANCEL", "") == "exchange"


# ── 종결 하향 방지 가드 ────────────────────────────────────────────


def test_terminal_orders_are_not_downgraded():
    """이미 취소완료/반품완료/교환완료된 주문은 요청 상태로 되돌리지 않는다(손성아)."""
    assert _should_overwrite_order("cancelled") is False
    assert _should_overwrite_order("returned") is False
    assert _should_overwrite_order("exchanged") is False
    assert _should_overwrite_order("CANCELLED") is False  # 대소문자 무관


def test_non_terminal_orders_are_overwritten():
    """배송완료 주문의 반품요청 등 정상 전이는 계속 허용."""
    assert _should_overwrite_order("delivered") is True
    assert _should_overwrite_order("pending") is True
    assert _should_overwrite_order("") is True
    assert _should_overwrite_order(None) is True  # type: ignore[arg-type]


# ── 완료단계 취소 귀속(RETURNS_COMPLETED 모호성) ──────────────────────


def test_completed_return_with_prior_cancel_is_promoted_to_cancel():
    """취소승인 후 RETURNS_COMPLETED 가 와도, 취소행이 있으면 취소로 귀속(반품행 재생성 방지).

    실측: 손성아/조미혜 취소승인 후 쿠팡이 RETURNS_COMPLETED 로 내려 반품완료 행이 재생성됨.
    """
    # RETURNS_COMPLETED 자체는 취소 신호가 아님(receiptStatus 판별 실패)
    assert _effective_type("return", "RETURN", "RETURNS_COMPLETED") == "return"
    # 하지만 살아있는 취소행이 있으면 취소로 승격
    assert _promote_cancel_if_prior("return", False, ["completed"]) is True
    assert _promote_cancel_if_prior("return", False, ["requested"]) is True


def test_completed_return_without_prior_cancel_stays_return():
    """취소행이 없으면 진짜 반품완료 — 반품 유지."""
    assert _promote_cancel_if_prior("return", False, []) is False


def test_rejected_prior_cancel_does_not_promote():
    """취소가 거부된 주문의 후속 반품은 진짜 반품 — 승격하지 않는다."""
    assert _promote_cancel_if_prior("return", False, ["rejected"]) is False


def test_exchange_never_promoted_by_prior_cancel():
    assert _promote_cancel_if_prior("exchange", False, ["completed"]) is False


# ── 완료/거부 상태 라벨(하향 방지) ──────────────────────────────────


def test_completed_cancel_label_is_not_downgraded_to_requested():
    """취소완료 취소행이 sync 로 취소요청으로 하향되지 않는다."""
    assert _market_status_label("cancel", "completed") == "취소완료"
    assert _market_status_label("return", "completed") == "반품완료"
    assert _market_status_label("exchange", "completed") == "교환완료"


def test_requested_and_rejected_labels():
    assert _market_status_label("cancel", "requested") == "취소요청"
    assert _market_status_label("cancel", "rejected") == "취소거부"
    assert _market_status_label("return", "requested") == "반품요청"
