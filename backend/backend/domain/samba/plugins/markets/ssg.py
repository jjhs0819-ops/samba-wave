"""SSG(신세계몰) 마켓 플러그인.

기존 dispatcher._handle_ssg 로직을 플러그인 구조로 추출.
SSGClient를 통해 인프라 조회 + 상품 변환 + 등록/수정 처리.
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.utils.logger import logger


class SSGPlugin(MarketPlugin):
  market_type = "ssg"
  policy_key = "신세계몰"
  required_fields = ["name", "sale_price"]

  def transform(self, product: dict, category_id: str, **kwargs) -> dict:
    """SSGClient.transform_product 위임."""
    from backend.domain.samba.proxy.ssg import SSGClient

    api_key = kwargs.get("api_key", "")
    store_id = kwargs.get("store_id", SSGClient.DEFAULT_SITE_NO)
    infra = kwargs.get("infra", {})
    client = SSGClient(api_key, site_no=store_id)
    return client.transform_product(product, category_id, infra=infra)

  async def execute(
    self,
    session,
    product: dict,
    creds: dict,
    category_id: str,
    account,
    existing_no: str,
  ) -> dict[str, Any]:
    """SSG 상품 등록/수정 — 전체 로직."""
    from backend.domain.samba.proxy.ssg import SSGClient

    api_key = creds.get("apiKey", "")
    if not api_key:
      return {"success": False, "message": "SSG 인증키가 비어있습니다."}

    store_id = creds.get("storeId", SSGClient.DEFAULT_SITE_NO)
    client = SSGClient(api_key, site_no=store_id)

    # 배송비/주소 인프라 데이터 자동 조회
    infra = await client.fetch_infra()
    logger.info(f"[SSG] 인프라 조회 완료: {list(infra.keys())}")

    data = client.transform_product(product, category_id, infra=infra)

    # 기존 상품번호가 있으면 수정, 없으면 신규등록
    if existing_no:
      data["itemId"] = existing_no
      result = await client.update_product(data)
    else:
      result = await client.register_product(data)

    # SSG API 응답 검증
    result_data = result.get("data", {})
    if isinstance(result_data, dict):
      res = result_data.get("result", {})
      if isinstance(res, dict):
        code = res.get("resultCode", "")
        if code and str(code) != "00" and str(code) != "SUCCESS":
          # resultDesc에 상세 에러 포함 — resultMessage("FAIL")보다 우선
          msg = res.get("resultDesc", "") or res.get("resultMessage", "") or f"resultCode={code}"
          return {"success": False, "message": f"SSG 등록 실패: {msg}", "data": result_data}

    action = "수정" if existing_no else "등록"
    return {"success": True, "message": f"SSG {action} 성공", "data": result}
