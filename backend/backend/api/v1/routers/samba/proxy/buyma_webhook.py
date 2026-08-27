"""BUYMA PS-API webhook 수신 — HMAC 서명 검증 후 주문/상품 이벤트 반영.

BUYMA는 우리 게이트웨이의 X-Api-Key를 보내지 않으므로 이 경로는 면제 등록이
필요하고(api_gateway._EXEMPT_PATHS), 대신 라우트가 직접 서명을 검증한다.
검증은 선택이 아니라 필수다 — order/create 페이로드에 구매자 실명·주소·전화가
들어오기 때문에, 서명 없는 요청이 그대로 들어오면 아무나 우리 DB에 가짜 주문을
넣거나 이 URL을 아는 것만으로 PII 경로를 흉내낼 수 있다.

서명: base64(HMAC-SHA256(앱 시크릿, 원문 바디)) == X-Buyma-Hmac-Sha256
     (BUYMA 공식 스펙의 Ruby 예제와 동일. 반드시 raw body 로 계산해야 하며
      json 파싱 후 재직렬화하면 공백·키순서가 달라져 서명이 깨진다.)

앱이 계정마다 다르므로(캐논/임형준) 어느 앱에서 온 요청인지는 서명이 맞는
시크릿으로 역판별한다. seller_id 로 먼저 찾지 않는 이유는, 그러려면 서명
검증 전에 바디를 신뢰해야 하기 때문이다.

BUYMA는 응답이 5초를 넘거나 200이 아니면 재시도한다(상품 1시간 5회 /
주문 24시간 10회). 그래서 여기서는 DB 반영까지만 하고 무거운 후속 작업은
하지 않는다. 처리 중 예외가 나도 200을 돌려주지 않는다 — 재시도를 받아야
이벤트를 잃지 않는다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.utils.logger import logger

buyma_webhook_router = APIRouter(prefix="/buyma", tags=["samba-proxy-buyma-webhook"])

# 스펙상 상품/주문 이벤트 전체
_PRODUCT_OK = {"product/create", "product/update"}
_PRODUCT_FAIL = {"product/fail_to_create", "product/fail_to_update"}
_ORDER_OK = {"order/create", "order/update"}
_ORDER_FAIL = {"order/fail_to_update"}


def _sign(secret: str, body: bytes) -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    ).decode("ascii")


async def _verify(session: AsyncSession, body: bytes, header_sig: str):
    """서명이 맞는 BUYMA 계정을 찾아 반환. 못 찾으면 None.

    테넌트를 모르는 상태로 들어오므로 활성 buyma 계정 전체를 대상으로 돈다.
    계정 수가 한 자릿수라 비용은 무시할 수준이고, compare_digest 로 비교해
    타이밍 차이로 시크릿을 캐내지 못하게 한다.
    """
    from backend.domain.samba.account.model import SambaMarketAccount

    rows = (
        (
            await session.execute(
                select(SambaMarketAccount)
                .where(SambaMarketAccount.market_type == "buyma")
                .where(SambaMarketAccount.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )

    for acc in rows:
        secret = (acc.api_secret or "").strip()
        if not secret:
            continue
        if hmac.compare_digest(_sign(secret, body), header_sig):
            return acc
    return None


def _parse_dt(v: Any) -> Optional[datetime]:
    """BUYMA는 이벤트마다 '2019-10-10 14:42:57 +0900' 과 ISO8601을 섞어 보낸다."""
    if not v or not isinstance(v, str):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _recipient_name(r: dict[str, Any]) -> str:
    """수취인 표시명 — 한자 > 카나 > 로마자 순. 일본 배송 라벨은 한자가 정본."""
    for last, first in (
        ("last_name_kanji", "first_name_kanji"),
        ("last_name_kana", "first_name_kana"),
        ("last_name", "first_name"),
    ):
        ln, fn = (r.get(last) or "").strip(), (r.get(first) or "").strip()
        if ln or fn:
            return f"{ln} {fn}".strip()
    return ""


def _recipient_address(r: dict[str, Any]) -> str:
    """주소 — 한자 필드가 있으면 그쪽을, 없으면 로마자 필드를 이어붙인다."""
    kanji = [
        (r.get(k) or "").strip()
        for k in ("address_kanji_1", "address_kanji_2", "address_kanji_3")
    ]
    if any(kanji):
        return " ".join(x for x in kanji if x)
    romaji = [
        (r.get(k) or "").strip()
        for k in ("address_4", "address_3", "address_2", "address_1")
    ]
    return " ".join(x for x in romaji if x)


async def _handle_order(session: AsyncSession, acc, payload: dict[str, Any]) -> str:
    """order/create·update → samba_order upsert. 키는 (tenant, order_number)."""
    from backend.domain.samba.order.model import SambaOrder

    order_id = str(payload.get("id") or "")
    if not order_id:
        return "no_order_id"

    row = (
        (
            await session.execute(
                select(SambaOrder)
                .where(SambaOrder.tenant_id == acc.tenant_id)
                .where(SambaOrder.order_number == order_id)
                .where(SambaOrder.source == "buyma")
            )
        )
        .scalars()
        .first()
    )

    prod = payload.get("product") or {}
    rec = payload.get("recipient") or {}
    ship = payload.get("order_shipment") or {}
    amount = int(payload.get("amount") or 1)
    unit = float(payload.get("unit_price") or 0)

    fields = {
        "channel_id": acc.id,
        "channel_name": acc.account_label or "BUYMA",
        "source": "buyma",
        # reference_number 는 우리가 등록 때 넣은 값(수집상품 식별자)이라
        # 상품관리 백필·오토튠이 이걸로 원본 상품을 되찾는다.
        "ext_order_number": str(prod.get("reference_number") or ""),
        "product_id": str(prod.get("id") or ""),
        "product_name": prod.get("name") or "",
        "product_option": payload.get("color_size_text") or "",
        "customer_name": _recipient_name(rec),
        "customer_phone": (rec.get("phone_number") or "").strip(),
        "customer_address": _recipient_address(rec),
        "customer_postal_code": (rec.get("zip_code") or "").strip(),
        "customer_note": payload.get("order_message") or "",
        "quantity": amount,
        "sale_price": unit,
        "total_payment_amount": float(payload.get("subtotal_price") or unit * amount),
        "status": str(payload.get("status") or ""),
        "tracking_number": (ship.get("tracking_number") or "").strip() or None,
        "shipping_company": (ship.get("service_name") or "").strip() or None,
        "paid_at": _parse_dt(payload.get("ordered_at")),
        "ship_by_at": _parse_dt(payload.get("shipping_deadline")),
        "shipped_at": _parse_dt(ship.get("shipped_at")),
        "delivered_at": _parse_dt(ship.get("received_at")),
    }

    if row is None:
        row = SambaOrder(tenant_id=acc.tenant_id, order_number=order_id, **fields)
        session.add(row)
        result = "created"
    else:
        for k, v in fields.items():
            # 이미 채워진 송장/배송사를 빈 값으로 덮지 않는다 —
            # order/update 가 배송 전 상태로도 오기 때문.
            if v in (None, "") and getattr(row, k, None):
                continue
            setattr(row, k, v)
        session.add(row)
        result = "updated"

    await session.commit()
    return result


async def _handle_product(session: AsyncSession, acc, payload: dict[str, Any]) -> str:
    """product/create·update → 수집상품에 BUYMA 상품ID 기록.

    등록 요청 응답에는 상품ID가 없고(request_uid만 옴) 이 webhook 으로만
    내려온다. 여기서 안 붙잡으면 나중에 수정·정지·삭제할 때 상품을 못 찾는다.
    """
    from backend.domain.samba.collector.model import (
        SambaCollectedProduct,
        as_market_nos,
    )

    ref = str(payload.get("reference_number") or "")
    pid = str(payload.get("id") or "")
    if not ref or not pid:
        return "no_ref_or_id"

    row = (
        (
            await session.execute(
                select(SambaCollectedProduct).where(SambaCollectedProduct.id == ref)
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        row = (
            (
                await session.execute(
                    select(SambaCollectedProduct).where(
                        SambaCollectedProduct.site_product_id == ref
                    )
                )
            )
            .scalars()
            .first()
        )
    if row is None:
        logger.warning(f"[바이마webhook] 수집상품 못 찾음 ref={ref} buyma_id={pid}")
        return "product_not_found"

    nos = as_market_nos(row.market_product_nos)
    nos[acc.id] = pid
    row.market_product_nos = nos

    accounts = list(row.registered_accounts or [])
    # 공개 상태일 때만 등록됨으로 본다 — 오토튠이 이 값으로 감시 대상을 고르므로
    # 정지/삭제된 건을 남겨두면 없는 상품에 재고 갱신을 쏜다.
    if str(payload.get("status") or "") == "public":
        if acc.id not in accounts:
            accounts.append(acc.id)
    elif acc.id in accounts:
        accounts.remove(acc.id)
    row.registered_accounts = accounts

    session.add(row)
    await session.commit()
    return "linked"


@buyma_webhook_router.post("/webhook")
async def buyma_webhook(
    request: Request,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    body = await request.body()
    event = request.headers.get("X-Buyma-Event", "")
    sig = request.headers.get("X-Buyma-Hmac-Sha256", "")

    if not sig:
        logger.warning(f"[바이마webhook] 서명 헤더 없음 event={event}")
        return JSONResponse({"error": "missing signature"}, status_code=401)

    acc = await _verify(session, body, sig)
    if acc is None:
        # 바디는 남기지 않는다 — 검증에 실패한 요청이라 PII 여부를 신뢰할 수 없다.
        logger.warning(f"[바이마webhook] 서명 불일치 event={event} bytes={len(body)}")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    import json

    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        logger.warning(f"[바이마webhook] JSON 파싱 실패 event={event}")
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if event in _ORDER_OK:
        result = await _handle_order(session, acc, payload)
        logger.info(
            f"[바이마webhook] {event} order={payload.get('id')} "
            f"status={payload.get('status')} → {result}"
        )
    elif event in _PRODUCT_OK:
        result = await _handle_product(session, acc, payload)
        logger.info(
            f"[바이마webhook] {event} ref={payload.get('reference_number')} "
            f"buyma_id={payload.get('id')} → {result}"
        )
    elif event in _PRODUCT_FAIL or event in _ORDER_FAIL:
        # 등록/수정 실패는 한도를 이미 소모한 뒤라, 왜 깨졌는지 남겨야
        # 같은 실수로 재전송을 반복하지 않는다.
        logger.warning(
            f"[바이마webhook] {event} uid={payload.get('request_uid')} "
            f"errors={payload.get('errors')}"
        )
    elif event == "product/bulk_variants_update_requested":
        logger.info(
            f"[바이마webhook] {event} uid={payload.get('request_uid')} "
            f"count={len(payload.get('products') or [])}"
        )
    else:
        logger.warning(f"[바이마webhook] 미지원 이벤트 event={event}")

    return {"ok": True}
