"""마켓 프록시 공통 베이스 클라이언트.

공통 기능: httpx 커넥션 풀 재사용, JSON 응답 파싱, 에러 처리, 로깅.
각 마켓 클라이언트는 _build_headers()와 _parse_error()만 오버라이드.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class ProxyApiError(Exception):
    """프록시 API 공통 에러."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        super().__init__(f"[{status}] {code}: {message}")


class BaseProxyClient:
    """마켓 API 프록시 베이스 클라이언트.

    httpx.AsyncClient를 클래스 레벨에서 관리하여 커넥션 풀 재사용.
    컨텍스트 매니저 또는 수동 close() 지원.
    """

    base_url: str = ""
    timeout: float = 60.0
    market_name: str = ""  # 로깅용 마켓 이름 (예: "카페24")

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # httpx 클라이언트 관리
    # ------------------------------------------------------------------

    def _get_client(self) -> httpx.AsyncClient:
        """httpx 클라이언트 lazy 생성 — 커넥션 풀 재사용."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=10.0),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """httpx 클라이언트 정리."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    # ------------------------------------------------------------------
    # 핵심 API 호출
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        method: str,
        path: str,
        body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, str]] = None,
        content: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """공통 API 호출.

        1. _build_headers()로 인증 헤더 생성 (서브클래스 오버라이드)
        2. httpx로 요청
        3. _parse_response()로 응답 파싱 (JSON 기본, XML 오버라이드 가능)
        4. _check_error()로 에러 검사 (서브클래스 오버라이드)
        """
        url = f"{self.base_url}{path}"
        headers = await self._build_headers(method, path)
        if extra_headers:
            headers.update(extra_headers)

        client = self._get_client()

        kwargs: dict[str, Any] = {"headers": headers}
        if params:
            kwargs["params"] = params
        # content(raw string)와 body(JSON)는 배타적 사용
        if content is not None:
            kwargs["content"] = content
        elif body is not None:
            kwargs["json"] = body

        resp = await client.request(method, url, **kwargs)

        # 응답 파싱
        data = await self._parse_response(resp)

        # 에러 검사
        await self._check_error(resp, data)

        return data

    # ------------------------------------------------------------------
    # 서브클래스 오버라이드 포인트
    # ------------------------------------------------------------------

    async def _build_headers(self, method: str, path: str) -> dict[str, str]:
        """인증 헤더 생성 — 서브클래스에서 오버라이드.

        기본: JSON Content-Type만 설정.
        """
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _parse_response(self, resp: httpx.Response) -> dict[str, Any]:
        """응답 파싱 — 기본 JSON. XML 마켓은 오버라이드."""
        try:
            return resp.json()
        except Exception:
            return {"_raw": resp.text, "_status": resp.status_code}

    async def _check_error(self, resp: httpx.Response, data: dict[str, Any]) -> None:
        """에러 검사 — 서브클래스에서 오버라이드.

        기본: HTTP 4xx/5xx면 ProxyApiError raise.
        """
        if resp.status_code >= 400:
            message = data.get("message", "") or data.get("error", "") or str(data)
            code = str(data.get("code", resp.status_code))
            raise ProxyApiError(resp.status_code, code, str(message)[:500])
