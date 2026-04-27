"""배경제거(워터마크 흰박스) — 백엔드 인라인 백그라운드 처리.

이전: 사용자 PC의 local_bg_worker.py가 폴링/처리 → 워커 미실행 시 작업 정체.
변경: transform_images 호출 시 SambaJob 등록 + asyncio.create_task로 즉시 백그라운드 실행.
처리 로직은 PIL 흰박스 1줄 — 서버 부담 미미, 사용자 의존성 제거.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 우측 상단 워터마크 박스 비율 (이미지 가로/세로 기준)
_BG_BOX_W_RATIO = 0.22
_BG_BOX_H_RATIO = 0.18
# 워터마크 유무 판정 임계값 (영역 평균 RGB가 이 값 미만이면 워터마크 있음)
_BG_DETECT_THRESHOLD = 240


def _remove_watermark_pil(image_bytes: bytes) -> bytes:
    """우측 상단 브랜드 워터마크 영역만 흰색으로 덮어 제거.

    rembg(silueta + alpha matting) → PIL 그리기.
    CPU 사용량 ~95% 감소, 처리 시간 수십초 → 즉시.
    """
    from PIL import Image, ImageDraw, ImageStat

    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    if max(src.size) > 1024:
        ratio = 1024 / max(src.size)
        src = src.resize(
            (int(src.width * ratio), int(src.height * ratio)), Image.LANCZOS
        )

    w, h = src.size
    box_w = int(w * _BG_BOX_W_RATIO)
    box_h = int(h * _BG_BOX_H_RATIO)
    box = (w - box_w, 0, w, box_h)

    # 영역이 이미 흰색에 가까우면 워터마크 없음으로 판단 → skip (5% 케이스 보호)
    crop = src.crop(box)
    avg = ImageStat.Stat(crop).mean
    if any(c < _BG_DETECT_THRESHOLD for c in avg[:3]):
        ImageDraw.Draw(src).rectangle(box, fill="white")

    buf = io.BytesIO()
    src.save(buf, format="WEBP", quality=90)
    return buf.getvalue()


def _r2_upload_sync(creds: dict, image_bytes: bytes, filename: str) -> str | None:
    """R2 동기 업로드 (asyncio.to_thread 안에서 호출). 실패 시 None."""
    try:
        import boto3

        account_id = str(creds.get("accountId", "")).strip()
        access_key = str(creds.get("accessKey", "")).strip()
        secret_key = str(creds.get("secretKey", "")).strip()
        bucket = str(creds.get("bucketName", "")).strip()
        public_url = str(creds.get("publicUrl", "")).strip().rstrip("/")
        if not bucket or not access_key or not secret_key:
            return None

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        key = f"transformed/{filename}"
        s3.put_object(
            Bucket=bucket, Key=key, Body=image_bytes, ContentType="image/webp"
        )
        return f"{public_url}/{key}" if public_url else None
    except Exception as exc:
        logger.error(f"[배경제거] R2 업로드 실패: {exc}")
        return None


async def _process_one_image(
    client: httpx.AsyncClient, url: str, r2_creds: dict
) -> str | None:
    """이미지 1장 처리: 다운로드 → 워터마크 제거 → R2 업로드."""
    try:
        resp = await client.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        processed = await asyncio.to_thread(_remove_watermark_pil, resp.content)
        md5 = hashlib.md5(resp.content).hexdigest()[:8]
        filename = f"ai_{md5}_{uuid.uuid4().hex[:6]}.webp"
        return await asyncio.to_thread(_r2_upload_sync, r2_creds, processed, filename)
    except Exception as exc:
        logger.error(f"[배경제거] 이미지 실패 ({url[:60]}): {exc}")
        return None


async def process_bg_remove_job(job_id: str) -> None:
    """배경제거 잡 백그라운드 실행.

    fire-and-forget asyncio.create_task로 호출됨.
    요청 세션과 분리된 새 세션을 생성하여 처리.
    """
    from sqlalchemy import select as sa_select

    from backend.api.v1.routers.samba.proxy._helpers import _get_setting
    from backend.db.orm import get_write_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from backend.domain.samba.job.model import JobStatus, SambaJob

    try:
        async with get_write_session() as session:
            res = await session.execute(
                sa_select(SambaJob).where(SambaJob.id == job_id)
            )
            job = res.scalar_one_or_none()
            if not job:
                logger.error(f"[배경제거] 잡 없음: {job_id}")
                return

            r2 = await _get_setting(session, "cloudflare_r2")
            if not r2 or not isinstance(r2, dict):
                job.status = JobStatus.FAILED
                job.error = "R2 설정이 저장되지 않았습니다"
                job.completed_at = datetime.now(timezone.utc)
                session.add(job)
                await session.commit()
                logger.error(f"[배경제거] R2 설정 누락: job_id={job_id}")
                return

            payload = job.payload or {}
            product_ids: list[str] = payload.get("product_ids", [])
            scope: dict = payload.get(
                "scope", {"thumbnail": True, "additional": False, "detail": False}
            )

            products: list[Any] = []
            if product_ids:
                prod_res = await session.execute(
                    sa_select(SambaCollectedProduct).where(
                        SambaCollectedProduct.id.in_(product_ids)
                    )
                )
                products = list(prod_res.scalars().all())

            job.status = JobStatus.RUNNING
            job.started_at = datetime.now(timezone.utc)
            session.add(job)
            await session.commit()

            success = 0
            fail = 0

            async with httpx.AsyncClient(
                timeout=30,
                limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
            ) as client:
                for idx, product in enumerate(products, 1):
                    pid = product.id
                    images: list[str] = product.images or []
                    detail_images: list[str] = product.detail_images or []

                    img_total = 0
                    if scope.get("thumbnail") and images:
                        img_total += 1
                    if scope.get("additional") and len(images) > 1:
                        img_total += len(images) - 1
                    if scope.get("detail") and detail_images:
                        img_total += len(detail_images)

                    new_images = list(images)
                    new_detail = list(detail_images)
                    transformed = 0
                    img_done = 0

                    async def _save_image_progress() -> None:
                        """사진 단위 진행률만 갱신 — current는 상품 완료 시 별도 처리."""
                        try:
                            r = dict(job.result or {})
                            r["image_current"] = img_done
                            r["image_total"] = img_total
                            r["current_product_id"] = pid
                            r["total_transformed"] = success
                            r["total_failed"] = fail
                            job.result = r
                            session.add(job)
                            await session.commit()
                        except Exception:
                            pass

                    await _save_image_progress()

                    if scope.get("thumbnail") and images:
                        url = await _process_one_image(client, images[0], r2)
                        if url:
                            new_images[0] = url
                            transformed += 1
                        img_done += 1
                        await _save_image_progress()

                    if scope.get("additional") and len(images) > 1:
                        for j, orig in enumerate(images[1:], 1):
                            url = await _process_one_image(client, orig, r2)
                            if url:
                                new_images[j] = url
                                transformed += 1
                            img_done += 1
                            await _save_image_progress()

                    if scope.get("detail") and detail_images:
                        for j, orig in enumerate(detail_images):
                            url = await _process_one_image(client, orig, r2)
                            if url:
                                new_detail[j] = url
                                transformed += 1
                            img_done += 1
                            await _save_image_progress()

                    if transformed > 0:
                        product.images = new_images
                        product.detail_images = new_detail
                        product.tags = list(
                            set(
                                (product.tags or [])
                                + ["__ai_image__", "__img_edited__"]
                            )
                        )
                        session.add(product)
                        success += 1
                    else:
                        fail += 1

                    # 상품 1건 완료 — current +1, 누적 카운터 갱신
                    r = dict(job.result or {})
                    r["total_transformed"] = success
                    r["total_failed"] = fail
                    r["current_product_id"] = pid
                    job.result = r
                    job.current = min(job.current + 1, job.total)
                    session.add(job)
                    await session.commit()

                    logger.info(
                        f"[배경제거] [{idx}/{len(products)}] {pid} -> "
                        f"{transformed} images"
                    )

            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now(timezone.utc)
            session.add(job)
            await session.commit()
            logger.info(
                f"[배경제거] 완료: job_id={job_id}, 성공={success}, 실패={fail}"
            )
    except Exception as exc:
        logger.error(f"[배경제거] 잡 실패: job_id={job_id}, error={exc}")
        # 실패 마킹 — 별도 세션
        try:
            from sqlalchemy import select as sa_select

            from backend.db.orm import get_write_session as _gws
            from backend.domain.samba.job.model import JobStatus, SambaJob

            async with _gws() as sess:
                r = await sess.execute(sa_select(SambaJob).where(SambaJob.id == job_id))
                j = r.scalar_one_or_none()
                if j and j.status not in (
                    JobStatus.COMPLETED.value,
                    JobStatus.FAILED.value,
                ):
                    j.status = JobStatus.FAILED
                    j.error = str(exc)[:500]
                    j.completed_at = datetime.now(timezone.utc)
                    sess.add(j)
                    await sess.commit()
        except Exception:
            pass
