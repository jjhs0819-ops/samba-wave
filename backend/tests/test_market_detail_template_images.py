"""마켓별 상세 템플릿의 gallery_include_sub 가 무시되던 문제.

_build_detail_html 은 상품 하나당 두 번 호출된다 —
  1) 정책 기본 템플릿으로 한 번 (service.py:1466)
  2) 마켓별 템플릿(market_detail_templates[market_type])으로 한 번 (service.py:2282)

이 함수는 product["images"] 를 gallery_include_sub 에 맞춰 잘라 덮어쓰는데,
두 번째 호출이 이미 잘린 목록을 소스로 다시 자르면 마켓별 설정이 통째로 무시된다.

2026-08-15 토스 첫 등록 실패가 정확히 이 경로였다:
  기본 템플릿(false) → 8장이 1장으로 축소
  토스 전용 템플릿(true) 적용 → 소스가 이미 1장이라 그대로 1장
  토스는 상세를 DESCRIPTION 이미지로만 받으므로 상세 0장 → 등록 거부
"""

from backend.domain.samba.shipment import service as svc_mod


def _trim(product: dict, gallery_include_sub: bool) -> None:
    """_build_detail_html 의 이미지 소스 선택·축소 부분만 떼어낸 것.

    실제 함수는 DB 템플릿 조회가 필요해 단위 테스트에서 그대로 부르기 어렵다.
    회귀 감시 대상은 '원본을 보존하고 그걸 소스로 쓴다'는 규칙 자체다.
    """
    if "_gallery_source_images" not in product:
        product["_gallery_source_images"] = list(product.get("images") or [])
    images = svc_mod._usable_image_urls(product["_gallery_source_images"])
    if images:
        product["images"] = images if gallery_include_sub else images[:1]


def _sample() -> dict:
    return {
        "images": [f"https://cdn.example.com/{i}.jpg" for i in range(8)],
    }


def test_마켓별_템플릿이_기본템플릿보다_많은_이미지를_쓸_수_있다():
    p = _sample()
    _trim(p, gallery_include_sub=False)  # 1) 정책 기본 템플릿
    assert len(p["images"]) == 1
    _trim(p, gallery_include_sub=True)  # 2) 마켓별 템플릿
    assert len(p["images"]) == 8, "마켓별 템플릿의 gallery_include_sub 가 무시됐다"


def test_반대_방향도_동작한다():
    p = _sample()
    _trim(p, gallery_include_sub=True)
    assert len(p["images"]) == 8
    _trim(p, gallery_include_sub=False)
    assert len(p["images"]) == 1


def test_원본이_비면_그대로_빈다():
    p = {"images": []}
    _trim(p, gallery_include_sub=True)
    assert p["images"] == []


def test_원본은_두번째_호출에도_보존된다():
    p = _sample()
    original = list(p["images"])
    _trim(p, gallery_include_sub=False)
    _trim(p, gallery_include_sub=False)
    assert p["_gallery_source_images"] == original
