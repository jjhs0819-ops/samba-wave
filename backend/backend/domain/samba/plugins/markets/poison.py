"""POIZON(포이즌) 마켓 플러그인.

KREAM과 동일한 카탈로그형 리셀 구조:
브랜드 공식품번(style_code)으로 POIZON 카탈로그 globalSkuId를 조회한 뒤,
사이즈별로 Manual Listing(Ship-to-verify) 판매 등록을 한다.

인증: app_key/app_secret (account 필드 또는 store_poison 설정에서 로드).
"""

from __future__ import annotations

import re
from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


def _normalize_size(text: str) -> str:
    """사이즈 비교용 정규화 — 단위/공백/대소문자 제거."""
    s = (text or "").upper().strip()
    for unit in ("MM", "EU", "US", "UK", "CN", "JP", "SIZE"):
        s = s.replace(unit, "")
    return re.sub(r"\s+", "", s)


class PoisonPlugin(MarketPlugin):
    market_type = "poison"
    policy_key = "포이즌"
    required_fields = ["name", "sale_price"]

    async def _load_auth(self, session, account) -> dict | None:
        """POIZON 인증 로드 — account.additional_fields 우선, store_poison 폴백."""
        if account:
            extras = account.additional_fields or {}
            # additional_fields 키: appKey(구), apiKey(신 프론트 저장명) 모두 허용
            app_key = (
                extras.get("appKey") or extras.get("apiKey") or account.api_key or ""
            )
            app_secret = (
                extras.get("appSecret")
                or extras.get("apiSecret")
                or account.api_secret
                or ""
            )
            if app_key and app_secret:
                return {"app_key": str(app_key), "app_secret": str(app_secret)}
            # account 지정됐으나 인증정보 없으면 폴백 없이 None (오인 전송 방지)
            return None

        # 레거시 단일계정 — store_poison 설정 폴백
        from sqlmodel import select

        from backend.domain.samba.forbidden.model import SambaSettings

        stmt = select(SambaSettings).where(SambaSettings.key == "store_poison")
        result = await session.execute(stmt)
        row = result.scalars().first()
        try:
            await session.commit()
        except Exception:
            pass
        if row and isinstance(row.value, dict):
            app_key = (
                row.value.get("appKey")
                or row.value.get("app_key")
                or row.value.get("apiKey")
                or ""
            )
            app_secret = (
                row.value.get("appSecret")
                or row.value.get("app_secret")
                or row.value.get("apiSecret")
                or ""
            )
            if app_key and app_secret:
                return {"app_key": str(app_key), "app_secret": str(app_secret)}
        return None

    def _validate_category(self, category_id: str) -> str:
        """POIZON은 카탈로그(globalSkuId)로 등록 — 마켓 카테고리 코드 불필요."""
        return category_id or "0"

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """POIZON은 카탈로그 매칭 방식 — 별도 변환 없이 원본 사용."""
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
        """품번으로 카탈로그 매칭 후 사이즈별 판매 등록."""
        from backend.domain.samba.proxy.poison import PoisonClient

        app_key = creds.get("app_key", "")
        app_secret = creds.get("app_secret", "")
        if not app_key or not app_secret:
            return {
                "success": False,
                "message": "POIZON 인증 정보(app_key/app_secret)가 없습니다.",
            }

        # 브랜드 공식품번 (카탈로그 매칭 키)
        article_number = str(
            product.get("style_code")
            or product.get("styleCode")
            or product.get("model_no")
            or ""
        ).strip()
        if not article_number:
            return {
                "success": False,
                "message": "POIZON 매칭용 품번(style_code)이 없습니다.",
            }

        client = PoisonClient(app_key=app_key, app_secret=app_secret)

        # 1. 카탈로그 SKU 조회 (사이즈별 globalSkuId)
        sku_list = await client.query_sku_by_article_number(article_number)
        if not sku_list:
            return {
                "success": False,
                "message": f"POIZON 카탈로그에 품번 '{article_number}' 없음 (등록 대상 아님)",
            }

        # 사이즈 → SKU 인덱싱 (대표 사이즈 + 모든 sizeKey 후보)
        size_index: dict[str, dict[str, Any]] = {}
        for sku in sku_list:
            keys = {_normalize_size(sku.get("sizeValue", ""))}
            for cand in (sku.get("sizeCandidates") or {}).values():
                keys.add(_normalize_size(cand))
            for key in keys:
                if key:
                    size_index.setdefault(key, sku)

        # 2. 옵션(사이즈)별 판매 등록
        options = product.get("options") or []
        fallback_price = self._safe_int(product.get("sale_price"))
        results: list[dict[str, Any]] = []

        for opt in options:
            opt_name = (opt.get("name") or opt.get("size") or "").strip()
            stock = self._safe_int(opt.get("stock"), default=0)
            price = self._safe_int(opt.get("price")) or fallback_price
            if stock <= 0 or price <= 0:
                continue
            sku = size_index.get(_normalize_size(opt_name))
            if not sku:
                results.append(
                    {"size": opt_name, "success": False, "message": "사이즈 매칭 실패"}
                )
                continue
            r = await client.manual_listing(
                global_sku_id=sku["globalSkuId"],
                price=price,
                quantity=stock,
            )
            r["size"] = opt_name
            results.append(r)

        ok_count = sum(1 for r in results if r.get("success"))
        if ok_count == 0:
            err = next((r.get("message") for r in results if not r.get("success")), "")
            return {
                "success": False,
                "message": err or "POIZON 등록 실패",
                "data": results,
            }

        # _extract_market_product_no가 인식하도록 product_no 노출
        first_no = next(
            (
                r.get("sellerBiddingNo")
                for r in results
                if r.get("success") and r.get("sellerBiddingNo")
            ),
            "",
        )
        return {
            "success": True,
            "message": f"POIZON {ok_count}건 등록 (품번 {article_number})",
            "product_no": first_no,
            "data": results,
        }

    @staticmethod
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
