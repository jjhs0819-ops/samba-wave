"""TenantContextMiddleware — JWT의 tid 클레임을 contextvar에 세팅.

Pure ASGI middleware로 구현 — starlette BaseHTTPMiddleware는 contextvar가
sub-task로 격리되어 라우트 핸들러로 전파되지 않는 알려진 이슈가 있다.
"""

import logging
from typing import Optional

import jwt

from backend.core.config import settings
from backend.core.tenant_context import current_tenant_id

logger = logging.getLogger(__name__)

# user_id → tenant_id 프로세스 캐시 (옛 토큰 폴백용)
_USER_TENANT_CACHE: dict[str, str] = {}


def _decode_jwt_from_headers(headers: list) -> tuple[Optional[str], Optional[str]]:
    """ASGI scope의 headers에서 (tenant_id, user_id) 추출."""
    auth = None
    for k, v in headers:
        if k == b"authorization":
            auth = v.decode()
            break
    if not auth or not auth.startswith("Bearer "):
        return None, None
    token = auth.split(" ", 1)[1]
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
    except Exception:
        return None, None
    return payload.get("tid"), payload.get("sub")


async def _db_lookup_tenant_id(user_id: str) -> Optional[str]:
    """SambaUser에서 tenant_id 폴백 조회 — 옛 토큰(tid 없음) 대응."""
    cached = _USER_TENANT_CACHE.get(user_id)
    if cached:
        return cached
    try:
        from backend.db.orm import get_read_session
        from sqlmodel import select
        from backend.domain.samba.user.model import SambaUser

        async with get_read_session() as sess:
            stmt = select(SambaUser.tenant_id).where(SambaUser.id == user_id)
            result = await sess.execute(stmt)
            tid = result.scalar_one_or_none()
            if tid:
                _USER_TENANT_CACHE[user_id] = tid
            return tid
    except Exception as e:
        logger.warning(f"[tenant_context] DB 폴백 실패 user_id={user_id}: {e}")
        return None


class TenantContextMiddleware:
    """Pure ASGI middleware — contextvar set in same task as route handler."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        tenant_id, user_id = _decode_jwt_from_headers(scope.get("headers", []))
        if not tenant_id and user_id:
            tenant_id = await _db_lookup_tenant_id(user_id)

        token = current_tenant_id.set(tenant_id)
        # 진단 로그 — 운영자 데이터 누수 디버깅용 (path 일부만)
        try:
            path = scope.get("path", "")
            if any(
                seg in path
                for seg in (
                    "/products",
                    "/settings",
                    "/cs",
                    "/forbidden",
                    "/scroll",
                    "/dashboard",
                )
            ):
                logger.info(
                    f"[tenant_ctx] path={path} user_id={user_id} tid={tenant_id}"
                )
        except Exception:
            pass
        try:
            await self.app(scope, receive, send)
        finally:
            current_tenant_id.reset(token)
