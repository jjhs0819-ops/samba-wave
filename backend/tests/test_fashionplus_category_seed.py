"""패션플러스 카테고리 시드 부재 확인.

패플 공식 카테고리 코드표를 아직 못 받았다. 코드표 없이 지어낸 시드는
① 시드 서비스가 병합만 하고 삭제하지 않아 한 번 돌면 DB 에 영구 잔존하고
② 한글 경로라 전송 단계의 숫자 게이트에 걸려 어차피 쓸 수 없다.
따라서 코드표 수령 전까지 시드를 넣지 않는 것이 규칙이며, 이 테스트가
그 규칙을 강제한다 — 누군가 창작 시드를 다시 넣으면 여기서 깨진다.
"""

from backend.domain.samba.category import rules


def test_패션플러스_시드는_코드표_수령_전까지_비워둔다():
    assert "fashionplus" not in rules.MARKET_CATEGORIES


def test_기존_마켓_시드는_그대로():
    """시드 제거가 기존 마켓을 건드리지 않았는지 확인."""
    assert "poison" in rules.MARKET_CATEGORIES
    assert "playauto" in rules.MARKET_CATEGORIES
