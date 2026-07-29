"""POIZON 주문 마켓상태 동기화 — 상태 전이 규칙 회귀 테스트.

배경:
  포이즌은 order_status 코드가 진실의 원천이지만, 삼바도 송장 전송 시
  shipping_status='송장전송완료' 를 직접 박는다. 마켓 라벨을 무조건 덮어쓰면
  포이즌이 아직 2000(발송대기)을 주는 구간에 송장 전송 사실이 사라지고,
  status 는 shipping 인데 라벨은 발송대기인 모순 상태가 된다.

  또 서열 맵에 없는 현재 상태(반품/교환/취소요청)를 최하위로 취급하면
  어떤 새 값이든 "전진"으로 판정돼 클레임 진행 주문을 덮어쓴다.

여기서는 라우터를 import 하지 않고(무거운 의존성 회피) 서열 상수만 AST 로
떼어와 전이 규칙을 그대로 재현해 검증한다.
"""

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _load_constants(names: set[str]) -> dict:
    """모듈 최상위 상수 할당만 AST 로 떼어 exec."""
    tree = ast.parse(ORDER_PY.read_text(encoding="utf-8"))
    body = [
        n
        for n in tree.body
        if isinstance(n, (ast.Assign, ast.AnnAssign))
        and {
            t.id
            for t in ([n.target] if isinstance(n, ast.AnnAssign) else n.targets)
            if isinstance(t, ast.Name)
        }
        & names
    ]
    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = {}
    exec(compile(mod, "<isolated>", "exec"), ns)
    missing = names - set(ns)
    assert not missing, f"상수 누락: {missing}"
    return ns


NS = _load_constants(
    {"POISON_ORDER_STATUS_MAP", "POISON_STATUS_RANK", "POISON_LABEL_RANK"}
)
STATUS_MAP: dict = NS["POISON_ORDER_STATUS_MAP"]
STATUS_RANK: dict = NS["POISON_STATUS_RANK"]
LABEL_RANK: dict = NS["POISON_LABEL_RANK"]


def _next_status(cur: str, new: str) -> str:
    """라우터 poison 분기의 status 전이 규칙 재현 — 결과 status 반환."""
    if not new or new == cur or cur == "cancelled":
        return cur
    if new == "cancelled":
        return new
    if cur in STATUS_RANK and STATUS_RANK.get(new, -1) > STATUS_RANK[cur]:
        return new
    return cur


def _next_label(cur: str, new: str) -> str:
    """라우터 poison 분기의 shipping_status 전이 규칙 재현."""
    if not new or new == cur:
        return cur
    if new == "거래실패":
        return new
    if cur in LABEL_RANK and LABEL_RANK.get(new, -1) > LABEL_RANK[cur]:
        return new
    return cur


class TestStatusMap:
    """코드 → (status, 라벨) 단일 맵."""

    def test_single_map_covers_all_codes(self) -> None:
        assert STATUS_MAP[2000] == ("preparing", "발송대기")
        assert STATUS_MAP[2100] == ("shipping", "발송완료")
        assert STATUS_MAP[4000] == ("delivered", "구매확정")
        assert STATUS_MAP[8080] == ("cancelled", "거래실패")

    def test_no_split_maps_left(self) -> None:
        """status용·label용 두 벌로 되돌아가면 코드 추가 때 조용히 어긋난다."""
        src = ORDER_PY.read_text(encoding="utf-8")
        assert "poison_ship_label_map" not in src
        assert "poison_status_map" not in src

    def test_every_status_is_ranked_or_terminal(self) -> None:
        for _code, (st, _label) in STATUS_MAP.items():
            assert st in STATUS_RANK or st == "cancelled", (
                f"서열 없는 status={st} — 전이 판정이 미지 상태로 샌다"
            )

    def test_every_label_is_ranked_or_terminal(self) -> None:
        for _code, (_st, label) in STATUS_MAP.items():
            assert label in LABEL_RANK or label == "거래실패", (
                f"서열 없는 라벨={label} — 전이 판정이 미지 라벨로 샌다"
            )


class TestLabelTransition:
    """마켓 라벨 전진 전이 — 송장전송완료 역행 차단이 핵심."""

    def test_invoice_sent_not_overwritten_by_pending(self) -> None:
        """삼바 송장전송완료 → 포이즌 발송대기 역행 금지 (핵심 회귀).

        포이즌이 2100으로 넘어가기 전 사이클에 덮이면 송장 전송 사실이 사라진다.
        """
        assert _next_label("송장전송완료", "발송대기") == "송장전송완료"

    def test_invoice_sent_advances_to_shipped(self) -> None:
        assert _next_label("송장전송완료", "발송완료") == "발송완료"

    def test_forward_transitions(self) -> None:
        assert _next_label("발송대기", "발송완료") == "발송완료"
        assert _next_label("발송완료", "배송중") == "배송중"
        assert _next_label("배송중", "배송완료") == "배송완료"
        assert _next_label("배송완료", "구매확정") == "구매확정"

    def test_backward_transitions_blocked(self) -> None:
        assert _next_label("배송완료", "배송중") == "배송완료"
        assert _next_label("구매확정", "발송완료") == "구매확정"

    def test_empty_label_filled(self) -> None:
        """최초 수집분(빈 라벨)은 채운다 — 고착 방지가 이 PR의 목적."""
        assert _next_label("", "발송대기") == "발송대기"

    def test_claim_label_protected(self) -> None:
        """서열 밖 라벨(취소요청/반품요청)은 포이즌 라벨로 덮지 않는다."""
        assert _next_label("취소요청", "발송완료") == "취소요청"
        assert _next_label("반품요청", "배송완료") == "반품요청"

    def test_trade_fail_always_applied(self) -> None:
        """거래실패는 마켓 종결 신호 — 서열과 무관하게 반영."""
        assert _next_label("배송완료", "거래실패") == "거래실패"
        assert _next_label("취소요청", "거래실패") == "거래실패"


class TestStatusTransition:
    """내부 status 전진 전이 + 미지 상태 보호."""

    def test_forward(self) -> None:
        assert _next_status("preparing", "shipping") == "shipping"
        assert _next_status("shipping", "delivered") == "delivered"

    def test_backward_blocked(self) -> None:
        assert _next_status("shipping", "preparing") == "shipping"
        assert _next_status("delivered", "pending") == "delivered"

    def test_confirmed_not_downgraded(self) -> None:
        """구매확정(confirmed)은 delivered 보다 위 — 역행 금지.

        서열에 confirmed 가 없으면 미지 상태(-1) 취급되어 어떤 값이든 이긴다.
        """
        assert _next_status("confirmed", "delivered") == "confirmed"

    def test_unknown_current_status_protected(self) -> None:
        """반품/취소요청 등 클레임 진행 주문을 포이즌 상태로 덮지 않는다."""
        assert _next_status("cancel_requested", "preparing") == "cancel_requested"
        assert _next_status("return_requested", "shipping") == "return_requested"

    def test_cancelled_is_terminal(self) -> None:
        assert _next_status("cancelled", "shipping") == "cancelled"

    def test_trade_fail_applied_from_any_stage(self) -> None:
        assert _next_status("shipping", "cancelled") == "cancelled"
        assert _next_status("delivered", "cancelled") == "cancelled"


class TestRouterContract:
    """라우터 분기가 위 규칙을 실제로 쓰는지 정적 확인."""

    def setup_method(self) -> None:
        self.src = ORDER_PY.read_text(encoding="utf-8")
        idx = self.src.find('if order_data.get("source") == "poison":')
        assert idx != -1, "poison 갱신 분기를 못 찾음"
        self.block = self.src[idx : idx + 2200]

    def test_uses_shared_rank_constants(self) -> None:
        assert "POISON_STATUS_RANK" in self.block
        assert "POISON_LABEL_RANK" in self.block

    def test_label_not_overwritten_unconditionally(self) -> None:
        """무조건 덮어쓰기로 되돌아가면 송장전송완료가 발송대기로 역행한다."""
        assert "_pz_cur_label in POISON_LABEL_RANK" in self.block

    def test_zombie_cancel_recovery_not_skipped(self) -> None:
        """좀비 '취소요청' 해제(cancel_requested_at 정리)를 포이즌도 타야 한다."""
        assert 'existing.shipping_status == "취소요청"' in self.block
