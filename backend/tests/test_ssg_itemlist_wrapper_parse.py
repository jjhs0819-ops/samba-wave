"""SSG getItemList 래퍼 리스트 파싱 회귀 테스트 (2026-08-04).

실응답이 items: [{"item": [...]}] (래퍼 리스트) 형태일 때 기존 파서는
리스트 길이(=1)를 상품 수로 오인해 유령 대조가 무력화됐다(market_total=1).
래퍼를 언랩해 전체 상품이 나열되는지 검증한다.
"""

from __future__ import annotations

import asyncio
import os

# settings import 가 DB env 를 요구 — 더미 주입 (기존 테스트 패턴)
for _k, _v in {
    "WRITE_DB_USER": "u",
    "WRITE_DB_PASSWORD": "p",
    "WRITE_DB_HOST": "localhost",
    "WRITE_DB_PORT": "5432",
    "WRITE_DB_NAME": "d",
    "READ_DB_USER": "u",
    "READ_DB_PASSWORD": "p",
    "READ_DB_HOST": "localhost",
    "READ_DB_PORT": "5432",
    "READ_DB_NAME": "d",
    "JWT_SECRET_KEY": "x",
}.items():
    os.environ.setdefault(_k, _v)

from backend.domain.samba.proxy.ssg import SSGClient  # noqa: E402


def _fake_resp(n, page_size=100):
    items = [
        {
            "itemId": f"I{i}",
            "splVenItemId": f"cp_{i}",
            "sellStatCd": "20",
            "itemNm": f"상품{i}",
        }
        for i in range(n)
    ]
    return {"result": {"resultCode": "SUCCESS", "items": [{"item": items}]}}


def test_list_live_items_unwraps_wrapper_list(monkeypatch):
    client = SSGClient("k")
    pages = [_fake_resp(100), _fake_resp(37)]
    calls = {"n": 0}

    async def fake_call(method, path, params=None, **kw):
        resp = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return resp

    monkeypatch.setattr(client, "_call_api", fake_call)
    out = asyncio.run(client.list_live_items())
    assert len(out) == 137
    assert out[0]["itemId"] == "I0"


def test_get_product_count_unwraps_wrapper_list(monkeypatch):
    client = SSGClient("k")
    pages = [_fake_resp(100), _fake_resp(5)]
    calls = {"n": 0}

    async def fake_call(method, path, params=None, **kw):
        resp = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return resp

    monkeypatch.setattr(client, "_call_api", fake_call)
    assert asyncio.run(client.get_product_count()) == 105


def test_find_live_item_id_unwraps_wrapper_list(monkeypatch):
    """안정키(splVenItemId) 검색도 래퍼 리스트를 언랩해야 한다 — #699 누락분 회귀.

    래퍼를 상품으로 오인하면 항상 미발견 → 멱등가드 무력화 → 재전송이
    "동일상품 존재" __exists__ 마커로 전락 (8/5 스케쳐스 파일럿 실사고).
    """
    client = SSGClient("k")

    async def fake_call(method, path, params=None, **kw):
        return _fake_resp(3)

    monkeypatch.setattr(client, "_call_api", fake_call)
    assert asyncio.run(client.find_live_item_id_by_spl_ven("cp_1")) == "I1"
    assert asyncio.run(client.find_live_item_id_by_spl_ven("cp_없음")) == ""


def test_find_live_item_id_excludes_deleted(monkeypatch):
    client = SSGClient("k")
    resp = {
        "result": {
            "resultCode": "SUCCESS",
            "items": [
                {
                    "item": [
                        {
                            "itemId": "I9",
                            "splVenItemId": "cp_9",
                            "sellStatCd": "90",
                            "itemNm": "삭제됨",
                        }
                    ]
                }
            ],
        }
    }

    async def fake_call(method, path, params=None, **kw):
        return resp

    monkeypatch.setattr(client, "_call_api", fake_call)
    assert asyncio.run(client.find_live_item_id_by_spl_ven("cp_9")) == ""
