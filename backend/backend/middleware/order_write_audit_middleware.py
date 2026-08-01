"""주문 수정 API 호출자 추적 — 임시 진단용 미들웨어.

포이즌 주문의 실구매가(cost)·소싱주문번호(sourcing_order_number)가
주문 이행도 안 했는데 자동으로 채워지는 문제의 호출자를 특정하기 위해
PUT /orders/{id} 요청의 출처(IP/UA/Origin)와 body 를 로그로 남긴다.

DB 감사 트리거로 확인된 SQL 지문:
  - UPDATE samba_order SET cost, profit, profit_rate  → body {cost}
  - UPDATE samba_order SET sourcing_order_number      → body {sourcing_order_number}
둘 다 PUT /orders/{id} 경로이므로 이 미들웨어가 호출자를 잡는다.

원인 확정 후 제거할 것 (app_factory.py 등록 라인도 함께).
"""

from backend.utils.logger import logger

# 추적 대상 필드 — 이 키가 body 에 있을 때만 로그 (일반 주문수정 노이즈 제외)
_WATCH_KEYS = ("cost", "sourcing_order_number", "shipping_fee")
_MAX_BODY = 2000


def _header(headers: list, name: bytes) -> str:
    """ASGI raw headers 에서 헤더 값 추출 (없으면 빈 문자열)."""
    for k, v in headers:
        if k.lower() == name:
            try:
                return v.decode("utf-8", "replace")
            except Exception:
                return ""
    return ""


class OrderWriteAuditMiddleware:
    """Pure ASGI — PUT /orders/{id} 호출자 기록 (임시 진단)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "") or ""
        method = (scope.get("method", "") or "").upper()
        # /orders/{id} 단건 수정만 — 하위 경로(/status 등)는 별도 엔드포인트라 제외
        is_target = (
            method == "PUT"
            and "/orders/" in path
            and not path.rstrip("/").endswith("/status")
        )
        if not is_target:
            await self.app(scope, receive, send)
            return

        # body 를 소비하면 라우터가 못 읽으므로 캐시 후 재생(replay)
        chunks: list[bytes] = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b"") or b"")
                more = msg.get("more_body", False)
            else:
                more = False
        body = b"".join(chunks)

        try:
            body_txt = body.decode("utf-8", "replace")[:_MAX_BODY]
            if any(k in body_txt for k in _WATCH_KEYS):
                headers = scope.get("headers", []) or []
                client = scope.get("client") or ("", 0)
                logger.warning(
                    "[주문쓰기추적] path=%s ip=%s cf_ip=%s xff=%s ua=%s origin=%s "
                    "referer=%s devid=%s body=%s",
                    path,
                    client[0],
                    _header(headers, b"cf-connecting-ip"),
                    _header(headers, b"x-forwarded-for"),
                    _header(headers, b"user-agent")[:160],
                    _header(headers, b"origin"),
                    _header(headers, b"referer")[:120],
                    _header(headers, b"x-device-id"),
                    body_txt,
                )
        except Exception as exc:  # 진단 코드가 요청을 막으면 안 됨
            logger.warning(f"[주문쓰기추적] 로깅 실패(무시): {exc}")

        sent = False

        async def replay():
            """캐시한 body 를 라우터에 그대로 흘려보냄."""
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
