"""롯데홈쇼핑 유령상품 리컨실러 단위 테스트.

검증 항목:
  ① 유령 판정: 덤프 판매진행(10) ∧ DB 매핑 없음 — 그 외 상태는 유령 아님
  ② 등록 경쟁 가드: 덤프 수신 중 등록된 상품(재수집 매핑에 등장)은 유령 제외
  ③ 죽은기록 판정: 매핑 ∧ 덤프 품절(20)/중단(30), 단 삼바도 품절로 아는
     상품(sold_out)은 정상 동작이라 제외
  ④ 매핑 값 깨진 형태(dict/list 문자열)에서도 goods_no 수확 — 보호셋 과소포함 방지
  ⑤ AUTO_END 기본 OFF: 감지만 하고 update_sale_status 호출 없음

reconciler 모듈은 DB/lifecycle 을 import 하므로 함수 단위 monkeypatch 로 격리.
"""

import asyncio
import re
import sys
import types
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))


def _load_module():
    from backend.domain.samba.proxy import lottehome_ghost_reconciler as mod

    return mod


def test_digit_extraction_from_broken_shapes():
    """④ 순수 숫자 외 dict/list 문자열에서도 goods_no 수확."""
    mod = _load_module()
    assert mod._DIGITS_RE.findall('{"goods_no": "3312216975"}') == ["3312216975"]
    assert mod._DIGITS_RE.findall("['3312216975', '3364613397']") == [
        "3312216975",
        "3364613397",
    ]
    assert mod._DIGITS_RE.findall("pending") == []


def test_row_regex_parses_stocklist_xml():
    """스트리밍 정규식이 GoodNo/SaleStatCd 쌍을 정확히 뽑는다."""
    mod = _load_module()
    xml = (
        b"<Row><GoodNo>111</GoodNo><GoodsNm><![CDATA[\xb8\xc5\xc0\xe5]]></GoodsNm>"
        b"<SaleStatCd>10</SaleStatCd></Row>"
        b"<Row><GoodNo>222</GoodNo><GoodsNm><![CDATA[x]]></GoodsNm>"
        b"<SaleStatCd>30</SaleStatCd></Row>"
    )
    pairs = {m.group(1).decode(): m.group(2).decode() for m in mod._ROW_RE.finditer(xml)}
    assert pairs == {"111": "10", "222": "30"}


def _run_reconcile(mod, mapping_calls, dump, auto_end_calls):
    """_reconcile_one_account 를 외부 의존성 전부 스텁으로 실행."""
    call_idx = {"n": 0}

    async def fake_fetch(account_id):
        i = min(call_idx["n"], len(mapping_calls) - 1)
        call_idx["n"] += 1
        return mapping_calls[i]

    async def fake_stream(client):
        return dump

    async def fake_log_event(*a, **k):
        return None

    class FakeClient:
        async def update_sale_status(self, g, cd):
            auto_end_calls.append((g, cd))
            return {}

    async def fake_get_client(tenant_id):
        return FakeClient()

    mod._fetch_db_mapping = fake_fetch
    mod._stream_stocklist = fake_stream
    mod._log_event = fake_log_event
    mod._get_client_for = fake_get_client

    return asyncio.run(
        mod._reconcile_one_account(
            {"id": "acc1", "account_label": "마놀", "tenant_id": None}
        )
    )


def test_ghost_and_stale_detection():
    """①③ 유령/죽은기록 판정 + sold_out 노이즈 제외."""
    mod = _load_module()
    calls = []
    mapping = ({"100", "200", "300"}, {"300"})  # 300 은 삼바도 품절로 앎
    dump = {
        "100": "10",  # 매핑+판매중 = 정상
        "200": "20",  # 매핑+품절, 삼바는 in_stock = 죽은기록
        "300": "30",  # 매핑+중단, 삼바 sold_out = 정상(제외)
        "900": "10",  # 미매핑+판매중 = 유령
        "901": "20",  # 미매핑+품절 = 판정대상 아님(주문 불가)
    }
    result = _run_reconcile(mod, [mapping, mapping], dump, calls)
    assert result["ghosts"] == 1
    assert result["stale"] == 1
    assert calls == []  # AUTO_END 기본 OFF ⑤


def test_registration_race_guard():
    """② 덤프 수신 중 등록된 상품은 재수집 매핑으로 유령에서 제외."""
    mod = _load_module()
    calls = []
    first = ({"100"}, set())
    second = ({"100", "900"}, set())  # 900 이 덤프 수신 중 등록됨
    dump = {"100": "10", "900": "10", "901": "10"}
    result = _run_reconcile(mod, [first, second], dump, calls)
    assert result["ghosts"] == 1  # 901 만 유령 (900 은 가드로 제외)


def test_auto_end_fires_when_enabled():
    """AUTO_END=on 이면 유령만 영구중단(30) 호출."""
    mod = _load_module()
    calls = []
    orig = mod.AUTO_END
    try:
        mod.AUTO_END = True
        mod.END_BATCH_DELAY = 0
        mapping = ({"100"}, set())
        dump = {"100": "10", "900": "10"}
        result = _run_reconcile(mod, [mapping, mapping], dump, calls)
        assert result["ghosts"] == 1
        assert calls == [("900", "30")]
        assert result["auto_end_success"] == 1
    finally:
        mod.AUTO_END = orig
