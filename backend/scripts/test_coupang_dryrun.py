"""쿠팡 SEO 최적화 드라이런 테스트.

transform_product 변환 결과를 JSON으로 출력하여 검증.
실행: cd backend && python -m scripts.test_coupang_dryrun
"""

import json
import sys
import os

# 프로젝트 루트를 PATH에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.domain.samba.proxy.coupang import (
    CoupangClient,
    _build_display_product_name,
    _build_search_tags,
    _parse_option_color_size,
    _build_content_details,
)


def test_display_product_name():
    """노출상품명 생성 테스트."""
    print("=" * 60)
    print("1. 노출상품명 테스트")
    print("=" * 60)

    # 케이스 1: market_names에 쿠팡 설정됨
    p1 = {"market_names": {"쿠팡": "수동 설정 쿠팡 상품명"}, "name": "원본명"}
    result = _build_display_product_name(p1)
    print(f"  수동설정: {result}")
    assert result == "수동 설정 쿠팡 상품명", f"기대: 수동 설정 쿠팡 상품명, 실제: {result}"

    # 케이스 2: 자동생성
    p2 = {
        "brand": "나이키",
        "sex": "남성",
        "name": "에어맥스 95 에센셜 런닝화 블랙",
        "category2": "운동화",
        "category3": "런닝화",
        "category4": "로드런닝",
        "style_code": "CT1268-001",
    }
    result = _build_display_product_name(p2)
    print(f"  자동생성: {result}")
    assert len(result) <= 100, f"100자 초과: {len(result)}자"
    assert "나이키" in result
    assert "CT1268-001" in result
    print(f"  길이: {len(result)}자 ✓")

    # 케이스 3: 빈 상품
    p3 = {"name": "기본 상품"}
    result = _build_display_product_name(p3)
    print(f"  최소정보: {result}")

    print()


def test_search_tags():
    """검색태그 생성 테스트."""
    print("=" * 60)
    print("2. 검색태그 테스트")
    print("=" * 60)

    product = {
        "brand": "아디다스",
        "name": "울트라부스트 22 남성 러닝화 코어블랙",
        "seo_keywords": ["운동화", "러닝화", "아디다스운동화"],
        "category1": "패션",
        "category2": "스포츠",
        "category3": "운동화",
        "category4": "런닝화",
        "style_code": "GX5460",
        "material": "메쉬",
        "color": "코어블랙",
    }
    result = _build_search_tags(product)
    tags = result.split(",")
    print(f"  태그 수: {len(tags)}")
    print(f"  태그: {result}")
    assert len(tags) <= 20, f"20개 초과: {len(tags)}개"
    for t in tags:
        assert len(t) <= 20, f"20자 초과 태그: '{t}' ({len(t)}자)"
    print(f"  20개 이내 ✓, 각 20자 이내 ✓")
    print()


def test_option_color_size():
    """옵션 색상/사이즈 분리 테스트."""
    print("=" * 60)
    print("3. 옵션 색상/사이즈 분리 테스트")
    print("=" * 60)

    cases = [
        ("블랙 / 090(S)", "기본", ("블랙", "090(S)")),
        ("Black/M", "기본", ("Black", "M")),
        ("L", "기본색상", ("기본색상", "L")),
        ("레드", "기본색상", ("레드", "FREE")),
        ("화이트 / XL", "기본", ("화이트", "XL")),
        ("270", "블랙", ("블랙", "270")),
        ("", "기본색상", ("기본색상", "FREE")),
        ("FREE", "네이비", ("네이비", "FREE")),
    ]

    for opt_name, default_color, expected in cases:
        result = _parse_option_color_size(opt_name, default_color)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{opt_name}' → {result} (기대: {expected})")
        if result != expected:
            print(f"    ⚠ 불일치!")

    print()


def test_content_details():
    """상세 컨텐츠 분리 테스트."""
    print("=" * 60)
    print("4. 상세 컨텐츠 IMAGE/TEXT 분리 테스트")
    print("=" * 60)

    # 케이스 1: img 태그 포함
    html1 = '<p>상품설명</p><img src="//img.example.com/a.jpg"><p>추가설명</p><img src="https://img.example.com/b.jpg">'
    result1 = _build_content_details(html1)
    types = [d["detailType"] for d in result1]
    print(f"  img 포함: {types}")
    assert "IMAGE" in types, "IMAGE 타입이 없음"
    assert "TEXT" in types, "TEXT 타입이 없음"
    # // 보정 확인
    for d in result1:
        if d["detailType"] == "IMAGE":
            assert d["content"].startswith("https://"), f"URL 보정 실패: {d['content']}"
    print(f"  URL https 보정 ✓")

    # 케이스 2: img 없음
    html2 = "<p>일반 텍스트 상세설명</p>"
    result2 = _build_content_details(html2)
    print(f"  img 없음: {[d['detailType'] for d in result2]}")
    assert len(result2) == 1 and result2[0]["detailType"] == "TEXT"

    # 케이스 3: 빈 HTML
    result3 = _build_content_details("")
    print(f"  빈 HTML: {[d['detailType'] for d in result3]}")

    print()


def test_transform_product():
    """전체 transform_product 통합 테스트."""
    print("=" * 60)
    print("5. transform_product 통합 테스트")
    print("=" * 60)

    product = {
        "name": "나이키 에어맥스 95 에센셜 런닝화 CT1268-001",
        "brand": "나이키",
        "sex": "남성",
        "color": "블랙",
        "style_code": "CT1268-001",
        "original_price": 189000,
        "sale_price": 159000,
        "images": [
            "https://img.example.com/main.jpg",
            "https://img.example.com/detail1.jpg",
            "https://img.example.com/detail2.jpg",
        ],
        "detail_html": '<p>상품설명</p><img src="//img.example.com/desc1.jpg"><p>추가정보</p><img src="https://img.example.com/desc2.jpg">',
        "options": [
            {"name": "블랙 / 260", "stock": 10},
            {"name": "화이트 / 270", "stock": 5},
            {"name": "레드 / M", "stock": 3},
        ],
        "category1": "패션",
        "category2": "신발",
        "category3": "스니커즈",
        "category4": "런닝화",
        "seo_keywords": ["나이키운동화", "에어맥스95"],
        "market_names": {},
        "material": "메쉬",
        "manufacturer": "나이키코리아",
    }

    result = CoupangClient.transform_product(product, category_id="12345")

    # 검증
    print(f"  displayProductName: {result['displayProductName']}")
    print(f"  sellerProductName: {result['sellerProductName']}")
    print(f"  generalProductName: {result['generalProductName']}")
    assert result["sellerProductName"] == product["name"][:100], "셀러상품명은 원본 유지"
    assert len(result["displayProductName"]) <= 100, "노출상품명 100자 초과"

    # searchTags
    if "searchTags" in result:
        tags = result["searchTags"].split(",")
        print(f"  searchTags: {len(tags)}개 → {result['searchTags'][:80]}...")
        assert len(tags) <= 20
    else:
        print("  searchTags: 없음 (빈 태그)")

    # 아이템별 색상 분리
    print(f"  items 수: {len(result['items'])}")
    for i, item in enumerate(result["items"]):
        attrs = {a["attributeTypeName"]: a["attributeValueName"] for a in item["attributes"]}
        print(f"    item[{i}]: name={item['itemName']}, 색상={attrs.get('색상')}, 사이즈={attrs.get('패션의류/잡화 사이즈')}")

    # contents IMAGE/TEXT 확인
    first_item = result["items"][0]
    content_types = [d["detailType"] for d in first_item["contents"][0]["contentDetails"]]
    print(f"  contents detailType: {content_types}")
    assert "IMAGE" in content_types, "IMAGE 타입 없음"

    print()
    print("전체 JSON (일부):")
    # 간결한 출력
    summary = {k: v for k, v in result.items() if k not in ("items",)}
    summary["items_count"] = len(result["items"])
    summary["first_item_attrs"] = result["items"][0]["attributes"]
    summary["first_item_content_types"] = content_types
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    print("\n🔍 쿠팡 SEO 최적화 드라이런 테스트\n")
    try:
        test_display_product_name()
        test_search_tags()
        test_option_color_size()
        test_content_details()
        test_transform_product()
        print("\n✅ 모든 테스트 통과!")
    except Exception as e:
        print(f"\n❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
