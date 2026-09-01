"""POIZON 주문 shipment_id 폴백 중복매칭 제외 — 회귀 테스트.

배경 (2026-08-31 DM0950-108 사고):
  포이즌은 서버가 같은 seller_bidding_no(=shipment_id)를 재발급 없이 재체결시키는
  "부활" 이 있어, 같은 상품이 여러 번 팔려도 shipment_id+product_id 가 그대로
  같다. order_number 로 기존 주문을 못 찾으면 (shipment_id, product_id,
  product_option) 이 같은 기존 주문에 붙여버리는 폴백이 있는데, 여기 걸리면
  실제로는 별개인 주문 2건이 먼저 생긴 주문 1건으로 합쳐져 사라진다
  (주문 21315194655623299/21315195889963299 이 21315195034863299 로 합쳐짐 —
  삼바에 1건만 노출).

  롯데ON·이베이는 같은 이유로 이미 제외돼 있었다(2026-05-19, 2026-07-14).
  POIZON 도 같은 실패 모드라 제외 목록에 추가한다.

무거운 라우터 의존성을 피하기 위해(다른 poison 테스트와 동일 원칙) 소스를 직접
읽어 제외 튜플만 검사한다.
"""

import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _dedup_fallback_excluded_sources() -> set[str]:
    """shipment_id+product_id 폴백 매칭에서 제외된 source 집합을 소스에서 추출."""
    src = ORDER_PY.read_text(encoding="utf-8")
    m = re.search(
        r'and order_data\.get\("source"\) not in \(([^)]*)\)',
        src,
    )
    assert m, "shipment_id 폴백의 제외 조건을 찾지 못함 — order.py 구조가 바뀌었을 수 있음"
    return {tok.strip().strip('"') for tok in m.group(1).split(",")}


class TestPoisonExcludedFromShipmentIdFallback:
    def test_poison_is_excluded(self) -> None:
        excluded = _dedup_fallback_excluded_sources()
        assert "poison" in excluded, (
            "POIZON이 shipment_id+product_id 폴백에서 제외돼 있지 않다 — "
            "부활 입찰로 같은 shipment_id가 재사용되면 별개 주문이 하나로 합쳐진다"
        )

    def test_existing_exclusions_untouched(self) -> None:
        # 이번 수정이 기존 롯데ON·이베이 제외를 실수로 지우지 않았는지 확인.
        excluded = _dedup_fallback_excluded_sources()
        assert {"lotteon", "ebay"} <= excluded
