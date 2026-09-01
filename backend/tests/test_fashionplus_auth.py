"""패션플러스 인증키 생성 검증.

레퍼런스 구현(API_key.php)과 동일한 결과를 내는지 고정값으로 확인한다.
"""

from datetime import datetime, timedelta, timezone

import pytest

from backend.domain.samba.proxy.fashionplus_auth import (
    KST,
    build_api_key,
    build_open_key,
    decode_api_key,
)

CUST = "012555"
FIXED = datetime(2026, 9, 1, 14, 30, 15, tzinfo=KST)
FIXED_IV = bytes(range(16))


def test_공개키는_md5_32자_hex():
    key = build_open_key(CUST, FIXED)
    assert key == "b53e81f9dc8814fbed62b60e80d693e2"
    assert len(key) == 32


def test_공개키는_시간마다_바뀐다():
    한시간뒤 = FIXED + timedelta(hours=1)
    assert build_open_key(CUST, FIXED) != build_open_key(CUST, 한시간뒤)


def test_공개키는_같은_시간대_안에서는_동일():
    같은시간 = FIXED.replace(minute=59, second=59)
    assert build_open_key(CUST, FIXED) == build_open_key(CUST, 같은시간)


def test_인증키_고정IV_알려진값():
    assert build_api_key(CUST, FIXED, FIXED_IV) == (
        "AAECAwQFBgcICQoLDA0OD2puGav0JGrrx8drcNilFteDdMmMqs8N1Z0Xc3qxMIwXIR0CdoQhyN744h//OYoX/A=="
    )


def test_UTC로_넘겨도_KST로_계산된다():
    """서버가 KST 기준이라 UTC 로 계산하면 9시간 어긋나 전 호출이 실패한다."""
    utc_same_moment = FIXED.astimezone(timezone.utc)
    assert build_api_key(CUST, utc_same_moment, FIXED_IV) == build_api_key(
        CUST, FIXED, FIXED_IV
    )


def test_naive_datetime은_KST로_간주():
    naive = datetime(2026, 9, 1, 14, 30, 15)
    assert build_open_key(CUST, naive) == build_open_key(CUST, FIXED)


def test_IV를_주지_않으면_매번_달라진다():
    assert build_api_key(CUST, FIXED) != build_api_key(CUST, FIXED)


def test_복호화하면_공개키_카렛_타임스탬프():
    api_key = build_api_key(CUST, FIXED, FIXED_IV)
    assert decode_api_key(CUST, api_key, FIXED) == (
        "b53e81f9dc8814fbed62b60e80d693e2^20260901143015"
    )


def test_빈_custcode는_거부():
    with pytest.raises(ValueError):
        build_api_key("", FIXED)
