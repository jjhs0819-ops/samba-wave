"""롯데홈쇼핑 QA 폴러 credentials 조회 회귀 테스트.

배경(2026-07-27 운영 사고):
  폴러가 `key == "lottehome_credentials"` (bare 키)로만 설정을 찾았는데,
  멀티테넌트 격리(2026-05-18) 이후 설정은 `{tenant_id}:{key}` 로 저장된다.
  → credentials 를 못 찾고 조용히 `return 0, 0` → 로그조차 없음
  → 롯데홈 등록분의 `{acc_id}_qa` 마커가 영구 pending
  → 오토튠이 pending 상품을 스킵하므로 가격·재고가 전혀 갱신되지 않음.
  실제로 등록 1,564건 전량이 48시간 동안 pending 에 갇혀 역마진 8건이 발생했다.

검증 항목:
  ① bare 키가 있으면 그대로 사용 (기존 동작 유지)
  ② bare 키가 없고 prefixed 키만 있으면 폴백으로 찾는다 (사고 재발 방지)
  ③ 어느 쪽도 없으면 (0, 0) 반환하되 경고 로그를 남긴다 (조용한 실패 금지)
"""

import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

BARE_KEY = "lottehome_credentials"
PREFIXED_KEY = "tn_testtenant:lottehome_credentials"
CREDS = {"userId": "039039LT", "password": "pw", "agncNo": "039039", "env": "prod"}


class _Row:
    def __init__(self, key, value):
        self.key = key
        self.value = value


class _ExecResult:
    """session.exec() 반환값 스텁 — first()/all() 만 사용."""

    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeSession:
    """settings 테이블만 흉내내는 세션.

    where 절을 해석하는 대신, 호출 순서로 판단한다:
      1번째 exec = bare 키 조회, 2번째 exec = prefixed like 조회.
    """

    def __init__(self, bare_row, prefixed_rows):
        self._bare_row = bare_row
        self._prefixed_rows = prefixed_rows
        self.exec_calls = 0

    async def exec(self, _stmt):
        self.exec_calls += 1
        if self.exec_calls == 1:
            return _ExecResult([self._bare_row] if self._bare_row else [])
        return _ExecResult(self._prefixed_rows)

    async def execute(self, *_a, **_kw):  # pending 목록 조회 — 항상 비움
        return _ExecResult([])

    async def commit(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_a):
        return False


def _run_with_session(monkeypatch, session):
    """_run_lottehome_qa_sync 를 가짜 세션으로 실행하고 (checked, updated) 반환."""
    from backend.domain.samba.order import lottehome_qa_poller as mod

    def _fake_get_write_session():
        return session

    monkeypatch.setattr(
        "backend.db.orm.get_write_session", _fake_get_write_session, raising=False
    )
    return asyncio.run(mod._run_lottehome_qa_sync())


def test_bare_key_is_used_when_present(monkeypatch):
    """① bare 키가 있으면 prefixed 조회까지 가지 않는다."""
    session = _FakeSession(_Row(BARE_KEY, CREDS), [])
    _run_with_session(monkeypatch, session)
    assert session.exec_calls == 1, "bare 키가 있는데 불필요한 폴백 조회를 했다"


def test_prefixed_key_fallback(monkeypatch):
    """② bare 키가 없으면 '{tenant}:{key}' 로 폴백해 credentials 를 찾는다.

    폴백이 없던 시절에는 여기서 exec 1회 후 즉시 (0,0) 으로 끝났다.
    """
    session = _FakeSession(None, [_Row(PREFIXED_KEY, CREDS)])
    _run_with_session(monkeypatch, session)
    assert session.exec_calls == 2, "prefixed 폴백 조회가 수행되지 않았다"


def test_missing_credentials_logs_warning(monkeypatch, caplog):
    """③ 설정이 아예 없으면 (0,0) 이되, 조용히 끝내지 말고 경고를 남긴다."""
    session = _FakeSession(None, [])
    with caplog.at_level("WARNING"):
        checked, updated = _run_with_session(monkeypatch, session)
    assert (checked, updated) == (0, 0)
    assert any("lottehome_credentials" in r.message for r in caplog.records), (
        "credentials 부재가 로그에 남지 않아 원인 추적이 불가능하다"
    )
