"""롯데ON 마켓 플러그인.

기존 dispatcher._handle_lotteon 로직을 플러그인 구조로 추출.
인증 로드는 base._load_auth 가 처리하므로 execute 에서는 creds dict 사용.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin


async def _get_setting(session, key: str) -> Any:
    """samba_settings 테이블에서 설정값 조회."""
    from backend.domain.samba.forbidden.model import SambaSettings
    from sqlmodel import select

    stmt = select(SambaSettings).where(SambaSettings.key == key)
    result = await session.execute(stmt)
    row = result.scalars().first()
    return row.value if row else None


class LotteonPlugin(MarketPlugin):
    market_type = "lotteon"
    policy_key = "롯데ON"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """상품 데이터 → 롯데ON API 포맷 변환."""
        from backend.domain.samba.proxy.lotteon import LotteonClient

        tr_grp_cd = kwargs.get("tr_grp_cd", "SR")
        tr_no = kwargs.get("tr_no", "")
        return LotteonClient.transform_product(product, category_id, tr_grp_cd, tr_no)

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """롯데ON 상품 등록/수정 — 전체 로직."""
        from backend.domain.samba.proxy.lotteon import LotteonClient

        api_key = creds.get("apiKey", "")

        # account 필드에서 보완
        if not api_key and account:
            extras = getattr(account, "additional_fields", None) or {}
            api_key = extras.get("apiKey", "") or getattr(account, "api_key", "") or ""

        if not api_key:
            return {
                "success": False,
                "message": "롯데ON API Key가 비어있습니다. 설정에서 해당 계정을 수정 후 저장해주세요.",
            }

        client = LotteonClient(api_key)
        # 거래처 정보 자동 획득 (trGrpCd, trNo)
        await client.test_auth()

        # 출고지/배송비정책/회수지 번호를 계정 또는 Settings에서 전달
        product = dict(product)
        extras: dict[str, Any] = {}
        if account:
            extras = getattr(account, "additional_fields", None) or {}
        if not extras.get("owhpNo"):
            settings_creds = await _get_setting(session, "store_lotteon")
            if settings_creds and isinstance(settings_creds, dict):
                extras = {**settings_creds, **extras}
        product["owhp_no"] = extras.get("owhpNo", "")
        product["dv_cst_pol_no"] = extras.get("dvCstPolNo", "")
        product["rtrp_no"] = extras.get("rtrpNo", "")

        data = LotteonClient.transform_product(
            product, category_id, client.tr_grp_cd or "SR", client.tr_no
        )

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        try:
            if existing_no:
                data["selPrdNo"] = existing_no
                result = await client.update_product(data)
                return {"success": True, "message": "롯데ON 수정 성공", "data": result}
            else:
                result = await client.register_product(data)
                return {"success": True, "message": "롯데ON 등록 성공", "data": result}
        except Exception as e:
            action = "수정" if existing_no else "등록"
            return {"success": False, "message": f"롯데ON {action} 실패: {e}"}
