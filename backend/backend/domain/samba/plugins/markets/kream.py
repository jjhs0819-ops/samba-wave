"""KREAM 마켓 플러그인.

기존 dispatcher._handle_kream 로직을 플러그인 구조로 추출.
KREAM은 token/cookie를 settings에서 로드하므로 _load_auth 오버라이드.
사이즈별 매도 입찰(ask) 방식으로 등록.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


async def _get_setting(session, key: str):
    """samba_settings 테이블에서 설정값 조회 후 즉시 커밋 — idle in transaction 방지."""
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    stmt = select(SambaSettings).where(SambaSettings.key == key)
    result = await session.execute(stmt)
    row = result.scalars().first()
    val = row.value if row else None
    try:
        await session.commit()
    except Exception:
        pass
    return val


class KreamPlugin(MarketPlugin):
    market_type = "kream"
    policy_key = "KREAM"
    required_fields = ["name", "sale_price"]

    async def _load_auth(self, session, account) -> dict | None:
        """KREAM 인증 로드 — settings에서 token/cookie 우선 조회.

        KREAM은 일반 마켓과 달리 계정 필드가 아닌
        kream_token / kream_cookie / store_kream 설정에서 인증정보를 가져온다.
        """
        token = await _get_setting(session, "kream_token") or ""
        cookie = await _get_setting(session, "kream_cookie") or ""

        # token/cookie가 없으면 store_kream 설정에서 폴백
        if not token and not cookie:
            creds = await _get_setting(session, "store_kream")
            if creds and isinstance(creds, dict):
                token = creds.get("token", "")

        if not token:
            return None

        return {"token": str(token), "cookie": str(cookie)}

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """KREAM은 변환 없이 원본 데이터 사용 (매도 입찰 방식)."""
        return product

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """KREAM 매도 입찰 등록 — 사이즈별 ask bidding."""
        from backend.domain.samba.proxy.kream import KreamClient

        token = creds.get("token", "")
        cookie = creds.get("cookie", "")

        if not token:
            return {"success": False, "message": "KREAM 인증 정보가 없습니다."}

        client = KreamClient(token=token, cookie=cookie)
        kream_data = product.get("kream_data") or {}
        product_id = kream_data.get("product_id", "")
        if not product_id:
            return {"success": False, "message": "KREAM 상품 ID가 없습니다."}

        # 사이즈별 매도 입찰
        options = product.get("options") or []
        sale_type = "auction"
        results = []
        for opt in options:
            size = opt.get("size", "") or opt.get("name", "")
            price = int(opt.get("price", product.get("sale_price", 0)))
            if size and price:
                r = await client.create_ask(product_id, size, price, sale_type)
                results.append(r)

        if not results:
            # 단일 상품 (옵션 없음)
            price = int(product.get("sale_price", 0))
            r = await client.create_ask(product_id, "ONE_SIZE", price, sale_type)
            results.append(r)

        return {
            "success": True,
            "message": f"KREAM {len(results)}건 입찰 등록",
            "data": results,
        }
