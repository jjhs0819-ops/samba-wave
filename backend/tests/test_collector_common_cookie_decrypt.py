"""collector_common.get_musinsa_cookie가 암호화된 DB 값을 복호화해 반환하는지 검증.

배경: SambaSettings.musinsa_cookie는 _set_setting을 통해 Fernet 암호화 상태로 저장된다
(crypto.ENCRYPTED_KEYS). 그러나 collector_common.get_musinsa_cookie는 ORM으로 row.value를
직접 반환하여 암호화된 토큰('gAAAAA...')을 그대로 무신사 API에 전달, 무신사가 인증 안 된
요청으로 인식해 LV.5 등급 할인이 0%로 응답되는 문제(2026-05-01 진단)를 발생시켰다.

본 테스트는 함수가 _get_setting과 동일하게 자동 복호화를 수행하는지를 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_get_musinsa_cookie_returns_decrypted_value():
    """DB에 Fernet 암호화 상태로 저장된 musinsa_cookie를 복호화해 평문으로 반환해야 한다."""
    from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie
    from backend.utils.crypto import encrypt_value

    plain = "PCID=abc123; _gid=GA1.2.xyz; auth_token=lv5_silver_session"
    encrypted = encrypt_value(plain)

    # ORM/_get_setting 어느 경로로 구현돼도 같은 결과를 주도록 양쪽 mock을 둔다.
    # 1) ORM 경로 — session.execute() → result.scalar_one_or_none() → row.value
    mock_row = MagicMock()
    mock_row.value = encrypted
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=mock_row)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    # 2) Repository 경로 — find_by_async/get_async 응답도 같은 row 반환
    mock_session.exec = AsyncMock(return_value=mock_result)

    cookie = await get_musinsa_cookie(mock_session)

    assert cookie == plain, (
        "get_musinsa_cookie는 Fernet 암호화 토큰을 복호화해 평문 쿠키를 반환해야 한다.\n"
        f"  반환값 시작 12자: {cookie[:12]!r}\n"
        f"  기대 시작 12자: {plain[:12]!r}\n"
        f"  암호화된 형태(잘못된 값) 시작: {encrypted[:12]!r}"
    )


@pytest.mark.asyncio
async def test_get_musinsa_cookie_returns_empty_string_when_missing():
    """저장된 쿠키가 없으면 빈 문자열을 반환해야 한다 (기존 호출지점 호환)."""
    from backend.api.v1.routers.samba.collector_common import get_musinsa_cookie

    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.exec = AsyncMock(return_value=mock_result)

    cookie = await get_musinsa_cookie(mock_session)
    assert cookie == "", f"누락 시 빈 문자열이어야 함. 받은 값: {cookie!r}"
