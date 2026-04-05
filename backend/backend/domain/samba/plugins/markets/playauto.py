"""플레이오토 EMP 마켓 플러그인.

솔루션 연동형 — 플레이오토 EMP API를 통해 상품 등록/수정/품절.
EMP에 마스터 상품을 등록하면, EMP 스케줄러가 연결된 쇼핑몰에 자동 전송.
"""

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.domain.samba.proxy.playauto import PlayAutoClient, PlayAutoApiError
from backend.utils.logger import logger


class PlayAutoPlugin(MarketPlugin):
    """플레이오토 EMP 마켓 플러그인."""

    market_type = "playauto"
    policy_key = "플레이오토"
    required_fields = ["name", "sale_price"]

    def _validate_category(self, category_id: str) -> str:
        """플레이오토 카테고리는 8자리 숫자 코드 — 빈 값도 허용."""
        # 카테고리 없어도 등록 가능 (EMP에서 매핑)
        if not category_id:
            return "__SKIP__"
        return category_id

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        """삼바웨이브 상품 → 플레이오토 EMP 포맷 변환."""
        stock_qty = int(product.get("_max_stock", 999))
        return PlayAutoClient.transform_product(
            product=product,
            category_id=category_id if category_id != "__SKIP__" else "",
            stock_qty=stock_qty,
        )

    async def execute(
        self,
        session,
        product: dict,
        creds: dict,
        category_id: str,
        account,
        existing_no: str,
    ) -> dict[str, Any]:
        """플레이오토 EMP API 호출 — 등록 또는 수정."""
        api_key = creds.get("apiKey", "")
        if not api_key:
            return {
                "success": False,
                "message": "플레이오토 API Key가 비어있습니다. 설정에서 API Key를 입력해주세요.",
            }

        client = PlayAutoClient(api_key)

        try:
            # 상품 데이터 변환
            emp_data = self.transform(product, category_id)

            if existing_no:
                # 수정: MasterCode를 기존 코드로 교체
                emp_data["MasterCode"] = existing_no
                results = await client.update_product([emp_data])
            else:
                # 신규 등록
                results = await client.register_product([emp_data])

            # 응답 처리
            if not results:
                return {
                    "success": False,
                    "message": "플레이오토 API 응답이 비어있습니다.",
                }

            result = results[0] if isinstance(results, list) else results

            # 성공 여부 판단
            status = str(result.get("status", "false")).lower()
            msg = result.get("msg", result.get("message", ""))

            if status == "true":
                # 등록 성공 — msg에 MasterCode가 들어옴
                master_code = msg if not existing_no else existing_no
                logger.info(
                    f"[플레이오토] {'수정' if existing_no else '등록'} 성공: "
                    f"{master_code}"
                )
                return {
                    "success": True,
                    "message": f"플레이오토 {'수정' if existing_no else '등록'} 성공",
                    "data": {
                        "market_product_no": master_code,
                        "raw_response": result,
                    },
                }
            else:
                logger.warning(f"[플레이오토] 실패: {msg}")
                return {
                    "success": False,
                    "message": f"플레이오토 실패: {msg}",
                    "data": result,
                }

        except PlayAutoApiError as e:
            logger.error(f"[플레이오토] API 에러: {e.message}")
            return {
                "success": False,
                "error_type": "network"
                if "타임아웃" in e.message or "연결" in e.message
                else "unknown",
                "message": e.message,
            }
        finally:
            await client.close()

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        """상품 품절 처리 (EMP는 삭제 = 품절/취소대기 전환)."""
        creds = await self._load_auth(session, account)
        if not creds:
            return {"success": False, "message": "플레이오토 인증정보 없음"}

        api_key = creds.get("apiKey", "")
        if not api_key:
            return {"success": False, "message": "플레이오토 API Key가 비어있습니다."}

        client = PlayAutoClient(api_key)
        try:
            results = await client.soldout_product([product_no])
            result = results[0] if isinstance(results, list) else results
            status = str(result.get("status", "false")).lower()
            msg = result.get("msg", "")

            if status == "true":
                logger.info(f"[플레이오토] 품절 처리 성공: {product_no}")
                return {"success": True, "message": f"플레이오토 품절 처리 완료: {msg}"}
            else:
                return {"success": False, "message": f"플레이오토 품절 실패: {msg}"}
        except PlayAutoApiError as e:
            return {"success": False, "message": e.message}
        finally:
            await client.close()

    async def test_auth(self, session, account) -> bool:
        """API 키 인증 테스트."""
        creds = await self._load_auth(session, account)
        if not creds:
            return False

        api_key = creds.get("apiKey", "")
        if not api_key:
            return False

        client = PlayAutoClient(api_key)
        try:
            return await client.test_connection()
        finally:
            await client.close()
