"""더현대Hi 잡워커 수집 어댑터(search/get_detail) 회귀 테스트.

배경: 잡워커 _collect_direct_api 는 client.search(keyword, max_count, **kwargs)
→ {"products": [...], "total": N} 인터페이스를 요구한다 (단일 페이지
search_products 와 다름). 그룹 URL 파싱 폴백과 페이징 집계를 검증한다.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import TheHyundaiSourcingClient


def _fake_items(start: int, n: int) -> list[dict]:
    return [
        {"site_product_id": f"40B{start + i:07d}", "name": f"상품{start + i}"}
        for i in range(n)
    ]


class _PagedClient(TheHyundaiSourcingClient):
    """search_products 를 페이지 응답 시뮬레이션으로 대체."""

    def __init__(self, pages: dict[int, list[dict]]):
        super().__init__()
        self._pages = pages
        self.calls: list[dict] = []

    async def search_products(self, keyword: str, **filters):
        self.calls.append({"keyword": keyword, **filters})
        return self._pages.get(int(filters.get("page") or 1), [])


class TestSearchAdapter:
    async def test_single_page(self) -> None:
        client = _PagedClient({1: _fake_items(1, 10)})
        result = await client.search("나이키", max_count=100)
        assert result["total"] == 10
        assert len(result["products"]) == 10
        assert result["products"][0]["site_product_id"] == "40B0000001"

    async def test_pagination_until_max_count(self) -> None:
        pages = {1: _fake_items(1, 36), 2: _fake_items(37, 36), 3: _fake_items(73, 36)}
        client = _PagedClient(pages)
        result = await client.search("나이키", max_count=50)
        assert result["total"] == 50
        # 2페이지에서 max_count 도달 → 3페이지 미호출
        assert max(c["page"] for c in client.calls) == 2

    async def test_stops_on_empty_page(self) -> None:
        client = _PagedClient({1: _fake_items(1, 36), 2: []})
        result = await client.search("나이키", max_count=999)
        assert result["total"] == 36

    async def test_duplicate_page_terminates(self) -> None:
        # 사이트가 마지막 페이지를 반복 반환하는 경우 무한루프 방지
        same = _fake_items(1, 36)
        client = _PagedClient({1: same, 2: same, 3: same})
        result = await client.search("나이키", max_count=999)
        assert result["total"] == 36
        assert max(c["page"] for c in client.calls) == 2  # 중복 감지 즉시 종료

    async def test_group_url_parsing_fallback(self) -> None:
        # 워커 외 호출자가 그룹 URL 원문을 넘겨도 q/flBrand/flCate 추출
        client = _PagedClient({1: _fake_items(1, 5)})
        url = (
            "https://hi.thehyundai.com/search?q=%EB%82%98%EC%9D%B4%ED%82%A4"
            "&flBrand=101047&flCate=400004&includeSoldOut=1"
        )
        result = await client.search(url, max_count=10)
        assert result["total"] == 5
        call = client.calls[0]
        assert call["keyword"] == "나이키"
        assert call["flBrand"] == "101047"
        assert call["flCate"] == "400004"
        assert call["includeSoldOut"] is True

    async def test_worker_search_kwargs_passthrough(self) -> None:
        # 워커 _search_kwargs 의 flBrand/flCate 채택 + 타 소싱처 키 무시
        client = _PagedClient({1: _fake_items(1, 3)})
        result = await client.search(
            "나이키",
            max_count=10,
            flCate="400004",
            category1Id="123",  # 패션플러스용 키 — 무시돼야 함
            brand_name="나이키",  # 패션플러스용 키 — 무시돼야 함
        )
        assert result["total"] == 3
        call = client.calls[0]
        assert call["flCate"] == "400004"
        assert "category1Id" not in call
        assert "brand_name" not in call


class TestWorkerSnakeCaseKeys:
    """잡워커 수집 루프는 sale_price/original_price/cost(snake) 를 읽음 —
    정규화·상세가 camelCase 만 내면 판매가 0·원가 100,000 폴백 사고 발생 (실측 버그)."""

    def test_search_item_has_snake_price_keys(self) -> None:
        raw = {
            "slitmCd": "40B0696270",
            "slitmNm": "런 디파이",
            "sellPrc": 55300,
            "bnftPrc": 42590,
            "freeDlvYn": "1",
        }
        n = TheHyundaiSourcingClient._normalize_search_item(raw)
        assert n["sale_price"] == 42590
        assert n["original_price"] == 55300
        assert n["cost"] == 42590  # 상세 누락 시 폴백용 표시가
        assert n["free_shipping"] is True
        # 원문링크 — 잡워커가 source_url(snake)로 읽음 (미제공 시 링크 빈값 사고)
        assert n["source_url"] == "https://hi.thehyundai.com/product/40B0696270"


class TestMndrFields:
    """필수고시(mndrInfoList) → 부가필드 매핑. 카테고리별 고시양식이 달라
    itstCd 코드가 아닌 itstTitl 키워드 매칭 사용."""

    def test_extract_full(self) -> None:
        mndr = {
            "brndBcdVal": "HQ7901001",
            "mndrInfoList": [
                {"itstTitl": "제품 주소재", "itstCntn": "겉감 : 합성가죽"},
                {"itstTitl": "색상", "itstCntn": "블랙/앤트러사이트"},
                {"itstTitl": "치수", "itstCntn": "230-260"},
                {"itstTitl": "제조자(수입자명)", "itstCntn": "(유)나이키코리아"},
                {"itstTitl": "제조국", "itstCntn": "베트남 외"},
                {"itstTitl": "취급시 주의사항", "itstCntn": "단독 세탁"},
                {"itstTitl": "품질보증기준", "itstCntn": "공정위 고시 기준"},
            ],
        }
        out = TheHyundaiSourcingClient._extract_mndr_fields(mndr)
        assert out["material"] == "겉감 : 합성가죽"
        assert out["color"] == "블랙/앤트러사이트"
        assert out["manufacturer"] == "(유)나이키코리아"
        assert out["origin"] == "베트남 외"
        assert out["care_instructions"] == "단독 세탁"
        assert out["quality_guarantee"] == "공정위 고시 기준"
        assert out["style_code"] == "HQ7901001"
        assert "치수" not in str(out)  # 미매핑 항목은 제외

    def test_extract_none_and_empty(self) -> None:
        assert TheHyundaiSourcingClient._extract_mndr_fields(None) == {}
        assert TheHyundaiSourcingClient._extract_mndr_fields({}) == {}
        # 내용 빈 행은 스킵
        out = TheHyundaiSourcingClient._extract_mndr_fields(
            {"mndrInfoList": [{"itstTitl": "색상", "itstCntn": ""}]}
        )
        assert "color" not in out

    def test_first_match_wins(self) -> None:
        out = TheHyundaiSourcingClient._extract_mndr_fields(
            {
                "mndrInfoList": [
                    {"itstTitl": "소재", "itstCntn": "면 100%"},
                    {"itstTitl": "겉감 소재", "itstCntn": "폴리 100%"},
                ]
            }
        )
        assert out["material"] == "면 100%"


class TestInferSex:
    def test_priority_and_values(self) -> None:
        f = TheHyundaiSourcingClient._infer_sex
        assert f("레저/스포츠 > 스포츠 슈즈 > 여성스포츠화", "V5 RNR (여성)") == "여성용"
        assert f("레저/스포츠 > 일반스포츠 > 남성/공용의류", "카고 쇼츠") == "남성용"
        # 아동이 성별보다 우선 (유아동 카테고리에 여아/남아 혼재)
        assert f("유아동/패밀리 > 토들러패션", "여아 티셔츠") == "아동/주니어공용"
        assert f("", "나이키 V5 RNR (리틀키즈)") == "아동/주니어공용"
        # '우먼'의 '먼' 오탐 방지 — 여성이 남성보다 먼저
        assert f("", "우먼스 에어포스") == "여성용"
        assert f("", "에어맥스 슬라이드") == ""  # 미판정 → 워커 기본값


class TestGetDetailAlias:
    async def test_alias_delegates(self) -> None:
        client = TheHyundaiSourcingClient()
        captured = {}

        async def _fake_detail(pid):
            captured["pid"] = pid
            return {"site_product_id": pid}

        client.get_product_detail = _fake_detail  # type: ignore[method-assign]
        detail = await client.get_detail("40B0696270", shared_client=None)
        assert captured["pid"] == "40B0696270"
        assert detail["site_product_id"] == "40B0696270"
