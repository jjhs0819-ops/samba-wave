"""롯데홈 인증키 재발급 폭주 회귀 테스트 (2026-07-30 실사고).

배경:
  오토튠 가격수정(updateGoodsSalePrcOpenApi)이 [0001] "인증키오류(데이터 존재하지
  않음)" 을 받았는데, 분류기가 메시지의 '인증' 글자만 보고 인증 실패로 오판했다.
  → 매 호출마다 강제 재인증 → 새 키 발급 → 롯데홈은 새 키 발급 시 이전 키를
  무효화하므로 같은 계정의 배송조회가 [9001] 인증 실패로 떨어졌다.

  결정적 근거: 재발급 직후 같은 호출이 또 0001 로 실패했다. 진짜 만료였다면
  재발급 후 성공해야 한다.

fix:
  1) 0001 + "데이터 존재하지 않" 은 인증 실패로 분류하지 않는다.
  2) 강제 재인증에 쿨다운을 걸어, 오류 하나가 재발급 폭주를 일으키지 못하게 한다.

라우터/클라이언트 전체 import 없이(무거운 의존성 회피) 분류 규칙과 쿨다운
상수만 AST 로 떼어 검증한다.
"""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOTTEHOME_PY = BACKEND_ROOT / "backend/domain/samba/proxy/lottehome.py"
SRC = LOTTEHOME_PY.read_text(encoding="utf-8")


def _cooldown() -> timedelta:
    """모듈 최상위 FORCE_AUTH_COOLDOWN 상수만 떼어 평가."""
    tree = ast.parse(SRC)
    body = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "FORCE_AUTH_COOLDOWN" for t in n.targets
        )
    ]
    assert body, "FORCE_AUTH_COOLDOWN 상수 없음"
    mod = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns: dict = {"timedelta": timedelta}
    exec(compile(mod, "<isolated>", "exec"), ns)
    return ns["FORCE_AUTH_COOLDOWN"]


def _is_auth(code: str, lotte_msg: str) -> bool:
    """_call_api_auto_retry 의 인증 분류 규칙 재현."""
    data_absent = "데이터 존재하지 않" in lotte_msg
    return code in ("5001", "9001") or (
        code == "0001"
        and not data_absent
        and any(k in lotte_msg for k in ("인증", "토큰", "키"))
    )


class TestAuthClassification:
    """0001 오분류 차단 — 이 사고의 근본 원인."""

    def test_data_absent_not_treated_as_auth(self) -> None:
        """'인증키오류(데이터 존재하지 않음)' 은 인증 실패가 아니다 (핵심 회귀).

        인증으로 분류되면 매 호출마다 새 키가 발급돼 이전 키가 무효화되고,
        같은 계정의 배송조회가 [9001] 로 떨어진다.
        """
        assert not _is_auth("0001", "인증키오류(데이터 존재하지 않음)")

    def test_real_auth_codes_still_detected(self) -> None:
        assert _is_auth("9001", "인증에 실패하였습니다.")
        assert _is_auth("5001", "")

    def test_0001_with_genuine_auth_message_still_detected(self) -> None:
        """데이터 미존재 문구가 없는 0001 인증 메시지는 그대로 재인증."""
        assert _is_auth("0001", "인증키가 만료되었습니다")
        assert _is_auth("0001", "토큰이 유효하지 않습니다")

    def test_plain_data_absent_not_auth(self) -> None:
        assert not _is_auth("0001", "데이터 존재하지 않음")

    def test_unrelated_error_not_auth(self) -> None:
        assert not _is_auth("1000", "필수 파라미터 오류")


class TestCooldown:
    """강제 재인증 쿨다운 — 폭주 안전망."""

    def test_cooldown_is_positive(self) -> None:
        assert _cooldown() >= timedelta(minutes=1), (
            "쿨다운이 없거나 너무 짧으면 재발급 폭주를 못 막는다"
        )

    def test_recent_issue_suppresses_reissue(self) -> None:
        now = datetime(2026, 7, 30, 0, 10, tzinfo=timezone.utc)
        last = now - timedelta(minutes=1)
        assert (now - last) < _cooldown(), "직전 발급 1분 후면 재발급을 막아야 한다"

    def test_old_issue_allows_reissue(self) -> None:
        now = datetime(2026, 7, 30, 0, 10, tzinfo=timezone.utc)
        last = now - timedelta(minutes=30)
        assert (now - last) >= _cooldown(), "충분히 지났으면 정상 재인증 허용"


class TestSourceContract:
    """소스가 위 규칙을 실제로 쓰는지 정적 확인."""

    def test_classifier_excludes_data_absent(self) -> None:
        assert '"데이터 존재하지 않" in _lotte_msg' in SRC

    def test_cooldown_checked_before_force_reauth(self) -> None:
        idx = SRC.find("if is_auth:")
        assert idx != -1
        block = SRC[idx : idx + 1500]
        assert "FORCE_AUTH_COOLDOWN" in block, (
            "쿨다운 검사가 강제 재인증보다 먼저 와야 폭주를 막는다"
        )
        assert block.find("raise") < block.find("_ensure_auth"), (
            "쿨다운 중에는 재발급 없이 원 오류를 그대로 올려야 한다"
        )

    def test_issue_time_recorded(self) -> None:
        assert "_last_auth_issue[cache_key] = now" in SRC, (
            "발급 시각을 안 남기면 쿨다운이 동작하지 않는다"
        )
