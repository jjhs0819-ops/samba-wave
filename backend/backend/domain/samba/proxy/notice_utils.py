"""상품정보제공고시 — 카테고리별 동적 분기 유틸리티.

상품의 category1 값을 기반으로 각 마켓 API가 요구하는
고시정보 타입과 필드를 자동 결정한다.
"""

from __future__ import annotations

from typing import Any


# ────────────────────────────────────────────
# 1. 카테고리 → 고시정보 타입 판별 (공통)
# ────────────────────────────────────────────

# category1 → 고시정보 그룹 매핑
_CATEGORY_GROUP: dict[str, str] = {
    # 의류
    "상의": "wear",
    "하의": "wear",
    "아우터": "wear",
    "원피스": "wear",
    "니트": "wear",
    "셔츠": "wear",
    "스커트": "wear",
    "팬츠": "wear",
    "의류": "wear",
    "패션의류": "wear",
    "남성의류": "wear",
    "여성의류": "wear",
    "속옷": "wear",
    "잠옷": "wear",
    "정장": "wear",
    # 신발
    "신발": "shoes",
    "스니커즈": "shoes",
    "부츠": "shoes",
    "샌들": "shoes",
    "슬리퍼": "shoes",
    "스포츠화": "shoes",
    "구두": "shoes",
    "로퍼": "shoes",
    "운동화": "shoes",
    "러닝화": "shoes",
    "축구화": "shoes",
    "농구화": "shoes",
    # 가방
    "가방": "bag",
    "백팩": "bag",
    "크로스백": "bag",
    "숄더백": "bag",
    "토트백": "bag",
    "클러치": "bag",
    "에코백": "bag",
    "캐리어": "bag",
    # 잡화/액세서리
    "모자": "accessories",
    "벨트": "accessories",
    "지갑": "accessories",
    "시계": "accessories",
    "주얼리": "accessories",
    "안경": "accessories",
    "액세서리": "accessories",
    "패션잡화": "accessories",
    # 화장품/뷰티
    "화장품": "cosmetic",
    "뷰티": "cosmetic",
    "스킨케어": "cosmetic",
    "메이크업": "cosmetic",
    "향수": "cosmetic",
    "헤어": "cosmetic",
    "바디": "cosmetic",
    # 식품
    "식품": "food",
    "음료": "food",
    "건강식품": "food",
    "과일": "food",
    "채소": "food",
    "수산물": "food",
    "축산물": "food",
    "농산물": "food",
    # 전자제품
    "전자": "electronics",
    "가전": "electronics",
    "디지털": "electronics",
    "컴퓨터": "electronics",
    "모바일": "electronics",
}


def detect_notice_group(product: dict[str, Any]) -> str:
    """상품의 category1 기반으로 고시정보 그룹을 판별한다.

    Returns: "wear" | "shoes" | "bag" | "accessories" | "cosmetic" | "food" | "electronics" | "etc"
    """
    cat1 = (product.get("category1") or "").strip()
    if cat1 in _CATEGORY_GROUP:
        return _CATEGORY_GROUP[cat1]

    # category1에 키워드가 포함된 경우 (예: "남성신발" → "신발" 포함)
    for keyword, group in _CATEGORY_GROUP.items():
        if keyword in cat1:
            return group

    # category (전체 경로) 에서도 시도
    full_cat = (product.get("category") or "").strip()
    for keyword, group in _CATEGORY_GROUP.items():
        if keyword in full_cat:
            return group

    # 상품명에서 카테고리 추론 (카테고리 미설정 소싱처 대응)
    name = (product.get("name") or "").lower()
    name_hints = {
        "shoes": [
            "운동화",
            "신발",
            "스니커즈",
            "부츠",
            "샌들",
            "슬리퍼",
            "러닝화",
            "로퍼",
            "구두",
            "플라이",
            "에어맥스",
            "에어포스",
            "덩크",
            "조던",
            "트레이너",
            "베이퍼",
        ],
        "wear": [
            "티셔츠",
            "셔츠",
            "자켓",
            "팬츠",
            "후드",
            "맨투맨",
            "바지",
            "코트",
            "조거",
            "트레이닝",
        ],
        "bag": ["가방", "백팩", "크로스백", "토트백", "숄더백"],
        "accessories": ["모자", "벨트", "지갑", "시계", "양말"],
    }
    for group, hints in name_hints.items():
        for h in hints:
            if h in name:
                return group

    # 신발 브랜드 + 카테고리 미설정 → 기본 shoes 추론
    brand = (product.get("brand") or "").lower()
    shoe_brands = {
        "나이키",
        "nike",
        "아디다스",
        "adidas",
        "뉴발란스",
        "new balance",
        "퓨마",
        "puma",
        "리복",
        "reebok",
        "아식스",
        "asics",
        "컨버스",
        "converse",
        "반스",
        "vans",
    }
    if brand in shoe_brands:
        return "shoes"

    return "etc"


# ────────────────────────────────────────────
# 2. 쿠팡 고시정보
# ────────────────────────────────────────────

# 쿠팡 noticeCategoryName 매핑
_COUPANG_NOTICE_CATEGORY: dict[str, str] = {
    "wear": "의류",
    "shoes": "신발",
    "bag": "가방",
    "accessories": "패션잡화(모자/벨트/액세서리)",
    "cosmetic": "화장품(기능성화장품 포함)",
    "food": "식품(일반식품)",
    "electronics": "전자제품",
    "etc": "기타 재화",
}

# 쿠팡 카테고리별 고시정보 상세 필드
_COUPANG_NOTICE_FIELDS: dict[str, list[str]] = {
    "의류": [
        "제품 소재",
        "색상",
        "치수",
        "제조자(수입자)",
        "제조국",
        "세탁방법 및 취급시 주의사항",
        "제조연월",
        "품질보증기준",
        "A/S 책임자와 전화번호",
    ],
    "신발": [
        "제품 소재",
        "색상",
        "치수",
        "제조자(수입자)",
        "제조국",
        "세탁방법 및 취급시 주의사항",
        "제조연월",
        "품질보증기준",
        "A/S 책임자와 전화번호",
    ],
    "가방": [
        "종류",
        "소재",
        "색상",
        "크기",
        "제조자(수입자)",
        "제조국",
        "세탁방법 및 취급시 주의사항",
        "제조연월",
        "품질보증기준",
        "A/S 책임자와 전화번호",
    ],
    "패션잡화(모자/벨트/액세서리)": [
        "종류",
        "소재",
        "치수",
        "제조자(수입자)",
        "제조국",
        "취급시 주의사항",
        "품질보증기준",
        "A/S 책임자와 전화번호",
    ],
    "화장품(기능성화장품 포함)": [
        "용량 또는 중량",
        "제품 주요 사양",
        "사용기한 또는 개봉 후 사용기간",
        "사용방법",
        "제조자 및 제조판매업자",
        "제조국",
        "주요 성분",
        "기능성 화장품 심사필 유무",
        "사용할 때 주의사항",
        "품질보증기준",
        "소비자상담관련 전화번호",
    ],
    "식품(일반식품)": [
        "식품의 유형",
        "생산자 및 소재지",
        "제조연월일/유통기한/품질유지기한",
        "포장단위별 내용물의 용량(중량),수량",
        "원재료명 및 함량",
        "영양성분",
        "유전자변형식품 여부",
        "소비자상담관련 전화번호",
    ],
    "전자제품": [
        "품명 및 모델명",
        "KC 인증 필 유무",
        "정격전압/소비전력",
        "에너지소비효율등급",
        "동일모델의 출시년월",
        "제조자(수입자)",
        "제조국",
        "크기/무게",
        "주요 사양",
        "품질보증기준",
        "A/S 책임자와 전화번호",
    ],
    "기타 재화": [
        "품명 및 모델명",
        "제조자(수입자)",
        "제조국",
        "A/S 책임자와 전화번호",
    ],
}


def build_coupang_notices(product: dict[str, Any]) -> list[dict[str, str]]:
    """상품 카테고리에 맞는 쿠팡 고시정보 notices 배열을 생성한다."""
    group = detect_notice_group(product)
    cat_name = _COUPANG_NOTICE_CATEGORY.get(group, "기타 재화")
    fields = _COUPANG_NOTICE_FIELDS.get(cat_name, _COUPANG_NOTICE_FIELDS["기타 재화"])

    # 상품 데이터에서 값 추출 (없으면 카테고리별 기본값)
    fallback = "상세페이지 참조"
    _caution_defaults: dict[str, str] = {
        "의류": "세탁 시 뒤집어서 단독 손세탁, 표백제 사용 금지, 직사광선을 피해 그늘에서 건조",
        "신발": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 화학제품 사용 금지",
        "가방": "직사광선 및 고온 다습한 환경을 피해 보관, 마찰에 의한 색 이염 주의",
    }
    caution_text = (
        product.get("care_instructions", "")
        or product.get("careInstructions", "")
        or _caution_defaults.get(cat_name, fallback)
    )

    value_map: dict[str, str] = {
        "제품 소재": product.get("material", "") or fallback,
        "소재": product.get("material", "") or fallback,
        "색상": product.get("color", "") or fallback,
        "치수": fallback,
        "크기": fallback,
        "종류": fallback,
        "제조자(수입자)": product.get("manufacturer", "")
        or product.get("brand", "")
        or fallback,
        "제조자 및 제조판매업자": product.get("manufacturer", "")
        or product.get("brand", "")
        or fallback,
        "제조국": product.get("origin", "") or fallback,
        "세탁방법 및 취급시 주의사항": caution_text,
        "취급시 주의사항": caution_text,
        "사용할 때 주의사항": caution_text,
        "제조연월": fallback,
        "품질보증기준": "제품 이상 시 공정거래위원회 고시 소비자분쟁해결기준에 의거 보상합니다.",
        "A/S 책임자와 전화번호": fallback,
        "소비자상담관련 전화번호": fallback,
    }

    notices = []
    for field in fields:
        notices.append(
            {
                "noticeCategoryName": cat_name,
                "noticeCategoryDetailName": field,
                "content": value_map.get(field, fallback),
            }
        )
    return notices


# ────────────────────────────────────────────
# 3. 스마트스토어 고시정보
# ────────────────────────────────────────────

# 스마트스토어 카테고리 ID → 고시정보 그룹 매핑
# 50000000 대역: 패션의류/잡화
_SS_CATEGORY_GROUP: dict[str, str] = {
    # 신발 카테고리 (50003xxx 대역)
    "50003822": "shoes",  # 운동화 > 스니커즈
    "50003835": "shoes",  # 운동화 > 런닝화
    "50003801": "shoes",  # 신발
    "50003802": "shoes",  # 남성신발
    "50003803": "shoes",  # 여성신발
    "50003804": "shoes",  # 아동신발
    "50003820": "shoes",  # 운동화
    "50003821": "shoes",  # 워킹화
    "50003830": "shoes",  # 구두
    "50003840": "shoes",  # 부츠
    "50003850": "shoes",  # 샌들/슬리퍼
}


def _detect_group_from_ss_category(category_id: str) -> str | None:
    """스마트스토어 카테고리 ID로 고시정보 그룹을 판별.
    직접 매핑이 없으면 상위 카테고리 대역으로 추론.
    """
    if not category_id:
        return None
    # 1. 직접 매핑
    if category_id in _SS_CATEGORY_GROUP:
        return _SS_CATEGORY_GROUP[category_id]
    # 2. 대역 추론 (5000380x~5000389x = 신발)
    try:
        cid = int(category_id)
        if 50003800 <= cid <= 50003899:
            return "shoes"
        if 50000100 <= cid <= 50002999:
            return "wear"
        if 50004000 <= cid <= 50004099:
            return "bag"
        if 50004100 <= cid <= 50004299:
            return "accessories"
    except (ValueError, TypeError):
        pass
    return None


# 스마트스토어 고시정보 타입 매핑
_SMARTSTORE_NOTICE_TYPE: dict[str, str] = {
    "wear": "WEAR",
    "shoes": "SHOES",
    "bag": "BAG",
    "accessories": "FASHION_ITEMS",
    "cosmetic": "COSMETIC",
    "food": "FOOD",
    "electronics": "DIGITAL_CONTENTS",
    "etc": "ETC",
}


def build_smartstore_notice(product: dict[str, Any], **kwargs: str) -> dict[str, Any]:
    """상품 카테고리에 맞는 스마트스토어 고시정보를 생성한다.

    kwargs: color_text, size_text, mfr, brand, ss_category_id 등 transform_product에서 가공된 값
    """
    # 매핑된 스마트스토어 카테고리 ID로 고시정보 타입 우선 판별
    ss_cat_id = kwargs.get("ss_category_id", "")
    group = _detect_group_from_ss_category(ss_cat_id) if ss_cat_id else None
    if not group:
        group = detect_notice_group(product)
    notice_type = _SMARTSTORE_NOTICE_TYPE.get(group, "ETC")

    fallback = "상세 이미지 참조"
    # 스마트스토어 금지 특수문자 제거: \ * ? " < >
    import re as _re_special

    def _clean_special(text: str) -> str:
        return _re_special.sub(r'[\\*?"<>]', "", text).strip() if text else text

    material = _clean_special(product.get("material", "") or fallback)
    color_text = kwargs.get("color_text", fallback)
    size_text = kwargs.get("size_text", fallback)
    mfr = kwargs.get(
        "mfr", product.get("manufacturer", "") or product.get("brand", "") or fallback
    )
    brand = kwargs.get("brand", product.get("brand", "") or fallback)

    # 카테고리별 기본 취급주의사항
    _DEFAULT_CAUTION: dict[str, str] = {
        "wear": "세탁 시 뒤집어서 단독 손세탁, 표백제 사용 금지, 직사광선을 피해 그늘에서 건조",
        "shoes": "물세탁 불가, 직사광선 및 고온 다습한 곳 보관 금지, 벤젠/신나 등 화학제품 사용 금지",
        "bag": "직사광선 및 고온 다습한 환경을 피해 보관, 마찰에 의한 색 이염 주의, 물에 젖었을 경우 마른 천으로 닦아 그늘에서 건조",
        "accessories": "직사광선 및 습기를 피해 보관, 화학제품 접촉 주의",
        "cosmetic": "사용 후 뚜껑을 꼭 닫아 보관, 직사광선을 피해 서늘한 곳에 보관, 이상 증상 발생 시 사용 중지",
        "food": "직사광선을 피해 서늘한 곳에 보관, 개봉 후 빠른 시일 내 섭취",
        "electronics": "물기에 주의, 직사광선 및 고온 다습한 곳 보관 금지",
        "etc": "상세페이지 참조",
    }

    caution = (
        product.get("care_instructions", "")
        or product.get("careInstructions", "")
        or _DEFAULT_CAUTION.get(group, _DEFAULT_CAUTION["etc"])
    )

    # 소비자보호 가이드 5항목 — "0"=법정기준, "1"=상품상세 참조
    _GUIDE_FIELDS = {
        "returnCostReason": "0",
        "noRefundReason": "0",
        "qualityAssuranceStandard": "0",
        "compensationProcedure": "0",
        "troubleShootingContents": "0",
    }

    # 제조사에서 (주) 제거
    import re as _re

    mfr = _re.sub(r"\(주\)|㈜|\(株\)", "", mfr).strip() if mfr else mfr

    # 공통 필드 (의류/신발/가방은 필드가 거의 동일) — 수집 데이터 우선 사용
    caution = _clean_special(
        product.get("care_instructions", "")
        or product.get("careInstructions", "")
        or _DEFAULT_CAUTION.get(group, _DEFAULT_CAUTION["etc"])
    )
    common_fields = {
        **_GUIDE_FIELDS,
        "material": material,
        "color": _clean_special(color_text),
        "size": _clean_special(size_text),
        "manufacturer": _clean_special(mfr or fallback),
        "caution": caution,
        "packDateText": "주문 후 개별포장 발송",
        "warrantyPolicy": _clean_special(
            product.get("quality_guarantee", "")
            or product.get("qualityGuarantee", "")
            or "제품 하자 시 소비자분쟁해결기준(공정거래위원회 고시)에 따라 보상"
        ),
        "afterServiceDirector": _clean_special(f"{brand} 고객센터"),
    }

    # 타입별 필드 키 이름
    type_key_map: dict[str, str] = {
        "WEAR": "wear",
        "SHOES": "shoes",
        "BAG": "bag",
        "FASHION_ITEMS": "fashionItems",
        "COSMETIC": "cosmetic",
        "FOOD": "food",
        "DIGITAL_CONTENTS": "digitalContents",
        "ETC": "etc",
    }

    field_key = type_key_map.get(notice_type, "etc")

    # 화장품/식품은 필드가 다름
    if notice_type == "COSMETIC":
        notice_data = {
            "capacity": product.get("material", "") or fallback,
            "manufacturer": mfr,
            "expirationDateText": fallback,
            "mainIngredient": fallback,
            "caution": fallback,
            "warrantyPolicy": common_fields["warrantyPolicy"],
            "afterServiceDirector": common_fields["afterServiceDirector"],
        }
    elif notice_type == "FOOD":
        notice_data = {
            "foodType": fallback,
            "manufacturer": mfr,
            "location": fallback,
            "packDateText": fallback,
            "expirationDateText": fallback,
            "weight": fallback,
            "amount": fallback,
            "ingredients": fallback,
            "nutritionFacts": fallback,
            "geneticallyModified": "해당 없음",
            "consumerSafetyCaution": fallback,
            "importDeclaration": "해당 없음",
            "customerServicePhoneNumber": "상세페이지 참조",
        }
    elif notice_type == "ETC":
        notice_data = {
            "itemName": (product.get("name", "") or fallback)[:50],
            "modelName": fallback,
            "manufacturer": mfr,
            "afterServiceDirector": common_fields["afterServiceDirector"],
        }
    elif notice_type == "FASHION_ITEMS":
        # 패션잡화 — type 필드 필수 (모자/벨트/지갑 등 세부 분류)
        _cat_parts = [
            p.strip() for p in (product.get("category") or "").split(">") if p.strip()
        ]
        _fashion_type = (
            _cat_parts[1]
            if len(_cat_parts) > 1
            else (_cat_parts[0] if _cat_parts else "패션잡화")
        )
        if not _fashion_type:
            _fashion_type = "패션잡화"
        from backend.utils.logger import logger as _notice_logger

        _notice_logger.info(
            f"[고시정보] FASHION_ITEMS type={_fashion_type!r}, "
            f"category={product.get('category')!r}, "
            f"category1={product.get('category1')!r}, "
            f"category_levels={product.get('category_levels')!r}"
        )
        notice_data = {
            **common_fields,
            "type": _clean_special(_fashion_type),
        }
    elif notice_type == "SHOES":
        # 신발 — height 필드 필수
        notice_data = {
            **common_fields,
            "height": _clean_special(size_text) or "상세 이미지 참조",
        }
    else:
        # WEAR, BAG — 공통 필드 사용
        notice_data = common_fields

    # 화장품/식품/ETC에도 가이드 필드 추가
    if isinstance(notice_data, dict):
        for gk, gv in _GUIDE_FIELDS.items():
            if gk not in notice_data:
                notice_data[gk] = gv

    return {
        "productInfoProvidedNoticeType": notice_type,
        field_key: notice_data,
    }


# ────────────────────────────────────────────
# 4. 롯데ON 고시정보
# ────────────────────────────────────────────

# 롯데ON pdItmsCd 매핑
_LOTTEON_NOTICE_CODE: dict[str, str] = {
    "wear": "38",  # 의류
    "shoes": "39",  # 신발
    "bag": "40",  # 가방
    "accessories": "41",  # 패션잡화
    "cosmetic": "42",  # 화장품
    "food": "01",  # 식품
    "electronics": "14",  # 전자제품
    "etc": "35",  # 기타
}


def build_lotteon_notice(product: dict[str, Any]) -> dict[str, Any]:
    """상품 카테고리에 맞는 롯데ON 고시정보를 생성한다."""
    group = detect_notice_group(product)
    code = _LOTTEON_NOTICE_CODE.get(group, "35")

    name = product.get("name", "")
    brand = product.get("brand", "")

    articles = [
        {"pdArtlCd": "0160", "pdArtlCnts": name},
        {
            "pdArtlCd": "0060",
            "pdArtlCnts": product.get("origin", "") or "상세페이지 참조",
        },
        {
            "pdArtlCd": "0070",
            "pdArtlCnts": product.get("manufacturer", "")
            or brand
            or "제조자 정보 없음",
        },
        {"pdArtlCd": "0080", "pdArtlCnts": "소비자 기본법에 따름"},
        {"pdArtlCd": "0090", "pdArtlCnts": brand or "판매자 문의"},
    ]

    return {
        "pdItmsCd": code,
        "pdItmsArtlLst": articles,
    }


# ────────────────────────────────────────────
# 5. SSG 고시정보 (상품관리속성)
# ────────────────────────────────────────────


def build_ssg_notice(product: dict[str, Any]) -> list[dict[str, str]]:
    """상품 카테고리에 맞는 SSG 상품관리속성을 생성한다."""
    fallback = "상세설명참조"
    material = product.get("material", "") or fallback
    color = product.get("color", "") or fallback
    manufacturer = (
        product.get("manufacturer", "") or product.get("brand", "") or fallback
    )

    return [
        {"itemMngPropId": "0000000001", "itemMngCntt": material},  # 소재
        {"itemMngPropId": "0000000003", "itemMngCntt": color},  # 색상
        {"itemMngPropId": "0000000006", "itemMngCntt": fallback},  # 품질보증
        {"itemMngPropId": "0000000007", "itemMngCntt": manufacturer},  # 제조자
        {"itemMngPropId": "0000000008", "itemMngCntt": "N"},  # 사이즈표기안내
        {"itemMngPropId": "0000000011", "itemMngCntt": "1000000001"},  # 제조국
        {"itemMngPropId": "0000000012", "itemMngCntt": fallback},  # A/S
    ]
