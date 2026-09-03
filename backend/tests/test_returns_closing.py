"""반품행 마감(종결) 서비스·마감행 보호 테스트 (T7·T8 — 2026-09-03).

- closing.close_returns / reopen_returns: 멱등성 (재마감·재해제 스킵)
- order.py::_sync_returns_with_order_status: 마감행은 갱신·삭제 제외,
  단 '기존 행 있음' 판정에는 포함 (마감건 재생성 방지)
- returns.py::_backfill_returns_from_claim_orders: existing_* 판정이
  마감행을 걸러내지 않는지 정적 검증 (closed_at 필터 금지)

⚠️ DB 없이 동작 — 세션은 전부 대역(Fake), 외부 HTTP 없음.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.returns.closing import (  # noqa: E402
    CLOSED_BY_AUTO,
    CLOSED_BY_MANUAL,
    auto_close_candidates,
    close_returns,
    reopen_returns,
)
from backend.domain.samba.returns.model import SambaReturn  # noqa: E402
from backend.utils import now_kst  # noqa: E402


# ── 세션 대역 ─────────────────────────────────────────────────────────


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    """AsyncSession 대역 — execute 는 미리 준비한 행을 반환. WHERE 절은
    실행되지 않으므로 (SQL 미실행) Python 쪽 멱등 가드를 검증하게 된다."""

    def __init__(self, rows):
        self._rows = rows
        self.added: list = []
        self.deleted: list = []
        self.commits = 0

    async def execute(self, stmt):
        return _ScalarResult(self._rows)

    def add(self, obj):
        self.added.append(obj)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1


def _make_return(**kwargs) -> SambaReturn:
    base = dict(order_id="ord1", type="return", status="requested")
    base.update(kwargs)
    return SambaReturn(**base)


# ── close_returns / reopen_returns 멱등성 ─────────────────────────────


class TestCloseReturns:
    async def test_미마감_행은_마감된다(self):
        ret = _make_return()
        session = _FakeSession([ret])
        closed = await close_returns(session, [ret.id])
        assert closed == 1
        assert ret.closed_at is not None
        assert ret.closed_by == CLOSED_BY_MANUAL
        assert session.commits == 1

    async def test_이미_마감된_행은_재마감_스킵(self):
        original_at = now_kst()
        ret = _make_return(closed_at=original_at, closed_by=CLOSED_BY_MANUAL)
        session = _FakeSession([ret])
        closed = await close_returns(session, [ret.id], by=CLOSED_BY_AUTO)
        assert closed == 0
        # 원본 마감 정보 보존 — auto 가 manual 마감을 덮지 않는다
        assert ret.closed_at == original_at
        assert ret.closed_by == CLOSED_BY_MANUAL
        assert session.commits == 0  # 변경 없으면 commit 안 함

    async def test_혼합_배치는_미마감분만_마감(self):
        done = _make_return(closed_at=now_kst(), closed_by=CLOSED_BY_MANUAL)
        fresh = _make_return()
        session = _FakeSession([done, fresh])
        closed = await close_returns(session, [done.id, fresh.id])
        assert closed == 1
        assert fresh.closed_at is not None

    async def test_by_파라미터가_closed_by_에_기록(self):
        ret = _make_return()
        session = _FakeSession([ret])
        await close_returns(session, [ret.id], by=CLOSED_BY_AUTO)
        assert ret.closed_by == CLOSED_BY_AUTO

    async def test_빈_ids_는_조회없이_0(self):
        session = _FakeSession([])
        assert await close_returns(session, []) == 0
        assert session.commits == 0


class TestReopenReturns:
    async def test_마감행은_해제된다(self):
        ret = _make_return(closed_at=now_kst(), closed_by=CLOSED_BY_MANUAL)
        session = _FakeSession([ret])
        reopened = await reopen_returns(session, [ret.id])
        assert reopened == 1
        assert ret.closed_at is None
        assert ret.closed_by is None
        assert session.commits == 1

    async def test_미마감_행은_해제_스킵_멱등(self):
        ret = _make_return()
        session = _FakeSession([ret])
        assert await reopen_returns(session, [ret.id]) == 0
        assert session.commits == 0

    async def test_마감후_해제_왕복(self):
        ret = _make_return()
        session = _FakeSession([ret])
        assert await close_returns(session, [ret.id]) == 1
        assert await reopen_returns(session, [ret.id]) == 1
        assert ret.closed_at is None
        # 다시 마감도 가능 (왕복 멱등)
        assert await close_returns(session, [ret.id]) == 1
        assert ret.closed_at is not None


class TestAutoCloseCandidates:
    async def test_스텁은_항상_빈_리스트(self):
        # 자동 마감 조건이 채워지기 전까지는 어떤 행도 자동 마감되면 안 된다
        session = _FakeSession([_make_return()])
        assert await auto_close_candidates(session) == []
        assert await auto_close_candidates(session, tenant_id="t1", older_than_days=1) == []


# ── order.py::_sync_returns_with_order_status 마감행 보호 ─────────────


def _make_order(**kwargs) -> SimpleNamespace:
    base = dict(
        id="ord1",
        order_number="ON1",
        status="paid",
        shipping_status="배송완료",
        tenant_id=None,
        customer_address=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _import_sync_fn():
    """order.py 의 _sync_returns_with_order_status 를 안전하게 import.

    order.py 를 곧장 import 하면 backend.dtos ↔ backend.domain.user 순환
    import 에 걸린다 — app_factory 와 같은 순서로 domain.user 를 먼저 import
    해 순환을 끊는다.
    """
    import backend.domain.user  # noqa: F401 — 순환 import 해소용 선행 import
    from backend.api.v1.routers.samba.order import (
        _sync_returns_with_order_status,
    )

    return _sync_returns_with_order_status


class TestSyncReturnsClosedRowProtection:
    async def test_claim_철회시_마감행은_삭제_안됨(self):
        _sync_returns_with_order_status = _import_sync_fn()

        closed = _make_return(closed_at=now_kst(), closed_by=CLOSED_BY_MANUAL)
        open_row = _make_return()  # 손 안 댄 자동생성 행 — 삭제 대상
        session = _FakeSession([closed, open_row])
        order = _make_order(status="paid", shipping_status="배송완료")  # claim 아님
        await _sync_returns_with_order_status(session, order)
        # 마감행은 남고, 열린 자동생성 행만 삭제된다
        assert session.deleted == [open_row]

    async def test_claim_상태여도_마감행은_갱신_안됨(self):
        _sync_returns_with_order_status = _import_sync_fn()

        # type 이 어긋난 두 행 — 가드 없으면 둘 다 type='return' 으로 갱신됨
        closed = _make_return(
            type="cancel", closed_at=now_kst(), closed_by=CLOSED_BY_MANUAL
        )
        open_row = _make_return(type="cancel")
        session = _FakeSession([closed, open_row])
        order = _make_order(status="return_requested", shipping_status="반품요청")
        await _sync_returns_with_order_status(session, order)
        assert closed.type == "cancel"  # 마감행 보존
        assert open_row.type == "return"  # 열린 행만 동기화

    async def test_마감행만_있어도_기존행으로_인정되어_재생성_안됨(self, monkeypatch):
        _sync_returns_with_order_status = _import_sync_fn()

        # rows 가 마감행뿐이어도 'if not rows' 분기(백필 재생성)를 타면 안 된다
        called = {"backfill": False}

        async def _boom(*args, **kwargs):
            called["backfill"] = True
            return 1

        monkeypatch.setattr(
            "backend.api.v1.routers.samba.returns._backfill_returns_from_claim_orders",
            _boom,
        )
        closed = _make_return(closed_at=now_kst(), closed_by=CLOSED_BY_MANUAL)
        session = _FakeSession([closed])
        order = _make_order(status="return_requested", shipping_status="반품요청")
        await _sync_returns_with_order_status(session, order)
        assert called["backfill"] is False  # 마감행이 있으니 새 행 생성 금지


# ── returns.py 백필 existing_* 판정 정적 검증 ─────────────────────────


class TestBackfillExistingGuardSource:
    """백필의 기존행 판정이 마감행을 걸러내지 않는지 소스 정적 검증.

    (백필 함수는 DB 세션 다중 쿼리 + repo.create_async 경로라 대역이 과대해져
    이 코드베이스 관례대로 소스 텍스트 검증으로 회귀를 차단한다 —
    test_approve_cancel_status_consistency.py 와 동일 방식)
    """

    def _backfill_body(self) -> str:
        src = (
            Path(__file__).resolve().parents[1]
            / "backend/api/v1/routers/samba/returns.py"
        ).read_text(encoding="utf-8")
        start = src.find("async def _backfill_returns_from_claim_orders(")
        assert start != -1
        end = src.find("\n@router.", start)
        return src[start : end if end != -1 else len(src)]

    def test_existing_판정에_closed_at_필터가_없다(self):
        body = self._backfill_body()
        # existing_stmt 블록(기존행 판정)에서 closed_at 조건으로 마감행을
        # 제외하면 마감건이 재생성된다 — WHERE 에 closed_at 사용 금지
        idx = body.find("existing_stmt")
        assert idx != -1
        existing_block = body[idx : body.find("existing_order_numbers", idx)]
        assert "closed_at" not in existing_block.replace(
            "# ⚠️ 여기에 closed_at 필터를 추가하지 말 것.", ""
        )

    def test_보호_주석_존재(self):
        body = self._backfill_body()
        assert "마감행" in body  # T7 보호 의도 주석이 지워지지 않았는지
