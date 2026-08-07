"""쿠팡 출고지 택배사 코드 무언 폴백 제거 회귀 테스트 (2026-08-07 실사고).

증상:
  승인반려 2,811건 — 롯데택배 출고지 계정인데 등록 상품의 택배사가 전량 CJ.

원인:
  출고지 택배사 코드가 계정에 저장돼 있지 않고 출고지 조회로도 못 얻으면
  `CJGLS` 를 조용히 폴백으로 사용 → 실제 택배사(롯데택배=HYUNDAI)와 불일치
  → 쿠팡 검수 반려가 계정 전체로 확산.

수정:
  폴백 제거 — 코드 미확인 시 명시적 실패({"success": False})로 남겨
  계정 설정 보완을 유도한다. 성공한 척 잘못된 택배사로 등록하지 않는다.
"""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_PY = BACKEND_ROOT / "backend/domain/samba/plugins/markets/coupang.py"


class TestCourierNoSilentFallback:
    def setup_method(self) -> None:
        self.src = PLUGIN_PY.read_text(encoding="utf-8")

    def test_no_cjgls_silent_fallback(self) -> None:
        assert '= "CJGLS"  # 최후 폴백' not in self.src, (
            "CJGLS 무언 폴백이 부활함 — 출고지 택배사 불일치 반려 재발 위험"
        )

    def test_explicit_failure_on_missing_code(self) -> None:
        i = self.src.find("if not outbound_delivery_code:")
        assert i >= 0, "출고지 택배사 코드 검증 블록을 찾지 못함"
        block = self.src[i : i + 900]
        assert '"success": False' in block, (
            "코드 미확인 시 명시적 실패 반환이 없음 — 조용한 오등록 경로 존재"
        )
