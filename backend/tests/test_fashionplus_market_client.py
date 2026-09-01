"""패션플러스 마켓 클라이언트 — 순수 로직 검증(네트워크 없음)."""

import pytest

from backend.domain.samba.proxy.fashionplus_market import (
    FP_OPS,
    FashionPlusMarketClient,
    classify_error,
    endpoint,
    extract_credentials,
    is_ok,
)


class FakeAccount:
    def __init__(self, additional_fields=None, api_key="", seller_id=""):
        self.additional_fields = additional_fields
        self.api_key = api_key
        self.seller_id = seller_id


def test_운영_엔드포인트():
    assert endpoint("goods_add", use_test=False) == (
        "https://api2.fashionplus.co.kr/api/json/GoodsAdd"
    )


def test_테스트_엔드포인트():
    assert endpoint("goods_add", use_test=True) == (
        "https://tst-api.fashionplus.co.kr/api/json/GoodsAdd"
    )


def test_모르는_op은_거부():
    with pytest.raises(KeyError):
        endpoint("nope", use_test=False)


def test_필수_op이_모두_정의되어_있다():
    필수 = {
        "goods_add", "option_add", "goods_upt", "option_upt", "scm_option_upt",
        "goods_dsp", "goods_delete", "goods_qry", "option_qry",
        "brand_list", "sender_add", "delivery_list", "invoice_proc",
        "out_of_stock_proc", "recall_list", "exchange_list",
    }
    assert 필수 <= set(FP_OPS)


def test_인증정보_추출():
    acc = FakeAccount({"custCode": "012555", "partnerLoginID": "sambauser"})
    assert extract_credentials(acc) == ("012555", "sambauser")


def test_인증정보_컬럼_폴백():
    """additional_fields 가 비면 api_key/seller_id 컬럼으로 폴백한다."""
    acc = FakeAccount(None, api_key="012555", seller_id="sambauser")
    assert extract_credentials(acc) == ("012555", "sambauser")


def test_인증정보_없으면_빈값():
    assert extract_credentials(FakeAccount(None)) == ("", "")


def test_성공_응답_판정():
    assert is_ok({"Status": "OK", "Message": ""}) is True


def test_실패_응답_판정():
    assert is_ok({"Status": "Err-Dat-003", "Message": "필수 데이터 누락"}) is False


def test_대소문자_다른_Status_키도_판정():
    assert is_ok({"status": "OK"}) is True


@pytest.mark.parametrize(
    "status,expected",
    [
        ("Err-Add-001", "auth_failed"),
        ("Err-Dat-003", "validation"),
        ("Err-Dat-104", "validation"),
        ("Err-Upt-110", "validation"),
        ("Err-Img-101", "image"),
        ("Err-Img-102", "image"),
        ("Err-Zzz-999", "unknown"),
    ],
)
def test_에러_분류(status, expected):
    assert classify_error(status) == expected


def test_요청_봉투에_인증필드가_주입된다():
    client = FashionPlusMarketClient("012555", "sambauser", use_test=True)
    body = client.build_body({"ItemNo": "A1"})
    assert body["ItemNo"] == "A1"
    assert body["CustCode"] == "012555"
    assert body["PartnerLoginID"] == "sambauser"
    assert isinstance(body["ApiKey"], str) and len(body["ApiKey"]) > 0


def test_인증필드는_호출마다_갱신된다():
    client = FashionPlusMarketClient("012555", "sambauser")
    assert client.build_body({})["ApiKey"] != client.build_body({})["ApiKey"]
