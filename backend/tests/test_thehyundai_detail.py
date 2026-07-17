"""더현대Hi 상세 응답 + 옵션 정규화 + new_cost 공식 회귀 테스트.

핵심 검증:
1. _normalize_options(): 단일/다차원/옵션없음 3가지 케이스
2. _compute_new_cost(): aplyDcPrc − Σ(step8a.dcAmt) − Σ(step8b.dcAmt) — Chrome 3-A G섹션 공식
3. 명품/예약판매 등 step8a/b 빈 배열 케이스 자동 처리

Chrome 3-A G섹션 검증 케이스:
- 나이키 40B0696270: aplyDcPrc=45350, step8b=3170 → new_cost=42180 (화면 최대혜택가 일치)
- 구찌 60B1015785: aplyDcPrc=823500, step8b 없음 → new_cost=823500
- 예약 40B1160122: aplyDcPrc=50000, step8 둘 다 없음 → new_cost=50000
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.thehyundai_sourcing import TheHyundaiSourcingClient


# ──────────────────────────────────────────────────────────────
# fixtures — Chrome 2차 D섹션 + 3차 G섹션 raw 발췌
# ──────────────────────────────────────────────────────────────

# 케이스 A: 단일 차원 옵션 (사이즈만) — 40B0696270
DETAIL_SINGLE_DIM = {
    "slitmCd": "40B0696270",
    "slitmNm": "런 디파이 (여성) NIKE HM9593-107",
    "prcInfo": {
        "csmPrc": 0,
        "sellPrc": 55300,
        "dcPrc": 45350,
        "dcRate": 18,
        "maxDcPrc": 45350,
    },
    "uitmCombYn": "0",
    "uitmAttrTypeList": [{"uitmAttrTypeNm": "사이즈", "uitmAttrTypeSeq": 1}],
    "uitmAttrList": [
        {
            "uitmAttrTypeNm": "사이즈", "uitmAttrTypeSeq": 1,
            "uitmCd": "00001", "uitmNm": "230", "uitmTotNm": "230",
            "uitmDcPrc": 45350, "uitmSellGbcd": "11",  # 품절
            "uitmSeq": 1, "sellPossQty": 0,
        },
        {
            "uitmAttrTypeNm": "사이즈", "uitmAttrTypeSeq": 1,
            "uitmCd": "00002", "uitmNm": "235", "uitmTotNm": "235",
            "uitmDcPrc": 45350, "uitmSellGbcd": "00",
            "uitmSeq": 2, "sellPossQty": 4,
        },
        {
            "uitmAttrTypeNm": "사이즈", "uitmAttrTypeSeq": 1,
            "uitmCd": "00003", "uitmNm": "240", "uitmTotNm": "240",
            "uitmDcPrc": 45350, "uitmSellGbcd": "00",
            "uitmSeq": 3, "sellPossQty": 12,
        },
    ],
    "ostkYn": "0",
    "sellPossQty": 16,
}

# 케이스 B: 다차원 옵션 (선택/색상/사이즈) — 40B1027064
DETAIL_MULTI_DIM = {
    "slitmCd": "40B1027064",
    "prcInfo": {"sellPrc": 100000, "dcPrc": 80000, "maxDcPrc": 80000},
    "uitmCombYn": "1",
    "uitmAttrTypeList": [
        {"uitmAttrTypeNm": "선택(품번)/색상", "uitmAttrTypeSeq": 1},
        {"uitmAttrTypeNm": "사이즈", "uitmAttrTypeSeq": 2},
    ],
    # 다차원에서 uitmAttrList는 1차원만 열거. uitmCd=null
    "uitmAttrList": [
        {"uitmAttrTypeNm": "선택(품번)/색상", "uitmCd": None, "uitmSellGbcd": None,
         "uitmNm": "선택1(1010)/DOR"},
        {"uitmAttrTypeNm": "선택(품번)/색상", "uitmCd": None, "uitmSellGbcd": None,
         "uitmNm": "선택2(1020)/LMT"},
    ],
    "ostkYn": "0",
}
STCK_LIST_MULTI = [
    {"uitmCd": "00016", "uitmTotNm": "선택1(1010)/DOR/XXL(110)", "sellPossQty": 2},
    {"uitmCd": "00045", "uitmTotNm": "선택2(1020)/LMT/M(95)", "sellPossQty": 3},
    {"uitmCd": "00046", "uitmTotNm": "선택2(1020)/LMT/L(100)", "sellPossQty": 4},
]

# 케이스 C: 옵션 없는 단순 상품 — 40B1065628
DETAIL_NO_OPTIONS = {
    "slitmCd": "40B1065628",
    "prcInfo": {"sellPrc": 30000, "dcPrc": 30000, "maxDcPrc": 30000},
    "uitmCombYn": "0",
    "uitmAttrTypeList": None,
    "uitmAttrList": None,
    "ostkYn": "0",
    "sellPossQty": 61,
}


# ──────────────────────────────────────────────────────────────
# G섹션 maxBnftList fixtures
# ──────────────────────────────────────────────────────────────

# 나이키 40B0696270 — step8b 있음 (현대백화점카드 7% 즉시할인)
MAX_BNFT_NIKE = {
    "aplyDcPrc": 45350,
    "sellPrc": 55300,
    "slitmCd": "40B0696270",
    "slitmRealMgrt": 100,
    "step1BnftInfo": {"dcAmt": 0, "prmoNm": None},
    "step2BnftList": [
        # "더할인" 쿠폰 — 보유자 한정 (화면 최대혜택가에서 의도적 제외)
        {"copnNm": "더할인", "dcAmt": 9950, "famtFxrtVal": 18, "chocYn": "1"},
    ],
    "step3BnftList": [],
    "step4BnftList": [],
    "step5BnftList": [],
    "step7BnftInfo": {"hpntBlnc": 0, "cdpstBlnc": 0},
    "step8aBnftList": [],
    "step8bBnftList": [
        # 현대백화점카드 즉시할인 7%
        {"prmoNm": "현대백화점카드 즉시할인", "dcAmt": 3170, "famtFxrtVal": 7,
         "crdcCd": "K", "crdcNm": "현대백화점카드"},
    ],
}

# 구찌 60B1015785 — step8b 없음 (명품은 카드즉시할인 미적용)
MAX_BNFT_GUCCI = {
    "aplyDcPrc": 823500,
    "sellPrc": 915000,
    "step1BnftInfo": {"dcAmt": 0},
    "step2BnftList": [{"copnNm": "더할인", "dcAmt": 91500}],  # 쿠폰만 (제외 대상)
    "step3BnftList": [],
    "step4BnftList": [],
    "step5BnftList": [],
    "step8aBnftList": [],
    "step8bBnftList": [],
}

# 예약 40B1160122 — step8 둘 다 없음 (할인 자체가 없음)
MAX_BNFT_RESERVATION = {
    "aplyDcPrc": 50000,
    "sellPrc": 50000,
    "step1BnftInfo": {"dcAmt": 0},
    "step2BnftList": [],
    "step8aBnftList": [],
    "step8bBnftList": [],
}


# ──────────────────────────────────────────────────────────────
# 테스트 — 옵션 정규화
# ──────────────────────────────────────────────────────────────

class TestNormalizeOptions:
    def test_no_options_returns_single_sku(self) -> None:
        out = TheHyundaiSourcingClient._normalize_options(DETAIL_NO_OPTIONS, None)
        assert len(out) == 1
        assert out[0]["name"] == "단일"
        assert out[0]["price"] == 30000
        assert out[0]["stock"] == 61
        assert out[0]["isSoldOut"] is False

    def test_single_dim_uses_attr_list_directly(self) -> None:
        out = TheHyundaiSourcingClient._normalize_options(DETAIL_SINGLE_DIM, None)
        assert len(out) == 3
        # 230 — 품절
        assert out[0]["name"] == "230"
        assert out[0]["stock"] == 0
        assert out[0]["isSoldOut"] is True
        # 235 — 재고 4
        assert out[1]["name"] == "235"
        assert out[1]["stock"] == 4
        assert out[1]["isSoldOut"] is False
        # 240 — 재고 12
        assert out[2]["stock"] == 12

    def test_single_dim_falls_back_to_sell_prc(self) -> None:
        # uitmDcPrc 가 0/null 인 옵션은 prcInfo.dcPrc 로 폴백
        detail = {
            **DETAIL_SINGLE_DIM,
            "uitmAttrList": [
                {"uitmCd": "00001", "uitmNm": "S", "uitmTotNm": "S",
                 "uitmDcPrc": None, "uitmSellGbcd": "00", "sellPossQty": 5},
            ],
        }
        out = TheHyundaiSourcingClient._normalize_options(detail, None)
        assert out[0]["price"] == 45350

    def test_multi_dim_uses_stck_list(self) -> None:
        out = TheHyundaiSourcingClient._normalize_options(
            DETAIL_MULTI_DIM, STCK_LIST_MULTI
        )
        assert len(out) == 3
        names = [o["name"] for o in out]
        assert "선택1(1010)/DOR/XXL(110)" in names
        # 다차원은 균일가 (옵션별 가격 응답 미제공)
        assert all(o["price"] == 80000 for o in out)

    def test_multi_dim_empty_stck_means_all_sold_out(self) -> None:
        # uitmCombYn="1" 인데 stckList 비어있으면 전 품절 (사이트가 가용 재고만 반환)
        out = TheHyundaiSourcingClient._normalize_options(DETAIL_MULTI_DIM, [])
        assert out == []  # 빈 옵션 = 가용 옵션 없음 = refresh() 가 sold_out 처리

    def test_single_dim_sold_out_flag(self) -> None:
        # 단일 차원에서 uitmSellGbcd="11" = 품절
        out = TheHyundaiSourcingClient._normalize_options(DETAIL_SINGLE_DIM, None)
        sold_out_opts = [o for o in out if o["isSoldOut"]]
        assert len(sold_out_opts) == 1
        assert sold_out_opts[0]["name"] == "230"


# ──────────────────────────────────────────────────────────────
# 테스트 — new_cost 공식 (G섹션 핵심)
# ──────────────────────────────────────────────────────────────

class TestComputeNewCost:
    def test_nike_card_discount_applied(self) -> None:
        """나이키 40B0696270 — 화면 최대혜택가 42,180원 = aplyDcPrc(45350) − step8b(3170)."""
        cost = TheHyundaiSourcingClient._compute_new_cost(MAX_BNFT_NIKE)
        assert cost == 42180, f"실제 사이트 노출값과 일치해야 함 (got {cost})"

    def test_gucci_no_step8(self) -> None:
        """구찌 — 명품 카드즉시할인 미적용. new_cost == aplyDcPrc."""
        cost = TheHyundaiSourcingClient._compute_new_cost(MAX_BNFT_GUCCI)
        assert cost == 823500

    def test_reservation_no_discount(self) -> None:
        """예약판매 — 할인 단계 전부 빈 배열. new_cost == aplyDcPrc."""
        cost = TheHyundaiSourcingClient._compute_new_cost(MAX_BNFT_RESERVATION)
        assert cost == 50000

    def test_step2_coupon_intentionally_excluded(self) -> None:
        """step2(더할인 쿠폰)는 보유자 한정 → 화면 최대혜택가에서 의도적 제외 (사이트 정책)."""
        # 나이키 케이스에서 step2.dcAmt=9950이 있지만 결과는 9950 차감되지 않음
        cost = TheHyundaiSourcingClient._compute_new_cost(MAX_BNFT_NIKE)
        # 만약 step2까지 차감했다면: 45350 - 3170 - 9950 = 32230 — 이 값이 아니어야 함
        assert cost != 32230

    def test_step1_already_included_in_aply_dc(self) -> None:
        """step1(기본할인)은 이미 aplyDcPrc 에 반영되어 있어 별도 차감 X."""
        bnft = {
            "aplyDcPrc": 10000,
            "step1BnftInfo": {"dcAmt": 5000},  # 이미 반영됐다고 가정
            "step8aBnftList": [],
            "step8bBnftList": [],
        }
        # 기대: 10000 (5000 추가 차감 X)
        assert TheHyundaiSourcingClient._compute_new_cost(bnft) == 10000

    def test_multiple_step8b_entries_summed(self) -> None:
        bnft = {
            "aplyDcPrc": 100000,
            "step8aBnftList": [{"dcAmt": 5000}],
            "step8bBnftList": [{"dcAmt": 7000}, {"dcAmt": 3000}],
        }
        assert TheHyundaiSourcingClient._compute_new_cost(bnft) == 85000

    def test_negative_clamped_to_zero(self) -> None:
        # 가상 케이스 — 할인 합이 정가보다 클 때 음수 방지
        bnft = {
            "aplyDcPrc": 1000,
            "step8aBnftList": [{"dcAmt": 5000}],
            "step8bBnftList": [],
        }
        assert TheHyundaiSourcingClient._compute_new_cost(bnft) == 0

    def test_missing_step8_keys(self) -> None:
        # 응답에 step8a/b 키 자체가 없는 케이스 (서버 형식 변동 대비)
        bnft = {"aplyDcPrc": 5000}
        assert TheHyundaiSourcingClient._compute_new_cost(bnft) == 5000


# ──────────────────────────────────────────────────────────────
# 테스트 — 상세 응답 build
# ──────────────────────────────────────────────────────────────

class TestBuildDetail:
    def test_basic_fields_with_max_bnft(self) -> None:
        detail_data = {
            **DETAIL_SINGLE_DIM,
            "brndInfo": {
                "expsBrndNm": "나이키", "operBrndNm": "나이키",
                "operBrndCd": "101047", "expsEngBrndNm": "NIKE",
                "luitYn": "0",
            },
            "bnftInfo": {"upntAcmPnt": 90, "tcpPntAcmRate": 1},
            "thumbInfoList": [
                {"imgSeq": "0", "orglImgNm": "7/2/6/69/B0/40B0696270_0.jpg"},
                {"imgSeq": "1", "orglImgNm": "7/2/6/69/B0/40B0696270_1.jpg"},
            ],
            "itemLcsfNm": "스포츠 슈즈",
            "itemMcsfNm": "여성스포츠화",
            "itemScsfNm": "러닝/조깅/워킹화",
            "itemDcsfNm": "데일리/하이브리드",
            "itemDcsfCd": "30020101",
            "dlvFormInfoList": [
                {"dlvCost": 3000, "baseFee": 30000, "irgnMntrDlvCost": 3000,
                 "dlvFormGbcd": "10", "dlvcPlcyBsicGbcd": "04",
                 "dsrvDlvcoNm": "롯데택배"},
            ],
            "ostkYn": "0",
            "openMktItemYn": "0",
            "hdmalRsvSellYn": "0",
            "storeNm": "판교점",
        }
        client = TheHyundaiSourcingClient()
        out = client._build_detail("40B0696270", detail_data, None, MAX_BNFT_NIKE)
        assert out["name"] == "런 디파이 (여성) NIKE HM9593-107"
        assert out["brand"] == "나이키"
        assert out["brandCode"] == "101047"
        assert out["originalPrice"] == 55300
        assert out["salePrice"] == 45350
        assert out["cost"] == 42180  # G섹션 공식 적용
        assert out["isSoldOut"] is False
        assert len(out["images"]) == 2
        assert out["images"][0].startswith("https://image.thehyundai.com")
        assert out["category"] == "스포츠 슈즈 > 여성스포츠화 > 러닝/조깅/워킹화 > 데일리/하이브리드"
        assert out["shippingFee"] == 3000
        assert out["freeShippingThreshold"] == 30000
        assert out["remoteAreaFee"] == 3000
        assert out["carrierName"] == "롯데택배"
        assert out["loyaltyPoints"] == 90
        assert out["sourceUrl"] == "https://hi.thehyundai.com/product/40B0696270"

    def test_cost_falls_back_when_max_bnft_missing(self) -> None:
        client = TheHyundaiSourcingClient()
        out = client._build_detail(
            "40B0696270",
            {**DETAIL_SINGLE_DIM, "brndInfo": {}, "bnftInfo": {}},
            None,
            None,  # maxBnftList 응답 없음 → maxDcPrc 폴백
        )
        assert out["cost"] == 45350  # prcInfo.maxDcPrc 폴백

    def test_luxury_flag(self) -> None:
        client = TheHyundaiSourcingClient()
        out = client._build_detail(
            "60B1015785",
            {
                **DETAIL_NO_OPTIONS,
                "brndInfo": {"luitYn": "1", "operBrndCd": "146988"},
                "bnftInfo": {},
                "thumbInfoList": [],
            },
            None,
            MAX_BNFT_GUCCI,
        )
        assert out["luxury"] is True
