"""보강 엔드포인트 — enrich_product, enrich_all_products + 관련 헬퍼 함수."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency
from backend.domain.samba.exchange_rate_service import convert_cost_by_source_site
from backend.domain.samba.collector.refresher import _site_intervals

from backend.api.v1.routers.samba.collector_common import (
    _clean_text,
    _trim_history,
    _build_kream_price_snapshot,
    _get_services,
    get_musinsa_cookie,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["samba-collector"])


# ── enrich 전용 헬퍼 ──


async def _check_policy_price_changed(
    session: AsyncSession,
    product: Any,
    cost: float,
) -> bool:
    """소싱처 가격/재고 불변 시 정책 변동으로 마켓 판매가가 달라졌는지 확인.

    현재 정책 기반으로 재계산한 마켓 판매가와 last_sent_data의 마지막 전송 판매가를
    비교하여 하나라도 차이가 있으면 True를 반환한다.
    """
    policy_id = getattr(product, "applied_policy_id", None)
    last_sent: dict = getattr(product, "last_sent_data", None) or {}
    if not policy_id or not last_sent:
        return False

    try:
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        from backend.domain.samba.shipment.service import (
            calc_market_price,
        )
        from backend.domain.samba.account.model import SambaMarketAccount

        pol_repo = SambaPolicyRepository(session)
        policy = await pol_repo.get_async(policy_id)
        if not policy or not policy.pricing:
            return False

        source_site = getattr(product, "source_site", "") or ""
        policy_market_data = policy.market_policies or {}

        # 계정 배치 조회 (N+1 방지)
        acc_stmt = select(SambaMarketAccount).where(
            SambaMarketAccount.id.in_(list(product.registered_accounts))
        )
        acc_result = await session.execute(acc_stmt)

        for acc in acc_result.scalars().all():
            cost_info = await convert_cost_by_source_site(
                session, cost, source_site, getattr(product, "tenant_id", None)
            )
            new_price = calc_market_price(
                cost_info["convertedCost"],
                policy.pricing,
                acc.market_type,
                policy_market_data,
                source_site=source_site,
            )
            old_sent = last_sent.get(acc.id, {})
            old_price = (int(old_sent.get("sale_price") or 0) // 100) * 100
            if new_price != old_price:
                logger.info(
                    f"[정책변동] {product.id} {acc.market_type} "
                    f"판매가 변동: ₩{old_price:,} → ₩{new_price:,}"
                )
                return True
    except Exception as e:
        logger.error(f"[정책변동체크] {getattr(product, 'id', '')} 오류: {e}")

    return False


def _snapshot_old_values(product: Any) -> dict:
    """Identity map 오염 전에 비교용 이전 값 캡처.

    update_async 호출 전에 반드시 실행해야 함.
    update_async는 같은 session의 identity map 객체를 직접 수정하므로
    호출 후에는 old 값을 읽을 수 없음.
    """
    return {
        "sale_price": getattr(product, "sale_price", 0) or 0,
        "cost": getattr(product, "cost", 0) or 0,
        "sale_status": getattr(product, "sale_status", "in_stock"),
        "options": list(getattr(product, "options", None) or []),
    }


async def _retransmit_if_changed(
    session: AsyncSession,
    product: Any,
    updates: dict,
    old_values: dict | None = None,
) -> dict:
    """가격/재고 변동 시 등록된 마켓에 자동 수정등록."""
    result = {"retransmitted": False, "retransmit_accounts": 0}

    if not getattr(product, "registered_accounts", None):
        return result

    # DB 변경사항 플러시 (재전송 시 최신 데이터 조회 보장)
    await session.flush()

    # 품절 전환 → 마켓 삭제
    new_status = updates.get("sale_status")
    old_status = (old_values or {}).get("sale_status") or getattr(
        product, "sale_status", "in_stock"
    )
    if new_status == "sold_out":
        if getattr(product, "lock_delete", False):
            logger.info(
                f"[enrich] {product.id} 품절이지만 lock_delete=True, 마켓 삭제 건너뜀"
            )
            return result
        try:
            from backend.domain.samba.shipment.dispatcher import delete_from_market
            from backend.domain.samba.account.model import SambaMarketAccount

            # 계정 배치 조회 (N+1 방지)
            _acc_stmt = select(SambaMarketAccount).where(
                SambaMarketAccount.id.in_(product.registered_accounts)
            )
            _acc_result = await session.execute(_acc_stmt)
            acc_map = {a.id: a for a in _acc_result.scalars().all()}

            product_dict = {**product.model_dump(), **updates}
            for account_id in product.registered_accounts:
                account = acc_map.get(account_id)
                if not account:
                    continue
                m_nos = product.market_product_nos or {}
                pd = {
                    **product_dict,
                    "market_product_no": {
                        account.market_type: m_nos.get(account_id, "")
                    },
                }
                await delete_from_market(
                    session, account.market_type, pd, account=account
                )
                result["retransmit_accounts"] += 1
            result["retransmitted"] = True
        except Exception as e:
            logger.error(f"[enrich] {product.id} 마켓 판매중지 실패: {e}")
        return result

    # 가격 변동 확인 (old_values 우선 — identity map 오염 방지)
    price_changed = False
    _ov = old_values or {}
    old_sale = int(
        _ov.get("sale_price")
        if "sale_price" in _ov
        else getattr(product, "sale_price", 0) or 0
    )
    new_sale = int(updates.get("sale_price", old_sale) or 0)
    if new_sale != old_sale:
        price_changed = True

    old_cost = int(
        _ov.get("cost") if "cost" in _ov else getattr(product, "cost", 0) or 0
    )
    new_cost = int(updates.get("cost", old_cost) or 0)
    if new_cost != old_cost:
        price_changed = True

    # 재고(옵션) 변동 확인 (old_values 우선 — identity map 오염 방지)
    stock_changed = False
    old_options = (
        _ov.get("options")
        if "options" in _ov
        else (getattr(product, "options", None) or [])
    )
    new_options = updates.get("options")
    if new_options and old_options:
        old_stock_map = {
            (o.get("name", "") or o.get("size", "")): o.get("stock", 0)
            for o in old_options
            if isinstance(o, dict)
        }
        for o in new_options:
            if not isinstance(o, dict):
                continue
            key = o.get("name", "") or o.get("size", "")
            old_stock = old_stock_map.get(key, 0) or 0
            new_stock = o.get("stock", 0) or 0
            if (old_stock <= 0) != (new_stock <= 0):
                stock_changed = True
                break

    if not price_changed and not stock_changed:
        # 소싱처 가격/재고 불변 → 정책 변동으로 마켓 판매가가 달라졌는지 확인
        cost_for_check = updates.get("cost") or old_cost or 0
        policy_changed = await _check_policy_price_changed(
            session, product, cost_for_check
        )
        if not policy_changed:
            return result
        price_changed = True

    # 재전송 항목 결정
    update_items: list[str] = []
    if price_changed:
        update_items.append("price")
    if stock_changed:
        update_items.append("stock")

    try:
        from backend.domain.samba.shipment.repository import SambaShipmentRepository
        from backend.domain.samba.shipment.service import SambaShipmentService

        ship_repo = SambaShipmentRepository(session)
        ship_svc = SambaShipmentService(ship_repo, session)

        await ship_svc.start_update(
            [product.id],
            update_items,
            list(product.registered_accounts),
            skip_unchanged=False,
        )
        result["retransmitted"] = True
        result["retransmit_accounts"] = len(product.registered_accounts)
    except Exception as e:
        logger.error(f"[enrich] {product.id} 마켓 재전송 실패: {e}")

    return result


# ── 엔드포인트 ──


@router.post("/enrich/{product_id}")
async def enrich_product(
    product_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수집 상품의 상세 정보를 소싱사이트 API에서 보강 (카테고리, 옵션, 상세이미지 등)."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    svc = _get_services(session)
    product = await svc.get_collected_product(product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    if product.source_site == "MUSINSA" and product.site_product_id:
        cookie = await get_musinsa_cookie(session)

        client = MusinsaClient(cookie=cookie)
        try:
            # refresh_only=True: 가격/재고만 갱신, 이미지/고시정보 처리 스킵
            detail = await client.get_goods_detail(
                product.site_product_id, refresh_only=True
            )
        except Exception as e:
            raise HTTPException(502, f"무신사 상세 조회 실패: {str(e)}")

        if not detail or not detail.get("name"):
            raise HTTPException(502, "무신사 상세 조회 실패: 데이터 없음")
        # 긴 상세이미지 분할 (추가이미지 보충분)
        orig_cnt = detail.get("originalImageCount", len(detail.get("images", [])))
        if orig_cnt < len(detail.get("images", [])):
            from backend.domain.samba.image.service import split_long_images

            detail["images"] = await split_long_images(
                detail["images"], orig_cnt, session
            )

        # get_goods_detail은 { category: "키즈 > ...", category1: "키즈", ... } 형태로 반환

        # 가격 0 허용: None이 아닌 경우에만 업데이트, 0도 유효한 값으로 처리
        api_sale = detail.get("salePrice")
        api_original = detail.get("originalPrice")
        new_sale_price = api_sale if api_sale is not None else product.sale_price
        new_original_price = (
            api_original if api_original is not None else product.original_price
        )

        new_sale_status = detail.get("saleStatus", "in_stock")
        # 최대혜택가: best_benefit_price → cost 컬럼에 저장 (0은 None으로 처리)
        _raw_cost = detail.get("bestBenefitPrice")
        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None
        # 가격/재고만 업데이트 (카테고리, 브랜드, 상세HTML 등은 변경하지 않음)
        updates = {
            "original_price": new_original_price,
            "sale_price": new_sale_price,
            "cost": new_cost,
            "sale_status": new_sale_status,
        }

        # 가격 변동 추적
        if new_sale_price != product.sale_price:
            updates["price_before_change"] = product.sale_price
            updates["price_changed_at"] = datetime.now(timezone.utc)

        # 가격/옵션 이력 스냅샷 추가 (최신순, 최대 200건)
        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": new_sale_price,
            "original_price": new_original_price,
            "cost": new_cost,
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        # 옵션 보강 (HTML 태그 정제)
        if detail.get("options"):
            cleaned = []
            for opt in detail["options"]:
                if isinstance(opt, dict):
                    co = {**opt}
                    for k in ("name", "value", "label"):
                        if k in co and isinstance(co[k], str):
                            co[k] = _clean_text(co[k])
                    cleaned.append(co)
                else:
                    cleaned.append(opt)
            updates["options"] = cleaned

        # 이미지 보강
        if detail.get("images"):
            updates["images"] = detail["images"]

        _old_vals = _snapshot_old_values(product)
        updated = await svc.update_collected_product(product_id, updates)
        retransmit = await _retransmit_if_changed(
            session, product, updates, old_values=_old_vals
        )
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
            **retransmit,
        }

    if product.source_site == "KREAM" and product.site_product_id:
        from backend.domain.samba.proxy.kream import KreamClient

        client = KreamClient()
        try:
            raw = await client.get_product_via_extension(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"KREAM 상세 조회 실패: {str(e)}")

        if isinstance(raw, dict) and raw.get("success") and raw.get("product"):
            pd = raw["product"]
        elif isinstance(raw, dict) and raw.get("name"):
            pd = raw
        else:
            raise HTTPException(502, "KREAM 상세 조회 실패: 데이터 없음")

        opts = pd.get("options", [])
        cat_str = pd.get("category", "")
        cat_parts = (
            [c.strip() for c in cat_str.split(">") if c.strip()] if cat_str else []
        )

        fast_prices = [
            o.get("kreamFastPrice", 0) for o in opts if o.get("kreamFastPrice", 0) > 0
        ]
        general_prices = [
            o.get("kreamGeneralPrice", 0)
            for o in opts
            if o.get("kreamGeneralPrice", 0) > 0
        ]
        sale_p = (
            min(fast_prices)
            if fast_prices
            else (pd.get("salePrice") or product.sale_price)
        )
        cost_p = min(general_prices) if general_prices else sale_p

        # 가격재고업데이트: 가격/재고(옵션)만 갱신, 상품명/브랜드/이미지/카테고리 스킵
        updates = {
            "original_price": pd.get("originalPrice") or product.original_price,
            "sale_price": sale_p,
            "cost": cost_p,
            "options": opts if opts else product.options,
        }

        # 품절 판정: 모든 옵션 stock=0이면 sold_out
        _kream_opts = opts if opts else []
        if _kream_opts and all(o.get("stock", 0) <= 0 for o in _kream_opts):
            updates["sale_status"] = "sold_out"
        elif not _kream_opts:
            updates["sale_status"] = "sold_out"
        else:
            updates["sale_status"] = "in_stock"

        # 가격이력 스냅샷 추가 (최대 200건)
        snapshot = _build_kream_price_snapshot(
            sale_p, pd.get("originalPrice") or product.original_price, cost_p, opts
        )
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        _old_vals = _snapshot_old_values(product)
        updated = await svc.update_collected_product(product_id, updates)
        retransmit = await _retransmit_if_changed(
            session, product, updates, old_values=_old_vals
        )
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
            **retransmit,
        }

    if product.source_site == "Nike" and product.site_product_id:
        from backend.domain.samba.proxy.nike import NikeClient

        try:
            detail = await NikeClient().get_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"Nike 상세 조회 실패: {e}")
        if detail.get("error"):
            raise HTTPException(502, detail["error"])

        updates = {}
        for field in (
            "style_code",
            "sex",
            "manufacturer",
            "origin",
            "material",
            "care_instructions",
            "quality_guarantee",
            "color",
            "video_url",
            "detail_html",
            "images",
            "options",
        ):
            val = detail.get(field)
            if val is not None and val != "" and val != []:
                updates[field] = val

        sale_price = detail.get("sale_price")
        original_price = detail.get("original_price")
        if sale_price is not None:
            updates["sale_price"] = sale_price
        if original_price is not None:
            updates["original_price"] = original_price

        # sale_status 반영
        updates["sale_status"] = detail.get("sale_status", "in_stock")

        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": sale_price or product.sale_price,
            "original_price": original_price or product.original_price,
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        _old_vals = _snapshot_old_values(product)
        updated = await svc.update_collected_product(product_id, updates)
        retransmit = await _retransmit_if_changed(
            session, product, updates, old_values=_old_vals
        )
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
            **retransmit,
        }

    if product.source_site == "FashionPlus" and product.site_product_id:
        from backend.domain.samba.proxy.fashionplus import FashionPlusClient

        client = FashionPlusClient()
        try:
            detail = await client.get_detail(product.site_product_id)
        except Exception as e:
            raise HTTPException(502, f"패션플러스 상세 조회 실패: {str(e)}")

        new_sale = detail.get("sale_price") or product.sale_price
        new_orig = detail.get("original_price") or product.original_price
        shipping_fee = detail.get("shipping_fee", 0) or 0
        new_cost = new_sale + shipping_fee
        new_images = detail.get("images") or []

        new_options = detail.get("options") or []
        updates: dict[str, Any] = {
            "sale_price": new_sale,
            "original_price": new_orig,
            "cost": new_cost,
            "sourcing_shipping_fee": shipping_fee,
        }
        # 품절 판정
        if new_options and all(o.get("stock", 0) <= 0 for o in new_options):
            updates["sale_status"] = "sold_out"
        elif not new_options:
            updates["sale_status"] = "sold_out"
        else:
            updates["sale_status"] = detail.get("saleStatus", "in_stock")
        if new_options:
            updates["options"] = new_options

        snapshot = {
            "date": datetime.now(timezone.utc).isoformat(),
            "sale_price": new_sale,
            "original_price": new_orig,
            "cost": new_cost,
            "options": detail.get("options", []),
        }
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        _old_vals = _snapshot_old_values(product)
        updated = await svc.update_collected_product(product_id, updates)
        retransmit = await _retransmit_if_changed(
            session, product, updates, old_values=_old_vals
        )
        return {
            "success": True,
            "enriched_fields": list(updates.keys()),
            "product": updated,
            **retransmit,
        }

    # 플러그인 기반 소싱처 (FashionPlus, Nike, Adidas 등)
    from backend.domain.samba.plugins import SOURCING_PLUGINS

    _src = product.source_site or ""
    plugin = SOURCING_PLUGINS.get(_src) or SOURCING_PLUGINS.get(_src.upper())
    if plugin and product.site_product_id:
        try:
            # 롯데ON: benefits API 쿠키 캐시 로드
            if _src.upper() == "LOTTEON":
                from backend.api.v1.routers.samba.proxy import _get_setting
                from backend.domain.samba.proxy.lotteon_sourcing import (
                    set_lotteon_cookie,
                    _lotteon_cookie_cache,
                )

                if not _lotteon_cookie_cache:
                    _lt_ck = await _get_setting(session, "lotteon_cookie")
                    if _lt_ck:
                        set_lotteon_cookie(str(_lt_ck))

            result = await plugin.refresh(product)
            updates: dict[str, Any] = {}
            if result.new_sale_price is not None:
                updates["sale_price"] = result.new_sale_price
            if result.new_original_price is not None:
                updates["original_price"] = result.new_original_price
            if result.new_cost is not None:
                updates["cost"] = result.new_cost
            if result.new_sale_status:
                updates["sale_status"] = result.new_sale_status
            if result.new_options is not None:
                updates["options"] = result.new_options
            if result.error:
                return {"success": False, "message": result.error}

            # LOTTEON: 확장앱 DOM 파싱으로 최대혜택가 수집
            if _src.upper() == "LOTTEON" and product.site_product_id:
                try:
                    from backend.domain.samba.proxy.sourcing_queue import SourcingQueue

                    _sitm = (
                        getattr(product, "sitmNo", "")
                        or getattr(product, "sitm_no", "")
                        or (product.extra_data or {}).get("sitmNo", "")
                    )
                    _req_id, _future = SourcingQueue.add_detail_job(
                        "LOTTEON", product.site_product_id, sitm_no=_sitm
                    )
                    _ext_result = await asyncio.wait_for(_future, timeout=25)
                    if isinstance(_ext_result, dict) and _ext_result.get("success"):
                        _ext_benefit = int(
                            _ext_result.get("best_benefit_price", 0) or 0
                        )
                        if _ext_benefit > 0:
                            updates["cost"] = _ext_benefit
                            logger.info(
                                f"[LOTTEON] enrich 확장앱 혜택가: "
                                f"{product.site_product_id} → {_ext_benefit:,}"
                            )
                except asyncio.TimeoutError:
                    logger.info(
                        f"[LOTTEON] enrich 확장앱 타임아웃: {product.site_product_id}"
                    )
                except Exception as _ext_err:
                    logger.debug(
                        f"[LOTTEON] enrich 확장앱 실패: {product.site_product_id} — {_ext_err}"
                    )

            if not updates:
                return {"success": True, "message": "변동 없음", "product": product}
            # 가격이력 스냅샷
            snapshot = {
                "date": datetime.now(timezone.utc).isoformat(),
                "sale_price": updates.get("sale_price", product.sale_price),
                "original_price": updates.get("original_price", product.original_price),
                "cost": updates.get("cost", product.cost),
            }
            # 옵션: 신규 수집 우선, 없으면 기존 DB 옵션 폴백
            _snap_opts = result.new_options
            if not _snap_opts and product.options:
                _snap_opts = product.options
            if _snap_opts:
                snapshot["options"] = _snap_opts
            history = list(product.price_history or [])
            history.insert(0, snapshot)
            updates["price_history"] = _trim_history(history)
            _old_vals = _snapshot_old_values(product)
            updated = await svc.update_collected_product(product_id, updates)
            retransmit = await _retransmit_if_changed(
                session, product, updates, old_values=_old_vals
            )
            return {
                "success": True,
                "enriched_fields": list(updates.keys()),
                "product": updated,
                **retransmit,
            }
        except Exception as e:
            raise HTTPException(502, f"{product.source_site} 갱신 실패: {e}")

    raise HTTPException(
        400, f"'{product.source_site}' 상세 보강은 아직 지원하지 않습니다"
    )


@router.post("/enrich-all")
async def enrich_all_products(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """카테고리가 비어있는 모든 MUSINSA 수집 상품의 상세 정보를 일괄 보강."""
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    svc = _get_services(session)
    all_products = await svc.list_collected_products(skip=0, limit=1000)

    # 카테고리 없는 MUSINSA 상품만
    targets = [
        p
        for p in all_products
        if p.source_site == "MUSINSA" and p.site_product_id and not p.category1
    ]

    if not targets:
        return {"enriched": 0, "message": "보강할 상품이 없습니다"}

    # 쿠키 로드
    cookie = await get_musinsa_cookie(session)

    client = MusinsaClient(cookie=cookie)
    enriched = 0

    for product in targets:
        try:
            detail = await client.get_goods_detail(product.site_product_id)
            if not detail or not detail.get("name"):
                continue
            # 긴 상세이미지 분할 (추가이미지 보충분)
            orig_cnt = detail.get("originalImageCount", len(detail.get("images", [])))
            if orig_cnt < len(detail.get("images", [])):
                from backend.domain.samba.image.service import split_long_images

                detail["images"] = await split_long_images(
                    detail["images"], orig_cnt, session
                )

            new_sale_status = detail.get("saleStatus", "in_stock")
            api_sale = detail.get("salePrice")
            api_original = detail.get("originalPrice")
            new_sale_price = api_sale if api_sale is not None else product.sale_price
            new_original_price = (
                api_original if api_original is not None else product.original_price
            )
            _raw_cost = detail.get("bestBenefitPrice")
            new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else None

            updates = {
                "category": detail.get("category") or product.category,
                "category1": detail.get("category1") or product.category1,
                "category2": detail.get("category2") or product.category2,
                "category3": detail.get("category3") or product.category3,
                "category4": detail.get("category4") or product.category4,
                "brand": detail.get("brand") or product.brand,
                "original_price": new_original_price,
                "sale_price": new_sale_price,
                "cost": new_cost,
                "sale_status": new_sale_status,
            }

            # 가격 변동 추적
            if new_sale_price != product.sale_price:
                from datetime import datetime, timezone as tz

                updates["price_before_change"] = product.sale_price
                updates["price_changed_at"] = datetime.now(tz.utc)

            # 가격/옵션 이력 스냅샷 추가 (최신순, 최대 200건)
            from datetime import datetime, timezone as tz

            snapshot = {
                "date": datetime.now(tz.utc).isoformat(),
                "sale_price": new_sale_price,
                "original_price": new_original_price,
                "cost": new_cost,
                "options": detail.get("options", []),
            }
            history = list(product.price_history or [])
            history.insert(0, snapshot)
            updates["price_history"] = _trim_history(history)

            if detail.get("options"):
                updates["options"] = detail["options"]
            if detail.get("images"):
                updates["images"] = detail["images"]

            await svc.update_collected_product(product.id, updates)
            enriched += 1

            # 적응형 인터벌: 차단 감지 시 자동 증가
            await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
        except Exception:
            continue

    return {"enriched": enriched, "total_targets": len(targets)}
