"""SSG 재등록(insertItem) 폴백에서 itemDesc 누락 회귀 방지 (2026-09-03).

배경: 경량 가격/재고 수정은 기존 상세 보존을 위해 itemDesc 를 payload 에서
제거한다(2026-07-26 커밋 eec5c971f). 그런데 옵션 구성 변경·영구판매중지 감지
시에는 같은 payload 로 insertItem(신규등록) 폴백을 타는데, insertItem 은
itemDesc 가 필수값이라 SSG 가 "Parameter error : [itemDesc] 은 필수값 입니다"
로 거부했다. 그 시점엔 기존 상품을 이미 판매중지시킨 뒤라 상품이 신세계몰에서
통째로 내려간 채 복구되지 않는다(2026-09-03 실측: 2시간 174건 전량 실패).

검증: execute() 내 register_product 폴백 호출 앞에 itemDesc 복원이 존재하는지
소스(AST)로 확인한다. execute 는 session/DB/네트워크 의존이 커 단위 호출이
어려우므로, 두 폴백 경로의 '계약'만 좁게 고정한다.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

from backend.domain.samba.plugins.markets import ssg as ssg_plugin


def _execute_ast() -> ast.AST:
    src = textwrap.dedent(inspect.getsource(ssg_plugin.SSGPlugin.execute))
    return ast.parse(src)


def _assigns_item_desc(node: ast.AST) -> bool:
    """해당 서브트리에서 data["itemDesc"] = ... 대입이 있는지."""
    for n in ast.walk(node):
        if not isinstance(n, ast.Assign):
            continue
        for tgt in n.targets:
            if (
                isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "data"
                and isinstance(tgt.slice, ast.Constant)
                and tgt.slice.value == "itemDesc"
            ):
                return True
    return False


def _fallback_blocks() -> list[ast.AST]:
    """register_product 를 호출하는 폴백 분기(if 문) 목록.

    최상단 `else: register_product`(순수 신규등록)는 itemDesc 를 애초에 빼지
    않으므로 대상에서 제외 — pop 이 일어나는 `if existing_no:` 안쪽만 본다.
    """
    tree = _execute_ast()
    blocks: list[ast.AST] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        calls = [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "register_product"
        ]
        pops = [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "pop"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and n.args[0].value == "itemId"
        ]
        # itemId 를 떼고 register_product 를 부르는 = 재등록 폴백 분기
        if calls and pops:
            blocks.append(node)
    return blocks


def test_reregister_fallback_blocks_exist():
    # 옵션구성변경 / 영구판매중지 두 경로가 살아있어야 한다
    assert len(_fallback_blocks()) >= 2


def test_every_reregister_fallback_restores_item_desc():
    for blk in _fallback_blocks():
        assert _assigns_item_desc(blk), (
            "재등록 폴백에 itemDesc 복원이 없다 — insertItem 이 "
            "'[itemDesc] 은 필수값 입니다' 로 거부되어 상품이 내려간 채 "
            "복구되지 않는다."
        )


def test_light_mode_keeps_dropped_item_desc():
    """경량 모드에서 pop 한 값을 버리지 않고 변수에 보관하는지."""
    src = inspect.getsource(ssg_plugin.SSGPlugin.execute)
    assert '_saved_item_desc = data.pop("itemDesc", None)' in src
