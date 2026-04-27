"""AI 모델 테스트 엔드포인트 (Claude, Gemini, R2, fal.ai)."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_read_session_dependency, get_write_session_dependency
from backend.utils.logger import logger

from ._helpers import _get_setting

router = APIRouter(tags=["samba-proxy"])


# ═══════════════════════════════════════════════
# Claude AI API 인증 테스트
# ═══════════════════════════════════════════════


@router.post("/claude/test")
async def claude_api_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Claude API 키 유효성 검증 — 최소 메시지 전송 테스트."""
    creds = await _get_setting(session, "claude")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "Claude API 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    model = creds.get("model", "claude-sonnet-4-6")
    if not api_key:
        return {"success": False, "message": "API Key가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                used_model = data.get("model", model)
                return {
                    "success": True,
                    "message": f"인증 성공 (모델: {used_model})",
                }
            else:
                err = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                err_msg = (
                    err.get("error", {}).get("message", "")
                    if isinstance(err.get("error"), dict)
                    else str(err.get("error", ""))
                )
                return {
                    "success": False,
                    "message": err_msg or f"HTTP {resp.status_code}",
                }
    except Exception as exc:
        logger.error(f"[Claude] API 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


@router.post("/gemini/test")
async def gemini_api_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Gemini API 키 유효성 검증."""
    creds = await _get_setting(session, "gemini")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "Gemini API 설정이 저장되지 않았습니다."}

    api_key = creds.get("apiKey", "")
    model = creds.get("model", "gemini-2.5-flash")
    if not api_key:
        return {"success": False, "message": "API Key가 비어있습니다."}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": "hi"}]}],
                    "generationConfig": {"maxOutputTokens": 5},
                },
            )
            if resp.status_code == 200:
                return {"success": True, "message": f"인증 성공 (모델: {model})"}
            else:
                err = (
                    resp.json()
                    if resp.headers.get("content-type", "").startswith(
                        "application/json"
                    )
                    else {}
                )
                err_msg = (
                    err.get("error", {}).get("message", "")
                    if isinstance(err.get("error"), dict)
                    else str(err.get("error", ""))
                )
                return {
                    "success": False,
                    "message": err_msg or f"HTTP {resp.status_code}",
                }
    except Exception as exc:
        logger.error(f"[Gemini] API 테스트 실패: {exc}")
        return {"success": False, "message": f"API 호출 실패: {exc}"}


@router.post("/r2/test")
async def r2_test(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """Cloudflare R2 연결 테스트."""
    creds = await _get_setting(session, "cloudflare_r2")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "R2 settings not found"}

    account_id = str(creds.get("accountId", "")).strip()
    access_key = str(creds.get("accessKey", "")).strip()
    secret_key = str(creds.get("secretKey", "")).strip()
    bucket_name = str(creds.get("bucketName", "")).strip()

    if not access_key or not secret_key or not bucket_name:
        return {
            "success": False,
            "message": "Access Key, Secret Key, Bucket Name required",
        }

    try:
        import boto3

        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        s3.head_bucket(Bucket=bucket_name)
        return {"success": True, "message": f"R2 connected (bucket: {bucket_name})"}
    except Exception as exc:
        logger.error(f"[R2] test failed: {exc}")
        return {"success": False, "message": f"R2 connection failed: {str(exc)[:200]}"}


@router.post("/r2/upload-image")
async def r2_upload_image(
    filename: str = Query(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """브라우저 WASM 배경 제거 결과 이미지를 R2에 업로드."""
    creds = await _get_setting(session, "cloudflare_r2")
    if not creds or not isinstance(creds, dict):
        return {"success": False, "message": "R2 설정이 저장되지 않았습니다"}

    account_id = str(creds.get("accountId", "")).strip()
    access_key = str(creds.get("accessKey", "")).strip()
    secret_key = str(creds.get("secretKey", "")).strip()
    bucket_name = str(creds.get("bucketName", "")).strip()
    public_url_base = str(creds.get("publicUrl", "")).strip().rstrip("/")

    if not access_key or not secret_key or not bucket_name:
        return {
            "success": False,
            "message": "R2 설정 불완전 (Access Key, Secret Key, Bucket Name 필요)",
        }

    try:
        import boto3

        content = await file.read()
        s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )
        key = f"transformed/{filename}"
        s3.put_object(
            Bucket=bucket_name, Key=key, Body=content, ContentType="image/webp"
        )
        return {"success": True, "public_url": f"{public_url_base}/{key}"}
    except Exception as exc:
        logger.error(f"[R2] upload-image 실패: {exc}")
        return {"success": False, "message": str(exc)[:200]}


@router.get("/image-fetch")
async def image_fetch_proxy(url: str = Query(...)) -> Response:
    """외부 이미지 URL을 서버에서 가져와 반환 (브라우저 CORS 우회)."""
    if len(url) > 2000:
        return Response(status_code=400, content=b"URL too long")
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; SambaWave/1.0)"},
            )
            content = resp.content
            if len(content) > 20 * 1024 * 1024:
                return Response(status_code=413, content=b"Image too large")
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=content, media_type=content_type)
    except Exception as exc:
        logger.error(f"[image-fetch] 실패: {url[:100]} — {exc}")
        return Response(status_code=502, content=b"Fetch failed")


@router.get("/fal/status")
async def fal_ai_status(
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """fal.ai 계정 상태 확인 (잔액 부족 여부)."""
    creds = await _get_setting(session, "fal_ai")
    if not creds or not isinstance(creds, dict):
        return {"status": "no_key", "message": "API 키 미등록"}

    api_key = str(creds.get("apiKey", "")).strip()
    if not api_key:
        return {"status": "no_key", "message": "API 키 비어있음"}

    import os

    os.environ["FAL_KEY"] = api_key
    try:
        import fal_client

        # 최소 비용 호출로 계정 상태 확인 (실제 이미지 생성 없이 큐 제출만)
        handle = await fal_client.submit_async(
            "fal-ai/flux/dev",
            arguments={
                "prompt": "test",
                "num_inference_steps": 1,
                "image_size": "square_hd",
            },
        )
        # 큐 제출 성공 → 잔액 있음. 즉시 취소
        await fal_client.cancel_async("fal-ai/flux/dev", handle.request_id)
        return {"status": "ok", "message": "사용 가능"}
    except Exception as e:
        err = str(e)
        if "Exhausted balance" in err or "locked" in err.lower():
            return {"status": "no_balance", "message": "잔액 부족"}
        if "401" in err or "unauthorized" in err.lower():
            return {"status": "invalid_key", "message": "API 키 무효"}
        return {"status": "error", "message": err[:100]}


@router.post("/images/transform")
async def transform_images(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """AI 이미지 변환 — background 모드는 백엔드 백그라운드 태스크, 나머지는 Cloud Run 처리."""
    import asyncio

    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(session)
    product_ids = request.get("product_ids", [])
    group_ids = request.get("group_ids", [])
    scope = request.get(
        "scope", {"thumbnail": True, "additional": False, "detail": False}
    )
    mode = request.get("mode", "background")  # background | scene | model
    model_preset = request.get("model_preset", "female_v1")

    # 그룹 ID로 요청 시 해당 그룹의 상품 ID 조회
    if group_ids and not product_ids:
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )

        repo = SambaCollectedProductRepository(session)
        for gid in group_ids:
            products = await repo.list_by_filter(gid, skip=0, limit=10000)
            product_ids.extend([p.id for p in products])
        product_ids = list(set(product_ids))

    if not product_ids:
        return {"success": False, "message": "No products selected"}

    # 배경제거는 백엔드에서 fire-and-forget 백그라운드 태스크로 직접 처리
    # (이전: 사용자 PC의 local_bg_worker.py 폴링 — 워커 미실행 시 정체)
    if mode == "background":
        from backend.domain.samba.image.bg_remove import process_bg_remove_job
        from backend.domain.samba.job.model import SambaJob

        job = SambaJob(
            job_type="bg_remove",
            status="pending",
            payload={"product_ids": product_ids, "scope": scope},
            total=len(product_ids),
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        # 요청 세션은 곧 닫히므로 태스크는 자체 세션을 새로 생성함
        asyncio.create_task(process_bg_remove_job(job.id))
        logger.info(
            f"[배경제거] 백그라운드 태스크 시작: job_id={job.id}, "
            f"{len(product_ids)}개 상품"
        )
        return {
            "success": True,
            "status": "queued",
            "job_id": job.id,
            "message": f"배경제거 시작 ({len(product_ids)}개 상품)",
            "total_transformed": 0,
            "total_failed": 0,
        }

    try:
        result = await svc.transform_products(product_ids, scope, mode, model_preset)
        transformed = result.get("total_transformed", 0)
        return {"success": transformed > 0, **result}
    except Exception as exc:
        logger.error(f"[이미지변환] transform failed: {exc}")
        return {"success": False, "message": str(exc)[:300]}


@router.get("/bg-jobs/{job_id}/status")
async def bg_jobs_status(
    job_id: str,
    session: AsyncSession = Depends(get_read_session_dependency),
) -> dict[str, Any]:
    """프론트엔드 폴링용 — 배경제거 잡 상태 조회."""
    from sqlalchemy import select as sa_select

    from backend.domain.samba.job.model import SambaJob

    stmt = sa_select(SambaJob).where(SambaJob.id == job_id)
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        return {"status": "not_found"}

    res = job.result or {}
    return {
        "status": job.status,
        "total": job.total,
        "current": job.current,
        "total_transformed": res.get("total_transformed", 0),
        "total_failed": res.get("total_failed", 0),
        "image_current": res.get("image_current"),
        "image_total": res.get("image_total"),
        "current_product_id": res.get("current_product_id"),
    }
