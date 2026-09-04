"""토스 마켓 플러그인 — 토스쇼핑 Open API 상품 등록/수정/삭제."""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class TossPlugin(MarketPlugin):
    market_type = "toss"
    policy_key = "토스"
    required_fields = ["name", "sale_price"]

    # ------------------------------------------------------------------
    # 공통
    # ------------------------------------------------------------------

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        from backend.domain.samba.proxy.toss import TossClient

        settings = kwargs.get("account_settings", {})
        return TossClient.transform_product(product, category_id, settings)

    @staticmethod
    def _extract_keys(creds: dict, account) -> tuple[str, str]:
        access_key = creds.get("apiKey", "") or ""
        secret_key = creds.get("apiSecret", "") or ""
        if account:
            access_key = access_key or (getattr(account, "api_key", "") or "")
            secret_key = secret_key or (getattr(account, "api_secret", "") or "")
        return access_key, secret_key

    # ------------------------------------------------------------------
    # 등록/수정
    # ------------------------------------------------------------------

    async def execute_with_client(
        self,
        client,
        product: dict,
        category_id: str,
        settings: dict[str, Any],
        existing_no: str,
    ) -> dict[str, Any]:
        """클라이언트 주입형 등록/수정 — 테스트에서 이 경로를 검증한다."""
        from backend.domain.samba.proxy.toss import (
            TossClient,
            build_notice_items,
            fetch_notice_items,
        )

        payload = TossClient.transform_product(product, category_id, settings)

        # 고시 항목 id 는 토스가 카테고리코드별로 내려준다 — 비어 있으면 채운다.
        notice = payload.get("notice") or {}
        if not notice.get("items"):
            try:
                raw_items = await fetch_notice_items(client, notice.get("categoryCode"))
                notice["items"] = build_notice_items(raw_items, product, settings)
            except Exception as e:
                logger.warning(f"[토스] 고시 항목 조회 실패: {e}")

        try:
            if existing_no:
                await client.update_product(existing_no, payload)
                return {"success": True, "product_no": str(existing_no), "data": {}}
            result = await client.register_product(payload)
            return {
                "success": True,
                "product_no": str(result.get("id") or ""),
                "data": result,
            }
        except Exception as e:
            logger.error(f"[토스] {'수정' if existing_no else '등록'} 실패: {e}")
            return {
                "success": False,
                "message": str(e),
                "error_type": self._classify_error(e),
            }

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        from backend.domain.samba.proxy.toss import TossClient

        access_key, secret_key = self._extract_keys(creds, account)
        if not access_key or not secret_key:
            return {
                "success": False,
                "message": "토스 API Key/Secret이 없습니다.",
                "error_type": "auth_failed",
            }

        settings = (account.additional_fields or {}) if account else {}
        client = TossClient(access_key, secret_key)
        try:
            return await self.execute_with_client(
                client, product, category_id, settings, existing_no
            )
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # 삭제
    # ------------------------------------------------------------------

    async def delete_with_client(self, client, product_no: str) -> dict[str, Any]:
        """클라이언트 주입형 삭제 — 숨기기 후 삭제는 클라이언트가 처리한다."""
        try:
            await client.delete_product(product_no)
            return {"success": True, "product_no": str(product_no)}
        except Exception as e:
            logger.error(f"[토스] 삭제 실패 ({product_no}): {e}")
            return {
                "success": False,
                "message": str(e),
                "error_type": self._classify_error(e),
            }

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        from backend.domain.samba.proxy.toss import TossClient

        access_key, secret_key = self._extract_keys({}, account)
        if not access_key or not secret_key:
            return {
                "success": False,
                "message": "토스 API Key/Secret이 없습니다.",
                "error_type": "auth_failed",
            }

        client = TossClient(access_key, secret_key)
        try:
            return await self.delete_with_client(client, product_no)
        finally:
            await client.close()

    # ------------------------------------------------------------------
    # 인증 테스트
    # ------------------------------------------------------------------

    async def test_auth(self, session, account) -> bool:
        """카테고리 조회가 통과하면 키가 유효하다."""
        from backend.domain.samba.proxy.toss import TossClient

        access_key, secret_key = self._extract_keys({}, account)
        if not access_key or not secret_key:
            return False

        client = TossClient(access_key, secret_key)
        try:
            await client.list_categories()
            return True
        except Exception as e:
            logger.warning(f"[토스] 인증 테스트 실패: {e}")
            return False
        finally:
            await client.close()
