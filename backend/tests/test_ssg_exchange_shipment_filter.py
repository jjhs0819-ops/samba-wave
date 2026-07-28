"""SSG 교환출고 배송지시 판별 테스트.

SSG 교환건은 원주문(orordNo) 아래에 별도 ordNo 를 가진 '교환출고' 배송지시로 발행되어
listShppDirection/listWarehouseOut 응답에 신규주문과 섞여 나온다. 이걸 신규주문으로
INSERT 하면 ①배송지/수령인이 판매자(반품지)로 박히고 ②원가 0 매출 이중계상 ③자동
발주확인까지 걸려 미출고 페널티 리스크가 생긴다. (2026-07-28 실측 2건)

반대로 클레임 상태행(ordItemDiv 021/031/041/042)은 원주문 상태를 취소/반품/교환요청으로
갱신하는 데 필요하므로 걸러내면 안 된다.
"""

from __future__ import annotations

import os

# BackendSettings(전역 import 시 인스턴스화) 최소 env
os.environ.setdefault("WRITE_DB_USER", "u")
os.environ.setdefault("WRITE_DB_PASSWORD", "p")
os.environ.setdefault("WRITE_DB_HOST", "localhost")
os.environ.setdefault("WRITE_DB_PORT", "5432")
os.environ.setdefault("WRITE_DB_NAME", "d")
os.environ.setdefault("READ_DB_USER", "u")
os.environ.setdefault("READ_DB_PASSWORD", "p")
os.environ.setdefault("READ_DB_HOST", "localhost")
os.environ.setdefault("READ_DB_PORT", "5432")
os.environ.setdefault("READ_DB_NAME", "d")
os.environ.setdefault("JWT_SECRET_KEY", "s")

from backend.domain.samba.proxy.ssg import SSGClient  # noqa: E402


# 2026-07-28 실측 listWarehouseOut 응답 (ordNo 20260723E77451)
REAL_EXCHANGE_SHIPMENT = {
    "itemId": 1000834147489,
    "itemNm": "IQ2973 486 운동화 캐주얼스니커즈 에어 맥스 엑시 1010120612",
    "lastShppProgStatDtlCd": 22,
    "lastShppProgStatDtlNm": "피킹완료",
    "ordItemDivNm": "교환주문",
    "ordItemSeq": 2,
    "ordNo": "20260723E77451",
    "orordNo": "20260719DB22B6",
    "orordItemSeq": 1,
    "rcptpeNm": "세팅",
    "shppDivDtlCd": 15,
    "shppDivDtlNm": "교환출고",
    "shppNo": 10212480658,
    "shppSeq": 1,
    "shpplocBascAddr": "인천광역시 서구 솔빛로 93",
    "sellprc": 135600,
    "splPrc": 96153,
}

# 2026-07-28 실측 listShppDirection 응답 (정상 신규주문)
REAL_NORMAL_ORDER = {
    "itemId": 1000832700464,
    "itemNm": "JR8772 공용 패션스니커즈화 스니커즈 SL 72 RS 딥그린 화이트",
    "ordItemDivNm": "일반주문",
    "ordItemSeq": 1,
    "ordNo": "2026072803BCC9",
    "orordNo": "2026072803BCC9",
    "ordpeNm": "홍길동",
    "rcptpeNm": "홍길동",
    "shppNo": 10213327316,
    "shppSeq": 1,
    "shppProgStatDtlCd": "11",
}


def test_교환출고_배송지시는_제외대상():
    assert SSGClient.is_exchange_shipment(REAL_EXCHANGE_SHIPMENT) is True


def test_정상_신규주문은_제외대상_아님():
    assert SSGClient.is_exchange_shipment(REAL_NORMAL_ORDER) is False


def test_shppDivDtlCd가_문자열이어도_판별():
    raw = dict(REAL_EXCHANGE_SHIPMENT, shppDivDtlCd="15")
    assert SSGClient.is_exchange_shipment(raw) is True


def test_shppDivDtlCd_없어도_교환주문_별도발번이면_제외대상():
    """listShppDirection 응답에는 shppDivDtlCd 가 없을 수 있다."""
    raw = dict(REAL_EXCHANGE_SHIPMENT)
    raw.pop("shppDivDtlCd")
    raw.pop("shppDivDtlNm")
    assert SSGClient.is_exchange_shipment(raw) is True


def test_클레임_상태행은_제외하지_않음():
    """ordItemDiv 021/031/041/042 는 원주문 상태 갱신에 필요 — 걸러내면 안 됨."""
    for div in ("021", "031", "041", "042"):
        raw = {
            "ordItemDiv": div,
            "ordItemDivNm": "교환주문",
            "ordNo": "20260713C74245",
            "orordNo": "20260713C74245",
            "rcptpeNm": "김선규",
        }
        assert SSGClient.is_exchange_shipment(raw) is False, f"ordItemDiv={div}"


def test_교환요청_회수건_shppDivDtlCd_22는_제외하지_않음():
    """22 = 교환요청(회수) — 반품/교환 상태 동기화 경로가 쓰는 값."""
    raw = {
        "ordItemDivNm": "교환주문",
        "ordNo": "20260723E77451",
        "orordNo": "20260719DB22B6",
        "shppDivDtlCd": 22,
    }
    assert SSGClient.is_exchange_shipment(raw) is False


def test_원주문번호_없으면_제외하지_않음():
    """orordNo 누락 시 오탐으로 정상주문을 버리지 않는다."""
    raw = dict(REAL_EXCHANGE_SHIPMENT)
    raw.pop("shppDivDtlCd")
    raw.pop("shppDivDtlNm")
    raw["orordNo"] = ""
    assert SSGClient.is_exchange_shipment(raw) is False


def test_빈_dict_안전():
    assert SSGClient.is_exchange_shipment({}) is False


def test_주문동기화_라우터가_필터를_통과시킨_뒤_parse_order_한다():
    """정적 계약 — 필터가 parse_order/자동발주확인보다 먼저 걸려야 한다."""
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[1]
        / "backend/api/v1/routers/samba/order.py"
    ).read_text(encoding="utf-8")

    assert "is_exchange_shipment(_ssg_ro)" in src, "주문동기화에 교환출고 필터 미연결"

    idx_filter = src.index("is_exchange_shipment(_ssg_ro)")
    idx_parse = src.index("_ord = _ssg_client.parse_order(")
    idx_confirm = src.index("_ssg_unconfirmed.append(")
    assert idx_filter < idx_parse, "필터가 parse_order 보다 뒤에 있음"
    assert idx_filter < idx_confirm, "필터가 자동 발주확인 수집보다 뒤에 있음"
    # continue 로 루프를 빠져나가야 orders_data 에 안 들어간다
    assert "continue" in src[idx_filter:idx_parse], "필터 통과 시 continue 누락"
