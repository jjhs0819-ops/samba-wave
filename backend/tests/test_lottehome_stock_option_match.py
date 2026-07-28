"""롯데홈 재고 갱신 옵션 매칭 회귀 테스트.

2026-07-28 사고: 등록은 managedCode(=CorpItemNo)로 보내놓고 재고 갱신은
opt_name 으로 조회해 코오롱스포츠(색상^사이즈) 전 옵션이 미매칭 → 재고 0 전송
→ 롯데홈 품절 박제 452건. 한번 품절되면 되살리는 API 경로가 없어 삭제 후
재등록밖에 없었다.
"""

import pytest

from backend.domain.samba.plugins.markets.lottehome import (
    _EMPTY_ITEM_NO_TTL,
    _build_source_opt_map,
    _empty_item_no_cached_at,
    _item_no_cache,
    _item_no_cache_valid,
    _match_option_stock,
    _normalize_opt_key,
)


# 실측 데이터 (2026-07-28 운영 DB / 롯데홈 searchGoodsView)
KOLON_SHOES = [  # goods_no 3378291435 — CorpItemNo='블랙^230' 형식
    {"name": "230", "managedCode": "블랙^230", "stock": 99, "isSoldOut": False},
    {"name": "235", "managedCode": "블랙^235", "stock": 5, "isSoldOut": False},
    {"name": "240", "managedCode": "블랙^240", "stock": 0, "isSoldOut": True},
]
KOLON_CAP = [  # goods_no 3378291413 — 옵션명 '인디고 / XXX' vs CorpItemNo '인디고^XXX'
    {"name": "인디고 / XXX", "managedCode": "인디고^XXX", "stock": 99, "isSoldOut": False},
]
NIKE_SHOES = [  # managedCode 없음 → opt_name 이 곧 CorpItemNo
    {"name": "250", "stock": 99, "isSoldOut": False},
    {"name": "255", "stock": 99, "isSoldOut": False},
]


class TestSourceOptMap:
    def test_managed_code_는_키로_포함된다(self):
        """★핵심 회귀: managedCode 가 맵에 없으면 CorpItemNo 조회가 전부 실패한다."""
        m = _build_source_opt_map(KOLON_SHOES)
        assert m["블랙^230"] == 99
        assert m["블랙^235"] == 5

    def test_opt_name_도_함께_유지된다(self):
        m = _build_source_opt_map(KOLON_SHOES)
        assert m["230"] == 99

    def test_품절옵션은_재고0(self):
        m = _build_source_opt_map(KOLON_SHOES)
        assert m["블랙^240"] == 0

    def test_managed_code_없으면_opt_name만(self):
        m = _build_source_opt_map(NIKE_SHOES)
        assert m["250"] == 99

    def test_빈옵션_무시(self):
        assert _build_source_opt_map([{"name": "", "stock": 5}]) == {}
        assert _build_source_opt_map([]) == {}


class TestMatchOptionStock:
    def test_코오롱_신발_CorpItemNo_로_매칭(self):
        """수정 전에는 전부 None→0 이 되어 품절 박제됐다."""
        m = _build_source_opt_map(KOLON_SHOES)
        assert _match_option_stock(m, "블랙^230") == 99
        assert _match_option_stock(m, "블랙^235") == 5

    def test_코오롱_모자_구분자_다름_매칭(self):
        """소싱 '인디고 / XXX' ↔ 롯데 '인디고^XXX' — 구분자·공백만 다르다."""
        m = _build_source_opt_map(KOLON_CAP)
        assert _match_option_stock(m, "인디고^XXX") == 99

    def test_나이키_사이즈단독_매칭(self):
        m = _build_source_opt_map(NIKE_SHOES)
        assert _match_option_stock(m, "250") == 99

    def test_색상접두_폴백(self):
        """managedCode 가 없는데 롯데만 색상을 붙인 경우 사이즈 단독으로 맞춘다."""
        m = _build_source_opt_map(NIKE_SHOES)
        assert _match_option_stock(m, "블랙^250") == 99

    def test_진짜_미매칭은_None(self):
        """★매칭 실패는 품절이 아니다 — 0 이 아니라 None 을 돌려 호출부가 건너뛰게."""
        m = _build_source_opt_map(KOLON_SHOES)
        assert _match_option_stock(m, "레드^999") is None

    def test_품절옵션은_None_아니라_0(self):
        """실제 품절은 0 으로 전송돼야 한다(미매칭과 구분)."""
        m = _build_source_opt_map(KOLON_SHOES)
        assert _match_option_stock(m, "블랙^240") == 0


class TestNormalizeOptKey:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("블랙^230", "블랙/230"),
            ("인디고^XXX", "인디고 / XXX"),
            ("블랙 ^ 230", "블랙/230"),
        ],
    )
    def test_구분자_공백_차이_흡수(self, a, b):
        assert _normalize_opt_key(a) == _normalize_opt_key(b)


class TestEmptyCacheTTL:
    def setup_method(self):
        _item_no_cache.clear()
        _empty_item_no_cached_at.clear()

    teardown_method = setup_method

    def test_채워진_캐시는_항상_유효(self):
        _item_no_cache["G1"] = {"블랙^230": "1"}
        assert _item_no_cache_valid("G1") is True

    def test_미등록은_무효(self):
        assert _item_no_cache_valid("없음") is False

    def test_빈캐시는_TTL내_유효(self):
        import time

        _item_no_cache["G2"] = {}
        _empty_item_no_cached_at["G2"] = time.monotonic()
        assert _item_no_cache_valid("G2") is True

    def test_빈캐시는_TTL_지나면_무효(self):
        """★QA 승인 전 빈 ItemInfo 가 영구 캐시되면 승인 뒤에도 재고가 안 나간다."""
        import time

        _item_no_cache["G3"] = {}
        _empty_item_no_cached_at["G3"] = time.monotonic() - _EMPTY_ITEM_NO_TTL - 1
        assert _item_no_cache_valid("G3") is False
