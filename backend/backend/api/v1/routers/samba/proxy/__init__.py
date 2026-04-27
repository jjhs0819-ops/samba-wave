"""proxy 패키지 — 모든 서브라우터를 조립하여 router와 sourcing_queue_router 노출."""

from __future__ import annotations

from fastapi import APIRouter

from . import (
    ai_tags,
    ai_tools,
    cafe24_oauth,
    config,
    esmplus,
    gsshop,
    image_filter,
    kream,
    lottehome,
    message_history,
    misc,
    musinsa,
    notifications,
    preset_images,
    smartstore,
    sourcing,
)
from ._helpers import _get_setting, _set_setting

# 메인 라우터 — prefix 없음 (app_factory.py에서 /api/v1/samba/proxy prefix 적용)
router = APIRouter(prefix="/proxy", tags=["samba-proxy"])

router.include_router(config.router)
router.include_router(esmplus.router)
router.include_router(notifications.router)
router.include_router(message_history.router)
router.include_router(smartstore.router)
router.include_router(misc.router)
router.include_router(ai_tools.router)
router.include_router(preset_images.router)
router.include_router(ai_tags.router)
router.include_router(image_filter.router)
router.include_router(sourcing.router)
router.include_router(musinsa.router)
router.include_router(kream.router)
router.include_router(lottehome.router)
router.include_router(gsshop.router)

# 확장앱 소싱큐 전용 라우터 (인증 불필요) — app_factory.py에서 별도 등록
sourcing_queue_router = sourcing.sourcing_queue_router

# 카페24 OAuth 전용 라우터 (인증 불필요) — app_factory.py에서 별도 등록
cafe24_oauth_router = cafe24_oauth.cafe24_oauth_router

__all__ = [
    "router",
    "sourcing_queue_router",
    "cafe24_oauth_router",
    "_get_setting",
    "_set_setting",
]
