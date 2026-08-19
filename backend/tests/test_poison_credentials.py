"""POIZON 계정 인증정보 로드 테스트 (2026-08-16).

계정마다 키가 저장된 필드명이 제각각이다(appKey/apiKey/app_key, 최상위 api_key).
등록 플러그인은 apiKey 를 읽는데 주문 폴러·송장 전송은 읽지 않아, 등록은 되는데
주문 수집과 송장 전송만 조용히 실패했다(로그도 "키 없음" 한 줄). 48시간 발송 기한을
놓치면 위약금이 붙으므로 세 경로가 같은 함수를 쓰도록 통일한다.
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import extract_credentials


class _Acc:
    def __init__(self, extras=None, api_key=None, api_secret=None):
        self.additional_fields = extras
        self.api_key = api_key
        self.api_secret = api_secret


def test_운영계정_형식_apiKey():
    # 실제 운영 계정이 이 형식이다
    a = _Acc({"apiKey": "K1", "apiSecret": "S1"})
    assert extract_credentials(a) == ("K1", "S1")


def test_appKey_형식도_지원():
    a = _Acc({"appKey": "K2", "appSecret": "S2"})
    assert extract_credentials(a) == ("K2", "S2")


def test_snake_case_형식도_지원():
    a = _Acc({"app_key": "K3", "app_secret": "S3"})
    assert extract_credentials(a) == ("K3", "S3")


def test_최상위_컬럼_폴백():
    a = _Acc({}, api_key="K4", api_secret="S4")
    assert extract_credentials(a) == ("K4", "S4")


def test_extras_가_최상위보다_우선():
    a = _Acc({"apiKey": "K5", "apiSecret": "S5"}, api_key="OLD", api_secret="OLD")
    assert extract_credentials(a) == ("K5", "S5")


def test_없으면_빈문자열():
    assert extract_credentials(_Acc()) == ("", "")
    assert extract_credentials(None) == ("", "")


def test_additional_fields가_dict가_아니어도_안전():
    assert extract_credentials(_Acc("이상한값")) == ("", "")


def test_dict_계정도_지원한다():
    # 주문 동기화 경로는 계정을 dict(row)로 다룬다 — 여기서도 apiKey 를 읽어야 한다
    acc = {"additional_fields": {"apiKey": "K", "apiSecret": "S"},
           "api_key": None, "api_secret": None}
    assert extract_credentials(acc) == ("K", "S")


def test_dict_최상위_컬럼_폴백():
    acc = {"additional_fields": {}, "api_key": "TK", "api_secret": "TS"}
    assert extract_credentials(acc) == ("TK", "TS")
