"""이종영 누락 주문 강제 수집 + DB INSERT.

가디(enclehhg@naver.com) productOrderId=2026051197491491 수동 수집.
_parse_smartstore_order를 인라인 복제 — router import 시 circular 발생.
"""

import asyncio
import sys
from datetime import datetime
from typing import Any

sys.path.insert(0, "/app/backend")

from sqlalchemy import text

from backend.db.orm import get_write_session
from backend.domain.samba.proxy.smartstore import SmartStoreClient
from backend.domain.samba.order.repository import SambaOrderRepository
from backend.domain.samba.order.model import SambaOrder


TARGET_PRODUCT_ORDER_ID = "2026051197491491"


def _parse_iso_datetime(val):
    if not val:
        return None
    try:
        return datetime.fromisoformat(val.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _parse_smartstore_order(
    po: dict,
    order_info: dict,
    account_id: str,
    account_label: str,
    claim_info: dict | None = None,
) -> dict[str, Any]:
    status_map = {
        "PAYED": "pending",
        "DELIVERING": "shipped",
        "DELIVERED": "delivered",
        "PURCHASE_DECIDED": "delivered",
        "EXCHANGED": "delivered",
        "CANCELED": "cancelled",
        "RETURNED": "returned",
        "CANCEL_REQUESTED": "pending",
    }
    naver_status = po.get("productOrderStatus", "")
    place_status = po.get("placeOrderStatus", "")
    sale_price = po.get("totalPaymentAmount", 0) or po.get("unitPrice", 0) or 0
    quantity = po.get("quantity", 1) or 1

    _ci = claim_info or {}
    claim_status = _ci.get("claimStatus") or po.get("claimStatus", "") or ""

    claim_status_map = {
        "CANCEL_REQUEST": "취소요청",
        "CANCELING": "취소처리중",
        "CANCEL_DONE": "취소완료",
        "CANCEL_REJECT": "취소거부",
        "RETURN_REQUEST": "반품요청",
        "COLLECTING": "수거중",
        "COLLECT_DONE": "수거완료",
        "RETURN_DONE": "반품완료",
        "RETURN_REJECT": "반품거부",
        "EXCHANGE_REQUEST": "교환요청",
        "EXCHANGING": "교환처리중",
        "EXCHANGE_DONE": "교환완료",
        "EXCHANGE_REJECT": "교환거부",
    }

    expected_settlement = po.get("expectedSettlementAmount")
    if expected_settlement and sale_price > 0:
        fee_rate = round((1 - expected_settlement / sale_price) * 100, 2)
    else:
        expected_settlement = None
        fee_rate = 0

    market_status_map = {
        "PAYED": "결제완료",
        "DELIVERING": "배송중",
        "DELIVERED": "배송완료",
        "PURCHASE_DECIDED": "구매확정",
        "EXCHANGED": "교환완료",
        "CANCELED": "취소완료",
        "RETURNED": "반품완료",
    }
    if claim_status and claim_status in claim_status_map:
        market_order_status = claim_status_map[claim_status]
    elif place_status == "NOT_YET" and naver_status == "PAYED":
        market_order_status = "발주미확인"
    elif naver_status == "PAYED":
        market_order_status = "발송대기"
    else:
        market_order_status = market_status_map.get(naver_status, naver_status)

    shipping = po.get("shippingAddress", {})
    customer_name = shipping.get("name", "") or order_info.get("ordererName", "")
    customer_tel = (
        shipping.get("tel1", "")
        or shipping.get("tel2", "")
        or order_info.get("ordererTel", "")
    )
    channel_product_no = str(
        po.get("channelProductNo", "") or po.get("productId", "") or ""
    )

    return {
        "order_number": po.get("productOrderId", ""),
        "shipment_id": order_info.get("orderId", ""),
        "channel_id": account_id,
        "channel_name": account_label,
        "product_id": channel_product_no,
        "product_name": po.get("productName", ""),
        "product_option": po.get("productOption", "") or "",
        "product_image": po.get("imageUrl", ""),
        "customer_name": customer_name,
        "orderer_name": order_info.get("ordererName", "") or "",
        "customer_phone": customer_tel,
        "customer_address": (shipping.get("baseAddress", "") or "").strip(),
        "customer_address_detail": (shipping.get("detailedAddress", "") or "").strip(),
        "customer_note": po.get("shippingMemo", "") or "",
        "quantity": quantity,
        "sale_price": sale_price,
        "cost": 0,
        "fee_rate": fee_rate,
        "revenue": expected_settlement if expected_settlement else sale_price,
        "status": (
            "cancel_requested"
            if claim_status in ("CANCEL_REQUEST", "CANCELING")
            else (
                "cancelled"
                if claim_status == "CANCEL_DONE"
                else (
                    "return_requested"
                    if claim_status in ("RETURN_REQUEST", "COLLECTING", "COLLECT_DONE")
                    else (
                        "returned"
                        if claim_status == "RETURN_DONE"
                        else status_map.get(naver_status, "pending")
                    )
                )
            )
        ),
        "shipping_status": market_order_status,
        "shipping_company": po.get("deliveryCompany", ""),
        "tracking_number": po.get("trackingNumber", ""),
        "paid_at": _parse_iso_datetime(
            order_info.get("paymentDate") or po.get("paymentDate")
        ),
        "source": "smartstore",
    }


async def main():
    async with get_write_session() as session:
        row = await session.execute(
            text(
                """
                SELECT id, market_name, additional_fields->>'clientId' AS cid,
                       additional_fields->>'clientSecret' AS csec, tenant_id
                FROM samba_market_account
                WHERE market_type='smartstore' AND seller_id='enclehhg@naver.com'
                """
            )
        )
        rec = row.fetchone()
        if not rec:
            print("ERROR: 가디 계정 없음")
            return
        acc_id, market_name, cid, csec, tenant_id = rec
        label = f"{market_name}(enclehhg@naver.com)"
        print(f"가디 account_id={acc_id}, tenant_id={tenant_id}")

        dup = await session.execute(
            text("SELECT id FROM samba_order WHERE order_number = :on"),
            {"on": TARGET_PRODUCT_ORDER_ID},
        )
        if dup.fetchone():
            print("이미 DB에 존재 — 중단")
            return

        client = SmartStoreClient(cid, csec)
        raws = await client.get_product_orders_by_ids([TARGET_PRODUCT_ORDER_ID])
        if not raws:
            print("ERROR: API에서 주문 없음")
            return
        print(f"API 응답 {len(raws)}건")

        ro = raws[0]
        po = ro.get("productOrder", ro)
        order_info = ro.get("order", {})
        claim_info = (
            ro.get("claim")
            or ro.get("cancel")
            or ro.get("currentClaim")
            or po.get("claim")
            or {}
        )

        data = _parse_smartstore_order(po, order_info, acc_id, label, claim_info=claim_info)
        if tenant_id:
            data["tenant_id"] = tenant_id

        valid_keys = set(SambaOrder.model_fields.keys())
        cleaned = {k: v for k, v in data.items() if k in valid_keys}
        dropped = set(data.keys()) - valid_keys
        if dropped:
            print(f"WARN: 모델에 없는 키 제거 {dropped}")

        print("=" * 80)
        print("INSERT 대상 (요약):")
        for k in (
            "order_number",
            "shipment_id",
            "customer_name",
            "orderer_name",
            "channel_id",
            "product_name",
            "quantity",
            "sale_price",
            "revenue",
            "shipping_status",
            "paid_at",
            "customer_address",
            "customer_phone",
        ):
            print(f"  {k}: {cleaned.get(k)}")
        print("=" * 80)

        repo = SambaOrderRepository(session)
        created = await repo.create_async(**cleaned)
        print(f"INSERT 완료 — samba_order.id={created.id}")

        chk = await session.execute(
            text(
                "SELECT id, order_number, customer_name, orderer_name, paid_at, "
                "shipping_status, channel_id FROM samba_order WHERE order_number = :on"
            ),
            {"on": TARGET_PRODUCT_ORDER_ID},
        )
        for r in chk.fetchall():
            print("VERIFY:", dict(r._mapping))


asyncio.run(main())
