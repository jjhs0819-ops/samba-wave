"""collector_collection 패키지 — 수집/보강/브랜드 서브라우터 조립."""

from fastapi import APIRouter

from .collect import router as _collect_router
from .enrich import router as _enrich_router
from .brands import router as _brands_router

# 메인 라우터: prefix=/collector 유지 (app_factory.py에서 직접 include)
router = APIRouter(prefix="/collector", tags=["samba-collector"])

router.include_router(_collect_router)
router.include_router(_enrich_router)
router.include_router(_brands_router)
