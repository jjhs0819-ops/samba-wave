"""프리셋 이미지 관련 엔드포인트."""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_session_dependency

router = APIRouter(tags=["samba-proxy"])


@router.get("/preset-images/list")
async def list_preset_images() -> dict[str, Any]:
    """프리셋 목록 + 이미지 URL 반환."""
    from backend.domain.samba.image.service import MODEL_PRESETS, PRESET_IMAGE_DIR

    presets = []
    for key, p in MODEL_PRESETS.items():
        filename = p.get("image", "")
        local_path = PRESET_IMAGE_DIR / filename if filename else None
        presets.append(
            {
                "key": key,
                "label": p["label"],
                "desc": p["desc"],
                "image": f"/static/model_presets/{filename}"
                if local_path and local_path.exists()
                else None,
            }
        )
    return {"success": True, "presets": presets}


@router.post("/preset-images/upload")
async def upload_preset_image(
    preset_key: str = Form(...),
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """프리셋 이미지를 직접 업로드."""
    from backend.domain.samba.image.service import MODEL_PRESETS, PRESET_IMAGE_DIR

    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        return {"success": False, "message": f"프리셋 '{preset_key}' 없음"}

    filename = preset.get("image", f"{preset_key}.png")
    out_path = PRESET_IMAGE_DIR / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    out_path.write_bytes(content)

    return {
        "success": True,
        "message": f"{preset['label']} 이미지 업로드 완료 ({len(content)} bytes)",
        "image": f"/static/model_presets/{filename}",
    }


@router.post("/preset-images/regenerate")
async def regenerate_preset_image(
    request: dict[str, Any],
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """프리셋 이미지를 FLUX로 재생성."""
    from backend.domain.samba.image.service import (
        ImageTransformService,
        MODEL_PRESETS,
        PRESET_IMAGE_DIR,
    )

    preset_key = request.get("preset_key", "")
    custom_desc = request.get("desc", "")
    custom_label = request.get("label", "")
    save_only = request.get("save_only", False)
    preset = MODEL_PRESETS.get(preset_key)
    if not preset:
        return {"success": False, "message": f"프리셋 '{preset_key}' 없음"}

    # label/desc 텍스트 업데이트
    if custom_label:
        preset["label"] = custom_label
    if custom_desc:
        preset["desc"] = custom_desc

    # 텍스트만 저장 (이미지 재생성 없이)
    if save_only:
        return {"success": True, "message": f"{preset['label']} 설정 저장 완료"}

    svc = ImageTransformService(session)
    fal_key = await svc._get_flux_config()

    desc = custom_desc or preset["desc"]
    prompt = (
        f"Full body photo of {desc}. "
        "Wearing a black oversized crewneck and wide slacks. "
        "Minimal black derby shoes. Runway walking pose, cool expressionless face. "
        "Light gray studio background. Paris haute couture editorial style, photorealistic."
    )

    import os
    import fal_client

    os.environ["FAL_KEY"] = fal_key

    result = await fal_client.run_async(
        "fal-ai/flux/dev",
        arguments={
            "prompt": prompt,
            "num_inference_steps": 28,
            "guidance_scale": 3.5,
            "image_size": "portrait_3_4",
            "output_format": "png",
        },
    )

    images = result.get("images", [])
    if not images:
        return {"success": False, "message": "FLUX 응답에 이미지 없음"}

    output_url = images[0].get("url", "")
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(output_url)
        resp.raise_for_status()
        img_bytes = resp.content

    filename = preset.get("image", f"{preset_key}.png")
    out_path = PRESET_IMAGE_DIR / filename
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(img_bytes)

    if custom_desc:
        preset["desc"] = custom_desc

    return {
        "success": True,
        "message": f"{preset['label']} 이미지 재생성 완료",
        "image": f"/static/model_presets/{filename}",
    }


@router.post("/preset-images/sync-to-r2")
async def sync_preset_images_to_r2(
    session: AsyncSession = Depends(get_write_session_dependency),
) -> dict[str, Any]:
    """로컬 프리셋 이미지를 R2에 일괄 업로드."""
    from backend.domain.samba.image.service import ImageTransformService

    svc = ImageTransformService(session)
    return await svc.sync_presets_to_r2()
