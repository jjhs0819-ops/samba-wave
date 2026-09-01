"""KREAM 공식 파트너 API 주문 수집 (2026-07-15 정식 API 허가).

옛 경로(발송완료 엑셀 업로드 `/orders/kream-excel` + 샵마인 백필)는 폐기됨(2026-08-01).
이제 이 API 가 유일한 크림 주문 수집 경로. 사고 방지 위해 **생성 전용**이다:
  - 없는 주문만 INSERT
  - 이미 있는 주문은 **건드리지 않음** (정산/원가/송장이 이미 채워져 있을 수 있음)

매핑 (실응답 기준, 추측 아님):
  order_number "A-LI188509289"        → order_number
  order_products[].product_id 652721  → product_id (크림 상품번호)
  order_products[].option "PSA 10"    → product_option
  order_products[].price 108000       → sale_price / revenue
  product_name_kr                     → product_name
  order_date                          → paid_at
  collected_product_id                → SNKRDUNK 수집상품(resell_matches.kream.product_id 역조회)

배송비 8,000 고정·소싱계정(SNKRDUNK)·채널은 엑셀 경로와 동일 규칙 유지.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 수집 대상 상태 — canceled 는 제외(유령 주문 생성 방지)
_SYNC_STATUSES = ("payment_completed", "preparing_package", "delivering", "delivered")

# KREAM order_status → (samba status, shipping_status)
# 크림 delivering 은 크림 바이어측 배송흐름일 뿐, 우리(셀러)는 아직 발송 처리 전 → samba pending
# (미발송 뷰에 떠야 함). delivering→shipping 으로 박으면 미발송 뷰에서 빠져 안 보임
# [2026-07-21 사고: delivering 중 수집된 주문 다수가 shipping 으로 숨겨짐].
_STATUS_MAP: dict[str, tuple[str, str]] = {
    "payment_completed": ("pending", "결제완료"),
    "preparing_package": ("wait_ship", "배송준비중"),
    "delivering": ("pending", "결제완료"),
    "delivered": ("delivered", "배송완료"),
}

_SHIPPING_FEE = 8000.0  # 크림 해외배송 고정 (엑셀 경로와 동일)
_MAX_PAGES = 40  # per_page=50 → 최대 2,000건/상태


def _parse_dt(val: Any) -> Optional[datetime]:
    if not val:
        return None
    try:
        s = str(val).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _tracking_no(order: dict[str, Any]) -> Optional[str]:
    """tracking 객체에서 송장번호 추출 — 스키마 변동 대비 관대하게."""
    t = order.get("tracking")
    if not isinstance(t, dict):
        return None
    for k in ("tracking_code", "tracking_number", "code", "number"):
        v = t.get(k)
        if v:
            return str(v)
    return None


async def sync_kream_orders_from_api(
    tenant_id: Optional[str] = None, dry_run: bool = False
) -> dict:
    """크림 공식 API에서 주문을 받아 없는 것만 생성. 요약 dict 반환.

    dry_run=True 면 아무것도 쓰지 않고 생성 예정 목록만 preview 로 돌려준다.
    """
    from sqlalchemy import func as sfunc
    from sqlalchemy import text as sa_text
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.order.model import SambaOrder
    from backend.domain.samba.proxy.kream import KreamPartnerClient
    from backend.domain.samba.sourcing_account.model import SambaSourcingAccount

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "fetched": 0,
        "created": 0,
        "skipped_exists": 0,
        "unmatched_product": 0,
        "preview": [],
        "errors": [],
    }

    async with get_write_session() as session:
        # 1) KREAM 계정 = channel_id + API 인증정보
        acc_stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.market_type == "kream"
        )
        if tenant_id is not None:
            acc_stmt = acc_stmt.where(SambaMarketAccount.tenant_id == tenant_id)
        # [2026-09-01 사고수정] 크림 계정 **전부** 순회.
        # 종전 first() 는 첫 계정(JP=스니덩크)만 동기화해, CN(식화) 계정 주문이
        # 삼바 주문페이지에 통째로 안 들어왔다(일본상품 CN오등록 사고 주문 포함).
        kream_accs = (await session.execute(acc_stmt)).scalars().all()
        if not kream_accs:
            summary["errors"].append("KREAM 계정 없음 — 설정>스토어연결에서 등록 필요")
            return summary

        # tenant_id 미지정(자동수집 루프 lifecycle.py 가 인자 없이 호출) 시 KREAM 계정의
        # tenant 로 채운다. 안 하면 생성 주문 tenant_id=None → 테넌트 필터 주문페이지에 안 보임
        # [2026-07-21 사고: 자동수집분 6건 tenant None 으로 숨겨짐].
        if tenant_id is None:
            tenant_id = kream_accs[0].tenant_id

        # 2) 소싱계정(SNKRDUNK) — 원가 역조회용(계정 무관, 1회만)
        snkr_stmt = (
            select(SambaSourcingAccount.id)
            .where(
                sfunc.upper(SambaSourcingAccount.site_name) == "SNKRDUNK",
                SambaSourcingAccount.is_active.is_(True),
            )
            .order_by(
                SambaSourcingAccount.is_login_default.desc(),
                SambaSourcingAccount.created_at,
            )
        )
        if tenant_id is not None:
            snkr_id = (
                (
                    await session.execute(
                        snkr_stmt.where(SambaSourcingAccount.tenant_id == tenant_id)
                    )
                )
                .scalars()
                .first()
            )
        else:
            snkr_id = None
        if not snkr_id:
            snkr_id = (await session.execute(snkr_stmt)).scalars().first()

        # 3) 계정별 상태별 페이지네이션 수집 (모든 크림 계정)
        raw: list[tuple[dict, dict, Any]] = []  # (order, order_product, kream_acc)
        for kream_acc in kream_accs:
            ext = (
                kream_acc.additional_fields
                if isinstance(kream_acc.additional_fields, dict)
                else {}
            )
            api_service = str(ext.get("apiService") or "")
            api_key = str(ext.get("apiKey") or kream_acc.api_key or "")
            api_secret = str(ext.get("apiSecret") or kream_acc.api_secret or "")
            if not (api_service and api_key and api_secret):
                summary["errors"].append(
                    f"{kream_acc.account_label or kream_acc.id}: API 인증정보 없음 — 건너뜀"
                )
                continue
            client = KreamPartnerClient(api_service, api_key, api_secret)
            for status in _SYNC_STATUSES:
                page = 1
                while page <= _MAX_PAGES:
                    code, body = await client.list_orders(
                        status, page=page, per_page=50
                    )
                    if code != 200 or not isinstance(body, dict):
                        if page == 1:
                            summary["errors"].append(
                                f"{kream_acc.account_label or kream_acc.id}/{status}: HTTP {code}"
                            )
                        break
                    items = body.get("items") or []
                    if not items:
                        break
                    for od in items:
                        for op in od.get("order_products") or []:
                            raw.append((od, op, kream_acc))
                    if len(items) < 50:
                        break
                    page += 1
        summary["fetched"] = len(raw)
        if not raw:
            return summary

        # 4) 크림 상품번호 → SNKRDUNK 수집상품 역조회 (엑셀 경로 cp_map 과 동일)
        kream_pids = sorted(
            {str(op.get("product_id")) for _od, op, _ac in raw if op.get("product_id")}
        )
        cp_map: dict[str, str] = {}
        if kream_pids:
            tid_cond = "AND tenant_id = :tid" if tenant_id is not None else ""
            bind: dict[str, Any] = {"pids": kream_pids}
            if tenant_id is not None:
                bind["tid"] = tenant_id
            rows = await session.execute(
                sa_text(
                    f"""
                    SELECT id, resell_matches->'kream'->>'product_id' AS kream_pid
                    FROM samba_collected_product
                    WHERE source_site IN ('SNKRDUNK', 'SHIHUO')
                      AND resell_matches->'kream'->>'product_id' = ANY(:pids)
                      {tid_cond}
                    """
                ),
                bind,
            )
            for r in rows.mappings():
                cp_map[str(r["kream_pid"])] = str(r["id"])

        # 5) 기존 주문번호 — 있는 건 절대 건드리지 않음
        onums = sorted(
            {
                str(od.get("order_number"))
                for od, _op, _ac in raw
                if od.get("order_number")
            }
        )
        existing: set[str] = set()
        if onums:
            ex_stmt = select(SambaOrder.order_number).where(
                SambaOrder.order_number.in_(onums)
            )
            if tenant_id is not None:
                ex_stmt = ex_stmt.where(SambaOrder.tenant_id == tenant_id)
            existing = {
                str(x) for x in (await session.execute(ex_stmt)).scalars().all()
            }

        # 6) 생성
        for od, op, kream_acc in raw:
            onum = str(od.get("order_number") or "")
            if not onum or onum in existing:
                summary["skipped_exists"] += 1
                continue
            existing.add(onum)  # 같은 배치 내 중복 방지

            kream_pid = str(op.get("product_id") or "")
            cp_id = cp_map.get(kream_pid)
            if not cp_id:
                summary["unmatched_product"] += 1

            st, ship_st = _STATUS_MAP.get(
                str(op.get("order_status") or ""), ("pending", "결제완료")
            )
            price = float(op.get("price") or 0)
            qty = int(op.get("quantity") or 1)

            if dry_run:
                summary["created"] += 1
                if len(summary["preview"]) < 20:
                    summary["preview"].append(
                        {
                            "order_number": onum,
                            "kream_pid": kream_pid,
                            "option": str(op.get("option") or ""),
                            "price": price,
                            "status": st,
                            "cp_matched": bool(cp_id),
                            "name": str(op.get("product_name_kr") or "")[:30],
                        }
                    )
                continue

            session.add(
                SambaOrder(
                    tenant_id=tenant_id,
                    order_number=onum,
                    channel_id=kream_acc.id,
                    channel_name="KREAM",
                    source_site="KREAM",
                    product_id=kream_pid or None,
                    product_name=str(
                        op.get("product_name_kr") or op.get("product_name") or ""
                    ),
                    product_option=str(op.get("option") or ""),
                    quantity=qty,
                    sale_price=price,
                    # 정산금액 = 결제금액 (크림 해외판매 — 마켓수수료 별도, 엑셀 경로와 동일)
                    revenue=price,
                    cost=0.0,
                    shipping_fee=_SHIPPING_FEE,
                    profit=0.0,
                    tracking_number=_tracking_no(od),
                    paid_at=_parse_dt(od.get("order_date")),
                    status=st,
                    shipping_status=ship_st,
                    shipping_company="허브넷로지스틱스",
                    collected_product_id=cp_id,
                    sourcing_account_id=snkr_id,
                )
            )
            summary["created"] += 1

        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    logger.info(
        "[크림API주문] 조회 %d / 생성 %d / 기존 %d / 미매칭 %d",
        summary["fetched"],
        summary["created"],
        summary["skipped_exists"],
        summary["unmatched_product"],
    )
    return summary
