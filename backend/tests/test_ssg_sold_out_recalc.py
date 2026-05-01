from pathlib import Path
from types import SimpleNamespace
import asyncio
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.plugins.sourcing.ssg import SSGPlugin
from backend.domain.samba.proxy.sourcing_queue import SourcingQueue
from backend.domain.samba.proxy.ssg_sourcing import SSGSourcingClient


def _install_fake_config(monkeypatch) -> None:
    fake_config = types.SimpleNamespace(
        settings=types.SimpleNamespace(http_timeout_default=5)
    )
    monkeypatch.setitem(sys.modules, "backend.core.config", fake_config)


def test_ssg_layered_select_parser_combines_color_and_size() -> None:
    html = """
    <select id="ordOpt1">
      <option value="">선택하세요.</option>
      <option value="red" selected>01(레드)</option>
    </select>
    <select id="ordOpt2">
      <option value="">선택하세요.</option>
      <option value="200">200</option>
      <option value="210">210</option>
      <option value="215">215(품절)</option>
    </select>
    """

    options = SSGSourcingClient._parse_layered_select_options(html, base_price=125100)

    assert options == [
        {"name": "01(레드)/200", "price": 0, "stock": 99, "isSoldOut": False},
        {"name": "01(레드)/210", "price": 0, "stock": 99, "isSoldOut": False},
        {"name": "01(레드)/215", "price": 0, "stock": 0, "isSoldOut": True},
    ]


def test_ssg_detail_parser_prefers_positive_option_stock_over_item_soldout_flag(
    monkeypatch,
) -> None:
    _install_fake_config(monkeypatch)
    client = SSGSourcingClient()

    monkeypatch.setattr(client, "_extract_uitem_list", lambda _js: [])
    monkeypatch.setattr(client, "_strip_nested_structures", lambda js: js)
    monkeypatch.setattr(
        client,
        "_extract_js_str_field",
        lambda _js, key: {
            "itemNm": "SSG Test Item",
            "soldOut": "Y",
            "repBrandNm": "PUMA",
        }.get(key, ""),
    )
    monkeypatch.setattr(
        client,
        "_extract_js_num_field",
        lambda _js, key: {"sellprc": 125100, "bestAmt": 125100}.get(key, 0),
    )
    monkeypatch.setattr(client, "_extract_dept_sale_price", lambda _html: 125100)
    monkeypatch.setattr(client, "_extract_card_benefit_price", lambda _html: 125100)
    monkeypatch.setattr(client, "_parse_product_notice", lambda _html: {})
    monkeypatch.setattr(client, "_build_images_from_base_url", lambda *_args: [])
    monkeypatch.setattr(client, "_parse_detail_content", lambda _html: ("", []))
    monkeypatch.setattr(
        client,
        "_parse_uitem_options",
        lambda _obj: [{"name": "260", "price": 125100, "stock": 1, "isSoldOut": False}],
    )
    monkeypatch.setattr(
        client, "_parse_layered_select_options", lambda _html, base_price=0: []
    )

    detail = client._parse_result_item_obj(
        "var resultItemObj = { itemNm: 'SSG Test Item' };",
        "1000262887860",
        False,
    )

    assert detail["isOutOfStock"] is False
    assert detail["saleStatus"] == "in_stock"


def test_ssg_refresh_recomputes_sale_status_after_dom_stock_overlay(
    monkeypatch,
) -> None:
    async def _run() -> None:
        _install_fake_config(monkeypatch)
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        future.set_result(
            {
                "success": True,
                "html": "<html></html>",
                "resultItemObj": {"sellprc": 125100, "bestAmt": 125100},
                "domOptions": [{"name": "260", "stock": 1, "isSoldOut": False}],
                "uitemOptions": [],
            }
        )

        monkeypatch.setattr(
            SourcingQueue,
            "add_detail_job",
            staticmethod(lambda *_args, **_kwargs: ("req-1", future)),
        )
        monkeypatch.setattr(
            SSGSourcingClient,
            "_parse_result_item_obj",
            lambda self, _html, _item_id, _refresh_only: {
                "salePrice": 125100,
                "originalPrice": 139000,
                "bestBenefitPrice": 125100,
                "options": [
                    {
                        "name": "260",
                        "price": 125100,
                        "stock": 0,
                        "isSoldOut": True,
                    }
                ],
                "isOutOfStock": True,
                "isSoldOut": True,
            },
        )

        product = SimpleNamespace(
            id="prod-1",
            site_product_id="1000262887860",
            options=[{"name": "260", "price": 125100, "stock": 0, "isSoldOut": True}],
            sale_price=125100,
            sale_status="sold_out",
        )

        result = await SSGPlugin().refresh(product)

        assert result.new_sale_status == "in_stock"
        assert result.new_options == [
            {"name": "260", "price": 125100, "stock": 1, "isSoldOut": False}
        ]

    asyncio.run(_run())
