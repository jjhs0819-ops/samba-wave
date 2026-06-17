"""주문 자동수집 후 역마진(가격X)·재고없음(재고X) 자동 판정 + 상품 갱신 + 메모 기록.

주문수집(poller)이 끝난 뒤 호출된다. 출고 전(활성) 주문 중 수집상품이 연결된 건만 대상으로:
  1) 연결된 소싱 상품을 refresh_products_bulk 로 원소싱처에서 실시간 재조회(오토튠과 동일 엔진)
  2) 최신 원가/재고를 상품 DB(samba_collected_product)에 반영
  3) 역마진(원가×수량 + 배송비 > 정산금액)이면 action_tag 'no_price'(가격X) 추가
  4) 주문 옵션이 품절(또는 상품 전체 품절)이면 action_tag 'no_stock'(재고X) 추가
  5) notes 에 사유 + 시각(KST) 1줄 기록

판정 기준은 "원소싱처 실시간 재조회 후 저장 cost". 값이 불확실한 주문
(price_uncertain / error / needs_extension)은 그 사이클에서 판정 보류한다 — 비로그인가/오류값으로
오판하지 않도록. 다음 사이클에 다시 시도된다.

ABC/SSG/LOTTEON/KREAM 은 정확한 혜택가가 확장앱(DOM) 경로라야 나온다. 확장앱 PC 가 꺼져 있으면
refresh 가 error/needs_extension 으로 떨어지고 → 그 주문은 자동 보류된다.

태그는 add-only — 한 번 붙으면 자동 제거하지 않는다(재입고/가격회복 시 사용자가 수동 해제).
이미 붙어 있는 태그는 건너뛰므로 메모도 중복 기록되지 않는다.
"""

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# 출고 전 활성 상태만 판정 — 이미 발송/취소/반품/완료된 주문은 역마진/재고 판정 의미 없음
_ACTIVE_STATUSES = ("pending", "preparing", "wait_ship", "arrived", "ship_failed")

# 한 번 실행에 재조회할 최대 상품 수 (소싱처 부하/차단 방지)
_MAX_PRODUCTS_PER_RUN = 150
# 조회할 최대 활성 주문 수
_MAX_ORDERS = 1000


def _now_kst_str() -> str:
    """현재 시각을 'YYYY-MM-DD HH:MM:SS KST' 로 반환 (UTC 노출 금지 규칙)."""
    return (datetime.now(timezone.utc) + timedelta(hours=9)).strftime(
        "%Y-%m-%d %H:%M:%S KST"
    )


def _fmt(n: float) -> str:
    """천 단위 콤마 정수 포맷 (메모/로그 숫자 규칙)."""
    try:
        return f"{int(round(float(n))):,}"
    except (TypeError, ValueError):
        return "0"


def _parse_tags(raw: str | None) -> list[str]:
    """action_tag CSV → 토큰 리스트 (빈 토큰 제거)."""
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _find_sold_out_option(product_option: str | None, options) -> str | None:
    """주문 옵션 문자열과 매칭되는 상품 옵션 중 재고 0 이하인 것의 이름을 반환.

    매칭은 옵션 key(name 또는 size)가 주문 옵션 문자열에 포함되는지로 판단한다.
    매칭되는 옵션이 없으면 None (옵션 단위 품절 판정 불가 → 호출부에서 전체품절만 사용).
    """
    if not product_option or not options:
        return None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        key = (opt.get("name") or opt.get("size") or "").strip()
        if not key or key not in product_option:
            continue
        try:
            stock = int(opt.get("stock") or 0)
        except (TypeError, ValueError):
            stock = 0
        if stock <= 0:
            return key
    return None


def _append_note(existing: str | None, line: str) -> str:
    """기존 notes 뒤에 한 줄 추가 (기존 내용 보존)."""
    base = (existing or "").rstrip()
    return f"{base}\n{line}" if base else line


async def auto_check_order_issues(tenant_id: str | None = None) -> dict:
    """활성 주문의 연결 상품을 재조회해 역마진/재고없음을 자동 태깅 + 메모 기록.

    Returns: 처리 요약 dict (검사 주문수/스킵/가격X/재고X 카운트).
    """
    from sqlmodel import col, select

    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.collector.refresher import refresh_products_bulk
    from backend.domain.samba.order.model import SambaOrder

    summary = {"checked": 0, "skipped": 0, "no_price": 0, "no_stock": 0, "errors": 0}

    async with get_write_session() as session:
        # 1) 활성 + 수집상품 연결된 주문 조회
        stmt = select(SambaOrder).where(
            col(SambaOrder.status).in_(_ACTIVE_STATUSES),
            col(SambaOrder.collected_product_id).is_not(None),
        )
        if tenant_id is not None:
            stmt = stmt.where(SambaOrder.tenant_id == tenant_id)
        stmt = stmt.order_by(col(SambaOrder.created_at).desc()).limit(_MAX_ORDERS)
        result = await session.execute(stmt)
        orders = list(result.scalars().all())

        # 이미 가격X·재고X 둘 다 붙은 주문은 더 볼 게 없음 (add-only)
        pending_orders = [
            o
            for o in orders
            if not {"no_price", "no_stock"}.issubset(set(_parse_tags(o.action_tag)))
        ]
        if not pending_orders:
            return summary

        # 2) 검사 대상 상품 distinct (부하 상한 적용)
        product_ids: list[str] = []
        seen: set[str] = set()
        for o in pending_orders:
            pid = o.collected_product_id
            if pid and pid not in seen:
                seen.add(pid)
                product_ids.append(pid)
        truncated = len(product_ids) > _MAX_PRODUCTS_PER_RUN
        if truncated:
            logger.info(
                "[주문이슈체크] 상품 %d개 중 %d개만 이번 사이클 검사 (상한)",
                len(product_ids),
                _MAX_PRODUCTS_PER_RUN,
            )
            product_ids = product_ids[:_MAX_PRODUCTS_PER_RUN]
            _id_set = set(product_ids)
            pending_orders = [
                o for o in pending_orders if o.collected_product_id in _id_set
            ]

        prod_stmt = select(SambaCollectedProduct).where(
            col(SambaCollectedProduct.id).in_(product_ids)
        )
        prod_result = await session.execute(prod_stmt)
        products = list(prod_result.scalars().all())
        if not products:
            return summary

        # LOTTEON benefits API 쿠키 캐시 로드 (refresh 라우트와 동일 사전준비)
        if any(
            (getattr(p, "source_site", "") or "").upper() == "LOTTEON" for p in products
        ):
            try:
                from backend.api.v1.routers.samba.proxy import _get_setting
                from backend.domain.samba.proxy.lotteon_sourcing import (
                    set_lotteon_cookie,
                )

                _lt_ck = await _get_setting(session, "lotteon_cookie")
                if _lt_ck:
                    set_lotteon_cookie(str(_lt_ck))
            except Exception as e:
                logger.warning("[주문이슈체크] LOTTEON 쿠키 로드 실패: %s", e)

        # 설정 읽기 트랜잭션 종료 (idle in transaction 방지)
        try:
            await session.commit()
        except Exception:
            pass

        # 3) 원소싱처 실시간 재조회 (오토튠/수동갱신과 동일 엔진, 자동분기)
        results, _bulk = await refresh_products_bulk(products, source="manual")
        result_map = {r.product_id: r for r in results}
        product_map = {p.id: p for p in products}

        # 4) 상품 DB 최신화 — 신뢰 가능한 결과만 핵심필드 반영 (거대 모니터/재전송 로직은 제외)
        now = datetime.now(timezone.utc)
        for r in results:
            prod = product_map.get(r.product_id)
            if not prod:
                continue
            if r.error or r.needs_extension or r.price_uncertain:
                # 값 불확실 → 상품 cost/재고 덮어쓰지 않음 (stale 보존)
                continue
            if r.new_cost is not None:
                prod.cost = r.new_cost  # type: ignore[assignment]
            if r.new_cost_excl_held_point is not None:
                prod.cost_excl_held_point = r.new_cost_excl_held_point  # type: ignore[assignment]
            if r.new_options is not None:
                prod.options = r.new_options  # type: ignore[assignment]
            if r.new_sale_status:
                prod.sale_status = r.new_sale_status  # type: ignore[assignment]
            if r.changed and r.new_sale_price is not None:
                prod.sale_price = r.new_sale_price  # type: ignore[assignment]
            prod.last_refreshed_at = now  # type: ignore[assignment]
            session.add(prod)

        # 5) 주문별 판정 + 태깅 + 메모
        for o in pending_orders:
            summary["checked"] += 1
            r = result_map.get(o.collected_product_id or "")
            if r is None:
                summary["skipped"] += 1
                continue
            # 값 불확실 → 이번 사이클 보류 (비로그인가/오류값 오판 방지)
            if r.error or r.needs_extension or r.price_uncertain:
                summary["skipped"] += 1
                continue

            tags = _parse_tags(o.action_tag)
            tag_set = set(tags)
            new_notes = o.notes
            changed = False

            qty = int(o.quantity or 1)

            # 역마진(가격X): 원소싱처 원가(단가) × 수량 + 배송비 > 정산금액(revenue)
            if "no_price" not in tag_set and r.new_cost is not None:
                unit_cost = float(r.new_cost or 0)
                revenue = float(o.revenue or 0)
                ship_fee = float(o.shipping_fee or 0)
                if unit_cost > 0 and revenue > 0:
                    line_cost = unit_cost * qty
                    profit = revenue - line_cost - ship_fee
                    if profit < 0:
                        tag_set.add("no_price")
                        new_notes = _append_note(
                            new_notes,
                            f"[{_now_kst_str()}] 자동: 역마진 감지 — 원가 {_fmt(unit_cost)}"
                            f"×{_fmt(qty)}={_fmt(line_cost)} + 배송 {_fmt(ship_fee)} > "
                            f"정산 {_fmt(revenue)} (손익 {_fmt(profit)})",
                        )
                        changed = True
                        summary["no_price"] += 1

            # 재고없음(재고X): 상품 전체 품절 또는 주문 옵션 품절
            if "no_stock" not in tag_set:
                reason: str | None = None
                if r.new_sale_status == "sold_out":
                    reason = "상품 전체 품절"
                else:
                    _opt = _find_sold_out_option(o.product_option, r.new_options)
                    if _opt:
                        reason = f"옵션 품절 ({_opt})"
                if reason:
                    tag_set.add("no_stock")
                    new_notes = _append_note(
                        new_notes,
                        f"[{_now_kst_str()}] 자동: 재고없음 — {reason}",
                    )
                    changed = True
                    summary["no_stock"] += 1

            if changed:
                o.action_tag = ",".join(sorted(tag_set))
                o.notes = new_notes
                session.add(o)

        await session.commit()

    logger.info(
        "[주문이슈체크] 완료 — 검사 %d / 보류 %d / 가격X %d / 재고X %d",
        summary["checked"],
        summary["skipped"],
        summary["no_price"],
        summary["no_stock"],
    )
    return summary
