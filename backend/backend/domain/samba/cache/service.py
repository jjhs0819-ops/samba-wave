"""캐시 서비스 — Redis 우선, 연결 실패 시 인메모리 dict 폴백."""

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheService:
    """Redis/메모리 캐시. Redis 없어도 동작."""

    def __init__(self, redis_url: Optional[str] = None):
        self._redis = None
        self._memory: dict[str, tuple[Any, float]] = {}  # {key: (value, expires_at)}
        self._redis_url = redis_url

    async def connect(self):
        """Redis 연결 시도. 실패해도 예외 없음."""
        if not self._redis_url:
            logger.info("[캐시] Redis URL 미설정 — 인메모리 모드")
            return
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("[캐시] Redis 연결 성공")
        except Exception as e:
            logger.warning(f"[캐시] Redis 연결 실패 — 인메모리 폴백: {e}")
            self._redis = None

    async def get(self, key: str) -> Any | None:
        """캐시 조회."""
        if self._redis:
            try:
                data = await self._redis.get(key)
                if data:
                    return json.loads(data)
            except Exception:
                pass
        if key in self._memory:
            value, expires_at = self._memory[key]
            if time.time() < expires_at:
                return value
            del self._memory[key]
        return None

    async def set(self, key: str, value: Any, ttl: int = 30):
        """캐시 저장. ttl 단위: 초."""
        if self._redis:
            try:
                await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
                return
            except Exception:
                pass
        self._memory[key] = (value, time.time() + ttl)

    async def delete(self, key: str):
        """캐시 삭제."""
        if self._redis:
            try:
                await self._redis.delete(key)
            except Exception:
                pass
        self._memory.pop(key, None)

    async def clear_pattern(self, pattern: str):
        """패턴 매칭 키 삭제. 예: 'products:*'"""
        if self._redis:
            try:
                keys = await self._redis.keys(pattern)
                if keys:
                    await self._redis.delete(*keys)
            except Exception:
                pass
        prefix = pattern.replace("*", "")
        to_delete = [k for k in self._memory if k.startswith(prefix)]
        for k in to_delete:
            del self._memory[k]
