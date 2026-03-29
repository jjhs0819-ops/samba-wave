"""SambaWave Collector — 갱신/모니터링 엔드포인트."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.domain.samba.collector.refresher import _site_intervals

from backend.api.v1.routers.samba.collector_common import (
    _trim_history,
    _get_services,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/collector", tags=["samba-collector"])


# ── DTOs ──

class RefreshRequest(BaseModel):
    product_ids: Optional[List[str]] = None
    search_filter_ids: Optional[List[str]] = None  # 선택된 그룹(검색필터) ID
    priority: Optional[str] = None  # hot / warm / cold
    auto_retransmit: bool = True


class RateLimitTestRequest(BaseModel):
    goods_no: str = "4746833"  # 테스트용 상품번호
    count: int = 100  # 요청 횟수
    interval: float = 0.0  # 요청 간격 (초)
    mode: str = "autotune"  # autotune(상세+옵션 2개) / collect(상세+옵션+고시정보 3개)


class VideoGenerateRequest(BaseModel):
    product_id: str
    max_images: int = 3
    duration_per_image: float = 1.0


# ══════════════════════════════════════════════════════════════
# 재고/가격 변동 모니터링 — 벌크 갱신 + 스케줄러
# ══════════════════════════════════════════════════════════════


@router.post("/products/refresh")
async def refresh_products(
    body: RefreshRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """벌크 재크롤링 — 소싱처에서 최신 가격/재고 재수집 후 자동 업데이트."""
    from backend.domain.samba.collector.refresher import (
        refresh_products_bulk,
    )
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository

    repo = SambaCollectedProductRepository(session)

    # 대상 상품 조회 (배치 쿼리)
    if body.product_ids:
        from backend.domain.samba.collector.model import SambaCollectedProduct as _CP
        _stmt = select(_CP).where(_CP.id.in_(body.product_ids))
        _result = await session.execute(_stmt)
        products = list(_result.scalars().all())
    elif body.search_filter_ids:
        # 선택된 그룹의 상품만 조회
        products = []
        for sf_id in body.search_filter_ids:
            group_products = await repo.filter_by_async(search_filter_id=sf_id, limit=10000)
            products.extend(group_products)
    elif body.priority:
        # 우선순위 기반 조회
        from sqlmodel import select as sel
        from backend.domain.samba.collector.model import SambaCollectedProduct
        stmt = sel(SambaCollectedProduct).where(
            SambaCollectedProduct.monitor_priority == body.priority
        ).limit(500)
        result = await session.execute(stmt)
        products = list(result.scalars().all())
    else:
        # 전체 (최대 500건)
        products = await repo.list_async(skip=0, limit=500, order_by="-updated_at")

    if not products:
        return {
            "total": 0, "refreshed": 0, "changed": 0,
            "sold_out": 0, "retransmitted": 0,
            "needs_extension": [], "errors": 0,
        }

    # 벌크 갱신 실행 (수동 갱신 — 오토튠 로그에 노출되지 않음)
    results, summary = await refresh_products_bulk(products, source="manual")

    # 모니터링 서비스 초기화
    from backend.domain.samba.warroom.service import SambaMonitorService
    monitor = SambaMonitorService(session)

    # 상품 Map (재전송/품절 처리에서 재조회 방지)
    product_map = {p.id: p for p in products}

    # 변동 감지된 상품 DB 업데이트
    now = datetime.now(timezone.utc)
    changed_ids: list[str] = []
    soldout_ids: list[str] = []

    for r in results:
        if r.error:
            # 에러 카운트 증가 — product_map 활용 (N+1 제거)
            product = product_map.get(r.product_id)
            if product:
                await repo.update_async(
                    r.product_id,
                    refresh_error_count=(product.refresh_error_count or 0) + 1,
                    last_refreshed_at=now,
                )
                # 모니터링: 갱신 에러
                await monitor.emit(
                    "refresh_error", "warning",
                    summary=f"갱신 실패 — {product.name[:30] if product.name else r.product_id}",
                    source_site=getattr(product, "source_site", None),
                    product_id=r.product_id,
                    product_name=getattr(product, "name", None),
                    detail={"error": r.error},
                )
            continue
        if r.needs_extension:
            # 모니터링: 확장앱 타임아웃
            await monitor.emit(
                "extension_timeout", "warning",
                summary=f"KREAM 확장앱 타임아웃 — {r.product_id}",
                source_site="KREAM",
                product_id=r.product_id,
            )
            continue

        # 상품 조회 — product_map 활용 (N+1 제거)
        product = product_map.get(r.product_id)
        if not product:
            continue

        # 갱신 시각 업데이트 + 에러 카운트 리셋
        updates: dict = {
            "last_refreshed_at": now,
            "refresh_error_count": 0,
        }

        # 가격이력 스냅샷 — 변동 여부와 관계없이 항상 기록
        snapshot: dict = {
            "date": now.isoformat(),
            "source": "refresh",
            "sale_price": r.new_sale_price if r.new_sale_price is not None else product.sale_price,
            "original_price": r.new_original_price if r.new_original_price is not None else product.original_price,
            "cost": r.new_cost if r.new_cost is not None else product.cost,
            "sale_status": r.new_sale_status,
            "changed": r.changed,
        }
        # KREAM 옵션별 가격도 기록
        if r.new_options:
            snapshot["options"] = r.new_options
        history = list(product.price_history or [])
        history.insert(0, snapshot)
        updates["price_history"] = _trim_history(history)

        # 이미지/소재/색상 — 기존에 비어있고 편집 이력 없으면 갱신
        _tags = product.tags or []
        _img_edited = "__img_edited__" in _tags or "__img_filtered__" in _tags
        if r.new_images and not product.images and not _img_edited:
            updates["images"] = r.new_images
        if r.new_detail_images and not getattr(product, "detail_images", None) and not _img_edited:
            updates["detail_images"] = r.new_detail_images
        if r.new_material and not getattr(product, "material", None):
            updates["material"] = r.new_material
        if r.new_color and not getattr(product, "color", None):
            updates["color"] = r.new_color
        # 배송 정보 항상 갱신
        if r.new_free_shipping is not None:
            updates["free_shipping"] = r.new_free_shipping
        if r.new_same_day_delivery is not None:
            updates["same_day_delivery"] = r.new_same_day_delivery

        # 옵션은 가격 변동과 무관하게 항상 갱신
        if r.new_options is not None:
            updates["options"] = r.new_options

        if r.changed:
            if r.new_sale_price is not None:
                updates["sale_price"] = r.new_sale_price
            if r.new_original_price is not None:
                updates["original_price"] = r.new_original_price
            if r.new_cost is not None:
                updates["cost"] = r.new_cost

            updates["sale_status"] = r.new_sale_status
            updates["is_sold_out"] = r.new_sale_status == "sold_out"

            # 가격 변동 추적
            old_price = product.sale_price or 0
            new_price = r.new_sale_price or 0
            if new_price != old_price:
                updates["price_before_change"] = old_price
                updates["price_changed_at"] = now
                # 모니터링: 가격 변동
                diff_pct = round((new_price - old_price) / old_price * 100, 1) if old_price else 0
                await monitor.emit(
                    "price_changed", "info",
                    summary=f"가격 변동 — {product.name[:30] if product.name else ''} ₩{int(old_price):,}→₩{int(new_price):,}",
                    source_site=product.source_site,
                    product_id=r.product_id,
                    product_name=product.name,
                    detail={"old_price": old_price, "new_price": new_price, "diff_pct": diff_pct},
                )

            changed_ids.append(r.product_id)
            if r.new_sale_status == "sold_out":
                soldout_ids.append(r.product_id)
                # 모니터링: 품절 감지
                await monitor.emit(
                    "sold_out", "warning",
                    summary=f"품절 감지 — {product.name[:30] if product.name else r.product_id}",
                    source_site=product.source_site,
                    product_id=r.product_id,
                    product_name=product.name,
                )

        await repo.update_async(r.product_id, **updates)

    await session.commit()

    # 자동 재전송 + 품절 삭제
    retransmitted = 0
    deleted_ids: list[str] = []
    if body.auto_retransmit and (changed_ids or soldout_ids):
        from backend.domain.samba.shipment.repository import SambaShipmentRepository
        from backend.domain.samba.shipment.service import SambaShipmentService

        ship_repo = SambaShipmentRepository(session)
        ship_svc = SambaShipmentService(ship_repo, session)

        # 가격 변동 상품 → 재전송 (계정별로 묶어서 배치 호출)
        price_changed = [pid for pid in changed_ids if pid not in soldout_ids]
        # 계정별 상품 그룹핑
        retransmit_groups: dict[str, list[str]] = {}
        for pid in price_changed:
            product = product_map.get(pid)
            if product and product.registered_accounts:
                acc_key = ",".join(sorted(product.registered_accounts))
                retransmit_groups.setdefault(acc_key, []).append(pid)
        for acc_key, pids in retransmit_groups.items():
            acc_ids = acc_key.split(",")
            try:
                await ship_svc.start_update(pids, ["price"], acc_ids, skip_unchanged=False)
                retransmitted += len(pids)
            except Exception as e:
                logger.error(f"[refresh] 재전송 실패 ({len(pids)}건): {e}")

        # 품절 상품 → 마켓 판매중지/삭제 → 삼바 DB 삭제
        import asyncio
        from backend.domain.samba.shipment.dispatcher import delete_from_market
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        account_repo = SambaMarketAccountRepository(session)

        # 계정 배치 조회 (N+1 방지)
        all_acc_ids = set()
        for pid in soldout_ids:
            product = product_map.get(pid)
            if product and product.registered_accounts:
                all_acc_ids.update(product.registered_accounts)
        acc_map: dict = {}
        if all_acc_ids:
            from backend.domain.samba.account.model import SambaMarketAccount as _MA
            _acc_stmt = select(_MA).where(_MA.id.in_(list(all_acc_ids)))
            _acc_result = await session.execute(_acc_stmt)
            acc_map = {a.id: a for a in _acc_result.scalars().all()}

        # 1단계: 삭제 대상 수집 (lock_delete 필터링, product_map 재사용)
        delete_targets: list[tuple] = []  # (pid, product_dict, account_id, account)
        deletable_pids: set[str] = set()  # DB 삭제 대상 pid
        for pid in soldout_ids:
            product = product_map.get(pid)
            if not product:
                continue
            if getattr(product, "lock_delete", False):
                logger.info(f"[refresh] {pid} 품절이지만 lock_delete=True, 삭제 건너뜀")
                continue
            deletable_pids.add(pid)
            product_dict = product.model_dump()
            if product.registered_accounts:
                for account_id in product.registered_accounts:
                    account = acc_map.get(account_id)
                    if not account:
                        continue
                    m_nos = product.market_product_nos or {}
                    pd = {**product_dict, "market_product_no": {account.market_type: m_nos.get(account_id, "")}}
                    delete_targets.append((pid, pd, account_id, account))

        # 2단계: 마켓 판매중지 병렬 처리 (5개씩)
        sem = asyncio.Semaphore(5)
        async def _do_market_delete(pid: str, pd: dict, acc: object) -> None:
            async with sem:
                try:
                    result = await delete_from_market(session, acc.market_type, pd, account=acc)  # type: ignore[union-attr]
                    if result.get("success"):
                        logger.info(f"[refresh] {pid} → {acc.market_type} 판매중지 완료")  # type: ignore[union-attr]
                    else:
                        logger.warning(f"[refresh] {pid} → {acc.market_type} 판매중지 실패: {result.get('message')}")  # type: ignore[union-attr]
                except Exception as e:
                    logger.error(f"[refresh] {pid} → 마켓 삭제 오류: {e}")

        if delete_targets:
            await asyncio.gather(*[_do_market_delete(pid, pd, acc) for pid, pd, _, acc in delete_targets])

        # 3단계: DB 일괄 삭제 (단일 쿼리)
        deleted_ids: list[str] = []
        if deletable_pids:
            from sqlalchemy import delete as sa_delete
            from sqlmodel import col
            from backend.domain.samba.collector.model import SambaCollectedProduct
            del_stmt = sa_delete(SambaCollectedProduct).where(col(SambaCollectedProduct.id).in_(list(deletable_pids)))
            await session.exec(del_stmt)  # type: ignore[arg-type]
            deleted_ids = list(deletable_pids)
            logger.info(f"[refresh] 품절 상품 {len(deleted_ids)}건 일괄 삭제 완료")

        await session.commit()

    summary.retransmitted = retransmitted

    # 모니터링: 재전송/삭제 이벤트
    if retransmitted > 0:
        await monitor.emit(
            "market_retransmit", "info",
            summary=f"가격변동 재전송 {retransmitted}건",
            detail={"count": retransmitted},
        )
    if body.auto_retransmit and deleted_ids:
        for did in deleted_ids:
            await monitor.emit(
                "market_deleted", "info",
                summary=f"품절 삭제 — {did}",
                product_id=did,
            )

    # 모니터링: 배치 갱신 완료
    await monitor.emit(
        "refresh_batch", "info",
        summary=f"배치 갱신 완료 — {summary.total}건 중 {summary.refreshed}건 갱신, {summary.changed}건 변동",
        detail={
            "total": summary.total,
            "refreshed": summary.refreshed,
            "changed": summary.changed,
            "sold_out": summary.sold_out,
            "deleted": len(deleted_ids) if body.auto_retransmit else 0,
            "retransmitted": retransmitted,
            "errors": summary.errors,
        },
    )
    await session.commit()

    return {
        "total": summary.total,
        "refreshed": summary.refreshed,
        "changed": summary.changed,
        "sold_out": summary.sold_out,
        "deleted": len(deleted_ids) if body.auto_retransmit else 0,
        "retransmitted": summary.retransmitted,
        "needs_extension": summary.needs_extension,
        "errors": summary.errors,
    }


# ══════════════════════════════════════════════════════════════
# 무신사 차단 임계값 테스트
# ══════════════════════════════════════════════════════════════


@router.post("/test/rate-limit")
async def test_rate_limit(body: RateLimitTestRequest = RateLimitTestRequest()):
    """무신사 차단 임계값 테스트."""
    import asyncio
    import httpx
    import time

    from backend.domain.samba.collector.refresher import _get_musinsa_cookie
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    cookie = await _get_musinsa_cookie()
    if not cookie:
        return {"error": "무신사 쿠키 없음"}

    client = MusinsaClient(cookie)
    headers = client._headers()
    base = "https://goods-detail.musinsa.com/api2/goods"

    results = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as http:
        for i in range(body.count):
            start = time.monotonic()
            try:
                urls = [f"{base}/{body.goods_no}", f"{base}/{body.goods_no}/options"]
                if body.mode == "collect":
                    urls.append(f"{base}/{body.goods_no}/essential")

                statuses = []
                for url in urls:
                    r = await http.get(url, headers=headers)
                    statuses.append(r.status_code)
                    if r.status_code in (429, 403):
                        elapsed = round((time.monotonic() - start) * 1000)
                        retry_after = r.headers.get("Retry-After", "?")
                        api_name = url.split("/")[-1] if "/" in url else "detail"
                        results.append({"req": i + 1, "statuses": statuses, "ms": elapsed, "blocked": api_name})
                        return {
                            "blocked_at": {"request_no": i + 1, "status": r.status_code, "api": api_name, "retry_after": retry_after},
                            "total_ok": i,
                            "mode": body.mode,
                            "api_per_req": len(urls),
                            "total_api_calls": i * len(urls) + len(statuses),
                            "results": results[-10:],
                            "summary": f"{body.mode} 모드: {i + 1}번째에서 {api_name} API {r.status_code} 차단",
                        }

                elapsed = round((time.monotonic() - start) * 1000)
                results.append({"req": i + 1, "statuses": statuses, "ms": elapsed})
            except Exception as e:
                elapsed = round((time.monotonic() - start) * 1000)
                results.append({"req": i + 1, "error": str(e), "ms": elapsed})

            if body.interval > 0:
                await asyncio.sleep(body.interval)

    avg_ms = sum(r.get("ms", 0) for r in results) // len(results) if results else 0
    total_apis = body.count * (3 if body.mode == "collect" else 2)
    return {
        "blocked_at": None,
        "total_ok": len(results),
        "mode": body.mode,
        "api_per_req": 3 if body.mode == "collect" else 2,
        "total_api_calls": total_apis,
        "avg_ms": avg_ms,
        "results": results[-10:],
        "summary": f"{body.mode} 모드: {len(results)}회 성공 (API {total_apis}회, 평균 {avg_ms}ms/상품)",
    }


# ══════════════════════════════════════════════════════════════
# 소싱처/마켓 Probe (구조 변경 감지)
# ══════════════════════════════════════════════════════════════


@router.get("/probe/status")
async def probe_status(
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """최근 probe 결과 조회."""
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository
    repo = SambaSettingsRepository(session)
    results: dict = {"sources": {}, "markets": {}}

    # 소싱처 probe 결과
    from backend.domain.samba.probe.health_checker import PROBE_TARGETS, MARKET_PROBES
    for site in PROBE_TARGETS:
        row = await repo.find_by_async(key=f"probe_{site}")
        if row and row.value:
            results["sources"][site] = row.value

    # 마켓 probe 결과
    for mt in MARKET_PROBES:
        row = await repo.find_by_async(key=f"probe_market_{mt}")
        if row and row.value:
            results["markets"][mt] = row.value

    return results


@router.post("/probe/run")
async def probe_run(
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """수동 probe 실행 — 전체 소싱처+마켓 헬스체크."""
    from backend.domain.samba.probe.health_checker import run_all_probes
    results = await run_all_probes(session)

    # 모니터링: probe 결과 이벤트 발행
    from backend.domain.samba.warroom.service import SambaMonitorService
    monitor = SambaMonitorService(session)

    for site, data in results.get("sources", {}).items():
        if not data.get("ok"):
            missing = data.get("missing_fields", [])
            if missing:
                await monitor.emit(
                    "api_structure_changed", "critical",
                    summary=f"API 구조 변경 감지 — {site} 필드 누락: {', '.join(missing)}",
                    source_site=site,
                    detail={"missing_fields": missing, "error": data.get("error")},
                )
            elif data.get("error"):
                await monitor.emit(
                    "probe_failed", "warning",
                    summary=f"Probe 실패 — {site}: {data.get('error')}",
                    source_site=site,
                    detail=data,
                )

    for mt, data in results.get("markets", {}).items():
        if not data.get("ok") and data.get("error"):
            await monitor.emit(
                "probe_failed", "warning",
                summary=f"마켓 Probe 실패 — {mt}: {data.get('error')}",
                market_type=mt,
                detail=data,
            )

    await session.commit()
    return results


# ══════════════════════════════════════════════════════════════
# Ken Burns 영상 생성
# ══════════════════════════════════════════════════════════════


@router.post("/products/generate-video")
async def generate_product_video(
    body: VideoGenerateRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """상품 이미지로 Ken Burns 효과 영상(2~3초) 생성 → R2/로컬 저장 → 상품에 매칭."""
    from backend.domain.samba.video.kenburns import generate_kenburns_video
    from backend.domain.samba.image.service import ImageTransformService
    import uuid
    from pathlib import Path

    svc = _get_services(session)
    product = await svc.get_collected_product(body.product_id)
    if not product:
        raise HTTPException(404, "상품을 찾을 수 없습니다")

    images = product.images or []
    if not images:
        raise HTTPException(400, "상품 이미지가 없습니다")

    # AI 변환 이미지가 없으면 자동 생성
    ai_images = [u for u in images if '/transformed/' in u or '/ai_' in u]
    if not ai_images:
        logger.info(f"[영상생성] AI이미지 없음 — 자동 생성 시작 ({body.product_id})")
        img_svc_auto = ImageTransformService(session)
        try:
            # 대표이미지는 건드리지 않고 별도 생성
            ai_result = await img_svc_auto.transform_single_image(
                body.product_id, images[0], "video",
            )
            if ai_result:
                logger.info(f"[영상생성] AI이미지 자동 생성 완료")
                # 추가이미지 마지막에 추가
                updated_images = list(images)
                updated_images.append(ai_result)
                await svc.update_collected_product(body.product_id, {"images": updated_images})
                images = updated_images
                ai_images = [ai_result]
        except Exception as e:
            logger.warning(f"[영상생성] AI이미지 자동 생성 실패, 원본으로 진행: {e}")

    source_images = ai_images if ai_images else images

    try:
        output_path = generate_kenburns_video(
            image_urls=source_images,
            duration_per_image=body.duration_per_image,
            max_images=body.max_images,
        )
    except Exception as e:
        raise HTTPException(500, f"영상 생성 실패: {str(e)}")

    # R2/로컬 저장
    filename = f"video_{product.site_product_id or uuid.uuid4().hex[:8]}_{uuid.uuid4().hex[:6]}.mp4"
    video_bytes = Path(output_path).read_bytes()

    img_svc = ImageTransformService(session)
    r2 = await img_svc._get_r2_client()
    if r2:
        client, bucket_name, public_url = r2
        try:
            import io
            client.upload_fileobj(
                io.BytesIO(video_bytes),
                bucket_name,
                f"videos/{filename}",
                ExtraArgs={"ContentType": "video/mp4"},
            )
            video_url = f"{public_url}/videos/{filename}"
        except Exception:
            # R2 실패 시 로컬 저장
            local_dir = Path("static/videos")
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / filename).write_bytes(video_bytes)
            video_url = f"/static/videos/{filename}"
    else:
        local_dir = Path("static/videos")
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / filename).write_bytes(video_bytes)
        video_url = f"/static/videos/{filename}"

    # 상품에 video_url 매칭
    await svc.update_collected_product(body.product_id, {"video_url": video_url})

    # 임시파일 삭제
    Path(output_path).unlink(missing_ok=True)

    return {"success": True, "video_url": video_url}
