"""image_validator 단위 테스트 — HEAD 검증 + 거부 확장자 제외."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.domain.samba.image import image_validator


@pytest.mark.asyncio
async def test_empty_input_returns_empty():
    assert await image_validator.filter_alive_urls([]) == []


@pytest.mark.asyncio
async def test_gif_extension_excluded():
    """.gif는 HEAD 호출 없이 즉시 제외 (롯데ON 9999 회피)."""
    urls = [
        "https://example.com/img.gif",
        "https://example.com/IMG.GIF",
        "https://example.com/img.gif?v=1",
    ]

    with patch.object(httpx, "AsyncClient") as mock_cls:
        # AsyncClient 컨텍스트 매니저
        client_inst = AsyncMock()
        mock_cls.return_value.__aenter__.return_value = client_inst
        mock_cls.return_value.__aexit__.return_value = None

        result = await image_validator.filter_alive_urls(urls)

        assert result == []
        # .gif는 HEAD 호출 자체가 일어나지 않아야 함
        client_inst.head.assert_not_awaited()


@pytest.mark.asyncio
async def test_alive_urls_pass():
    urls = [
        "https://example.com/a.jpg",
        "https://example.com/b.png",
    ]

    async def fake_head(url, **kwargs):
        resp = AsyncMock()
        resp.status_code = 200
        return resp

    with patch.object(httpx, "AsyncClient") as mock_cls:
        client_inst = AsyncMock()
        client_inst.head = fake_head
        mock_cls.return_value.__aenter__.return_value = client_inst
        mock_cls.return_value.__aexit__.return_value = None

        result = await image_validator.filter_alive_urls(urls)

    assert result == urls


@pytest.mark.asyncio
async def test_404_excluded():
    urls = [
        "https://example.com/alive.jpg",
        "https://example.com/dead.jpg",
    ]

    async def fake_head(url, **kwargs):
        resp = AsyncMock()
        resp.status_code = 404 if "dead" in url else 200
        return resp

    with patch.object(httpx, "AsyncClient") as mock_cls:
        client_inst = AsyncMock()
        client_inst.head = fake_head
        mock_cls.return_value.__aenter__.return_value = client_inst
        mock_cls.return_value.__aexit__.return_value = None

        result = await image_validator.filter_alive_urls(urls)

    assert result == ["https://example.com/alive.jpg"]


@pytest.mark.asyncio
async def test_network_exception_excluded():
    urls = [
        "https://example.com/ok.jpg",
        "https://example.com/timeout.jpg",
    ]

    async def fake_head(url, **kwargs):
        if "timeout" in url:
            raise httpx.ConnectTimeout("boom")
        resp = AsyncMock()
        resp.status_code = 200
        return resp

    with patch.object(httpx, "AsyncClient") as mock_cls:
        client_inst = AsyncMock()
        client_inst.head = fake_head
        mock_cls.return_value.__aenter__.return_value = client_inst
        mock_cls.return_value.__aexit__.return_value = None

        result = await image_validator.filter_alive_urls(urls)

    assert result == ["https://example.com/ok.jpg"]


@pytest.mark.asyncio
async def test_referer_mapping_for_known_hosts():
    """msscdn.net → musinsa.com Referer 자동 주입."""
    captured: dict[str, str] = {}

    async def fake_head(url, **kwargs):
        captured["referer"] = kwargs["headers"]["Referer"]
        resp = AsyncMock()
        resp.status_code = 200
        return resp

    with patch.object(httpx, "AsyncClient") as mock_cls:
        client_inst = AsyncMock()
        client_inst.head = fake_head
        mock_cls.return_value.__aenter__.return_value = client_inst
        mock_cls.return_value.__aexit__.return_value = None

        await image_validator.filter_alive_urls(
            ["https://image.msscdn.net/images/goods_img/x.jpg"]
        )

    assert captured["referer"] == "https://www.musinsa.com/"


def test_resolve_referer_unknown_host_falls_back_to_origin():
    """매핑 없는 호스트는 schema://host/ 로 폴백."""
    ref = image_validator._resolve_referer("https://random.example.org/path/x.jpg")
    assert ref == "https://random.example.org/"


def test_is_rejected_extension():
    assert image_validator._is_rejected_extension("foo.gif")
    assert image_validator._is_rejected_extension("FOO.GIF")
    assert image_validator._is_rejected_extension("https://x/y.gif?v=1")
    assert not image_validator._is_rejected_extension("foo.jpg")
    assert not image_validator._is_rejected_extension("foo.png")
