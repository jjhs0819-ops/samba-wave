"""R2 이미지 공개 프록시 — 마켓 서버가 우리 도메인으로 이미지를 받아가게 한다.

배경(2026-08-14 실측):
  롯데ON 은 R2 공개 도메인(img.sambawave-cdn.shop)을 상품등록 API 의 origFileNm
  검증에서 9999 "URL 형식이 올바르지 않습니다" 로 거부한다. 경로/파일명을 원본
  CDN 과 똑같이 맞춰도 거부되므로 호스트가 사유다. 반면 자체 도메인
  (api.samba-wave.co.kr)으로 주면 등록에 성공한다.

  VM Caddy 에 이미 R2 리버스 프록시(/images/*)가 있지만 그 origin(R2_PUBLIC_HOST)이
  현재 테넌트 버킷이 아닌 옛 버킷을 가리키고 있어, 새로 만든 이미지(AI 변환분 등)는
  404 가 난다. VM 설정을 못 고치는 상황에서도 동작하도록 백엔드에서 직접 스트리밍
  하는 경로를 둔다 — 같은 도메인이므로 마켓 입장에서는 동일하다.

인증:
  마켓 서버가 헤더 없이 받아가야 하므로 공개 경로다. ApiGatewayMiddleware 의
  _EXEMPT_PREFIXES 에 등록되어 있고 JWT 의존성도 걸지 않는다. 노출 범위는 R2 버킷의
  이미지 오브젝트로 한정되며, 키 검증으로 경로 이탈을 막는다.
"""

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.db.orm import get_read_session
from backend.utils.logger import logger

router = APIRouter(prefix="/img", tags=["samba-image-proxy"])

# 허용 키 형태 — 우리 서비스가 만드는 오브젝트 키만 통과시킨다.
# (mirror/<hash>.jpg, transformed/ai_*.jpg, model_presets/*.png 등)
# 상위 경로 이탈(../)·쿼리 주입·비이미지 확장자를 원천 차단.
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-/]+\.(jpe?g|png|gif|webp|bmp)$", re.IGNORECASE)

_CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
    "bmp": "image/bmp",
}


@router.get("/{key:path}")
async def get_image(key: str) -> Any:
    """R2 오브젝트를 우리 도메인으로 스트리밍.

    마켓 서버(롯데ON 등)가 등록 시 1회씩 받아가는 용도다. Cloudflare 가 앞단에서
    캐시하므로 반복 요청이 백엔드까지 오지는 않는다.
    """
    if ".." in key or not _KEY_RE.match(key):
        raise HTTPException(404, "not found")

    try:
        async with get_read_session() as session:
            from backend.domain.samba.image.service import ImageTransformService

            r2 = await ImageTransformService(session)._get_r2_client()
        if not r2:
            raise HTTPException(503, "storage unavailable")
        client, bucket, _ = r2

        obj = await asyncio.to_thread(client.get_object, Bucket=bucket, Key=key)
        body = await asyncio.to_thread(obj["Body"].read)
    except HTTPException:
        raise
    except Exception as e:
        # 존재하지 않는 키는 404 로 — 그 외 오류도 마켓 입장에선 동일하지만
        # 원인 추적을 위해 로그는 남긴다(silent fail 금지).
        logger.warning(f"[이미지프록시] 조회 실패 key={key!r}: {e}")
        raise HTTPException(404, "not found")

    ext = key.rsplit(".", 1)[-1].lower()
    return Response(
        content=body,
        media_type=obj.get("ContentType") or _CONTENT_TYPES.get(ext, "image/jpeg"),
        headers={
            # 마켓/CDN 이 오래 캐시하도록 — 키가 내용 해시 기반이라 불변이다.
            "Cache-Control": "public, max-age=31536000, immutable",
        },
    )
