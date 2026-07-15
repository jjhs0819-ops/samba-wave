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

# pending(주문접수) + wait_ship(배송대기중) 상태만 판정.
# GS샵 등 마켓에서 발주확인(301) 상태로 수집되면 wait_ship으로 저장되므로 포함.
_ACTIVE_STATUSES = ("pending", "wait_ship")

# ABC/GrandStage = 혜택가가 판매가와 분리(#421) + 배송비 별도. 역마진 판정 시 배송비 가산.
_ABC_FAMILY = {"ABCMART", "GRANDSTAGE"}
_ABC_SHIPPING = 2300

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

    매칭은 옵션 key(name 또는 size)가 주문 옵션 문자열에 단어 경계 기준으로 포함되는지 판단한다.
    단순 in 비교 시 "S" in "XS" = True 오판 발생 → regex 단어 경계로 방지.
    매칭되는 옵션이 없으면 None (옵션 단위 품절 판정 불가 → 호출부에서 전체품절만 사용).
    """
    import re

    if not product_option or not options:
        return None
    for opt in options:
        if not isinstance(opt, dict):
            continue
        key = (opt.get("name") or opt.get("size") or "").strip()
        if not key:
            continue
        # 단어 경계 매칭: XS 주문에 S 옵션이 걸리지 않도록 (S in XS = True 오판 방지)
        if not re.search(
            r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])", product_option
        ):
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
    from sqlmodel import col, or_, select

    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.collector.refresher import refresh_products_bulk
    from backend.domain.samba.order.model import SambaOrder

    summary = {
        "checked": 0,
        "skipped": 0,
        "no_price": 0,
        "no_stock": 0,
        "auto_delivered": 0,
        "errors": 0,
    }

    # 정산금액 1,000원 미만 주문 → 소액 처리비만 남는 건으로 배송완료 자동 처리
    _AUTO_DELIVER_THRESHOLD = 1000

    async with get_write_session() as session:
        # 1) 활성 + 수집상품 연결된 주문 조회
        # 이미 소싱처에 발주(주문처리)된 건은 제외 — 발주 시 실제 매입가가 확정되므로
        # refresh 한 현재가로 재판정하면 오판(예: ABC 는 #421 로 cost=판매가라 혜택가보다
        # 과대계상 → 흑자 주문을 역마진으로 오판). sourcing_order_number 있으면 주문처리 완료.
        stmt = select(SambaOrder).where(
            col(SambaOrder.status).in_(_ACTIVE_STATUSES),
            col(SambaOrder.collected_product_id).is_not(None),
            or_(
                col(SambaOrder.sourcing_order_number).is_(None),
                col(SambaOrder.sourcing_order_number) == "",
            ),
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
        # 역마진 감지된 상품 ID 수집 → 오토튠 우선 처리용
        no_price_product_ids: set[str] = set()
        # 재고없음 감지된 상품 ID 수집 → 즉시 마켓 품절 전송용
        no_stock_product_ids: set[str] = set()
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
            # last_refreshed_at: 역마진/재고없음 감지 상품은 오토튠이 다음 사이클에서
            # 최우선 처리하도록 2일 과거로 설정. 정상 상품만 now로 기록.
            prod.last_refreshed_at = now  # type: ignore[assignment]  # 5)에서 no_price 확인 후 재설정
            # 가격이력 스냅샷 추가 (UI 가격/재고 이력에 표시되도록)
            _snapshot = {
                "date": now.isoformat(),
                "source": "order-issue-check",
                "sale_price": r.new_sale_price
                if r.new_sale_price is not None
                else getattr(prod, "sale_price", None),
                "cost": r.new_cost
                if r.new_cost is not None
                else getattr(prod, "cost", None),
                "sale_status": r.new_sale_status,
                "changed": r.changed,
                "options": r.new_options
                if r.new_options is not None
                else getattr(prod, "options", None),
            }
            _history = list(getattr(prod, "price_history", None) or [])
            _history.insert(0, _snapshot)
            prod.price_history = _history[:200]  # type: ignore[assignment]
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
            prod = product_map.get(o.collected_product_id or "")
            site_u = (getattr(prod, "source_site", "") or "").upper() if prod else ""
            is_abc = site_u in _ABC_FAMILY

            # 역마진(가격X): "혜택가" 기준. 대부분 사이트는 new_cost 자체가 혜택가.
            # ABC/GrandStage 는 new_cost=판매가(#421)라 혜택가(new_benefit_cost)를 별도로 쓰고,
            # ABC 혜택가는 배송 미포함이라 배송비 2,300 을 가산한다.
            # ABC 혜택가를 못 얻으면(new_benefit_cost None) 판매가로 오판하지 않도록 보류.
            if is_abc:
                benefit = (
                    float(r.new_benefit_cost)
                    if r.new_benefit_cost is not None
                    else None
                )
            else:
                benefit = float(r.new_cost) if r.new_cost is not None else None

            if "no_price" not in tag_set and benefit is not None and benefit > 0:
                revenue = float(o.revenue or 0)
                ship_add = _ABC_SHIPPING if is_abc else 0
                if revenue > 0:
                    line_cost = benefit * qty
                    effective = line_cost + ship_add
                    profit = revenue - effective
                    if profit < 0:
                        tag_set.add("no_price")
                        _ship_txt = f" + 배송 {_fmt(ship_add)}" if ship_add else ""
                        new_notes = _append_note(
                            new_notes,
                            f"[{_now_kst_str()}] 자동: 역마진 감지 — 혜택가 {_fmt(benefit)}"
                            f"×{_fmt(qty)}={_fmt(line_cost)}{_ship_txt} > 정산 "
                            f"{_fmt(revenue)} (손익 {_fmt(profit)})",
                        )
                        changed = True
                        summary["no_price"] += 1
                        pid = o.collected_product_id
                        if pid:
                            no_price_product_ids.add(pid)

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
                    pid = o.collected_product_id
                    if pid:
                        no_stock_product_ids.add(pid)
                        no_price_product_ids.add(pid)  # last_refreshed_at 우선순위용

            # 소액 주문 자동 배송완료: 정산금액 < 1,000원인 주문
            # (역마진·재고없음과 무관하게 처리 — 이미 배송완료 상태인 건은 건너뜀)
            _rev = float(o.revenue or 0)
            if o.status in _ACTIVE_STATUSES and 0 < _rev < _AUTO_DELIVER_THRESHOLD:
                o.status = "delivered"
                o.shipping_status = "배송완료"
                o.delivered_at = now
                new_notes = _append_note(
                    new_notes,
                    f"[{_now_kst_str()}] 자동: 소액주문 배송완료 처리 — 정산 {_fmt(_rev)}원",
                )
                changed = True
                summary["auto_delivered"] += 1

            if changed:
                o.action_tag = ",".join(sorted(tag_set))
                o.notes = new_notes
                session.add(o)

        # 6) 역마진/재고없음 감지 상품 → last_refreshed_at 2일 과거로 재설정
        #    오토튠이 ORDER BY last_refreshed_at ASC 로 처리하므로, 과거로 설정하면
        #    다음 사이클에서 최우선 처리 → 마켓 판매가 즉시 재계산·전송
        if no_price_product_ids:
            _past = now - timedelta(days=2)
            for _pid in no_price_product_ids:
                _p = product_map.get(_pid)
                if _p:
                    _p.last_refreshed_at = _past  # type: ignore[assignment]
                    session.add(_p)
            logger.info(
                "[주문이슈체크] 역마진/재고없음 상품 %d개 → 오토튠 우선 처리 예약",
                len(no_price_product_ids),
            )

        await session.commit()

        # 역마진/재고없음 감지 상품 → 즉시 가격·재고 직접 전송 (업데이트 버튼과 동일 경로)
        # skip_refresh=True: 위에서 이미 소싱처 재조회 완료, DB 최신 원가/재고 반영됨
        # skip_policy_account_filter=True: worker.py 테트리스 게이트 우회, start_update 레이어 직접 호출
        if no_price_product_ids:
            from backend.db.orm import get_write_session as _gws
            from backend.domain.samba.shipment.repository import SambaShipmentRepository
            from backend.domain.samba.shipment.service import SambaShipmentService

            _sent = 0
            for _pid in no_price_product_ids:
                _p = product_map.get(_pid)
                if not _p or not getattr(_p, "registered_accounts", None):
                    continue
                try:
                    async with _gws() as _ship_sess:
                        _ship_svc = SambaShipmentService(
                            SambaShipmentRepository(_ship_sess), _ship_sess
                        )
                        await _ship_svc.start_update(
                            [_pid],
                            ["price", "stock"],
                            list(_p.registered_accounts),
                            skip_unchanged=False,
                            skip_refresh=True,
                            skip_policy_account_filter=True,
                        )
                        await _ship_sess.commit()
                    _sent += 1
                except Exception as _se:
                    logger.warning(
                        "[주문이슈체크] 즉시 전송 실패 pid=%s: %s",
                        _pid,
                        str(_se)[:120],
                    )
            if _sent:
                logger.info(
                    "[주문이슈체크] 역마진/재고없음 상품 %d개 즉시 가격·재고 전송 완료",
                    _sent,
                )

        # 재고없음 감지 상품 → 마켓 삭제 + 주문 스냅샷(이미지/소싱처 보존) + DB 삭제
        # 수동 삭제 버튼과 동일한 파이프: _snapshot_cp_to_orders → delete_from_markets → bulk_delete
        if no_stock_product_ids:
            from sqlalchemy import text as _t2
            from backend.db.orm import get_write_session as _gws2
            from backend.domain.samba.collector.repository import (
                SambaCollectedProductRepository,
            )
            from backend.domain.samba.shipment.repository import (
                SambaShipmentRepository as _SR2,
            )
            from backend.domain.samba.shipment.service import (
                SambaShipmentService as _SS2,
            )

            _deleted = 0
            for _pid in no_stock_product_ids:
                _p = product_map.get(_pid)
                if not _p:
                    continue
                # SNKRDUNK(스니덩크) 리셀 매칭상품은 절대 자동삭제 금지.
                # C2C 다중셀러라 원소싱 품절돼도 곧 재입고됨 → 삭제하면 크림 리스팅·주문연결이
                # 통째로 끊긴다(주문 collected_product_id='DELETED' 사고). 재고없음 태그만 남기고
                # 상품·마켓 삭제는 건너뛴다. lock_delete 여부와 무관하게 소싱처 기준으로 차단.
                if (getattr(_p, "source_site", "") or "").upper() == "SNKRDUNK":
                    logger.info(
                        "[주문이슈체크] SNKRDUNK 리셀상품 자동삭제 제외 pid=%s (재입고 대비)",
                        _pid,
                    )
                    continue
                # 삭제잠금(크림 매칭 등 보호 대상)은 소싱처 무관하게 자동삭제에서 제외.
                if getattr(_p, "lock_delete", False):
                    logger.info(
                        "[주문이슈체크] lock_delete=True 상품 자동삭제 제외 pid=%s",
                        _pid,
                    )
                    continue
                _reg_accounts = list(getattr(_p, "registered_accounts", None) or [])
                try:
                    async with _gws2() as _del_sess:
                        # 1) 주문에 이미지/소싱처 스냅샷 저장 + collected_product_id='DELETED'
                        _cp_rows = (
                            await _del_sess.execute(
                                _t2(
                                    "SELECT id, source_site, images->>0 AS thumb "
                                    "FROM samba_collected_product WHERE id = :id"
                                ),
                                {"id": _pid},
                            )
                        ).fetchall()
                        if _cp_rows:
                            _cp_src = _cp_rows[0][1] or ""
                            _cp_thumb = _cp_rows[0][2] or ""
                            await _del_sess.execute(
                                _t2(
                                    "UPDATE samba_order "
                                    "SET product_image = CASE WHEN product_image IS NULL OR product_image = '' "
                                    "    THEN :img ELSE product_image END, "
                                    "source_site = CASE WHEN source_site IS NULL OR source_site = '' "
                                    "    THEN :src ELSE source_site END, "
                                    "collected_product_id = 'DELETED' "
                                    "WHERE collected_product_id = :cpid"
                                ),
                                {"img": _cp_thumb, "src": _cp_src, "cpid": _pid},
                            )
                            # 배지 UPDATE를 마켓삭제 이전에 독립 commit.
                            # delete_from_market 디스패처가 예외 시 session.rollback()을
                            # 호출해 같은 세션의 pending UPDATE까지 날리는 버그 방지.
                            await _del_sess.commit()

                        # 2) 마켓 삭제 (등록된 계정 전체)
                        _del_ok = True
                        if _reg_accounts:
                            _ship_svc2 = _SS2(_SR2(_del_sess), _del_sess)
                            _del_r = await _ship_svc2.delete_from_markets(
                                [_pid], _reg_accounts
                            )
                            _del_entry = (_del_r.get("results") or [{}])[0]
                            _del_ok = _del_entry.get("success_count", 0) >= len(
                                _del_entry.get("delete_results") or {}
                            )
                            if not _del_ok:
                                logger.warning(
                                    "[주문이슈체크] 마켓삭제 일부 실패 — DB삭제 보류 pid=%s "
                                    "(issue #546: 고아상품 방지)",
                                    _pid,
                                )

                        # 3) 수집상품 DB 삭제 — 마켓삭제 전부 성공 시에만
                        if _del_ok:
                            _coll_repo = SambaCollectedProductRepository(_del_sess)
                            await _coll_repo.delete_async(_pid)

                        await _del_sess.commit()
                    if _del_ok:
                        _deleted += 1
                except Exception as _de:
                    logger.warning(
                        "[주문이슈체크] 자동삭제 실패 pid=%s: %s",
                        _pid,
                        str(_de)[:120],
                    )
            if _deleted:
                logger.info(
                    "[주문이슈체크] 재고없음 상품 %d개 마켓삭제·DB삭제·DELETED 처리 완료",
                    _deleted,
                )

    logger.info(
        "[주문이슈체크] 완료 — 검사 %d / 보류 %d / 가격X %d / 재고X %d / 소액배송완료 %d",
        summary["checked"],
        summary["skipped"],
        summary["no_price"],
        summary["no_stock"],
        summary["auto_delivered"],
    )
    return summary
