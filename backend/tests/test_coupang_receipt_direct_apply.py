"""#641 회귀테스트 — 쿠팡 클레임 종결 미반영·오분류 3건.

배경 (#641, #599 후속):
  ① 취소·반품 종결 주문은 ordersheet 단건조회(orderId·shipmentBoxId 모두)가
     HTTP 400(The order has been cancelled or returned) 반환 → orphan 되살리기가
     종결 주문에서 구조적으로 실패, receipt 신호가 매 sync 유실.
     → receipt 의 shipmentBoxId(=쿠팡 order_number)로 기존 주문 직접 UPDATE 폴백.
       종결(COMPLETED) receipt 뿐인 orphan 은 ordersheet 호출 자체를 생략.
  ② 반품요청→반품완료 전진 전이 부재 → d5c5ec31 에서 수정 (본 파일 계약 가드).
  ③ 쿠팡은 환불 먼저 종결(RETURNS_COMPLETED), releaseStatus 는 야간 정산(00:45)
     일괄 갱신 — N + RETURNS_COMPLETED 과도기는 미출고 취소. 반품완료로 확정하면
     종결 배지 보호 가드에 걸려 취소완료 정정이 영구 차단됨.

테스트 방식:
  order.py 는 모듈 최상단 순환참조로 cold import 불가(기존 쿠팡 테스트와 동일 제약).
  _classify_coupang_claim 은 순수 함수라 ast 로 소스 추출·exec 하여 기능 검증하고,
  직접반영 폴백은 소스 정적 계약으로 회귀 PR 머지를 차단한다.
"""

import ast
from pathlib import Path
from typing import Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ORDER_PY = BACKEND_ROOT / "backend/api/v1/routers/samba/order.py"


def _src() -> str:
    return ORDER_PY.read_text(encoding="utf-8")


def _load_classify():
    """_classify_coupang_claim 함수를 ast 로 추출해 격리 실행 후 반환."""
    tree = ast.parse(_src())
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "_classify_coupang_claim"
    )
    mod = ast.Module(body=[fn], type_ignores=[])
    ns: dict = {"Optional": Optional}
    exec(compile(mod, str(ORDER_PY), "exec"), ns)  # noqa: S102
    return ns["_classify_coupang_claim"]


def _receipt(
    receipt_type: str,
    receipt_status: str = "",
    release_status: str = "",
    release_stop: str = "",
) -> dict:
    return {
        "receiptType": receipt_type,
        "receiptStatus": receipt_status,
        "releaseStopStatus": release_stop,
        "returnItems": [{"releaseStatus": release_status}] if release_status else [],
    }


class TestClassifyCoupangClaim:
    """③ — 판정 매트릭스 (releaseStatus 권위 신호 + 야간정산 과도기)."""

    def setup_method(self) -> None:
        self.classify = _load_classify()

    def test_none_receipt(self) -> None:
        assert self.classify(None) is None
        assert self.classify({}) is None

    def test_cancel_requested(self) -> None:
        assert self.classify(_receipt("CANCEL")) == ("취소요청", "cancel_requested")

    def test_cancel_completed(self) -> None:
        assert self.classify(_receipt("CANCEL", "RETURNS_COMPLETED")) == (
            "취소완료",
            "cancelled",
        )

    def test_return_shipped_completed_is_returned(self) -> None:
        """출고 이력(Y) 있는 종결만 반품완료."""
        assert self.classify(_receipt("RETURN", "RETURNS_COMPLETED", "Y")) == (
            "반품완료",
            "returned",
        )

    def test_return_unshipped_transitional_is_cancelled(self) -> None:
        """[#641 ③ 핵심] N + RETURNS_COMPLETED + 출고중지 '미처리' 과도기 =
        정산 전 미출고 취소 — 반품완료로 확정하면 취소완료 정정 영구 차단."""
        assert self.classify(
            _receipt("RETURN", "RETURNS_COMPLETED", "N", "미처리")
        ) == ("취소완료", "cancelled")

    def test_return_release_stopped_completed_is_cancelled(self) -> None:
        """야간정산 후 S / '처리(출고중지)' 도 동일하게 취소완료."""
        assert self.classify(
            _receipt("RETURN", "RETURNS_COMPLETED", "S", "처리(출고중지)")
        ) == ("취소완료", "cancelled")

    def test_return_stop_marker_without_release_status(self) -> None:
        """releaseStatus 비어도 releaseStopStatus '출고중지' 표기면 취소."""
        assert self.classify(_receipt("RETURN", "", "", "출고중지요청")) == (
            "취소요청",
            "cancel_requested",
        )

    def test_return_in_progress_shipped(self) -> None:
        assert self.classify(_receipt("RETURN", "RELEASE_STOP_UNCHECKED", "Y")) == (
            "반품요청",
            "return_requested",
        )


class TestParseUsesSharedClassifier:
    """_parse_coupang_order 가 공용 헬퍼를 사용 (판정 로직 이원화 방지)."""

    def test_parse_calls_helper(self) -> None:
        src = _src()
        assert "_claim = _classify_coupang_claim(cancel_info)" in src, (
            "_parse_coupang_order 가 공용 판정 헬퍼를 안 씀 — 로직 이원화 회귀"
        )


class TestOrphanDirectApplyFallback:
    """① — 종결 orphan receipt 직접반영 폴백 계약."""

    def setup_method(self) -> None:
        self.src = _src()

    def test_direct_apply_helper_exists(self) -> None:
        assert "async def _apply_receipt_direct" in self.src, (
            "종결 receipt 직접반영 폴백 누락 — 400 으로 클레임 신호 매 sync 유실 회귀"
        )

    def test_completed_only_orphan_skips_ordersheet_call(self) -> None:
        """종결 receipt 뿐인 orphan 은 ordersheet 호출 생략 (400 노이즈 제거)."""
        assert "_all_completed" in self.src

    def test_400_falls_back_instead_of_skip(self) -> None:
        """400 예외는 continue 가 아니라 직접반영 폴백으로 진행."""
        assert '"cancelled or returned" in _re_s' in self.src

    def test_direct_apply_has_transition_guards(self) -> None:
        """직접반영도 중앙 전이 체인과 동일 원칙의 가드 유지."""
        idx = self.src.find("async def _apply_receipt_direct")
        block = self.src[idx : idx + 4000]
        assert "취소처리중" in block, "취소 상태 보호 가드 누락"
        assert "송장전송완료" in block, "배송 진행 상태 보호 가드 누락"


class TestReturnForwardTransition:
    """② — 반품요청→반품완료 전진 전이 (d5c5ec31) 계약 가드."""

    def test_forward_branch_present(self) -> None:
        src = _src()
        assert "[#641] 반품 진행 → 반품 종결 전진 전이" in src, (
            "반품 전진 전이 분기 제거 회귀 — 반품요청 영구 고착 재발"
        )
