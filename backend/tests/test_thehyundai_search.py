"""더현대Hi 검색 응답 파싱 회귀 테스트.

배경: search_products()가 더현대 searchResult 응답의 productInfoList[] 를
삼바 표준 dict 스키마로 정규화해야 함. 매핑 표는 plan v5 참조.

기준 상품: 40B0696270 (나이키 런 디파이 여성) — Chrome 1차 조사 raw JSON.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import (
    BASE_URL,
    TheHyundaiSourcingClient,
    _SORT_MAP,
)


SAMPLE_SEARCH_ITEM = {
    "bnftPrc": 42590,
    "bnftPrcRate": 22,
    "expsBrndNm": "나이키",
    "operBrndNm": "나이키",
    "operEngBrndNm": "NIKE",
    "expsEngBrndNm": "NIKE",
    "operBrndCd": "101047",
    "itemImageUrl": "/7/2/6/69/B0/40B0696270_0.jpg",
    "sellPrc": 55300,
    "slitmNm": "런 디파이 (여성) NIKE HM9593-107",
    "slitmCd": "40B0696270",
    "catLNm": "레저/스포츠",
    "catLcd": "400004",
    "itemDcsfCd": "30020101",
    "itemLcsfNm": "스포츠 슈즈",
    "itemMcsfNm": "여성스포츠화",
    "itemScsfNm": "러닝/조깅/워킹화",
    "freeDlvYn": "1",
    "giftNm": "",
    "giftYn": "0",
    "hdptNm": "판교점",
    "openMktItemYn": "0",
    "hdmalRsvSellYn": "0",
    "ostkYn": "0",
    "itemAvrgEvalScrg": 5,
    "itemEvalCnt": 1,
    "salePct": 22,
}


class TestNormalizeSearchItem:
    def test_core_field_mapping(self) -> None:
        out = TheHyundaiSourcingClient._normalize_search_item(SAMPLE_SEARCH_ITEM)
        assert out["siteProductId"] == "40B0696270"
        assert out["site_product_id"] == "40B0696270"
        assert out["name"] == "런 디파이 (여성) NIKE HM9593-107"
        assert out["brand"] == "나이키"  # expsBrndNm 우선
        assert out["brandCode"] == "101047"  # canonical key = operBrndCd
        assert out["originalPrice"] == 55300  # sellPrc
        assert out["salePrice"] == 42590  # bnftPrc (할인 후)
        assert out["discountRate"] == 22
        assert out["isSoldOut"] is False
        assert out["sourceUrl"] == f"{BASE_URL}/product/40B0696270"
        assert out["categoryCode"] == "400004"
        assert out["category"] == "레저/스포츠 > 스포츠 슈즈 > 여성스포츠화 > 러닝/조깅/워킹화"

    def test_image_url_prefix(self) -> None:
        out = TheHyundaiSourcingClient._normalize_search_item(SAMPLE_SEARCH_ITEM)
        # itemImageUrl 이 절대 URL 로 변환 + RS 리사이즈(기본 600 → 1000) 부여
        assert out["imageUrl"].startswith("https://image.thehyundai.com")
        assert out["imageUrl"].endswith("40B0696270_0.jpg?RS=1000x1000")

    def test_sold_out_flag(self) -> None:
        item = {**SAMPLE_SEARCH_ITEM, "ostkYn": "1"}
        out = TheHyundaiSourcingClient._normalize_search_item(item)
        assert out["isSoldOut"] is True

    def test_brand_fallback_to_oper_brnd_nm(self) -> None:
        # expsBrndNm 비어있을 때 operBrndNm 로 폴백
        item = {**SAMPLE_SEARCH_ITEM, "expsBrndNm": "", "operBrndNm": "라프리마"}
        out = TheHyundaiSourcingClient._normalize_search_item(item)
        assert out["brand"] == "라프리마"

    def test_brand_code_always_oper_brnd_cd(self) -> None:
        # canonical key는 expsBrndNm 폴백 여부와 무관하게 operBrndCd
        item = {**SAMPLE_SEARCH_ITEM, "expsBrndNm": "", "operBrndCd": "146988"}
        out = TheHyundaiSourcingClient._normalize_search_item(item)
        assert out["brandCode"] == "146988"

    def test_open_market_flag(self) -> None:
        item = {**SAMPLE_SEARCH_ITEM, "openMktItemYn": "1"}
        out = TheHyundaiSourcingClient._normalize_search_item(item)
        assert out["openMarket"] is True

    def test_reservation_flag(self) -> None:
        item = {**SAMPLE_SEARCH_ITEM, "hdmalRsvSellYn": "1"}
        out = TheHyundaiSourcingClient._normalize_search_item(item)
        assert out["reservation"] is True


class TestSortMapping:
    def test_default_popular_returns_empty(self) -> None:
        # POPULAR (기본) → 빈 문자열 → 파라미터 미전송
        assert TheHyundaiSourcingClient._map_sort("POPULAR") == ""

    def test_recent_to_dtm(self) -> None:
        assert TheHyundaiSourcingClient._map_sort("RECENT") == "dtm"

    def test_low_price_to_sellA(self) -> None:
        assert TheHyundaiSourcingClient._map_sort("LOW_PRICE") == "sellA"

    def test_high_price_to_sellD(self) -> None:
        assert TheHyundaiSourcingClient._map_sort("HIGH_PRICE") == "sellD"

    def test_review_to_eval(self) -> None:
        assert TheHyundaiSourcingClient._map_sort("REVIEW") == "eval"

    def test_unknown_passes_through(self) -> None:
        # 알 수 없는 정렬은 그대로 통과 (사이트가 인식하면 동작, 아니면 무시)
        assert TheHyundaiSourcingClient._map_sort("foo") == "foo"

    def test_empty_returns_empty(self) -> None:
        assert TheHyundaiSourcingClient._map_sort("") == ""

    def test_all_keys_mapped(self) -> None:
        # _SORT_MAP 키 전수 호환 확인
        for k, v in _SORT_MAP.items():
            assert TheHyundaiSourcingClient._map_sort(k) == v


class TestExtractSlitmCd:
    def test_raw_id(self) -> None:
        assert TheHyundaiSourcingClient._extract_slitm_cd("40B0696270") == "40B0696270"

    def test_product_url(self) -> None:
        assert (
            TheHyundaiSourcingClient._extract_slitm_cd(
                "https://hi.thehyundai.com/product/40B0696270"
            )
            == "40B0696270"
        )

    def test_lowercase_input_uppercased(self) -> None:
        assert TheHyundaiSourcingClient._extract_slitm_cd("40b0696270") == "40B0696270"

    def test_url_with_query_params(self) -> None:
        assert (
            TheHyundaiSourcingClient._extract_slitm_cd(
                "https://hi.thehyundai.com/product/40B0696270?foo=bar"
            )
            == "40B0696270"
        )

    def test_empty_returns_empty(self) -> None:
        assert TheHyundaiSourcingClient._extract_slitm_cd("") == ""
        assert TheHyundaiSourcingClient._extract_slitm_cd(None) == ""

    def test_invalid_length_returns_empty(self) -> None:
        assert TheHyundaiSourcingClient._extract_slitm_cd("short") == ""
        assert TheHyundaiSourcingClient._extract_slitm_cd("12345") == ""

    def test_all_digit_id(self) -> None:
        # 2246940700 같은 전 숫자 케이스도 지원
        assert TheHyundaiSourcingClient._extract_slitm_cd("2246940700") == "2246940700"
