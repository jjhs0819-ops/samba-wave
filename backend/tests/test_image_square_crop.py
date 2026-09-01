"""정사각 변환 — 중앙 크롭 / 여백 패딩 픽셀 동작.

mirror_oversized_to_r2 는 R2·네트워크가 필요해 그대로 부를 수 없다. 여기서는
그 안의 정사각 변환 규칙만 같은 식으로 재현해 회귀를 감시한다.

배경: 2026-08-15 토스가 여백 방식을 반려했다 —
  "썸네일은 정해진 비율에 맞게 꽉 채워주세요. 이미지에 여백이 없도록 수정해 주세요."
무신사 원본은 정사각이 아니라(무작위 60건 중 5:6 이 65%) 크롭이 필요하다.
"""

import pytest
from PIL import Image


def _square(img: Image.Image, crop_square=False, pad_square=False, crop_max_cut=0.20):
    """service.mirror_oversized_to_r2 의 정사각 변환부와 동일한 규칙."""
    did_crop = False
    if crop_square and img.size[0] != img.size[1]:
        w, h = img.size
        side = min(w, h)
        cut = (max(w, h) - side) / max(w, h)
        if cut <= crop_max_cut:
            l, t = (w - side) // 2, (h - side) // 2
            img = img.crop((l, t, l + side, t + side))
            did_crop = True
    if (pad_square or (crop_square and not did_crop)) and img.size[0] != img.size[1]:
        w, h = img.size
        side = max(w, h)
        canvas = Image.new("RGB", (side, side), (255, 255, 255))
        canvas.paste(img, ((side - w) // 2, (side - h) // 2))
        img = canvas
    return img, did_crop


def _img(w, h, color=(10, 20, 30)):
    return Image.new("RGB", (w, h), color)


def test_5대6_원본은_크롭된다():
    """무신사 표준 비율 — 잘림 16.7% 로 상한 20% 안쪽."""
    out, cropped = _square(_img(1000, 1200), crop_square=True)
    assert out.size == (1000, 1000)
    assert cropped is True


def test_크롭_결과에_흰_여백이_없다():
    out, _ = _square(_img(1000, 1200, color=(10, 20, 30)), crop_square=True)
    colors = out.getcolors(maxcolors=10) or []
    assert colors == [(1000 * 1000, (10, 20, 30))], "여백(흰색)이 섞였다"


def test_이미_정사각이면_그대로():
    out, cropped = _square(_img(1000, 1000), crop_square=True)
    assert out.size == (1000, 1000)
    assert cropped is False


def test_잘림이_상한을_넘으면_크롭하지_않고_여백처리():
    """500x750(33% 잘림) 같은 극단 비율 — 제품이 크게 잘려나가는 것을 막는다."""
    out, cropped = _square(_img(1000, 1500), crop_square=True)
    assert cropped is False
    assert out.size == (1500, 1500)  # 정사각은 만들되 여백으로


def test_상한_경계값은_크롭한다():
    # 1000x1250 → 잘림 정확히 20%
    out, cropped = _square(_img(1000, 1250), crop_square=True)
    assert cropped is True
    assert out.size == (1000, 1000)


def test_가로형도_동작한다():
    out, cropped = _square(_img(1200, 1000), crop_square=True)
    assert cropped is True
    assert out.size == (1000, 1000)


def test_패딩_방식은_기존대로_유지된다():
    """롯데홈쇼핑은 여백 방식으로 정상 운영 중 — 회귀 금지."""
    out, cropped = _square(_img(1000, 1200), pad_square=True)
    assert cropped is False
    assert out.size == (1200, 1200)


@pytest.mark.parametrize(
    ("w", "h", "should_crop"),
    [
        (500, 600, True),  # 5:6  — 무신사 65%
        (500, 500, False),  # 1:1  — 무신사 32%, 변환 불필요
        (500, 667, False),  # 25% 잘림 — 상한 초과
        (500, 750, False),  # 33% 잘림 — 상한 초과
    ],
)
def test_무신사_실측_비율별_판정(w, h, should_crop):
    _, cropped = _square(_img(w, h), crop_square=True)
    assert cropped is should_crop
