"""롯데홈 인증키 재발급 폭주 회귀 테스트 (2026-07-30 실사고).

배경:
  롯데홈 호출이 [0001] "인증키 오류(데이터 존재하지 않음)" 을 반복하며 연동이
  멈췄다. 이 메시지는 "그 인증키가 존재하지 않는다"(= 무효 키) 를 뜻한다 —
  실호출 검증에서 createCertification 자체가 [9001] 로 거부되는 상태였고,
  그래서 재발급을 해도 무효 키가 그대로 남아 다시 0001 이 났다.

  한때 "재발급 직후 또 0001 → 인증 무관" 으로 오판해 이 조합을 인증 분류에서
  제외했는데, 그러면 키가 무효가 된 뒤 스스로 회복하지 못해 연동이 전면 정지한다.
  따라서 0001 + 인증 키워드는 재인증 대상으로 유지한다.

fix:
  1) 0001 + 인증 키워드는 인증 실패로 분류해 재인증한다(회복 경로 유지).
  2) 강제 재인증에 쿨다운을 걸어 폭주를 막는다. 발급 "시도" 시각을 기록해야
     한다 — 성공 시각만 남기면 발급이 계속 9001 로 거부되는 계정 문제 상황에서
     쿨다운이 영원히 비어 매 오류마다 발급을 재시도한다.

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
    return code in ("5001", "9001") or (
        code == "0001" and any(k in lotte_msg for k in ("인증", "토큰", "키"))
    )


class TestAuthClassification:
    """무효 인증키 감지 — 회복 경로가 끊기면 연동이 전면 정지한다."""

    def test_invalid_key_message_is_auth(self) -> None:
        """'인증키 오류(데이터 존재하지 않음)' 은 무효 키 = 재인증 대상 (핵심 회귀).

        데이터 미존재로 오판해 제외하면, 키가 무효가 된 뒤 스스로 회복하지
        못해 롯데홈 주문 동기화가 통째로 멈춘다 (2026-07-30 실사고).
        """
        assert _is_auth("0001", "인증키 오류(데이터 존재하지 않음)")
        assert _is_auth("0001", "인증키오류(데이터 존재하지 않음)")

    def test_real_auth_codes_still_detected(self) -> None:
        assert _is_auth("9001", "인증에 실패하였습니다.")
        assert _is_auth("5001", "")

    def test_other_auth_messages_detected(self) -> None:
        assert _is_auth("0001", "인증키가 만료되었습니다")
        assert _is_auth("0001", "토큰이 유효하지 않습니다")

    def test_data_absent_without_auth_keyword_not_auth(self) -> None:
        """인증 키워드가 없는 0001(마스터 데이터 미존재)은 재인증 대상 아님."""
        assert not _is_auth("0001", "데이터 존재하지 않음")
        assert not _is_auth("0001", "브랜드번호가 없습니다")

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

    def test_classifier_does_not_exclude_invalid_key_message(self) -> None:
        """무효 키 메시지를 인증 분류에서 빼면 회복 경로가 끊긴다."""
        assert "not _data_absent" not in SRC

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

    def test_attempt_time_recorded_before_reauth(self) -> None:
        """발급 '시도' 시각도 남겨야 한다.

        createCertification 이 계속 [9001] 로 거부되는 계정 문제 상황에선
        성공 시각만 기록하면 쿨다운이 영원히 비어 매 오류마다 발급을 재시도한다.
        """
        idx = SRC.find("if is_auth:")
        block = SRC[idx : idx + 1500]
        assert "_last_auth_issue[_ck] = _now" in block, (
            "발급 시도 시각 기록이 없으면 발급 실패 시 폭주를 못 막는다"
        )
