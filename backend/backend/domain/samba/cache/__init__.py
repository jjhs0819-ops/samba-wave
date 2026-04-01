"""캐시 싱글턴 인스턴스."""

from .service import CacheService

# settings에서 redis_url 로드 (없으면 None → 인메모리)
try:
    from backend.core.config import settings

    _redis_url = getattr(settings, "redis_url", None)
except Exception:
    _redis_url = None

cache = CacheService(redis_url=_redis_url)
