"""11번가 마켓 플러그인.

기존 dispatcher._handle_11st 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


class ElevenstPlugin(MarketPlugin):
    market_type = "11st"
    policy_key = "11번가"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 11번가 XML 포맷 변환."""
        from backend.domain.samba.proxy.elevenst import ElevenstClient

        settings = kwargs.get("settings", {})
        return ElevenstClient.transform_product(product, category_id, settings=settings)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """11번가 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.elevenst import ElevenstClient

        api_key = creds.get("apiKey", "")

        # account 필드에서 보완
        if not api_key and account:
            api_key = getattr(account, "api_key", "") or ""

        if not api_key:
            return {
                "success": False,
                "message": "11번가 API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요.",
            }

        # 카테고리 코드가 숫자가 아니면 (경로 문자열이면) 빈값 처리
        cat_code = category_id
        if cat_code and not cat_code.isdigit():
            cat_code = ""

        if not cat_code:
            return {
                "success": False,
                "message": "11번가 카테고리 코드가 없습니다. 카테고리 매핑을 설정해주세요.",
            }

        client = ElevenstClient(api_key)
        account_settings = (account.additional_fields or {}) if account else {}
        xml_data = ElevenstClient.transform_product(
            product, cat_code, settings=account_settings
        )

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        from backend.domain.samba.proxy.elevenst import ElevenstApiError

        try:
            if existing_no:
                result = await client.update_product(existing_no, xml_data)
                return {"success": True, "message": "11번가 수정 성공", "data": result}
            else:
                result = await client.register_product(xml_data)
                return {"success": True, "message": "11번가 등록 성공", "data": result}
        except ElevenstApiError as e:
            err = str(e)
            if "해외 쇼핑 카테고리" in err:
                return {
                    "success": False,
                    "message": f"카테고리 오류: 코드 {cat_code}가 해외쇼핑 카테고리입니다. 카테고리매핑에서 국내 카테고리 코드로 수정해주세요.",
                }
            return {"success": False, "message": f"11번가 등록 실패: {err}"}
