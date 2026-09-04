"""토스 상세 이미지 최소 가로(600) 보정 검증.

라이브 실측(2026-09-04 파일럿 17건): 토스 검수가 전량 반려됐고 사유가
"상세 이미지 가로 크기가 최소 600 이상이어야 합니다" 였다. 무신사 원본이
가로 500 이라 그대로 나가면 검수를 통과하지 못한다. 삼바는 대표 썸네일만
1000 정사각으로 보정하고 상세 이미지는 원본 URL 을 그대로 쓴다.
"""

import pytest

from backend.domain.samba.shipment.service import (
    detail_image_min_width,
    ensure_detail_image_min_width,
)

IMAGES = ["https://img/a_500.jpg", "https://img/b_500.jpg"]


class FakeImageService:
    def __init__(self, result=None, raises=False):
        self.calls = []
        self._result = (
            result
            if result is not None
            else ["https://cdn/a_600.jpg", "https://cdn/b_600.jpg"]
        )
        self._raises = raises

    async def mirror_oversized_to_r2(self, urls, **kwargs):
        self.calls.append((list(urls), kwargs))
        if self._raises:
            raise RuntimeError("미러 실패")
        return self._result, None, None


def test_토스만_상세이미지_최소가로를_요구한다():
    assert detail_image_min_width("toss") == 600
    assert detail_image_min_width("ssg") == 0
    assert detail_image_min_width("coupang") == 0


@pytest.mark.asyncio
async def test_토스는_상세이미지를_미러본으로_교체한다():
    svc = FakeImageService()
    product = {"images": list(IMAGES)}

    result = await ensure_detail_image_min_width(svc, "toss", product)

    assert result["images"] == ["https://cdn/a_600.jpg", "https://cdn/b_600.jpg"]
    urls, kwargs = svc.calls[0]
    assert urls == IMAGES
    assert kwargs["min_dim"] == 600
    # 상세는 잘라내면 안 된다 — 대표 썸네일 정사각 보정과 다른 처리다
    assert kwargs.get("crop_square") is False


@pytest.mark.asyncio
async def test_다른_마켓은_이미지를_건드리지_않는다():
    svc = FakeImageService()
    product = {"images": list(IMAGES)}

    result = await ensure_detail_image_min_width(svc, "ssg", product)

    assert result["images"] == IMAGES
    assert svc.calls == []


@pytest.mark.asyncio
async def test_미러가_실패하면_원본을_유지한다():
    """이미지 보정 실패로 전송 자체가 죽으면 안 된다."""
    svc = FakeImageService(raises=True)
    product = {"images": list(IMAGES)}

    result = await ensure_detail_image_min_width(svc, "toss", product)

    assert result["images"] == IMAGES


@pytest.mark.asyncio
async def test_이미지가_없으면_그대로_반환한다():
    svc = FakeImageService()
    assert await ensure_detail_image_min_width(svc, "toss", {"images": []}) == {
        "images": []
    }
    assert svc.calls == []
