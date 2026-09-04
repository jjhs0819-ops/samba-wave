"""썸네일 흰 여백 트림 검증.

토스 검수 반려 실측(2026-09-04, 룰루레몬 2건): "썸네일은 정해진 비율에 맞게
꽉 채워주세요. 이미지에 여백이 없도록 수정해 주세요."
원본이 이미 500x500 정사각인데 사진 자체에 좌우 41px 흰 여백이 있었다
(내용영역 417x500). 정사각 크롭만으로는 못 없앤다 — 여백을 잘라내야 한다.
"""

from PIL import Image

from backend.domain.samba.image.service import trim_white_border


def _canvas(w, h, box, color=(30, 30, 30)):
    im = Image.new("RGB", (w, h), (255, 255, 255))
    im.paste(
        Image.new("RGB", (box[2] - box[0], box[3] - box[1]), color), (box[0], box[1])
    )
    return im


def test_좌우_흰여백을_잘라낸다():
    im = _canvas(500, 500, (41, 0, 458, 500))
    out = trim_white_border(im)
    assert out.size == (417, 500)


def test_여백이_없으면_그대로_둔다():
    im = _canvas(500, 500, (0, 0, 500, 500))
    out = trim_white_border(im)
    assert out.size == (500, 500)


def test_사방_여백도_잘라낸다():
    im = _canvas(400, 400, (50, 30, 350, 370))
    assert trim_white_border(im).size == (300, 340)


def test_거의_흰색인_옅은_배경도_여백으로_본다():
    """소싱처 사진 배경은 순백(255)이 아니라 250 언저리인 경우가 많다."""
    im = Image.new("RGB", (300, 300), (252, 252, 252))
    im.paste(Image.new("RGB", (100, 300), (20, 20, 20)), (100, 0))
    assert trim_white_border(im).size == (100, 300)


def test_전부_흰색이면_원본을_유지한다():
    """다 잘라내면 이미지가 사라진다 — 안전하게 원본을 돌려준다."""
    im = Image.new("RGB", (200, 200), (255, 255, 255))
    assert trim_white_border(im).size == (200, 200)


def test_여백이_아주_얇으면_건드리지_않는다():
    """1~2px 여백까지 잘라내면 매번 재인코딩만 하고 이득이 없다."""
    im = _canvas(500, 500, (2, 2, 498, 498))
    assert trim_white_border(im).size == (500, 500)


# ── 마켓별 적용 여부 ──────────────────────────────────────────
from backend.domain.samba.shipment.dispatcher import thumbnail_trim_white  # noqa: E402


def test_토스만_썸네일_여백을_트림한다():
    """다른 마켓은 지금까지 여백으로 반려된 적이 없다 — 건드리지 않는다."""
    assert thumbnail_trim_white("toss") is True
    assert thumbnail_trim_white("ssg") is False
    assert thumbnail_trim_white("coupang") is False
