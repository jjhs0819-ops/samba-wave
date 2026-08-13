"""플레이오토 _build_options 축 분리 회귀 테스트.

2026-08-13 다이나핏 전송 사전점검 실측:
- SSG 수집 옵션은 optionName1/2(구조화 축)가 있는데도 name("펄 그레이(W7)/S")만
  파싱해 통짜 단일옵션으로 등록되던 문제 (1,261건).
- 품절 판정이 is_sold_out/sold_out(snake_case)만 인식 — 수집 표준 키는
  isSoldOut(camelCase).
"""

from backend.domain.samba.proxy.playauto import _build_options


def test_structured_axes_take_priority_over_name():
    opts = [
        {
            "name": "펄 그레이(W7)/S",
            "optionDepth": 2,
            "optionName1": "펄 그레이(W7)",
            "optionName2": "S",
            "price": 30000,
            "stock": 3,
            "isSoldOut": False,
        }
    ]
    built = _build_options(opts, 99, source_site="SSG")
    assert built[0]["opt1"] == "펄 그레이(W7)"
    assert built[0]["opt2"] == "S"
    assert built[0]["title1"] == "옵션1"
    assert built[0]["title2"] == "옵션2"


def test_structured_single_axis_uses_plain_title():
    opts = [{"name": "M", "optionName1": "M", "stock": 5, "isSoldOut": False}]
    built = _build_options(opts, 99)
    assert built[0]["opt1"] == "M"
    assert built[0]["title1"] == "옵션"
    assert "opt2" not in built[0]


def test_ssg_legacy_bare_slash_split():
    # optionName1/2가 없던 시절의 SSG 수집분 — SSG 한정 bare '/' 분리
    opts = [{"name": "핑크(P1)/S", "stock": 5, "isSoldOut": False}]
    built = _build_options(opts, 99, source_site="SSG")
    assert built[0]["opt1"] == "핑크(P1)"
    assert built[0]["opt2"] == "S"


def test_non_ssg_bare_slash_not_split():
    # 타 소싱처는 투톤 색상("블랙/화이트") 등 단일 값 내 '/' 가능 — 분리 금지
    opts = [{"name": "블랙/화이트", "stock": 5, "isSoldOut": False}]
    built = _build_options(opts, 99, source_site="MUSINSA")
    assert built[0]["opt1"] == "블랙/화이트"
    assert "opt2" not in built[0]


def test_spaced_slash_split_unchanged():
    opts = [{"name": "WHITE / M", "stock": 5, "isSoldOut": False}]
    built = _build_options(opts, 99)
    assert built[0]["opt1"] == "WHITE"
    assert built[0]["opt2"] == "M"


def test_camelcase_soldout_recognized():
    opts = [{"name": "L", "stock": 7, "isSoldOut": True}]
    built = _build_options(opts, 99)
    assert built[0]["soldout"] == "1"
    assert built[0]["stock"] == "0"


def test_snake_case_soldout_still_recognized():
    opts = [{"name": "L", "stock": 7, "is_sold_out": True}]
    built = _build_options(opts, 99)
    assert built[0]["soldout"] == "1"


def test_duplicate_options_dropped():
    opts = [
        {"name": "M", "stock": 5, "isSoldOut": False},
        {"name": "M", "stock": 3, "isSoldOut": False},
    ]
    built = _build_options(opts, 99)
    assert len(built) == 1


def test_structured_axes_dedupe_with_legacy_name_rows():
    # 같은 상품 안에서 구조화 행과 레거시 행이 같은 축 값으로 파싱되면 중복 제거
    opts = [
        {
            "name": "블랙(Z1)/S",
            "optionName1": "블랙(Z1)",
            "optionName2": "S",
            "stock": 5,
            "isSoldOut": False,
        },
        {"name": "블랙(Z1)/S", "stock": 5, "isSoldOut": False},
    ]
    built = _build_options(opts, 99, source_site="SSG")
    assert len(built) == 1
