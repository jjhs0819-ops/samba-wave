import asyncio
import sys
from types import ModuleType, SimpleNamespace

import pytest

from backend.domain.samba.shipment import dispatcher


def _install_module(monkeypatch, module_name: str, **attrs):
    module = ModuleType(module_name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, module_name, module)


@pytest.mark.parametrize(
    ("handler_name", "module_name", "client_name", "global_key", "product", "account"),
    [
        (
            "_delete_smartstore",
            "backend.domain.samba.proxy.smartstore",
            "SmartStoreClient",
            "store_smartstore",
            {"market_product_no": {"smartstore": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
        (
            "_delete_coupang",
            "backend.domain.samba.proxy.coupang",
            "CoupangClient",
            "store_coupang",
            {"market_product_no": {"coupang": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
        (
            "_delete_lottehome",
            "backend.domain.samba.proxy.lottehome",
            "LotteHomeClient",
            "store_lottehome",
            {"market_product_no": {"lottehome": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
        (
            "_delete_gsshop",
            "backend.domain.samba.proxy.gsshop",
            "GsShopClient",
            "store_gsshop",
            {"market_product_no": {"gsshop": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
        (
            "_delete_ssg",
            "backend.domain.samba.proxy.ssg",
            "SSGClient",
            "store_ssg",
            {"market_product_no": {"ssg": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
        (
            "_delete_11st",
            "backend.domain.samba.proxy.elevenst",
            "ElevenstClient",
            "store_11st",
            {"market_product_no": {"11st": "prd-1"}},
            SimpleNamespace(
                additional_fields={}, api_key="", api_secret="", seller_id=""
            ),
        ),
    ],
)
def test_explicit_account_delete_does_not_fallback_to_global_settings(
    monkeypatch,
    handler_name,
    module_name,
    client_name,
    global_key,
    product,
    account,
):
    created = {"value": False}

    class DummyClient:
        DEFAULT_SITE_NO = "6005"

        def __init__(self, *args, **kwargs):
            created["value"] = True

        async def delete_product(self, product_no: str):
            return {}

        async def update_sale_status(self, product_no: str, status: str):
            return {}

    attrs = {client_name: DummyClient}
    if module_name.endswith("smartstore"):
        attrs["SmartStoreApiError"] = Exception
    _install_module(monkeypatch, module_name, **attrs)

    async def fake_get_setting(session, key: str):
        if (
            key == global_key
            or (global_key == "store_lottehome" and key == "lottehome_credentials")
            or (global_key == "store_gsshop" and key == "gsshop_credentials")
        ):
            return {
                "apiKey": "GLOBAL_KEY",
                "clientId": "GLOBAL_ID",
                "clientSecret": "GLOBAL_SECRET",
            }
        return None

    monkeypatch.setattr(dispatcher, "_get_setting", fake_get_setting)

    result = asyncio.run(
        getattr(dispatcher, handler_name)(None, product, account=account)
    )

    assert result["success"] is False
    assert created["value"] is False


@pytest.mark.parametrize(
    (
        "handler_name",
        "module_name",
        "client_name",
        "product",
        "account",
        "expected_ctor",
        "expected_kwargs",
    ),
    [
        (
            "_delete_smartstore",
            "backend.domain.samba.proxy.smartstore",
            "SmartStoreClient",
            {"market_product_no": {"smartstore": "prd-1"}},
            SimpleNamespace(
                additional_fields={"clientId": "ACC_ID", "clientSecret": "ACC_SECRET"},
                api_key="",
                api_secret="",
                seller_id="seller-1",
            ),
            ("ACC_ID", "ACC_SECRET"),
            {},
        ),
        (
            "_delete_coupang",
            "backend.domain.samba.proxy.coupang",
            "CoupangClient",
            {"market_product_no": {"coupang": "prd-1"}},
            SimpleNamespace(
                additional_fields={
                    "accessKey": "ACC_ACCESS",
                    "secretKey": "ACC_SECRET",
                    "vendorId": "VENDOR-1",
                },
                api_key="",
                api_secret="",
                seller_id="",
            ),
            ("ACC_ACCESS", "ACC_SECRET", "VENDOR-1"),
            {},
        ),
        (
            "_delete_lottehome",
            "backend.domain.samba.proxy.lottehome",
            "LotteHomeClient",
            {"market_product_no": {"lottehome": "prd-1"}},
            SimpleNamespace(
                additional_fields={
                    "userId": "user1",
                    "password": "pw1",
                    "agncNo": "AG001",
                    "env": "prod",
                },
                api_key="",
                api_secret="",
                seller_id="",
            ),
            ("user1", "pw1", "AG001", "prod"),
            {},
        ),
        (
            "_delete_gsshop",
            "backend.domain.samba.proxy.gsshop",
            "GsShopClient",
            {"market_product_no": {"gsshop": "prd-1"}},
            SimpleNamespace(
                additional_fields={"apiKeyProd": "AES_PROD"},
                api_key="",
                api_secret="",
                seller_id="SUP001",
            ),
            ("SUP001", "AES_PROD", "", "prod"),
            {},
        ),
        (
            "_delete_ssg",
            "backend.domain.samba.proxy.ssg",
            "SSGClient",
            {"market_product_no": {"ssg": "prd-1"}},
            SimpleNamespace(
                additional_fields={"apiKey": "SSG_KEY", "storeId": "7009"},
                api_key="",
                api_secret="",
                seller_id="",
            ),
            ("SSG_KEY",),
            {"site_no": "7009"},
        ),
        (
            "_delete_11st",
            "backend.domain.samba.proxy.elevenst",
            "ElevenstClient",
            {"market_product_no": {"11st": "prd-1"}},
            SimpleNamespace(
                additional_fields={"apiKey": "ELEVEN_KEY"},
                api_key="",
                api_secret="",
                seller_id="",
            ),
            ("ELEVEN_KEY",),
            {},
        ),
    ],
)
def test_explicit_account_delete_uses_account_credentials(
    monkeypatch,
    handler_name,
    module_name,
    client_name,
    product,
    account,
    expected_ctor,
    expected_kwargs,
):
    captured: dict[str, object] = {}

    class DummyClient:
        DEFAULT_SITE_NO = "6005"

        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        async def delete_product(self, product_no: str):
            captured["product_no"] = product_no
            return {}

        async def update_sale_status(self, product_no: str, status: str):
            captured["product_no"] = product_no
            captured["status"] = status
            return {}

    attrs = {client_name: DummyClient}
    if module_name.endswith("smartstore"):
        attrs["SmartStoreApiError"] = Exception
    _install_module(monkeypatch, module_name, **attrs)

    async def fake_get_setting(session, key: str):
        return {"apiKey": "GLOBAL_KEY"}

    monkeypatch.setattr(dispatcher, "_get_setting", fake_get_setting)

    result = asyncio.run(
        getattr(dispatcher, handler_name)(None, product, account=account)
    )

    assert result["success"] is True
    assert captured["args"] == expected_ctor
    assert captured["kwargs"] == expected_kwargs
