"""SambaWave Shipment service — 실제 마켓 API 연동 상품 전송."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.shipment.model import SambaShipment
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.utils.logger import logger

import math

# 마켓타입 → 정책키 매핑
MARKET_TYPE_TO_POLICY_KEY = {
    "coupang": "쿠팡",
    "ssg": "신세계몰",
    "smartstore": "스마트스토어",
    "11st": "11번가",
    "gmarket": "지마켓",
    "auction": "옥션",
    "gsshop": "GS샵",
    "lotteon": "롯데ON",
    "lottehome": "롯데홈쇼핑",
    "homeand": "홈앤쇼핑",
    "hmall": "HMALL",
    "kream": "KREAM",
}


def calc_market_price(
    cost: float,
    policy_pricing: dict,
    market_type: str,
    market_policies: dict | None = None,
) -> int:
    """정책 기반 마켓 최종 판매가 계산.

    원가 + 마진 + 배송비 → 수수료 역산 → 추가요금.
    마켓별 오버라이드 적용.
    """
    if not policy_pricing:
        return int(cost)
    pr = policy_pricing
    common_margin_rate = pr.get("marginRate", 15)
    common_shipping = pr.get("shippingCost", 0)
    common_extra = pr.get("extraCharge", 0)
    common_fee = pr.get("feeRate", 0)
    min_margin = pr.get("minMarginAmount", 0)

    policy_key = MARKET_TYPE_TO_POLICY_KEY.get(market_type, "")
    mp = (market_policies or {}).get(policy_key, {}) if policy_key else {}
    m_margin_rate = mp.get("marginRate") or common_margin_rate
    m_shipping = mp.get("shippingCost") or common_shipping
    m_fee = mp.get("feeRate") or common_fee

    margin_amt = round(cost * m_margin_rate / 100)
    if min_margin > 0 and margin_amt < min_margin:
        margin_amt = min_margin
    calc_price = cost + margin_amt + m_shipping
    if m_fee > 0 and calc_price > 0:
        calc_price = math.ceil(calc_price / (1 - m_fee / 100))
    if common_extra > 0:
        calc_price += common_extra
    return int(calc_price)


# 그룹상품 동시성 제어 락 (account_id별)
_group_locks: dict[str, asyncio.Lock] = {}

# 상품별 전송 락 — 동일 상품 중복 전송 방지
_transmitting_products: set[str] = set()

# 계정별 세마포어 — API Rate Limit 방지 (계정당 동시 1건)
_account_semaphores: dict[str, asyncio.Semaphore] = {}

# 전송 중단 플래그 (threading.Event — 스레드 간 동기화 보장)
import threading as _threading

_cancel_event = _threading.Event()


def request_cancel_transmit():
    _cancel_event.set()


def clear_cancel_transmit():
    _cancel_event.clear()


def is_cancel_requested() -> bool:
    return _cancel_event.is_set()


def _get_group_lock(account_id: str) -> asyncio.Lock:
    if account_id not in _group_locks:
        _group_locks[account_id] = asyncio.Lock()
    return _group_locks[account_id]


def clear_account_semaphores():
    """별도 스레드 실행 시 이전 이벤트 루프 세마포어 정리."""
    _account_semaphores.clear()
    _transmitting_products.clear()  # 재시작 시 잔류 상품 정리


def _get_account_semaphore(account_id: str) -> asyncio.Semaphore:
    if account_id not in _account_semaphores:
        _account_semaphores[account_id] = asyncio.Semaphore(1)
    return _account_semaphores[account_id]


STATUS_LABELS: dict[str, str] = {
    "pending": "대기중",
    "updating": "업데이트중",
    "transmitting": "전송중",
    "completed": "완료",
    "partial": "부분완료",
    "failed": "실패",
}


class SambaShipmentService:
    def __init__(self, repo: SambaShipmentRepository, session: AsyncSession):
        self.repo = repo
        self.session = session

    # ==================== CRUD ====================

    async def list_shipments(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> list[SambaShipment]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def list_by_status(self, status: str) -> list[SambaShipment]:
        return await self.repo.list_by_status(status)

    async def get_shipment(self, shipment_id: str) -> Optional[SambaShipment]:
        return await self.repo.get_async(shipment_id)

    async def create_shipment(self, data: dict[str, Any]) -> SambaShipment:
        return await self.repo.create_async(**data)

    async def update_shipment(
        self, shipment_id: str, data: dict[str, Any]
    ) -> Optional[SambaShipment]:
        return await self.repo.update_async(shipment_id, **data)

    async def delete_shipment(self, shipment_id: str) -> bool:
        return await self.repo.delete_async(shipment_id)

    async def list_by_product(self, product_id: str) -> list[SambaShipment]:
        return await self.repo.list_by_product(product_id)

    # ==================== 실제 상품 전송 ====================

    async def start_update(
        self,
        product_ids: list[str],
        update_items: list[str],
        target_account_ids: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
    ) -> dict[str, Any]:
        """여러 상품을 대상 마켓 계정으로 실제 전송. 마켓별 결과 반환."""
        # 이전 취소 플래그 잔존 방지
        clear_cancel_transmit()

        processed = 0
        skipped = 0
        cancelled = 0
        results: list[dict[str, Any]] = []
        for product_id in product_ids:
            # 중단 체크
            if is_cancel_requested():
                cancelled = len(product_ids) - processed
                logger.info(
                    f"[전송] 강제 중단 — {processed}건 완료, {cancelled}건 취소"
                )
                clear_cancel_transmit()
                break
            try:
                shipment = await self._transmit_product(
                    product_id,
                    target_account_ids,
                    update_items,
                    skip_unchanged=skip_unchanged,
                    skip_refresh=skip_refresh,
                )
                results.append(
                    {
                        "product_id": product_id,
                        "status": shipment.status,
                        "transmit_result": shipment.transmit_result or {},
                        "transmit_error": shipment.transmit_error or {},
                        "update_result": shipment.update_result or {},
                    }
                )
                processed += 1
            except Exception as exc:
                logger.error(f"상품 {product_id} 전송 실패: {exc}")
                results.append(
                    {
                        "product_id": product_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        return {
            "processed": processed,
            "skipped": skipped,
            "cancelled": cancelled,
            "results": results,
        }

    # ==================== 그룹상품 전송 ====================

    async def transmit_group(self, product_ids: list[str], account_id: str) -> dict:
        """그룹상품을 스마트스토어에 등록."""

        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        product_repo = SambaCollectedProductRepository(self.session)
        account_repo = SambaMarketAccountRepository(self.session)

        # 상품 조회
        products = []
        for pid in product_ids:
            p = await product_repo.get_async(pid)
            if p:
                products.append(p)
        if len(products) < 2:
            raise ValueError("그룹상품은 2개 이상의 상품이 필요합니다")

        # 계정 조회
        account = await account_repo.get_async(account_id)
        if not account:
            raise ValueError(f"계정을 찾을 수 없습니다: {account_id}")

        additional = account.additional_fields or {}
        client_id = additional.get("clientId") or account.api_key
        client_secret = additional.get("clientSecret") or account.api_secret
        client = SmartStoreClient(client_id, client_secret)

        # 카테고리 매핑 조회 (기존 _transmit_product 패턴과 동일)
        first = products[0]
        cat_parts = [first.category1, first.category2, first.category3, first.category4]
        raw_category = " > ".join(c for c in cat_parts if c) or first.category or ""

        # 그룹 매핑 조회
        group_mappings = None
        if first.search_filter_id:
            from backend.domain.samba.collector.repository import (
                SambaSearchFilterRepository,
            )

            sf_repo = SambaSearchFilterRepository(self.session)
            sf = await sf_repo.get_async(first.search_filter_id)
            if sf and sf.target_mappings:
                group_mappings = sf.target_mappings

        mapped = await self._resolve_category_mappings(
            first.source_site or "",
            raw_category,
            [account_id],
            group_mappings=group_mappings,
        )
        category_id = mapped.get("smartstore", "")
        if not category_id:
            raise ValueError("카테고리 매핑을 찾을 수 없습니다")

        # 정책 조회 (가격 계산용)
        MARKET_TYPE_TO_POLICY_KEY = {
            "coupang": "쿠팡",
            "ssg": "신세계몰",
            "smartstore": "스마트스토어",
            "11st": "11번가",
            "gmarket": "지마켓",
            "auction": "옥션",
            "gsshop": "GS샵",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL",
            "kream": "KREAM",
        }
        policy = None
        policy_market_data: dict[str, Any] = {}
        if first.applied_policy_id:
            pol_repo = SambaPolicyRepository(self.session)
            policy = await pol_repo.get_async(first.applied_policy_id)
            if policy and policy.market_policies:
                policy_market_data = policy.market_policies

        # account_id별 동시성 락
        lock = _get_group_lock(account_id)
        async with lock:
            # guideId 조회
            guides = await client.get_purchase_option_guides(category_id)
            if not guides:
                # 카테고리 미지원 → 단일상품 폴백
                logger.info(
                    f"카테고리 {category_id} 그룹상품 미지원, 단일상품으로 전송"
                )
                for p in products:
                    await self._transmit_product(
                        p.id, [account_id], ["price", "stock", "image", "description"]
                    )
                return {
                    "group_product_no": None,
                    "product_count": len(products),
                    "deleted_count": 0,
                    "fallback": True,
                }
            guide_id = guides[0].get("guideId")

            # 기존 단일상품 삭제
            deleted_nos = []
            for p in products:
                market_nos = p.market_product_nos or {}
                existing_no = market_nos.get(account_id)
                origin_no = market_nos.get(f"{account_id}_origin")
                delete_no = origin_no or existing_no
                if delete_no:
                    try:
                        if isinstance(delete_no, dict):
                            delete_no = delete_no.get("originProductNo", delete_no)
                        await client.delete_product(str(delete_no))
                        deleted_nos.append(delete_no)
                    except Exception:
                        pass

            # 상품 데이터 준비 (가격 계산, 이미지 업로드)
            product_dicts = []
            for p in products:
                pd = p.model_dump()

                # 상세 HTML 재생성
                pd["detail_html"] = await self._build_detail_html(pd)

                # 정책 기반 판매가 계산 (기존 _transmit_product 라인 313-341 동일 패턴)
                if policy and policy.pricing:
                    cost = (
                        pd.get("cost")
                        or pd.get("sale_price")
                        or pd.get("original_price")
                        or 0
                    )
                    pr = policy.pricing
                    common_margin_rate = pr.get("marginRate", 15)
                    common_shipping = pr.get("shippingCost", 0)
                    common_extra = pr.get("extraCharge", 0)
                    common_fee = pr.get("feeRate", 0)
                    min_margin = pr.get("minMarginAmount", 0)

                    policy_key = MARKET_TYPE_TO_POLICY_KEY.get("smartstore")
                    mp = policy_market_data.get(policy_key, {}) if policy_key else {}
                    m_margin_rate = mp.get("marginRate") or common_margin_rate
                    m_shipping = mp.get("shippingCost") or common_shipping
                    m_fee = mp.get("feeRate") or common_fee

                    margin_amt = round(cost * m_margin_rate / 100)
                    if min_margin > 0 and margin_amt < min_margin:
                        margin_amt = min_margin
                    calc_price = cost + margin_amt + m_shipping
                    if m_fee > 0 and calc_price > 0:
                        calc_price = math.ceil(calc_price / (1 - m_fee / 100))
                    if common_extra > 0:
                        calc_price += common_extra

                    pd["_final_sale_price"] = calc_price
                    logger.info(
                        f"[그룹전송] 가격 계산: 원가={cost}, 마진={margin_amt}({m_margin_rate}%), "
                        f"배송={m_shipping}, 수수료={m_fee}% → 판매가={calc_price}"
                    )

                # 이미지 업로드
                uploaded_images = []
                for img_url in (pd.get("images") or [])[:5]:
                    try:
                        naver_url = await client.upload_image_from_url(img_url)
                        uploaded_images.append(naver_url)
                    except Exception:
                        uploaded_images.append(img_url)
                pd["images"] = uploaded_images
                product_dicts.append(pd)

            # 페이로드 변환
            payload = SmartStoreClient.transform_group_product(
                products=product_dicts,
                category_id=category_id,
                guide_id=guide_id,
                account_settings=additional,
            )

            # 그룹상품 등록
            await client.register_group_product(payload)

            # 폴링
            try:
                poll_result = await client.poll_group_status(max_wait=120)
            except Exception as e:
                # 그룹 등록 실패 → 삭제된 상품 롤백 (단일상품 재등록)
                logger.error(f"그룹등록 실패, 단일상품으로 롤백: {e}")
                for p in products:
                    try:
                        await self._transmit_product(
                            p.id,
                            [account_id],
                            ["price", "stock", "image", "description"],
                        )
                    except Exception:
                        pass
                raise e

            # 결과 저장
            group_product_no = poll_result.get("groupProductNo")
            product_nos = poll_result.get("productNos", [])

            for i, p in enumerate(products):
                updates: dict[str, Any] = {"group_product_no": group_product_no}
                if i < len(product_nos):
                    pno = product_nos[i]
                    market_nos = dict(p.market_product_nos or {})
                    market_nos[account_id] = {
                        "originProductNo": pno.get("originProductNo"),
                        "smartstoreChannelProductNo": pno.get(
                            "smartstoreChannelProductNo"
                        ),
                        "groupProductNo": group_product_no,
                    }
                    updates["market_product_nos"] = market_nos
                    registered = list(p.registered_accounts or [])
                    if account_id not in registered:
                        registered.append(account_id)
                    updates["registered_accounts"] = registered
                    updates["status"] = "registered"
                await product_repo.update_async(p.id, **updates)

            return {
                "group_product_no": group_product_no,
                "product_count": len(products),
                "deleted_count": len(deleted_nos),
            }

    async def _transmit_product(
        self,
        product_id: str,
        target_account_ids: list[str],
        update_items: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
    ) -> SambaShipment:
        """단일 상품에 대한 실제 마켓 전송."""

        # 상품 전송 락 — 동일 상품 중복 전송 방지
        if product_id in _transmitting_products:
            shipment = await self.repo.create_async(
                product_id=product_id,
                target_account_ids=target_account_ids,
                update_items=update_items,
                status="failed",
                update_result={},
                transmit_result={},
                transmit_error={"_all": "이미 전송 중인 상품입니다."},
            )
            return shipment
        _transmitting_products.add(product_id)

        try:
            return await asyncio.wait_for(
                self._transmit_product_inner(
                    product_id,
                    target_account_ids,
                    update_items,
                    skip_unchanged,
                    skip_refresh=skip_refresh,
                ),
                timeout=180,  # 상품 1건당 최대 180초 (최신화+이미지업로드 포함)
            )
        except asyncio.TimeoutError:
            logger.warning(f"[전송] 상품 {product_id} 전송 180초 타임아웃 — 스킵")
            shipment = await self.repo.create_async(
                product_id=product_id,
                target_account_ids=target_account_ids,
                update_items=update_items,
                status="failed",
                update_result={},
                transmit_result={},
                transmit_error={"_all": "전송 180초 타임아웃"},
            )
            return shipment
        finally:
            _transmitting_products.discard(product_id)

    async def _transmit_product_inner(
        self,
        product_id: str,
        target_account_ids: list[str],
        update_items: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
    ) -> SambaShipment:
        """상품 전송 실제 구현 (락 획득 후 호출)."""

        def _mem_mb():
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) // 1024
            except Exception:
                return -1

        def _cgroup_mb():
            """컨테이너 전체 메모리 (cgroup)"""
            try:
                with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
                    return int(f.read().strip()) // 1024 // 1024
            except Exception:
                return -1

        logger.info(f"[메모리] 전송시작: VmRSS={_mem_mb()}MB, cgroup={_cgroup_mb()}MB")

        from backend.domain.samba.account.model import SambaMarketAccount
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import dispatch_to_market

        # 강제 중단 체크
        if is_cancel_requested():
            raise Exception("전송 강제 중단됨")

        # 1. shipment 레코드 생성
        shipment = await self.repo.create_async(
            product_id=product_id,
            target_account_ids=target_account_ids,
            update_items=update_items,
            status="pending",
            update_result={},
            transmit_result={},
            transmit_error={},
        )

        # 2. 상품 데이터 조회
        product_repo = SambaCollectedProductRepository(self.session)
        product_row = await product_repo.get_async(product_id)
        if not product_row:
            await self.repo.update_async(
                shipment.id, status="failed", error="상품을 찾을 수 없습니다."
            )
            return shipment

        product_dict = product_row.model_dump()

        # 업데이트 항목이 체크되어 있으면 소싱처 최신화 먼저 실행
        # skip_refresh=True이면 오토튠에서 이미 리프레시 완료 → 이중 호출 방지
        has_update = bool(update_items) and len(update_items) > 0
        refresh_status = ""  # 프론트 로그용
        pending_refresh_updates: dict[str, Any] = {}  # 최종 업데이트에 통합
        if (
            has_update
            and not skip_refresh
            and product_row.source_site
            and product_row.site_product_id
        ):
            try:
                from backend.domain.samba.collector.refresher import refresh_product

                refresh_result = await asyncio.wait_for(
                    refresh_product(product_row, source="transmit"),
                    timeout=60,  # 갱신이 전송 전체를 막지 않도록 60초 제한
                )
                if refresh_result.error:
                    refresh_status = f"최신화실패:{refresh_result.error[:30]}"
                    logger.warning(f"[전송] 소싱처 최신화 실패: {refresh_result.error}")
                else:
                    # DB 반영
                    refresh_updates: dict[str, Any] = {
                        "last_refreshed_at": datetime.now(UTC),
                    }
                    if refresh_result.new_sale_price is not None:
                        refresh_updates["sale_price"] = refresh_result.new_sale_price
                    if refresh_result.new_original_price is not None:
                        refresh_updates["original_price"] = (
                            refresh_result.new_original_price
                        )
                    if refresh_result.new_cost is not None:
                        refresh_updates["cost"] = refresh_result.new_cost
                    if refresh_result.new_options is not None:
                        refresh_updates["options"] = refresh_result.new_options
                    if refresh_result.new_sale_status:
                        refresh_updates["sale_status"] = refresh_result.new_sale_status
                        # is_sold_out 제거 → sale_status로 통일
                    # 이미지 갱신: update_items에 "image"가 명시적으로 체크된 경우만
                    _update_image = update_items and "image" in update_items
                    if refresh_result.new_images and _update_image:
                        refresh_updates["images"] = refresh_result.new_images
                    if refresh_result.new_detail_images and _update_image:
                        refresh_updates["detail_images"] = (
                            refresh_result.new_detail_images
                        )
                    # 가격/재고 이력 스냅샷 기록
                    snapshot: dict[str, Any] = {
                        "date": datetime.now(UTC).isoformat(),
                        "source": "transmit_refresh",
                        "sale_price": refresh_result.new_sale_price
                        if refresh_result.new_sale_price is not None
                        else product_row.sale_price,
                        "original_price": refresh_result.new_original_price
                        if refresh_result.new_original_price is not None
                        else product_row.original_price,
                        "cost": refresh_result.new_cost
                        if refresh_result.new_cost is not None
                        else product_row.cost,
                        "sale_status": refresh_result.new_sale_status or "in_stock",
                        "changed": refresh_result.changed,
                    }
                    # 옵션이 없어도 현재 옵션 스냅샷 기록
                    snap_opts = refresh_result.new_options or (
                        product_row.options if product_row.options else None
                    )
                    if snap_opts:
                        snapshot["options"] = snap_opts
                    history = list(product_row.price_history or [])
                    history.insert(0, snapshot)
                    # 최초 수집 1개 + 최근 4개 = 최대 5개
                    if len(history) <= 5:
                        refresh_updates["price_history"] = history
                    else:
                        refresh_updates["price_history"] = history[:4] + [history[-1]]
                    # 최종 업데이트에서 통합 저장
                    pending_refresh_updates = refresh_updates
                    for k, v in refresh_updates.items():
                        product_dict[k] = v
                    # 가격/재고 변동 각각 판단
                    old_cost = getattr(product_row, "cost", None)
                    new_cost = refresh_result.new_cost
                    cost_changed = new_cost is not None and new_cost != old_cost
                    old_opts = getattr(product_row, "options", None) or []
                    new_opts = refresh_result.new_options
                    stock_changed = False
                    stock_change_count = 0
                    if new_opts is not None:
                        old_stocks = {
                            o.get("name", ""): o.get("stock", 0) for o in old_opts
                        }
                        new_stocks = {
                            o.get("name", ""): o.get("stock", 0) for o in new_opts
                        }
                        stock_changes = [
                            k
                            for k in set(
                                list(old_stocks.keys()) + list(new_stocks.keys())
                            )
                            if old_stocks.get(k) != new_stocks.get(k)
                        ]
                        stock_changed = len(stock_changes) > 0
                        stock_change_count = len(stock_changes)
                    cur_cost_val = (
                        int(new_cost)
                        if new_cost is not None
                        else (int(old_cost) if old_cost else 0)
                    )
                    old_cost_int = int(old_cost) if old_cost else 0
                    new_cost_int = (
                        int(new_cost) if new_cost is not None else old_cost_int
                    )
                    refresh_status = f"원가 {old_cost_int:,}>{new_cost_int:,}, 재고변동 {stock_change_count}건"
                    logger.info(f"[전송] 소싱처 최신화 완료 — {refresh_status}")
            except asyncio.TimeoutError:
                refresh_status = "최신화실패:60초 타임아웃"
                logger.warning("[전송] 소싱처 최신화 타임아웃 (60초) — 갱신 건너뜀")
            except Exception as ref_e:
                refresh_status = f"최신화예외:{str(ref_e)[:30]}"
                logger.warning(f"[전송] 소싱처 최신화 예외: {ref_e}")
        # 최신화를 안 했어도 현재 원가 표시
        if not refresh_status:
            _cur_cost = int(product_row.cost or product_row.sale_price or 0)
            _opt_count = len(product_row.options or [])
            refresh_status = f"원가 {_cur_cost:,}, 옵션 {_opt_count}건"

        # 조기 스킵: 이미 등록된 상품 + 가격재고 업데이트 모드 + 변동 없음 → 나머지 로직 전부 건너뜀
        _is_registered = product_row.status == "registered" and bool(
            product_row.registered_accounts
        )
        if skip_unchanged and has_update and _is_registered:
            # 소싱처 최신화에서 변동이 없었으면 즉시 스킵
            if not pending_refresh_updates or refresh_status.startswith("최신화실패"):
                pass  # 최신화 안 했거나 실패 → 스킵 판정 불가, 계속 진행
            else:
                _old_cost = product_row.cost or 0
                _new_cost = pending_refresh_updates.get("cost", _old_cost)
                _old_opts = product_row.options or []
                _new_opts = pending_refresh_updates.get("options", _old_opts)
                if _new_cost == _old_cost and _new_opts == _old_opts:
                    logger.info(
                        f"[전송] 조기 스킵 — 소싱처 변동 없음 (원가 {int(_old_cost):,})"
                    )
                    shipment = SambaShipment(
                        product_id=product_id,
                        status="completed",
                        result={"refresh": refresh_status} if refresh_status else None,
                    )
                    self.session.add(shipment)
                    await self.session.flush()
                    return shipment

        # 이미지/상세페이지 전송 판단
        # 오토튠 재전송(price/stock만) → 이미지 불필요
        # 그 외(수동 전송) → 항상 이미지 전송 (DB 현재 이미지 사용)
        is_price_stock_only = update_items and set(update_items) <= {"price", "stock"}
        needs_image = not is_price_stock_only

        # 2-1. 정책의 상세 템플릿으로 detail_html 재생성 (이미지/상세 업데이트 시에만)
        if needs_image:
            product_dict["detail_html"] = await self._build_detail_html(product_dict)

        # 3. 카테고리 매핑 자동 조회 (성별 + category1~4 조합)
        cat_parts = [
            product_row.category1,
            product_row.category2,
            product_row.category3,
            product_row.category4,
        ]
        raw_category = (
            " > ".join(c for c in cat_parts if c) or product_row.category or ""
        )

        # 성별 prefix는 의류 카테고리일 때만 추가 (신발/가방 등은 제외)
        sex_prefix = ""
        cat1 = (product_row.category1 or "").strip()
        clothing_categories = {
            "상의",
            "하의",
            "아우터",
            "원피스",
            "니트",
            "셔츠",
            "팬츠",
            "의류",
        }
        if cat1 in clothing_categories:
            kream = (
                product_row.kream_data if hasattr(product_row, "kream_data") else None
            )
            if isinstance(kream, dict):
                sex_list = kream.get("sex", [])
                if isinstance(sex_list, list) and sex_list:
                    sex = sex_list[0]
                    if "남" in sex:
                        sex_prefix = "남성의류"
                    elif "여" in sex:
                        sex_prefix = "여성의류"

        source_category = (
            f"{sex_prefix} > {raw_category}"
            if sex_prefix and raw_category
            else raw_category
        )

        # 그룹 매핑 조회
        group_mappings = None
        if product_row.search_filter_id:
            from backend.domain.samba.collector.repository import (
                SambaSearchFilterRepository,
            )

            sf_repo = SambaSearchFilterRepository(self.session)
            sf = await sf_repo.get_async(product_row.search_filter_id)
            if sf and sf.target_mappings:
                group_mappings = sf.target_mappings

        mapped_categories = await self._resolve_category_mappings(
            product_row.source_site or "",
            source_category,
            target_account_ids,
            group_mappings=group_mappings,
        )
        # 성별 prefix 포함 시 매핑 못 찾으면 prefix 없이 재시도
        if sex_prefix and not mapped_categories:
            mapped_categories = await self._resolve_category_mappings(
                product_row.source_site or "",
                raw_category,
                target_account_ids,
                group_mappings=group_mappings,
            )
        await self.repo.update_async(shipment.id, mapped_categories=mapped_categories)

        # 4. 업데이트 단계
        await self.repo.update_async(shipment.id, status="updating")
        update_result: dict[str, str] = {}
        for item in update_items:
            update_result[item] = "success"
        await self.repo.update_async(
            shipment.id, status="transmitting", update_result=update_result
        )

        # 5. 계정 정보 조회 및 마켓별 전송
        account_repo = SambaMarketAccountRepository(self.session)

        # 정책 기반 계정 필터링: 정책이 있으면 참조하되, 사용자 선택 계정은 보존
        policy = None
        policy_market_data: dict[str, Any] = {}
        MARKET_TYPE_TO_POLICY_KEY = {
            "coupang": "쿠팡",
            "ssg": "신세계몰",
            "smartstore": "스마트스토어",
            "11st": "11번가",
            "gmarket": "지마켓",
            "auction": "옥션",
            "gsshop": "GS샵",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL",
            "kream": "KREAM",
            "ebay": "eBay",
            "lazada": "Lazada",
            "qoo10": "Qoo10",
            "shopee": "Shopee",
            "shopify": "Shopify",
            "zoom": "Zum(줌)",
            "toss": "토스",
            "rakuten": "라쿠텐",
            "amazon": "아마존",
            "buyma": "바이마",
        }
        if not product_row.applied_policy_id:
            logger.warning(f"[전송] 상품 {product_id} 정책 미설정 — 전송 차단")
            await self.repo.update_async(
                shipment.id,
                status="failed",
                error="정책 미적용 상품은 전송할 수 없습니다.",
            )
            return shipment

        from backend.domain.samba.policy.repository import SambaPolicyRepository

        policy_repo = SambaPolicyRepository(self.session)
        policy = await policy_repo.get_async(product_row.applied_policy_id)
        if policy and policy.market_policies:
            policy_market_data = policy.market_policies

        # 정책의 상품명 규칙(name_rule) 기반 상품명 조합 적용
        if policy and policy.extras:
            name_rule_id = (policy.extras or {}).get("name_rule_id")
            if name_rule_id:
                from backend.domain.samba.policy.model import SambaNameRule
                from sqlmodel import select

                stmt = select(SambaNameRule).where(SambaNameRule.id == name_rule_id)
                result = await self.session.exec(stmt)
                name_rule = result.first()
                if name_rule:
                    product_dict["name"] = self._compose_product_name(
                        product_dict, name_rule
                    )
                    # 마켓별 상품명 조합이 있으면 _dispatch_one에서 덮어쓸 수 있도록 name_rule 보관
                    product_dict["_name_rule"] = name_rule
                    product_dict["_original_name"] = product_row.model_dump().get(
                        "name", ""
                    )

        # 글로벌 삭제어 적용 (상품명에서 금칙어 제거)
        # DB 실제 데이터: type='deletion', scope='all'
        import re as _re
        from backend.domain.samba.forbidden.repository import (
            SambaForbiddenWordRepository,
        )

        fw_repo = SambaForbiddenWordRepository(self.session)
        forbidden_words = await fw_repo.list_active("deletion")
        if forbidden_words and product_dict.get("name"):
            name = product_dict["name"]
            for fw in forbidden_words:
                if fw.word:
                    name = _re.sub(_re.escape(fw.word), "", name, flags=_re.IGNORECASE)
            # 연속 공백 정리
            product_dict["name"] = _re.sub(r"\s{2,}", " ", name).strip()

        # 정책이 있으면 계정 필터링, 없으면 사용자 선택 전체 유지
        if policy_market_data:
            # 배치 조회 (N+1 → 1회)
            from sqlmodel import select as _sel
            from backend.domain.samba.account.model import SambaMarketAccount

            _stmt = _sel(SambaMarketAccount).where(
                SambaMarketAccount.id.in_(target_account_ids)
            )
            _res = await self.session.execute(_stmt)
            _account_map = {a.id: a for a in _res.scalars().all()}

            filtered_ids = []
            for aid in target_account_ids:
                acc = _account_map.get(aid)
                if not acc:
                    continue
                policy_key = MARKET_TYPE_TO_POLICY_KEY.get(acc.market_type)
                if not policy_key:
                    # 정책 키 매핑 안 되는 마켓 → 그대로 허용
                    filtered_ids.append(aid)
                    continue
                mp = policy_market_data.get(policy_key, {})
                if not mp:
                    # 정책에 이 마켓이 없음 → 그대로 허용 (사용자가 직접 선택)
                    filtered_ids.append(aid)
                    continue
                policy_acc_ids = mp.get("accountIds", [])
                if not policy_acc_ids and mp.get("accountId"):
                    policy_acc_ids = [mp["accountId"]]
                # 정책에 계정 목록이 있으면 해당 계정만, 없으면 모두 허용
                if policy_acc_ids and aid not in policy_acc_ids:
                    continue
                filtered_ids.append(aid)
            target_account_ids = filtered_ids
            logger.info(f"[전송] 정책 필터링 후 계정: {len(target_account_ids)}개")

        transmit_result: dict[str, str] = {}
        transmit_error: dict[str, str] = {}
        update_mode_accounts: set[str] = (
            set()
        )  # PATCH 모드였던 계정 (실패해도 등록정보 보존)

        # 전송 대상 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel2
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA

        _stmt2 = _sel2(_SMA).where(_SMA.id.in_(target_account_ids))
        _res2 = await self.session.execute(_stmt2)
        _dispatch_account_map = {a.id: a for a in _res2.scalars().all()}

        # 전 옵션 품절 시 소싱처 1회 최신화 시도 (30초 타임아웃)
        _all_opts = product_dict.get("options") or []
        _all_sold = _all_opts and all(
            (o.get("isSoldOut", False) or (o.get("stock") or 0) <= 0)
            for o in _all_opts
            if isinstance(o, dict)
        )
        if (
            _all_sold
            and not pending_refresh_updates
            and product_row.source_site
            and product_row.site_product_id
        ):
            logger.info(
                f"[전송] 상품 {product_id} 전 옵션 품절 → 소싱처 1회 최신화 시도 (30초)"
            )
            try:
                from backend.domain.samba.collector.refresher import (
                    refresh_product as _refresh_sold,
                )

                _sold_refresh = await asyncio.wait_for(
                    _refresh_sold(product_row, source="transmit"),
                    timeout=30,
                )
                if not _sold_refresh.error and _sold_refresh.new_options is not None:
                    # 옵션/가격 업데이트
                    product_dict["options"] = _sold_refresh.new_options
                    if _sold_refresh.new_sale_price is not None:
                        product_dict["sale_price"] = _sold_refresh.new_sale_price
                    if _sold_refresh.new_original_price is not None:
                        product_dict["original_price"] = (
                            _sold_refresh.new_original_price
                        )
                    if _sold_refresh.new_cost is not None:
                        product_dict["cost"] = _sold_refresh.new_cost
                    if _sold_refresh.new_sale_status:
                        product_dict["sale_status"] = _sold_refresh.new_sale_status
                    # pending_refresh_updates에도 반영 (최종 DB 저장용)
                    pending_refresh_updates.update(
                        {
                            "options": _sold_refresh.new_options,
                            "last_refreshed_at": datetime.now(UTC),
                        }
                    )
                    if _sold_refresh.new_sale_price is not None:
                        pending_refresh_updates["sale_price"] = (
                            _sold_refresh.new_sale_price
                        )
                    if _sold_refresh.new_original_price is not None:
                        pending_refresh_updates["original_price"] = (
                            _sold_refresh.new_original_price
                        )
                    if _sold_refresh.new_cost is not None:
                        pending_refresh_updates["cost"] = _sold_refresh.new_cost
                    if _sold_refresh.new_sale_status:
                        pending_refresh_updates["sale_status"] = (
                            _sold_refresh.new_sale_status
                        )
                    # 가격/재고 변동 계산 (기존 최신화와 동일 포맷)
                    _old_cost = getattr(product_row, "cost", None) or 0
                    _new_cost = (
                        _sold_refresh.new_cost
                        if _sold_refresh.new_cost is not None
                        else _old_cost
                    )
                    _old_opts = getattr(product_row, "options", None) or []
                    _old_stocks = {
                        o.get("name", ""): o.get("stock", 0) for o in _old_opts
                    }
                    _new_stocks = {
                        o.get("name", ""): o.get("stock", 0)
                        for o in _sold_refresh.new_options
                    }
                    _stock_changes = [
                        k
                        for k in set(
                            list(_old_stocks.keys()) + list(_new_stocks.keys())
                        )
                        if _old_stocks.get(k) != _new_stocks.get(k)
                    ]
                    _stock_change_count = len(_stock_changes)
                    # 가격/재고 이력 스냅샷 기록
                    _snap = {
                        "date": datetime.now(UTC).isoformat(),
                        "source": "transmit_soldout_refresh",
                        "sale_price": _sold_refresh.new_sale_price
                        if _sold_refresh.new_sale_price is not None
                        else product_row.sale_price,
                        "original_price": _sold_refresh.new_original_price
                        if _sold_refresh.new_original_price is not None
                        else product_row.original_price,
                        "cost": _sold_refresh.new_cost
                        if _sold_refresh.new_cost is not None
                        else product_row.cost,
                        "sale_status": _sold_refresh.new_sale_status or "in_stock",
                        "changed": _sold_refresh.changed,
                        "options": _sold_refresh.new_options,
                    }
                    _history = list(product_row.price_history or [])
                    _history.insert(0, _snap)
                    if len(_history) <= 5:
                        pending_refresh_updates["price_history"] = _history
                    else:
                        pending_refresh_updates["price_history"] = _history[:4] + [
                            _history[-1]
                        ]
                    logger.info(
                        f"[전송] 품절 최신화 완료 — 원가 {int(_old_cost):,}>{int(_new_cost):,}, 재고변동 {_stock_change_count}건"
                    )
                    if not refresh_status:
                        refresh_status = f"원가 {int(_old_cost):,}>{int(_new_cost):,}, 재고변동 {_stock_change_count}건"
                else:
                    _err = (
                        _sold_refresh.error
                        if _sold_refresh.error
                        else "옵션 데이터 없음"
                    )
                    logger.info(f"[전송] 품절 최신화 실패 — {_err}")
            except asyncio.TimeoutError:
                logger.warning("[전송] 전 옵션 품절 소싱처 최신화 타임아웃 (30초)")
            except Exception as _sold_e:
                logger.warning(f"[전송] 전 옵션 품절 소싱처 최신화 예외: {_sold_e}")

        # 계정별 전송을 병렬 코루틴으로 실행

        async def _dispatch_one(account_id: str) -> dict[str, Any]:
            """단일 계정 전송 — 결과 dict 반환."""
            from backend.db.orm import get_write_sessionmaker

            res: dict[str, Any] = {
                "account_id": account_id,
                "status": "failed",
                "error": "",
                "product_nos": {},
                "sent_snapshot": None,
                "is_update": False,
                "clear_nos": [],
            }
            # 병렬 실행 시 AsyncSession 공유 방지 — 계정별 독립 세션 사용
            acct_session = get_write_sessionmaker()()
            try:
                account = _dispatch_account_map.get(account_id)
                if not account:
                    res["error"] = "계정을 찾을 수 없습니다."
                    return res

                market_type = account.market_type
                category_id = mapped_categories.get(market_type, "")

                # ESM Plus 크로스매핑: 지마켓↔옥션 자동 변환
                if not category_id and market_type in ("gmarket", "auction"):
                    other = "auction" if market_type == "gmarket" else "gmarket"
                    other_id = mapped_categories.get(other, "")
                    if other_id and str(other_id).isdigit():
                        from backend.domain.samba.proxy.esmplus import esm_map_category

                        category_id = esm_map_category(other_id, other, market_type)
                        if category_id:
                            logger.info(
                                f"[ESM 크로스매핑] {other}({other_id}) → {market_type}({category_id})"
                            )

                if not category_id:
                    res["error"] = "카테고리 매핑 없음"
                    logger.warning(
                        f"[전송] 상품 {product_id} → {market_type} 카테고리 매핑 없음 (스킵)"
                    )
                    return res

                if market_type != "coupang" and not str(category_id).isdigit():
                    res["error"] = f"최하단 카테고리 매핑 필요 (현재: {category_id})"
                    logger.warning(
                        f"[전송] 상품 {product_id} → {market_type} 최하단 카테고리 미매핑: '{category_id}' (스킵)"
                    )
                    return res

                # 기존 상품번호 확인 (품절 삭제 판단에도 필요)
                existing_nos = product_row.market_product_nos or {}
                if market_type == "smartstore":
                    existing_product_no = existing_nos.get(
                        f"{account_id}_origin", ""
                    ) or existing_nos.get(account_id, "")
                else:
                    existing_product_no = existing_nos.get(account_id, "")

                # 전 옵션 품절 체크 — 마켓 등록 상품이면 마켓 삭제, 미등록이면 스킵
                _opts = product_dict.get("options") or []
                if _opts and all(
                    (o.get("isSoldOut", False) or (o.get("stock") or 0) <= 0)
                    for o in _opts
                    if isinstance(o, dict)
                ):
                    # 이미 마켓 등록된 상품이면 삭제 처리
                    _reg_accs = product_dict.get("registered_accounts") or []
                    if account_id in _reg_accs and existing_product_no:
                        try:
                            from backend.domain.samba.shipment.dispatcher import (
                                delete_from_market,
                            )

                            del_result = await delete_from_market(
                                acct_session, market_type, product_dict, account_id
                            )
                            if del_result.get("success"):
                                # registered_accounts에서 제거 + DB 반영
                                _prod = await SambaCollectedProductRepository(
                                    acct_session
                                ).get_async(product_id)
                                if _prod:
                                    new_reg = [
                                        a
                                        for a in (_prod.registered_accounts or [])
                                        if a != account_id
                                    ]
                                    _prod.registered_accounts = (
                                        new_reg if new_reg else None
                                    )
                                    # 순차 실행이므로 세션 커밋 안전 (병렬 시 충돌 위험)
                                    await acct_session.commit()
                                res["status"] = "completed"
                                res["results"] = {account_id: "deleted"}
                                logger.info(
                                    f"[전송] 상품 {product_id} → {market_type} 전 옵션 품절 → 마켓 삭제 완료"
                                )
                                return res
                        except Exception as e:
                            logger.warning(f"[전송] 전 옵션 품절 마켓 삭제 실패: {e}")
                    res["error"] = "전 옵션 품절 (등록 불가)"
                    logger.info(
                        f"[전송] 상품 {product_id} → {market_type} 전 옵션 품절 스킵"
                    )
                    return res

                # 마켓별 판매가 계산 (product_dict 원본 보호를 위해 복사본 사용)
                acct_product = dict(product_dict)

                # 마켓별 상품명 조합 덮어쓰기
                _nr = product_dict.get("_name_rule")
                if _nr and getattr(_nr, "market_name_compositions", None):
                    _market_comp = _nr.market_name_compositions.get(market_type)
                    if _market_comp:
                        # 원본 상품 데이터로 마켓별 조합 실행
                        _orig = dict(product_dict)
                        _orig["name"] = product_dict.get(
                            "_original_name", product_dict.get("name", "")
                        )
                        acct_product["name"] = self._compose_product_name(
                            _orig, _nr, market_type=market_type
                        )
                cost = (
                    acct_product.get("cost")
                    or acct_product.get("sale_price")
                    or acct_product.get("original_price")
                    or 0
                )
                if policy and policy.pricing:
                    pr = policy.pricing
                    common_margin_rate = pr.get("marginRate", 15)
                    common_shipping = pr.get("shippingCost", 0)
                    common_extra = pr.get("extraCharge", 0)
                    common_fee = pr.get("feeRate", 0)
                    min_margin = pr.get("minMarginAmount", 0)

                    policy_key = MARKET_TYPE_TO_POLICY_KEY.get(market_type)
                    mp = policy_market_data.get(policy_key, {}) if policy_key else {}
                    m_margin_rate = mp.get("marginRate") or common_margin_rate
                    m_shipping = mp.get("shippingCost") or common_shipping
                    m_fee = mp.get("feeRate") or common_fee

                    margin_amt = round(cost * m_margin_rate / 100)
                    if min_margin > 0 and margin_amt < min_margin:
                        margin_amt = min_margin
                    calc_price = cost + margin_amt + m_shipping
                    if m_fee > 0 and calc_price > 0:
                        calc_price = math.ceil(calc_price / (1 - m_fee / 100))
                    if common_extra > 0:
                        calc_price += common_extra

                    acct_product["sale_price"] = calc_price
                    logger.info(
                        f"[전송] 정책 가격 계산: 원가={cost}, 마진={margin_amt}({m_margin_rate}%), 배송={m_shipping}, 수수료={m_fee}% → 판매가={calc_price}"
                    )
                    logger.info(f"[메모리] 가격계산 후: {_mem_mb()}MB")

                # 스킵 판단
                cur_price = int(acct_product.get("sale_price") or 0)
                cur_cost_int = int(acct_product.get("cost") or 0)
                last_sent = (product_row.last_sent_data or {}).get(account_id)
                if last_sent:
                    last_price = int(last_sent.get("sale_price") or 0)
                    last_cost_sent = int(last_sent.get("cost") or 0)
                    last_opts = last_sent.get("options", [])
                    cur_opts = [
                        {
                            "name": o.get("name", ""),
                            "price": o.get("price"),
                            "stock": o.get("stock"),
                        }
                        for o in (acct_product.get("options") or [])
                    ]
                    opts_changed = last_opts != cur_opts
                else:
                    last_price = 0
                    last_cost_sent = 0
                    opts_changed = False

                if skip_unchanged and has_update and last_sent:
                    if (
                        last_price == cur_price
                        and last_cost_sent == cur_cost_int
                        and not opts_changed
                    ):
                        res["status"] = "skipped"
                        logger.info(f"[전송] {market_type} 스킵")
                        return res

                # 기존 상품번호 확인
                existing_nos = product_row.market_product_nos or {}
                if market_type == "smartstore":
                    existing_product_no = existing_nos.get(
                        f"{account_id}_origin", ""
                    ) or existing_nos.get(account_id, "")
                else:
                    existing_product_no = existing_nos.get(account_id, "")
                if existing_product_no:
                    res["is_update"] = True
                    logger.info(
                        f"[전송] 기존 상품번호 발견 → 수정 모드: {market_type} #{existing_product_no}"
                    )

                # 마켓 API 호출 (계정별 세마포어 — 30초 타임아웃)
                account_sem = _get_account_semaphore(account_id)
                try:
                    await asyncio.wait_for(account_sem.acquire(), timeout=120)
                except asyncio.TimeoutError:
                    res["error"] = f"계정 사용 중 (120초 타임아웃, {market_type})"
                    logger.warning(f"[전송] 계정 {account_id} 세마포어 120초 타임아웃")
                    return res
                try:
                    logger.info(f"[메모리] 마켓전송 전: VmRSS={_mem_mb()}MB, cgroup={_cgroup_mb()}MB")
                    result = await dispatch_to_market(
                        acct_session,
                        market_type,
                        acct_product,
                        category_id,
                        account=account,
                        existing_product_no=existing_product_no,
                    )
                finally:
                    account_sem.release()

                # 404 → 상품번호 초기화
                if result.get("_clear_product_no"):
                    res["clear_nos"] = [account_id, f"{account_id}_origin"]
                    logger.info(
                        f"[전송] 404 상품번호 초기화: {market_type} (계정: {account_id})"
                    )

                if result.get("success"):
                    res["status"] = "success"
                    # 상품번호 추출
                    product_no = result.get("spdNo") or ""
                    api_data: dict[str, Any] = {}
                    if not product_no:
                        result_data = result.get("data", {})
                        if isinstance(result_data, dict):
                            api_data = result_data.get("data", result_data)
                            if isinstance(api_data, list) and api_data:
                                api_data = (
                                    api_data[0] if isinstance(api_data[0], dict) else {}
                                )
                            if isinstance(api_data, dict):
                                product_no = (
                                    api_data.get("smartstoreChannelProductNo")
                                    or api_data.get("originProductNo")
                                    or api_data.get("productNo")
                                    or api_data.get("sellerProductId")
                                    or api_data.get("spdNo")
                                    or api_data.get("itemId")
                                    or api_data.get("supPrdCd")
                                    or api_data.get("prdNo")
                                    or api_data.get("goodsNo")
                                    or api_data.get("product_id")
                                    or api_data.get("productId")
                                    or ""
                                )
                    if product_no:
                        nos: dict[str, str] = {account_id: str(product_no)}
                        if market_type == "smartstore" and isinstance(api_data, dict):
                            origin_no = api_data.get("originProductNo") or ""
                            if origin_no:
                                nos[f"{account_id}_origin"] = str(origin_no)
                            logger.info(
                                f"[전송] 스마트스토어 상품번호 — channel={product_no}, origin={origin_no}"
                            )
                        res["product_nos"] = nos
                        logger.info(f"[전송] {market_type} 상품번호: {product_no}")

                    # 스냅샷 준비
                    res["sent_snapshot"] = {
                        "sale_price": int(acct_product.get("sale_price") or 0),
                        "cost": int(acct_product.get("cost") or 0),
                        "options": [
                            {
                                "name": o.get("name", ""),
                                "price": o.get("price"),
                                "stock": o.get("stock"),
                            }
                            for o in (acct_product.get("options") or [])
                        ],
                        "sent_at": datetime.now(UTC).isoformat(),
                    }

                    action = "수정" if existing_product_no else "등록"
                    logger.info(
                        f"[전송] {market_type} {action} 성공 - 상품: {product_id}, 계정: {account_id}"
                    )
                else:
                    _msg = result.get("message", "알 수 없는 오류")
                    res["error"] = str(_msg) if not isinstance(_msg, str) else _msg
                    logger.warning(f"[전송] {market_type} 실패 - {_msg}")

            except Exception as exc:
                _err = str(exc)
                # asyncio 내부 객체 누출 방지
                if "<asyncio" in _err or "Semaphore" in _err:
                    _err = f"전송 타임아웃 또는 동시성 오류 ({market_type})"
                    logger.error(f"[전송] 계정 {account_id} 세마포어 누출: {exc}")
                else:
                    logger.error(f"[전송] 계정 {account_id} 예외: {exc}")
                res["error"] = _err
            finally:
                await acct_session.close()
            return res

        # 계정별 순차 전송 — AsyncSession 동시 접근 방지
        account_results = []
        for aid in target_account_ids:
            try:
                r = await _dispatch_one(aid)
                account_results.append(r)
            except Exception as e:
                account_results.append(e)

        # 결과 병합 + DB 일괄 업데이트
        merged_nos = dict(product_row.market_product_nos or {})
        merged_sent = dict(product_row.last_sent_data or {})
        for ar in account_results:
            if isinstance(ar, Exception):
                continue
            aid = ar["account_id"]
            transmit_result[aid] = ar["status"]
            if ar["error"]:
                transmit_error[aid] = ar["error"]
            if ar["is_update"]:
                update_mode_accounts.add(aid)
            # 404 초기화
            for key in ar.get("clear_nos", []):
                merged_nos.pop(key, None)
            # 상품번호 병합
            merged_nos.update(ar.get("product_nos", {}))
            # 스냅샷 병합
            if ar.get("sent_snapshot"):
                merged_sent[aid] = ar["sent_snapshot"]

        # DB 1회 업데이트
        try:
            await product_repo.update_async(
                product_id,
                market_product_nos=merged_nos or None,
                last_sent_data=merged_sent or None,
            )
        except Exception as _db_e:
            logger.warning(f"[전송] DB 업데이트 실패: {_db_e}")

        # 6. 최종 상태 결정
        values = list(transmit_result.values())
        non_skip = [v for v in values if v != "skipped"]
        all_skipped = len(values) > 0 and len(non_skip) == 0
        all_success = len(non_skip) > 0 and all(v == "success" for v in non_skip)
        all_failed = len(non_skip) > 0 and all(v == "failed" for v in non_skip)

        if all_skipped:
            final_status = "skipped"
        elif all_success:
            final_status = "completed"
        elif all_failed:
            final_status = "failed"
        else:
            final_status = "partial"

        final_update: dict[str, Any] = {
            "status": final_status,
            "transmit_result": transmit_result,
            "transmit_error": transmit_error if transmit_error else None,
            "completed_at": datetime.now(UTC),
        }
        if refresh_status:
            final_update["update_result"] = {"refresh": refresh_status}
        updated = await self.repo.update_async(shipment.id, **final_update)

        # 6. 상품 상태 업데이트 (등록된 계정 목록)
        # 성공한 계정은 추가, 실패한 계정은 제거
        # 단, PATCH(수정) 모드에서 실패한 계정은 등록정보 보존 (404 케이스는 이미 위에서 처리됨)
        success_accounts = [
            aid for aid, status in transmit_result.items() if status == "success"
        ]
        # 신규등록(POST) 실패만 제거 대상 — 수정(PATCH) 실패/스킵은 기존 등록정보 유지
        removable_failed = [
            aid
            for aid, status in transmit_result.items()
            if status not in ("success", "skipped") and aid not in update_mode_accounts
        ]
        # DB에서 최신 상태 다시 읽기 (전송 중 market_product_nos가 업데이트되었을 수 있음)
        refreshed = await product_repo.get_async(product_id)
        existing = (
            refreshed.registered_accounts
            if refreshed
            else product_row.registered_accounts
        ) or []
        existing_nos = dict(
            (
                refreshed.market_product_nos
                if refreshed
                else product_row.market_product_nos
            )
            or {}
        )
        # 성공 추가 + 신규등록 실패만 제거
        new_accounts = list(
            set([a for a in existing if a not in removable_failed] + success_accounts)
        )
        # 신규등록 실패한 계정의 상품번호만 제거
        new_nos = {k: v for k, v in existing_nos.items() if k not in removable_failed}
        # 최신화 실패 시에는 상품 데이터 변경하지 않음 (updated_at 유지)
        if refresh_status and (
            refresh_status.startswith("최신화실패")
            or refresh_status.startswith("최신화예외")
        ):
            logger.info("[전송] 최신화 실패 → 상품 데이터 변경 안 함")
        else:
            update_data: dict[str, Any] = {
                "registered_accounts": new_accounts if new_accounts else None,
                "market_product_nos": new_nos if new_nos else None,
                "status": "registered" if new_accounts else "collected",
                "updated_at": datetime.now(UTC),
            }
            # 소싱처 최신화 결과도 통합 저장
            if pending_refresh_updates:
                update_data.update(pending_refresh_updates)
            await product_repo.update_async(product_id, **update_data)

        logger.info(
            f"Shipment {shipment.id} 완료 status={final_status} "
            f"product={product_id} 성공={sum(1 for v in values if v == 'success')}/{len(values)}"
        )
        if not updated:
            logger.warning(f"Shipment {shipment.id} 업데이트 실패, DB 재조회")
            updated = await self.repo.get_async(shipment.id)
        return updated or shipment

    # ==================== 상품명 조합 ====================

    def _compose_product_name(
        self, product: dict[str, Any], name_rule: Any, *, market_type: str | None = None
    ) -> str:
        """정책의 상품명 규칙(name_composition)에 따라 상품명을 조합.

        market_type이 지정되고 market_name_compositions에 해당 마켓 설정이 있으면 마켓별 조합 사용.
        """
        # 마켓별 조합이 있으면 우선 사용
        composition = None
        if market_type and getattr(name_rule, "market_name_compositions", None):
            composition = name_rule.market_name_compositions.get(market_type)
        if not composition:
            composition = name_rule.name_composition
        if not composition:
            return product.get("name", "")

        # SEO 검색키워드: seo_keywords 배열을 공백 연결
        seo_kws = product.get("seo_keywords") or []
        seo_text = " ".join(seo_kws[:2]) if seo_kws else ""

        tag_map = {
            "{상품명}": product.get("name", ""),
            "{브랜드명}": product.get("brand", ""),
            "{모델명}": product.get("style_code", ""),
            "{사이트명}": product.get("source_site", ""),
            "{상품번호}": product.get("site_product_id", ""),
            "{검색키워드}": seo_text,
        }

        # 조합 태그 순서대로 값 치환 (빈 값이면 태그 자체 제거)
        parts = [tag_map.get(tag, "") if tag in tag_map else tag for tag in composition]
        composed = " ".join(p for p in parts if p and p.strip())

        # 치환어 적용
        import re

        replacements = name_rule.replacements or []
        if replacements:
            for r in replacements:
                fr = (
                    r.get("from", "")
                    if isinstance(r, dict)
                    else getattr(r, "from_", "")
                )
                to = r.get("to", "") if isinstance(r, dict) else getattr(r, "to", "")
                if not fr:
                    continue
                case_insensitive = (
                    r.get("caseInsensitive", False)
                    if isinstance(r, dict)
                    else getattr(r, "caseInsensitive", False)
                )
                flags = re.IGNORECASE if case_insensitive else 0
                composed = re.sub(re.escape(fr), to or "", composed, flags=flags)

        # 중복 단어 제거
        if name_rule.dedup_enabled:
            words = composed.split()
            seen: set[str] = set()
            deduped: list[str] = []
            for w in words:
                lower = w.lower()
                if lower not in seen:
                    seen.add(lower)
                    deduped.append(w)
            composed = " ".join(deduped)

        # prefix/suffix 적용
        if name_rule.prefix:
            composed = f"{name_rule.prefix} {composed}"
        if name_rule.suffix:
            composed = f"{composed} {name_rule.suffix}"

        return composed.strip()

    # ==================== 상세페이지 HTML 생성 ====================

    async def _build_detail_html(self, product: dict[str, Any]) -> str:
        """정책의 상세 템플릿(상단/하단 이미지)과 상품 이미지를 조합하여 상세 HTML 생성.

        구조: 상단이미지 → 대표이미지 → 추가이미지 → 하단이미지
        """
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        from backend.domain.samba.policy.model import SambaDetailTemplate
        from backend.domain.shared.base_repository import BaseRepository

        parts: list[str] = []
        img_tag = '<div style="text-align:center;"><img src="{url}" style="max-width:860px;width:100%;" /></div>'

        # 정책에서 상세 템플릿 조회
        policy_id = product.get("applied_policy_id")
        top_img = ""
        bottom_img = ""
        # 이미지 포함 설정 (기본값: 상단/대표/추가/상세/하단 포함)
        img_checks: dict[str, bool] = {
            "topImg": True,
            "main": True,
            "sub": True,
            "title": False,
            "option": False,
            "detail": True,
            "bottomImg": True,
        }
        img_order: list[str] = [
            "topImg",
            "main",
            "sub",
            "title",
            "option",
            "detail",
            "bottomImg",
        ]

        if policy_id:
            policy_repo = SambaPolicyRepository(self.session)
            policy = await policy_repo.get_async(policy_id)
            if policy and policy.extras:
                template_id = policy.extras.get("detail_template_id")
                logger.info(f"[상세HTML] 정책 {policy_id} 템플릿ID: {template_id}")
                if template_id:
                    tpl_repo = BaseRepository(self.session, SambaDetailTemplate)
                    tpl = await tpl_repo.get_async(template_id)
                    if tpl:
                        top_img = tpl.top_image_s3_key or ""
                        bottom_img = tpl.bottom_image_s3_key or ""
                        if tpl.img_checks:
                            img_checks.update(tpl.img_checks)
                        if tpl.img_order:
                            img_order = tpl.img_order
                        logger.info(
                            f"[상세HTML] 템플릿 로드 — 상단:{bool(top_img)}, 하단:{bool(bottom_img)}, checks:{img_checks}"
                        )
                    else:
                        logger.warning(f"[상세HTML] 템플릿 {template_id} 조회 실패")
            else:
                logger.info(
                    f"[상세HTML] 정책 {policy_id} extras 없음 또는 정책 조회 실패"
                )
        else:
            logger.info("[상세HTML] applied_policy_id 없음 — 템플릿 미적용")

        images = product.get("images") or []
        detail_images = product.get("detail_images") or []
        # 추가이미지(sub)에서 출력된 URL을 추적 → detail에서 중복 제외
        sub_set = set(images[1:]) if len(images) > 1 else set()

        # img_order 순서대로, img_checks가 True인 항목만 생성
        for item_id in img_order:
            if not img_checks.get(item_id, False):
                continue
            if item_id == "topImg" and top_img:
                parts.append(img_tag.format(url=top_img))
            elif item_id == "main" and images:
                parts.append(img_tag.format(url=images[0]))
            elif item_id == "sub":
                for sub_img in images[1:]:
                    parts.append(img_tag.format(url=sub_img))
            elif item_id == "title":
                name = product.get("name", "")
                if name:
                    parts.append(
                        f'<div style="text-align:center;padding:1rem 0;"><h2 style="color:#333;font-size:1.25rem;">{name}</h2></div>'
                    )
            elif item_id == "detail":
                for d_img in detail_images:
                    if d_img not in sub_set:
                        parts.append(img_tag.format(url=d_img))
            elif item_id == "bottomImg" and bottom_img:
                parts.append(img_tag.format(url=bottom_img))

        if not parts:
            return f"<p>{product.get('name', '')}</p>"

        return "\n".join(parts)

    # ==================== 카테고리 매핑 자동 조회 ====================

    async def _resolve_category_mappings(
        self,
        source_site: str,
        source_category: str,
        target_account_ids: list[str],
        group_mappings: dict[str, str] | None = None,  # 그룹별 매핑 (우선 적용)
    ) -> dict[str, str]:
        """수집 상품의 소싱처 카테고리 → 각 마켓 카테고리 자동 매핑.

        1. 그룹별 매핑이 있으면 우선 사용 (상품수집에서 설정)
        2. DB에 저장된 매핑이 있으면 사용 (카테고리매핑 페이지에서 설정)
        3. 없으면 키워드 기반 자동 제안으로 첫 번째 결과 사용
        """
        from backend.domain.samba.category.repository import (
            SambaCategoryMappingRepository,
        )
        from backend.domain.samba.category.service import SambaCategoryService

        if not source_category and not group_mappings:
            return {}

        # DB에서 매핑 조회
        mapping_repo = SambaCategoryMappingRepository(self.session)
        mapping = (
            await mapping_repo.find_mapping(source_site, source_category)
            if source_category
            else None
        )

        result: dict[str, str] = {}

        # 대상 계정의 마켓 타입 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_cat
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_cat

        _stmt_cat = _sel_cat(_SMA_cat).where(_SMA_cat.id.in_(target_account_ids))
        _res_cat = await self.session.execute(_stmt_cat)
        _cat_accounts = _res_cat.scalars().all()
        market_types = {a.market_type for a in _cat_accounts}

        # cat2 코드맵이 있는 모든 마켓에서 경로 → 숫자 코드 변환 시도
        code_required_markets = market_types  # 전체 대상 마켓

        for market_type in market_types:
            # 1순위: 그룹별 매핑 (상품수집에서 설정)
            if group_mappings and group_mappings.get(market_type):
                result[market_type] = group_mappings[market_type]
                continue

            # 2순위: DB 매핑 (카테고리매핑 페이지에서 설정)
            if mapping and mapping.target_mappings:
                target = mapping.target_mappings.get(market_type, "")
                if target:
                    result[market_type] = target
                    continue

            # DB 매핑 없으면 해당 마켓은 스킵 (사용자가 직접 매핑한 것만 전송)
            logger.info(f"[카테고리] {market_type} DB 매핑 없음 — 전송 대상에서 제외")

        # 경로 문자열 → 숫자 코드 변환 (11번가 등)
        from backend.domain.samba.category.repository import SambaCategoryTreeRepository

        category_svc = SambaCategoryService(
            mapping_repo, SambaCategoryTreeRepository(self.session)
        )
        for market_type in code_required_markets:
            if market_type in result:
                cat_path = result[market_type]
                if cat_path and not cat_path.isdigit():
                    code = await category_svc.resolve_category_code(
                        market_type, cat_path
                    )
                    if code:
                        logger.info(
                            "[카테고리 코드 변환] %s: '%s' → %s",
                            market_type,
                            cat_path,
                            code,
                        )
                        result[market_type] = code

        return result

    # ==================== 재전송 ====================

    async def retransmit(self, shipment_id: str) -> Optional[SambaShipment]:
        """실패한 계정에 대해 기존 shipment 레코드를 업데이트하며 재전송."""
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import dispatch_to_market

        shipment = await self.repo.get_async(shipment_id)
        if not shipment:
            return None

        old_result = shipment.transmit_result or {}
        old_errors = shipment.transmit_error or {}
        failed_accounts = [aid for aid, st in old_result.items() if st == "failed"]
        if not failed_accounts:
            return shipment

        # 상품 데이터 조회
        product_repo = SambaCollectedProductRepository(self.session)
        product_row = await product_repo.get_async(shipment.product_id)
        if not product_row:
            return shipment
        product_dict = product_row.model_dump()

        # 재전송
        await self.repo.update_async(shipment_id, status="transmitting")
        new_result = dict(old_result)
        new_errors = dict(old_errors)

        # 실패 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_rt
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_rt

        _stmt_rt = _sel_rt(_SMA_rt).where(_SMA_rt.id.in_(failed_accounts))
        _res_rt = await self.session.execute(_stmt_rt)
        _rt_account_map = {a.id: a for a in _res_rt.scalars().all()}

        # 카테고리 매핑 재조회
        raw_category = product_row.category or ""

        # 그룹 매핑 조회
        group_mappings = None
        if product_row.search_filter_id:
            from backend.domain.samba.collector.repository import (
                SambaSearchFilterRepository,
            )

            sf_repo = SambaSearchFilterRepository(self.session)
            sf = await sf_repo.get_async(product_row.search_filter_id)
            if sf and sf.target_mappings:
                group_mappings = sf.target_mappings

        mapped_categories = await self._resolve_category_mappings(
            product_row.source_site or "",
            raw_category,
            failed_accounts,
            group_mappings=group_mappings,
        )

        for account_id in failed_accounts:
            try:
                account = _rt_account_map.get(account_id)
                if not account:
                    continue
                category_id = mapped_categories.get(account.market_type, "")
                # ESM Plus 크로스매핑: 지마켓↔옥션 자동 변환
                if not category_id and account.market_type in ("gmarket", "auction"):
                    other = "auction" if account.market_type == "gmarket" else "gmarket"
                    other_id = mapped_categories.get(other, "")
                    if other_id and str(other_id).isdigit():
                        from backend.domain.samba.proxy.esmplus import esm_map_category

                        category_id = esm_map_category(
                            other_id, other, account.market_type
                        )
                        if category_id:
                            logger.info(
                                f"[ESM 크로스매핑] {other}({other_id}) → {account.market_type}({category_id})"
                            )
                if not category_id:
                    new_result[account_id] = "failed"
                    new_errors[account_id] = "카테고리 매핑 없음"
                    continue
                result = await dispatch_to_market(
                    self.session,
                    account.market_type,
                    product_dict,
                    category_id,
                    account=account,
                )
                if result.get("success"):
                    new_result[account_id] = "success"
                    new_errors.pop(account_id, None)
                else:
                    new_result[account_id] = "failed"
                    new_errors[account_id] = result.get("message", "")
            except Exception as exc:
                new_result[account_id] = "failed"
                new_errors[account_id] = str(exc)

        values = list(new_result.values())
        all_success = len(values) > 0 and all(v == "success" for v in values)
        all_failed = len(values) > 0 and all(v == "failed" for v in values)
        final_status = (
            "completed" if all_success else ("failed" if all_failed else "partial")
        )

        updated = await self.repo.update_async(
            shipment_id,
            status=final_status,
            transmit_result=new_result,
            transmit_error=new_errors if new_errors else None,
            completed_at=datetime.now(UTC),
        )
        return updated or shipment

    # ==================== 마켓 상품 삭제 ====================

    async def delete_from_markets(
        self,
        product_ids: list[str],
        target_account_ids: list[str],
    ) -> dict[str, Any]:
        """선택된 상품을 대상 마켓에서 삭제."""
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import delete_from_market

        product_repo = SambaCollectedProductRepository(self.session)

        # 대상 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_del
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_del

        _stmt_del = _sel_del(_SMA_del).where(_SMA_del.id.in_(target_account_ids))
        _res_del = await self.session.execute(_stmt_del)
        _del_account_map = {a.id: a for a in _res_del.scalars().all()}

        results: list[dict[str, Any]] = []

        for product_id in product_ids:
            # 강제 중단 체크
            if is_cancel_requested():
                logger.info(
                    f"[마켓삭제] 강제 중단 — {len(results)}건 완료, {len(product_ids) - len(results)}건 취소"
                )
                break
            product_row = await product_repo.get_async(product_id)
            if not product_row:
                results.append(
                    {"product_id": product_id, "status": "failed", "error": "상품 없음"}
                )
                continue

            product_dict = product_row.model_dump()
            market_product_nos = product_row.market_product_nos or {}
            reg_accounts = product_row.registered_accounts or []
            delete_results: dict[str, str] = {}

            for account_id in target_account_ids:
                # 이 상품에 등록된 계정만 삭제 대상
                if account_id not in reg_accounts:
                    continue

                account = _del_account_map.get(account_id)
                if not account:
                    delete_results[account_id] = "계정 없음"
                    continue

                # 상품번호를 product_dict에 주입 (디스패처가 사용)
                # 스마트스토어: 삭제 API는 originProductNo 사용
                if account.market_type == "smartstore":
                    product_no = market_product_nos.get(
                        f"{account_id}_origin", ""
                    ) or market_product_nos.get(account_id, "")
                else:
                    product_no = market_product_nos.get(account_id, "")
                product_dict["market_product_no"] = {account.market_type: product_no}

                result = await delete_from_market(
                    self.session, account.market_type, product_dict, account=account
                )
                # 429 방지 — 삭제 요청 간 0.5초 딜레이
                await asyncio.sleep(0.5)

                if result.get("success"):
                    delete_results[account_id] = "success"
                    logger.info(
                        f"[마켓삭제] {account.market_type} 성공 - 상품: {product_id}"
                    )
                else:
                    delete_results[account_id] = result.get("message", "실패")
                    logger.warning(
                        f"[마켓삭제] {account.market_type} 실패 - {result.get('message')}"
                    )

            # 성공한 계정만 등록 해제 (429 등 실패 시 등록 상태 유지)
            success_ids = [
                aid for aid, status in delete_results.items() if status == "success"
            ]
            if success_ids:
                new_reg = [a for a in reg_accounts if a not in success_ids]
                remove_keys = set(success_ids)
                for aid in success_ids:
                    remove_keys.add(f"{aid}_origin")
                new_nos = {
                    k: v for k, v in market_product_nos.items() if k not in remove_keys
                }
                update_data: dict[str, Any] = {
                    "registered_accounts": new_reg if new_reg else None,
                    "market_product_nos": new_nos if new_nos else None,
                }
                if not new_reg:
                    update_data["status"] = "collected"
                await product_repo.update_async(product_id, **update_data)

            results.append(
                {
                    "product_id": product_id,
                    "delete_results": delete_results,
                    "success_count": len(
                        [v for v in delete_results.values() if v == "success"]
                    ),
                }
            )

        return {
            "processed": len(results),
            "results": results,
        }

    @staticmethod
    def get_status_label(status: str) -> str:
        return STATUS_LABELS.get(status, status)
