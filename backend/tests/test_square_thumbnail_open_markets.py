"""오픈마켓 대표 썸네일 1:1 정사각 강제.

2026-08-15 토스 첫 등록이 "썸네일 이미지는 1:1 정사각형 비율만 업로드 가능합니다"
로 반려됐다. 등록 API 는 성공을 응답하고 판매자센터 검수에서 반려되므로 API 결과만
보면 성공한 줄 안다. 오픈마켓 공통 요구사항이라 마켓별로 흩지 않고 전 마켓 공통
진입점(dispatch_to_market)에서 처리한다.
"""

import asyncio
from types import SimpleNamespace

import pytest

from backend.domain.samba.shipment import dispatcher


class _FakeImageService:
    """mirror_oversized_to_r2 호출 인자를 기록하고 정사각 URL을 돌려주는 스텁."""

    calls: list[dict] = []

    def __init__(self, session):
        pass

    async def mirror_oversized_to_r2(self, urls, **kwargs):
        _FakeImageService.calls.append({"urls": list(urls), **kwargs})
        return [f"{u}#sq" for u in urls], {}, set()


@pytest.fixture(autouse=True)
def _stub_image_service(monkeypatch):
    _FakeImageService.calls = []
    import backend.domain.samba.image.service as img_mod

    monkeypatch.setattr(img_mod, "ImageTransformService", _FakeImageService)
    yield


def _run(market_type, product):
    return asyncio.run(
        dispatcher._ensure_square_thumbnail(None, market_type, product)
    )


@pytest.mark.parametrize(
    "market", ["smartstore", "lotteon", "11st", "gmarket", "auction", "coupang", "toss"]
)
def test_오픈마켓은_대표이미지를_정사각으로_보정한다(market):
    out = _run(market, {"images": ["a.jpg", "b.jpg", "c.jpg"]})
    assert out["images"][0] == "a.jpg#sq"
    # 상세 이미지는 손대지 않는다 — 정사각 여백이 끼면 상세페이지가 지저분해진다
    assert out["images"][1:] == ["b.jpg", "c.jpg"]


@pytest.mark.parametrize("market", ["poison", "kream"])
def test_리셀_플랫폼은_제외된다(market):
    product = {"images": ["a.jpg", "b.jpg"]}
    out = _run(market, product)
    assert out["images"] == ["a.jpg", "b.jpg"]
    assert _FakeImageService.calls == []


def test_여백이_아니라_중앙크롭으로_호출된다():
    """토스가 여백 방식을 반려했다 — "이미지에 여백이 없도록 수정해 주세요"."""
    _run("11st", {"images": ["a.jpg"]})
    kw = _FakeImageService.calls[0]
    assert kw["min_dim"] == 1000
    assert kw["crop_square"] is True
    assert kw.get("pad_square") is not True
    # max_dim 을 1000 으로 묶으면 업스케일이 막혀 크롭 후 1000 을 못 채운다
    assert kw["max_dim"] > 1000


def test_잘림_상한이_20퍼센트다():
    _run("11st", {"images": ["a.jpg"]})
    assert _FakeImageService.calls[0]["crop_max_cut"] == 0.20


def test_쿠팡_대표이미지_전용필드도_함께_보정된다():
    out = _run("coupang", {"images": ["a.jpg"], "coupang_main_image": "main.jpg"})
    assert out["images"][0] == "a.jpg#sq"
    assert out["coupang_main_image"] == "main.jpg#sq"


def test_이미지가_없으면_그대로_통과():
    out = _run("11st", {"images": []})
    assert out["images"] == []
    assert _FakeImageService.calls == []


def test_원본_dict를_변형하지_않는다():
    product = {"images": ["a.jpg", "b.jpg"]}
    _run("11st", product)
    assert product["images"] == ["a.jpg", "b.jpg"]


def test_변환_실패해도_전송을_막지_않는다(monkeypatch):
    class _Boom(_FakeImageService):
        async def mirror_oversized_to_r2(self, urls, **kwargs):
            raise RuntimeError("R2 다운")

    import backend.domain.samba.image.service as img_mod

    monkeypatch.setattr(img_mod, "ImageTransformService", _Boom)
    out = _run("11st", {"images": ["a.jpg"]})
    assert out["images"] == ["a.jpg"]  # 원본 유지, 예외 전파 없음


def test_대상_마켓_목록이_리셀을_포함하지_않는다():
    assert "poison" not in dispatcher._SQUARE_THUMBNAIL_MARKETS
    assert "kream" not in dispatcher._SQUARE_THUMBNAIL_MARKETS
    assert dispatcher._SQUARE_THUMBNAIL_MARKETS >= {
        "smartstore",
        "lotteon",
        "11st",
        "gmarket",
        "auction",
        "coupang",
    }
