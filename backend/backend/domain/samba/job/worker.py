"""백그라운드 잡 워커 — FastAPI lifespan에서 실행."""

import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
UTC = timezone.utc


class JobWorker:
    """pending 잡을 폴링하여 순차 실행."""

    POLL_INTERVAL = 5  # 초

    def __init__(self):
        self._running = True

    async def start(self):
        """무한 루프: pending 잡 조회 → 실행."""
        logger.info("[잡워커] 시작")
        while self._running:
            try:
                executed = await self._poll_once()
                if not executed:
                    await asyncio.sleep(self.POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[잡워커] 폴링 에러: {e}")
                await asyncio.sleep(self.POLL_INTERVAL)
        logger.info("[잡워커] 종료")

    def stop(self):
        self._running = False

    async def _poll_once(self) -> bool:
        """pending 잡 1개 처리. 처리했으면 True."""
        from backend.db.orm import get_write_session
        from backend.domain.samba.job.repository import SambaJobRepository

        async with get_write_session() as session:
            repo = SambaJobRepository(session)
            job = await repo.pick_next_pending()
            if not job:
                return False

            logger.info(f"[잡워커] 실행: {job.id} ({job.job_type})")

            try:
                if job.job_type == "transmit":
                    await self._run_transmit(job, repo, session)
                elif job.job_type == "collect":
                    await self._run_collect(job, repo, session)
                elif job.job_type == "refresh":
                    await self._run_stub(job, repo, "갱신")
                elif job.job_type == "ai_tag":
                    await self._run_stub(job, repo, "AI태그")
                else:
                    await repo.fail_job(job.id, f"알 수 없는 잡 타입: {job.job_type}")

                await session.commit()
            except Exception as e:
                logger.error(f"[잡워커] 잡 실행 실패: {job.id} — {e}")
                try:
                    await repo.fail_job(job.id, str(e))
                    await session.commit()
                except Exception:
                    pass

            return True

    async def _run_transmit(self, job, repo, session):
        """전송 잡 실행 — 기존 shipment_service 호출."""
        from backend.domain.samba.shipment.service import SambaShipmentService
        from backend.domain.samba.shipment.repository import SambaShipmentRepository

        payload = job.payload or {}
        product_ids = payload.get("product_ids", [])
        update_items = payload.get("update_items", [])
        target_account_ids = payload.get("target_account_ids", [])
        skip_unchanged = payload.get("skip_unchanged", False)

        if not product_ids:
            await repo.fail_job(job.id, "product_ids 없음")
            return

        svc = SambaShipmentService(SambaShipmentRepository(session), session)
        total = len(product_ids)
        await repo.update_progress(job.id, 0, total)

        results = []
        for i, pid in enumerate(product_ids):
            try:
                result = await svc.start_update(
                    [pid], update_items, target_account_ids,
                    skip_unchanged=skip_unchanged,
                )
                results.append(result)
            except Exception as e:
                logger.warning(f"[잡워커] 전송 실패 {pid}: {e}")
                results.append({"error": str(e)})
            await repo.update_progress(job.id, i + 1, total)

        await repo.complete_job(job.id, {"results": results})
        logger.info(f"[잡워커] 전송 완료: {job.id} ({total}건)")

    async def _run_collect(self, job, repo, session):
        """수집 잡 실행 — collector_collection의 _stream_musinsa 로직 이식."""
        from urllib.parse import urlparse, parse_qs
        from sqlmodel import select, func as _func
        from backend.domain.samba.collector.model import SambaSearchFilter
        from backend.domain.samba.collector.model import SambaCollectedProduct as CPModel
        from backend.domain.samba.proxy.musinsa import MusinsaClient, RateLimitError
        from backend.domain.samba.forbidden.model import SambaSettings
        from backend.api.v1.routers.samba.collector_common import _build_product_data
        from backend.domain.samba.collector.refresher import _site_intervals, _site_consecutive_errors

        payload = job.payload or {}
        filter_id = payload.get("filter_id")
        if not filter_id:
            await repo.fail_job(job.id, "filter_id 없음")
            return

        # 필터 조회
        sf = await session.get(SambaSearchFilter, filter_id)
        if not sf:
            await repo.fail_job(job.id, f"필터 없음: {filter_id}")
            return

        site = sf.source_site
        if site != "MUSINSA":
            await repo.fail_job(job.id, f"미지원 소싱처: {site}")
            return

        # 쿠키 로드
        result = await session.execute(
            select(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
        )
        row = result.scalar_one_or_none()
        cookie = (row.value if row and row.value else "") or ""
        if not cookie:
            await repo.fail_job(job.id, "무신사 로그인(쿠키) 필요")
            return

        client = MusinsaClient(cookie=cookie)

        # 키워드/옵션 추출
        keyword_or_url = sf.keyword or ""
        keyword = keyword_or_url
        _exclude_preorder = False
        _exclude_boutique = False
        _use_max_discount = False

        try:
            parsed = urlparse(keyword_or_url)
            if parsed.scheme:
                qs = parse_qs(parsed.query)
                keyword = qs.get("keyword", [keyword])[0]
                _exclude_preorder = qs.get("excludePreorder", [""])[0] == "1"
                _exclude_boutique = qs.get("excludeBoutique", [""])[0] == "1"
                _use_max_discount = qs.get("maxDiscount", [""])[0] == "1"
        except Exception:
            pass

        # 기존 수집 수 확인
        requested_count = sf.requested_count or 100
        count_stmt = select(_func.count()).where(
            CPModel.search_filter_id == filter_id
        )
        existing_count = (await session.execute(count_stmt)).scalar() or 0
        remaining = max(0, requested_count - existing_count)

        if remaining <= 0:
            await repo.complete_job(job.id, {
                "saved": 0,
                "message": f"이미 {existing_count}개 수집됨 (요청: {requested_count}개)",
            })
            return

        await repo.update_progress(job.id, 0, remaining)

        # 수집 루프
        total_saved = 0
        total_skipped = 0
        search_page = 1

        while total_saved < remaining and search_page <= 20:
            # 취소 확인 (DB에서 상태 재조회)
            await session.refresh(job)
            if job.status == "failed":
                logger.info(f"[잡워커] 수집 취소됨: {job.id}")
                return

            # 검색
            try:
                data = await client.search_products(keyword=keyword, page=search_page, size=100)
                search_items = data.get("data", [])
                if not search_items:
                    break
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
            except Exception:
                break

            # 중복 필터링
            candidate_ids = [str(item.get("siteProductId", item.get("goodsNo", ""))) for item in search_items]
            existing_result = await session.execute(
                select(CPModel.site_product_id).where(
                    CPModel.source_site == "MUSINSA",
                    CPModel.site_product_id.in_(candidate_ids),
                )
            )
            existing_ids = {row[0] for row in existing_result.all()}

            targets = []
            for item in search_items:
                if total_saved + len(targets) >= remaining:
                    break
                site_pid = str(item.get("siteProductId", item.get("goodsNo", "")))
                if site_pid in existing_ids:
                    continue
                if item.get("isSoldOut", False):
                    total_skipped += 1
                    continue
                targets.append(site_pid)

            if not targets:
                search_page += 1
                continue

            # 상세 수집
            for goods_no in targets:
                try:
                    detail = await client.get_goods_detail(goods_no)
                    if not detail or not detail.get("name"):
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    if _exclude_preorder and detail.get("saleStatus") == "preorder":
                        total_skipped += 1
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue
                    if _exclude_boutique and detail.get("isBoutique"):
                        total_skipped += 1
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                        continue

                    if _use_max_discount:
                        _raw_cost = detail.get("bestBenefitPrice")
                        new_cost = _raw_cost if (_raw_cost is not None and _raw_cost > 0) else (detail.get("salePrice") or 0)
                    else:
                        new_cost = detail.get("salePrice") or 0

                    raw_cat = detail.get("category", "") or ""
                    cat_parts = [c.strip() for c in raw_cat.split(">") if c.strip()] if raw_cat else []
                    _sale_price = detail.get("salePrice", 0)
                    _original_price = detail.get("originalPrice", 0)

                    raw_detail_html = detail.get("detailHtml", "")
                    if not raw_detail_html:
                        detail_imgs = detail.get("detailImages") or []
                        if detail_imgs:
                            raw_detail_html = "\n".join(
                                f'<div style="text-align:center;"><img src="{img}" style="max-width:860px;width:100%;" /></div>'
                                for img in detail_imgs
                            )

                    from backend.api.v1.routers.samba.collector_common import _get_services
                    svc, _ = await _get_services(session)

                    product_data = _build_product_data(
                        detail, goods_no, filter_id, "MUSINSA",
                        new_cost, _sale_price, _original_price,
                        raw_cat, cat_parts, raw_detail_html,
                    )
                    await svc.create_collected_product(product_data)
                    total_saved += 1

                    await repo.update_progress(job.id, total_saved, remaining)

                    if total_saved >= remaining:
                        break
                except RateLimitError as rle:
                    current = _site_intervals.get("MUSINSA", 1.0)
                    _site_intervals["MUSINSA"] = min(30.0, current * 2)
                    _site_consecutive_errors["MUSINSA"] = _site_consecutive_errors.get("MUSINSA", 0) + 1
                    if _site_consecutive_errors["MUSINSA"] >= 5:
                        await repo.fail_job(job.id, f"소싱처 차단 (HTTP {rle.status})")
                        return
                    if rle.retry_after > 0:
                        await asyncio.sleep(rle.retry_after)
                    else:
                        await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))
                    continue
                except Exception as e:
                    logger.warning(f"[잡워커] 수집 실패 {goods_no}: {e}")
                await asyncio.sleep(_site_intervals.get("MUSINSA", 1.0))

            search_page += 1

        # 수집 완료 → last_collected_at 갱신
        sf.last_collected_at = datetime.now(UTC)
        session.add(sf)

        # 정책 자동 적용
        policy_msg = ""
        if sf.applied_policy_id and total_saved > 0:
            try:
                from backend.domain.samba.policy.repository import SambaPolicyRepository
                from backend.api.v1.routers.samba.collector_common import _get_services
                svc, _ = await _get_services(session)
                policy_repo = SambaPolicyRepository(session)
                policy = await policy_repo.get_async(sf.applied_policy_id)
                policy_data = None
                if policy and policy.pricing:
                    pr = policy.pricing if isinstance(policy.pricing, dict) else {}
                    policy_data = {
                        "margin_rate": pr.get("marginRate", 15),
                        "shipping_cost": pr.get("shippingCost", 0),
                        "extra_charge": pr.get("extraCharge", 0),
                    }
                count = await svc.apply_policy_to_filter_products(
                    filter_id, sf.applied_policy_id, policy_data
                )
                policy_msg = f"정책 적용: {count}개"
            except Exception as e:
                logger.error(f"[잡워커] 정책 전파 실패: {e}")

        await repo.complete_job(job.id, {
            "saved": total_saved,
            "skipped": total_skipped,
            "policy": policy_msg,
        })
        logger.info(f"[잡워커] 수집 완료: {job.id} ({total_saved}건)")

    async def _run_stub(self, job, repo, name: str):
        """미구현 잡 타입 스텁."""
        logger.info(f"[잡워커] {name} 잡은 아직 미구현: {job.id}")
        await repo.complete_job(job.id, {"message": f"{name} 잡 미구현 — 추후 지원"})
