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
                    await self._run_stub(job, repo, "수집")
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

    async def _run_stub(self, job, repo, name: str):
        """미구현 잡 타입 스텁."""
        logger.info(f"[잡워커] {name} 잡은 아직 미구현: {job.id}")
        await repo.complete_job(job.id, {"message": f"{name} 잡 미구현 — 추후 지원"})
