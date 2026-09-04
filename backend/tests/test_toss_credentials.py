"""토스 인증정보 적재 위치 검증.

설정 화면 저장 경로는 키를 api_key/api_secret **컬럼이 아니라**
additional_fields 에 넣는다(2026-09-04 운영 DB 실측: 컬럼 0자,
additional_fields.apiKey 32자 / apiSecret 48자). 컬럼만 읽으면
전송이 전부 auth_failed 로 죽는다. SSG 도 같은 이유로 폴백을 둔다.
"""

from backend.domain.samba.account.credentials import toss_creds
from backend.domain.samba.plugins.markets.toss import TossPlugin


class FakeAccount:
    def __init__(self, api_key=None, api_secret=None, additional_fields=None):
        self.api_key = api_key
        self.api_secret = api_secret
        self.additional_fields = additional_fields


def test_컬럼에_있으면_컬럼을_쓴다():
    acc = FakeAccount(api_key="COL_KEY", api_secret="COL_SECRET")
    assert toss_creds(acc) == {"apiKey": "COL_KEY", "apiSecret": "COL_SECRET"}


def test_컬럼이_비면_additional_fields로_폴백한다():
    acc = FakeAccount(
        api_key="", api_secret="", additional_fields={"apiKey": "AF_KEY", "apiSecret": "AF_SECRET"}
    )
    assert toss_creds(acc) == {"apiKey": "AF_KEY", "apiSecret": "AF_SECRET"}


def test_계정이_없으면_빈값():
    assert toss_creds(None) == {}


def test_플러그인도_additional_fields에서_키를_찾는다():
    """삭제·인증테스트는 creds 없이 account 만 들고 온다."""
    acc = FakeAccount(
        api_key=None,
        api_secret=None,
        additional_fields={"apiKey": "AF_KEY", "apiSecret": "AF_SECRET"},
    )
    assert TossPlugin()._extract_keys({}, acc) == ("AF_KEY", "AF_SECRET")
