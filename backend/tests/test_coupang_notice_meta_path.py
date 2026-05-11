"""쿠팡 등록 고시정보 메타 API path 회귀 테스트 (2026-05 버그).

이전 버그: 잘못된 path `/meta/notice-categories/{id}` → 404 → 정적 매핑 폴백 →
스포츠/레저 카테고리에 '의류' notice 전송 → 쿠팡 거부.

수정: 공식 path `/meta/category-related-metas/display-category-codes/{id}` 사용.
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

from unittest.mock import AsyncMock, patch  # noqa: E402

import pytest  # noqa: E402


@pytest.mark.asyncio
async def test_get_notice_categories_uses_official_path():
    from backend.domain.samba.proxy.coupang import CoupangClient

    CoupangClient._notice_meta_cache.clear()
    client = CoupangClient("ak", "sk", "A01616738")
    expected = {"data": {"noticeCategories": []}}

    with patch.object(
        CoupangClient, "_call_api", new=AsyncMock(return_value=expected)
    ) as mock_call:
        result = await client.get_notice_categories("12345")

    assert result == expected
    mock_call.assert_awaited_once()
    args, _kwargs = mock_call.call_args
    method, path = args[0], args[1]
    assert method == "GET"
    assert (
        path
        == "/v2/providers/seller_api/apis/api/v1/marketplace/meta/category-related-metas/display-category-codes/12345"
    )
    assert "/notice-categories/" not in path  # 옛 잘못된 path 재발 방지


@pytest.mark.asyncio
async def test_get_notice_categories_caches_result():
    from backend.domain.samba.proxy.coupang import CoupangClient

    CoupangClient._notice_meta_cache.clear()
    client = CoupangClient("ak", "sk", "A01616738")
    expected = {"data": {"noticeCategories": [{"noticeCategoryName": "의류"}]}}

    with patch.object(
        CoupangClient, "_call_api", new=AsyncMock(return_value=expected)
    ) as mock_call:
        r1 = await client.get_notice_categories("99999")
        r2 = await client.get_notice_categories("99999")

    assert r1 is expected
    assert r2 is expected
    assert mock_call.await_count == 1
