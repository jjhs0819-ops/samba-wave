"""반품 회수상태 자동판정(collect_status) 단위 테스트 (T4-v2 — 2026-09-03).

- fetch_return_waybill: 원송장→반송장 자동획득 (CJ JSON / 한진 HTML / 미지원)
- _resolve_collect_tracking: 확보 우선순위 (저장값 → 원송장조회 → 마켓클레임)
- _extract_collect_tracking: 후보키 매칭 (평면/카멜·스네이크/중첩/미발견)
- judge_collect_status: 판정표 매핑 (404·이벤트0 → 미수거 / 진행중 → 수거중 /
  배송완료 → 수거완료)
- _may_transition: 되돌리기 금지 규칙 (진행 방향 전이만 허용)
- _fetch_track: 외부 HTTP 목킹 (실제 택배사/마켓 호출 금지)

⚠️ 외부 HTTP 는 전부 목킹 — 실제 택배사 호출 금지.
"""

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.domain.samba.returns.collect_status as cs  # noqa: E402
from backend.domain.samba.returns.collect_status import (  # noqa: E402
    RETURN_WAYBILL_SUPPORTED,
    STATUS_COLLECTED,
    STATUS_COLLECTING,
    STATUS_NOT_COLLECTED,
    _extract_collect_tracking,
    _fetch_track,
    _is_final_detail,
    _mask_tracking,
    _may_transition,
    _resolve_collect_tracking,
    fetch_return_waybill,
    judge_collect_status,
)


# ── _extract_collect_tracking ─────────────────────────────────────────


class TestExtractCollectTracking:
    def test_평면_카멜키_매칭(self):
        raw = {"rtngdDlvNo": "671234567890", "rtngdDlvCoNm": "CJ대한통운"}
        tracking, courier = _extract_collect_tracking(raw)
        assert tracking == "671234567890"
        assert courier == "CJ대한통운"

    def test_스네이크_대소문자_무시(self):
        raw = {"RETURN_INVOICE_NO": "123456789", "return_dlv_co": "한진택배"}
        tracking, courier = _extract_collect_tracking(raw)
        assert tracking == "123456789"
        assert courier == "한진택배"

    def test_중첩_dict_탐색(self):
        raw = {"claim": {"delivery": {"clctDlvNo": "987654321012"}}}
        tracking, courier = _extract_collect_tracking(raw)
        assert tracking == "987654321012"
        assert courier is None

    def test_중첩_list_탐색(self):
        raw = {"items": [{"returnInvoiceNo": "555666777888", "deliveryCompany": "롯데택배"}]}
        tracking, courier = _extract_collect_tracking(raw)
        assert tracking == "555666777888"
        assert courier == "롯데택배"

    def test_반품전용키가_범용키보다_우선(self):
        # invoiceNo(원송장일 수 있음)보다 rtngdDlvNo(회수송장)가 우선
        raw = {"invoiceNo": "111111111111", "rtngdDlvNo": "222222222222"}
        tracking, _ = _extract_collect_tracking(raw)
        assert tracking == "222222222222"

    def test_미발견시_None_과_키목록_로그(self, caplog):
        import logging

        raw = {"ordNo": "2026090312345", "buyerName": "홍길동", "detail": {"qty": 1}}
        with caplog.at_level(logging.INFO, logger="backend.domain.samba.returns.collect_status"):
            tracking, courier = _extract_collect_tracking(raw)
        assert tracking is None
        assert courier is None
        # 키 목록은 남기되 값(개인정보)은 로그에 없어야 한다
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert "ordNo" in joined
        assert "홍길동" not in joined

    def test_송장형식_아닌값은_무시(self):
        # 숫자 없는 값 / 너무 짧은 값은 송장으로 인정하지 않음
        raw = {"invoiceNo": "N/A", "dlvNo": "12"}
        tracking, _ = _extract_collect_tracking(raw)
        assert tracking is None

    def test_dict_아니면_None(self):
        assert _extract_collect_tracking(None) == (None, None)  # type: ignore[arg-type]
        assert _extract_collect_tracking("문자열") == (None, None)  # type: ignore[arg-type]


# ── judge_collect_status (판정표) ─────────────────────────────────────


class TestJudgeCollectStatus:
    def test_조회결과_없음은_미수거(self):
        status, _ = judge_collect_status(None)
        assert status == STATUS_NOT_COLLECTED

    def test_이벤트_0건은_미수거(self):
        status, _ = judge_collect_status({"state": {"id": "information_received"}, "progresses": []})
        assert status == STATUS_NOT_COLLECTED

    def test_진행중이면_수거중(self):
        track = {
            "state": {"id": "in_transit", "text": "이동중"},
            "progresses": [
                {"status": {"id": "at_pickup", "text": "집하완료"}},
                {"status": {"id": "in_transit", "text": "간선상차"}},
            ],
        }
        status, final_text = judge_collect_status(track)
        assert status == STATUS_COLLECTING
        assert final_text == "이동중"

    def test_배송완료_state_id_는_수거완료(self):
        track = {
            "state": {"id": "delivered", "text": "배송완료"},
            "progresses": [{"status": {"id": "delivered", "text": "배송완료"}}],
        }
        status, _ = judge_collect_status(track)
        assert status == STATUS_COLLECTED

    def test_배송완료_텍스트만_있어도_수거완료(self):
        track = {
            "state": {"id": "", "text": "배송완료"},
            "progresses": [{"status": {"id": "", "text": "배송완료"}}],
        }
        status, _ = judge_collect_status(track)
        assert status == STATUS_COLLECTED


# ── _may_transition (되돌리기 금지) ───────────────────────────────────


class TestMayTransition:
    def test_수거완료는_절대_하향_안됨(self):
        assert _may_transition(STATUS_COLLECTED, STATUS_COLLECTING) is False
        assert _may_transition(STATUS_COLLECTED, STATUS_NOT_COLLECTED) is False

    def test_수거중을_미수거로_내리지_않음(self):
        assert _may_transition(STATUS_COLLECTING, STATUS_NOT_COLLECTED) is False

    def test_진행방향_상향은_허용(self):
        assert _may_transition(STATUS_NOT_COLLECTED, STATUS_COLLECTING) is True
        assert _may_transition(STATUS_NOT_COLLECTED, STATUS_COLLECTED) is True
        assert _may_transition(STATUS_COLLECTING, STATUS_COLLECTED) is True

    def test_동일상태는_변경없음(self):
        assert _may_transition(STATUS_COLLECTING, STATUS_COLLECTING) is False

    def test_회수상태_아닌_기존상태는_최초판정_허용(self):
        # 클레임 어휘(requested 등)에서 회수상태로의 최초 판정은 허용
        assert _may_transition("requested", STATUS_NOT_COLLECTED) is True
        assert _may_transition(None, STATUS_COLLECTING) is True

    def test_회수상태_아닌_새값은_거부(self):
        assert _may_transition(STATUS_COLLECTING, "requested") is False


# ── 보조 헬퍼 ─────────────────────────────────────────────────────────


class TestHelpers:
    def test_송장_마스킹_뒤4자리만(self):
        assert _mask_tracking("671234567890") == "********7890"
        assert _mask_tracking("1234") == "1234"
        assert _mask_tracking("") == ""

    def test_완료확정값_스킵판정(self):
        for detail in ("취소", "반품", "교환", "거부"):
            assert _is_final_detail(detail) is True
        assert _is_final_detail("진행중") is False
        assert _is_final_detail(None) is False
        assert _is_final_detail("") is False


# ── _fetch_track (외부 HTTP 목킹) ─────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    """httpx.AsyncClient 대역 — 실제 네트워크 호출 금지."""

    response: _FakeResponse = _FakeResponse(200)
    raise_on_call: Exception | None = None  # 네트워크 예외 시뮬레이션
    last_url: str = ""
    last_method: str = ""
    last_data: dict | None = None
    last_params: dict | None = None
    call_count: int = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url: str, params=None, headers=None):
        cls = _FakeAsyncClient
        cls.call_count += 1
        cls.last_url = url
        cls.last_method = "GET"
        cls.last_params = params
        if cls.raise_on_call is not None:
            raise cls.raise_on_call
        return cls.response

    async def post(self, url: str, data=None, headers=None):
        cls = _FakeAsyncClient
        cls.call_count += 1
        cls.last_url = url
        cls.last_method = "POST"
        cls.last_data = data
        if cls.raise_on_call is not None:
            raise cls.raise_on_call
        return cls.response


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    # 클래스 상태 초기화 (테스트 간 오염 방지)
    _FakeAsyncClient.response = _FakeResponse(200)
    _FakeAsyncClient.raise_on_call = None
    _FakeAsyncClient.last_url = ""
    _FakeAsyncClient.last_method = ""
    _FakeAsyncClient.last_data = None
    _FakeAsyncClient.last_params = None
    _FakeAsyncClient.call_count = 0
    return _FakeAsyncClient


# ── fetch_return_waybill (원송장 → 반송장, 외부 HTTP 목킹) ────────────

# 실제 응답 샘플 (개인정보 없는 부분만, 2026-09-03 실측):
# CJ → {"data":{"wblNo":"302915206862","rtnWblno":"844708752215","ognWblno":"",
#        ...},"resultCode":200,"resultMessage":"성공"}
# 한진 → <span class="fr pad40r ">[<strong>반품운송장번호</strong> :
#        <a href="/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038&wblnum=573871357113
#        &schLang=KR" class="cblue">573871357113</a>]</span>


class TestFetchReturnWaybill:
    async def test_CJ_반송장_있으면_반환(self, fake_httpx):
        fake_httpx.response = _FakeResponse(
            200,
            {
                "data": {"wblNo": "302915206862", "rtnWblno": "844708752215", "ognWblno": ""},
                "resultCode": 200,
                "resultMessage": "성공",
            },
        )
        result = await fetch_return_waybill("CJ대한통운", "302915206862")
        assert result == "844708752215"
        assert fake_httpx.last_method == "POST"
        assert "trace.cjlogistics.com" in fake_httpx.last_url
        assert fake_httpx.last_data == {"wblNo": "302915206862"}

    async def test_CJ_반송장_빈값이면_미발행_None(self, fake_httpx):
        fake_httpx.response = _FakeResponse(
            200, {"data": {"wblNo": "302915206862", "rtnWblno": ""}, "resultCode": 200}
        )
        assert await fetch_return_waybill("CJ대한통운", "302915206862") is None

    async def test_CJ_별칭도_정규화되어_동작(self, fake_httpx):
        fake_httpx.response = _FakeResponse(
            200, {"data": {"rtnWblno": "844708752215"}, "resultCode": 200}
        )
        assert await fetch_return_waybill("CJ", "302915206862") == "844708752215"

    async def test_한진_HTML_기본패턴_파싱(self, fake_httpx):
        html = (
            '<span class="fr pad40r ">[<strong>반품운송장번호</strong> : '
            '<a href="/kor/CMS/DeliveryMgr/WaybillResult.do?mCode=MN038'
            '&wblnum=573871357113&schLang=KR" class="cblue">573871357113</a>]</span>'
        )
        fake_httpx.response = _FakeResponse(200, text=html)
        result = await fetch_return_waybill("한진택배", "512345678901")
        assert result == "573871357113"
        assert fake_httpx.last_method == "GET"
        assert "hanjin.com" in fake_httpx.last_url
        assert fake_httpx.last_params["wblnumText2"] == "512345678901"

    async def test_한진_반송장_미발행이면_None(self, fake_httpx):
        fake_httpx.response = _FakeResponse(200, text="<html><body>배송정보</body></html>")
        assert await fetch_return_waybill("한진택배", "512345678901") is None

    async def test_한진_마크업변경시_wblnum_폴백(self, fake_httpx):
        # 앵커 구조가 바뀌어도 링크 파라미터로 회수 (원송장 자기자신은 제외)
        html = (
            '<a href="?wblnum=512345678901">원송장</a>'
            '<div>반품 <a data-x href="?wblnum=573871357113">보기</a></div>'
        )
        fake_httpx.response = _FakeResponse(200, text=html)
        assert await fetch_return_waybill("한진택배", "512345678901") == "573871357113"

    async def test_미지원_택배사는_HTTP없이_즉시_None(self, fake_httpx):
        for courier in ("롯데택배", "로젠택배", "딜리박스", "우체국택배", "", None):
            assert await fetch_return_waybill(courier, "123456789012") is None  # type: ignore[arg-type]
        assert fake_httpx.call_count == 0

    async def test_빈송장은_HTTP없이_None(self, fake_httpx):
        assert await fetch_return_waybill("CJ대한통운", "") is None
        assert fake_httpx.call_count == 0

    async def test_네트워크_예외는_None_흡수(self, fake_httpx, caplog):
        import logging

        fake_httpx.raise_on_call = ConnectionError("boom")
        with caplog.at_level(logging.WARNING, logger=cs.logger.name):
            assert await fetch_return_waybill("한진택배", "512345678901") is None
        assert any("실패" in r.getMessage() for r in caplog.records)

    async def test_비정상_상태코드는_None(self, fake_httpx):
        fake_httpx.response = _FakeResponse(503)
        assert await fetch_return_waybill("CJ대한통운", "302915206862") is None

    async def test_지원목록_상수(self):
        assert RETURN_WAYBILL_SUPPORTED == {"CJ대한통운", "한진택배"}


# ── _resolve_collect_tracking (확보 우선순위) ─────────────────────────


class _FakeSession:
    """AsyncSession 대역 — add 호출만 기록."""

    def __init__(self):
        self.added: list = []

    def add(self, obj):
        self.added.append(obj)


def _make_order(**kwargs) -> SimpleNamespace:
    base = {
        "return_collect_tracking": None,
        "return_collect_courier": None,
        "return_collect_at": None,
        "tracking_number": None,
        "shipping_company": None,
        "channel_id": None,
        "order_number": "ORD1",
        "claim_order_number": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestResolveCollectTracking:
    @pytest.fixture(autouse=True)
    def _no_external(self, monkeypatch):
        """마켓 클레임 조회·반송장 조회는 기본 무응답으로 목킹."""

        async def _no_claims(session, order, cache):
            return []

        async def _no_waybill(courier, tracking):
            return None

        monkeypatch.setattr(cs, "_load_market_claim_items", _no_claims)
        monkeypatch.setattr(cs, "fetch_return_waybill", _no_waybill)

    async def test_1순위_저장값_그대로_사용(self, monkeypatch):
        called = {"fetch": False}

        async def _boom(courier, tracking):
            called["fetch"] = True
            return None

        monkeypatch.setattr(cs, "fetch_return_waybill", _boom)
        order = _make_order(
            return_collect_tracking="844708752215", return_collect_courier="CJ대한통운"
        )
        found = await _resolve_collect_tracking(_FakeSession(), order, {})
        assert found["tracking"] == "844708752215"
        assert found["source"] == "회수송장(저장값)"
        assert called["fetch"] is False  # 저장값 있으면 재조회 안 함

    async def test_2순위_원송장조회로_반송장_획득후_주문에_저장(self, monkeypatch):
        async def _hit(courier, tracking):
            assert courier == "CJ대한통운"
            assert tracking == "302915206862"
            return "844708752215"

        monkeypatch.setattr(cs, "fetch_return_waybill", _hit)
        session = _FakeSession()
        order = _make_order(
            tracking_number="302915206862", shipping_company="CJ대한통운"
        )
        found = await _resolve_collect_tracking(session, order, {})
        assert found["tracking"] == "844708752215"
        assert found["courier"] == "CJ대한통운"
        assert found["source"] == "반송장(원송장조회)"
        assert found["waybill_found"] is True
        # 재조회 절감용 저장 확인
        assert order.return_collect_tracking == "844708752215"
        assert order.return_collect_courier == "CJ대한통운"
        assert isinstance(order.return_collect_at, datetime)
        assert order in session.added

    async def test_3순위_마켓클레임은_원송장조회_다음(self, monkeypatch):
        async def _claims(session, order, cache):
            return [{"ordNo": "ORD1", "rtngdDlvNo": "555666777888"}]

        monkeypatch.setattr(cs, "_load_market_claim_items", _claims)
        order = _make_order(
            tracking_number="302915206862", shipping_company="CJ대한통운"
        )
        # fetch_return_waybill 은 (autouse 픽스처로) None → 클레임 폴백
        found = await _resolve_collect_tracking(_FakeSession(), order, {})
        assert found["tracking"] == "555666777888"
        assert found["source"] == "회수송장(마켓클레임)"
        assert found["waybill_found"] is False

    async def test_미지원_택배사는_unsupported_표기(self):
        order = _make_order(tracking_number="123456789012", shipping_company="롯데택배")
        found = await _resolve_collect_tracking(_FakeSession(), order, {})
        assert found["tracking"] is None
        assert found["unsupported"] is True
        assert found["source"] == "미지원택배사"

    async def test_지원사인데_미발행이면_반송장미발행(self):
        order = _make_order(
            tracking_number="302915206862", shipping_company="CJ대한통운"
        )
        found = await _resolve_collect_tracking(_FakeSession(), order, {})
        assert found["tracking"] is None
        assert found["unsupported"] is False
        assert found["source"] == "반송장미발행"

    async def test_원송장_자체가_없으면_원송장없음(self):
        order = _make_order()
        found = await _resolve_collect_tracking(_FakeSession(), order, {})
        assert found["tracking"] is None
        assert found["source"] == "원송장없음"


class TestFetchTrack:
    async def test_404는_None(self, fake_httpx):
        fake_httpx.response = _FakeResponse(404)
        assert await _fetch_track("kr.cjlogistics", "671234567890") is None

    async def test_200은_json_반환(self, fake_httpx):
        payload = {"state": {"id": "delivered", "text": "배송완료"}, "progresses": [{}]}
        fake_httpx.response = _FakeResponse(200, payload)
        assert await _fetch_track("kr.cjlogistics", "671234567890") == payload

    async def test_500은_예외(self, fake_httpx):
        fake_httpx.response = _FakeResponse(500)
        with pytest.raises(RuntimeError):
            await _fetch_track("kr.cjlogistics", "671234567890")

    async def test_송장_특수문자_정리되어_URL에_들어감(self, fake_httpx):
        fake_httpx.response = _FakeResponse(200, {})
        await _fetch_track("kr.hanjin", "6712-3456-7890")
        assert fake_httpx.last_url.endswith("/kr.hanjin/tracks/671234567890")

    async def test_빈송장은_호출없이_None(self, fake_httpx):
        fake_httpx.last_url = ""
        assert await _fetch_track("kr.hanjin", "") is None
        assert fake_httpx.last_url == ""


# ══════════════════════════════════════════════════════════════════════
# refresh_collect_status 배치 (T7 마감행 제외 · T8 체크날짜/쿨다운)
# — DB 없이 세션 대역으로 검증. 외부 HTTP 는 전부 목킹.
# ══════════════════════════════════════════════════════════════════════

from datetime import UTC, timedelta  # noqa: E402

from backend.domain.samba.order.model import SambaOrder  # noqa: E402
from backend.domain.samba.returns.model import SambaReturn  # noqa: E402
from backend.utils import now_kst  # noqa: E402


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)


class _BatchSession:
    """refresh_collect_status 용 세션 대역 — select 대상 모델로 결과를 분기.

    ⚠️ WHERE 절은 실행되지 않으므로(SQL 미실행) SQL 쪽 마감행 제외가 아니라
    Python 쪽 방어 가드·쿨다운·check_date 로직을 검증하게 된다.
    """

    def __init__(self, returns, orders=()):
        self._returns = list(returns)
        self._orders = list(orders)
        self.added: list = []
        self.commits = 0

    async def execute(self, stmt):
        entity = stmt.column_descriptions[0].get("entity")
        if entity is SambaReturn:
            return _ScalarResult(self._returns)
        if entity is SambaOrder:
            return _ScalarResult(self._orders)
        raise AssertionError(f"예상 밖 select: {entity}")

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1


def _ret(**kwargs) -> SambaReturn:
    base = dict(order_id="o1", type="return", status="requested")
    base.update(kwargs)
    return SambaReturn(**base)


@pytest.fixture
def batch_mocks(monkeypatch):
    """반송장 확보·배송조회 목킹 — resolve_map[order_id] 로 시나리오 지정."""
    state = {
        "resolve_map": {},  # order_id → _resolve_collect_tracking 반환 dict
        "track": None,  # _fetch_track 반환값 (배송조회 결과)
        "resolved_order_ids": [],  # 실제 조회(probe)된 주문 id 기록
    }

    async def _fake_resolve(session, order, cache):
        state["resolved_order_ids"].append(order.id)
        return state["resolve_map"].get(
            order.id,
            {
                "tracking": None,
                "courier": None,
                "source": "원송장없음",
                "waybill_found": False,
                "unsupported": False,
            },
        )

    async def _fake_track(carrier_id, invoice):
        return state["track"]

    def _fake_carrier(courier):
        return "kr.cjlogistics"

    monkeypatch.setattr(cs, "_resolve_collect_tracking", _fake_resolve)
    monkeypatch.setattr(cs, "_fetch_track", _fake_track)
    monkeypatch.setattr(cs, "_carrier_id_for", _fake_carrier)
    return state


_RESOLVED_CJ = {
    "tracking": "844708752215",
    "courier": "CJ대한통운",
    "source": "회수송장(저장값)",
    "waybill_found": False,
    "unsupported": False,
}

_TRACK_DELIVERED = {
    "state": {"id": "delivered", "text": "배송완료"},
    "progresses": [{"status": {"id": "delivered", "text": "배송완료"}}],
}


class TestRefreshBatchCheckDate:
    async def test_상태가_바뀐_행만_check_date_오늘로(self, batch_mocks):
        # changed: 반송장 있음 + 배송완료 → collected (상태 변경)
        changed = _ret(order_id="o1", status="collecting", check_date=None)
        # unchanged: 반송장 미발행 → not_collected 인데 이미 not_collected (변경 없음)
        old_date = now_kst() - timedelta(days=5)
        unchanged = _ret(
            order_id="o2", status=cs.STATUS_NOT_COLLECTED, check_date=old_date
        )
        batch_mocks["resolve_map"] = {
            "o1": _RESOLVED_CJ,
            "o2": {
                "tracking": None,
                "courier": None,
                "source": "반송장미발행",
                "waybill_found": False,
                "unsupported": False,
            },
        }
        batch_mocks["track"] = _TRACK_DELIVERED
        session = _BatchSession(
            [changed, unchanged],
            [SimpleNamespace(id="o1"), SimpleNamespace(id="o2")],
        )
        result = await cs.refresh_collect_status(session, cooldown_minutes=0)

        assert changed.status == cs.STATUS_COLLECTED
        # 상태 바뀐 행 — check_date = 오늘 KST 자정
        assert changed.check_date is not None
        today = now_kst().replace(hour=0, minute=0, second=0, microsecond=0)
        assert changed.check_date == today
        # 상태 안 바뀐 행 — check_date 그대로 (과거 날짜로 남아 눈에 띔)
        assert unchanged.check_date == old_date
        assert unchanged.status == cs.STATUS_NOT_COLLECTED
        assert result["updated"] == 1

    async def test_조회한_행은_상태변경_무관하게_auto_checked_at_기록(
        self, batch_mocks
    ):
        changed = _ret(order_id="o1", status="requested")
        unchanged = _ret(order_id="o2", status=cs.STATUS_NOT_COLLECTED)
        batch_mocks["resolve_map"] = {"o1": _RESOLVED_CJ}
        batch_mocks["track"] = _TRACK_DELIVERED
        session = _BatchSession(
            [changed, unchanged],
            [SimpleNamespace(id="o1"), SimpleNamespace(id="o2")],
        )
        await cs.refresh_collect_status(session, cooldown_minutes=0)
        assert changed.auto_checked_at is not None
        assert unchanged.auto_checked_at is not None  # 변경 없어도 '본 시각' 기록
        assert session.commits >= 1  # auto_checked_at 반영 commit


class TestRefreshBatchCooldown:
    async def test_쿨다운_1시간_이내_행은_스킵(self, batch_mocks):
        recent = _ret(
            order_id="o1", auto_checked_at=datetime.now(UTC) - timedelta(minutes=10)
        )
        stale = _ret(
            order_id="o2", auto_checked_at=datetime.now(UTC) - timedelta(hours=2)
        )
        never = _ret(order_id="o3")  # 한 번도 조회 안 한 행
        session = _BatchSession(
            [recent, stale, never],
            [SimpleNamespace(id="o2"), SimpleNamespace(id="o3")],
        )
        result = await cs.refresh_collect_status(session, cooldown_minutes=60)
        assert result["cooldown_skipped"] == 1
        # 쿨다운 스킵 행은 조회 자체가 없다 (택배사 호출 절감)
        assert "o1" not in batch_mocks["resolved_order_ids"]
        assert set(batch_mocks["resolved_order_ids"]) == {"o2", "o3"}

    async def test_쿨다운_0이면_전부_조회(self, batch_mocks):
        recent = _ret(
            order_id="o1", auto_checked_at=datetime.now(UTC) - timedelta(minutes=1)
        )
        session = _BatchSession([recent], [SimpleNamespace(id="o1")])
        result = await cs.refresh_collect_status(session, cooldown_minutes=0)
        assert result["cooldown_skipped"] == 0
        assert batch_mocks["resolved_order_ids"] == ["o1"]

    async def test_naive_datetime_도_쿨다운_판정(self, batch_mocks):
        # DB 드라이버가 naive 로 돌려줘도 UTC 간주해 쿨다운 적용
        naive_recent = datetime.now(UTC).replace(tzinfo=None)
        recent = _ret(order_id="o1", auto_checked_at=naive_recent)
        session = _BatchSession([recent], [SimpleNamespace(id="o1")])
        result = await cs.refresh_collect_status(session, cooldown_minutes=60)
        assert result["cooldown_skipped"] == 1

    async def test_반환_dict_에_cooldown_skipped_키(self, batch_mocks):
        session = _BatchSession([], [])
        result = await cs.refresh_collect_status(session)
        # 기존 키 유지 + cooldown_skipped 추가
        for key in (
            "ok",
            "checked",
            "updated",
            "skipped",
            "cooldown_skipped",
            "no_tracking",
            "waybill_found",
            "unsupported_courier",
            "errors",
        ):
            assert key in result


class TestRefreshBatchClosedRows:
    async def test_마감행은_조회대상_제외(self, batch_mocks):
        closed = _ret(order_id="o1", closed_at=now_kst(), closed_by="manual")
        open_row = _ret(order_id="o2")
        session = _BatchSession(
            [closed, open_row],
            [SimpleNamespace(id="o2")],
        )
        result = await cs.refresh_collect_status(session, cooldown_minutes=0)
        # 마감행은 Python 방어 가드로도 스킵 (SQL 필터와 이중)
        assert "o1" not in batch_mocks["resolved_order_ids"]
        assert batch_mocks["resolved_order_ids"] == ["o2"]
        assert closed.auto_checked_at is None  # 마감행은 건드리지 않는다
        assert result["skipped"] >= 1

    def test_SQL_쿼리에도_마감행_제외_조건(self):
        # 대역 세션은 WHERE 를 실행하지 않으므로, SQL 쪽 제외는 소스로 검증
        import inspect

        src = inspect.getsource(cs.refresh_collect_status)
        assert "closed_at.is_(None)" in src
