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
        store_id = kwargs.get("store_id", "6004")
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

        # 전시카테고리 미매핑 시 등록 불가 — 명확한 에러 반환
        if not category_id:
            product_name = product.get("name", "")
            return {
                "success": False,
                "message": f"신세계몰 전시카테고리가 매핑되지 않았습니다. 카테고리 매핑 후 다시 시도하세요. (상품: {product_name[:30]})",
            }

        store_id = creds.get("storeId", "6004")
        client = SSGClient(api_key, site_no=store_id)

        # 배송비/주소 인프라 데이터 자동 조회
        infra = await client.fetch_infra()
        logger.info(f"[SSG] 인프라 조회 완료: {list(infra.keys())}")

        # 설정 페이지 값을 infra에 주입 (설정값이 있으면 fetch_infra 조회값 우선 덮어쓰기)
        setting_shppcst_ids = {
            "whoutShppcstId": creds.get("whoutShppcstId", ""),
            "retShppcstId": creds.get("retShppcstId", ""),
            "addShppcstIdJeju": creds.get("addShppcstIdJeju", ""),
            "addShppcstIdIsland": creds.get("addShppcstIdIsland", ""),
            "whoutAddrId": creds.get("whoutAddrId", ""),
            "snbkAddrId": creds.get("snbkAddrId", ""),
        }
        for k, v in setting_shppcst_ids.items():
            if v:
                infra[k] = v

        # 필수 배송 인프라 ID 검증 — 없으면 SSG API 필수값 오류 발생
        missing_infra = []
        if not infra.get("whoutAddrId"):
            missing_infra.append("출고주소ID(whoutAddrId)")
        if not infra.get("snbkAddrId"):
            missing_infra.append("반품주소ID(snbkAddrId)")
        if not infra.get("whoutShppcstId"):
            missing_infra.append("출고배송비ID(whoutShppcstId)")
        if not infra.get("retShppcstId"):
            missing_infra.append("반품배송비ID(retShppcstId)")
        if missing_infra:
            return {
                "success": False,
                "message": f"SSG 배송 설정 누락: {', '.join(missing_infra)}. 설정 페이지에서 배송정보를 확인하세요.",
            }

        # 설정에서 마진율/배송소요일/구매수량 제한 추출
        margin_rate = int(creds.get("marginRate") or 0)
        shpp_rqrm_dcnt = int(creds.get("shppRqrmDcnt") or 3)
        day_max_qty = int(creds.get("dayMaxQty") or 5)
        once_min_qty = int(creds.get("onceMinQty") or 1)
        once_max_qty = int(creds.get("onceMaxQty") or 5)

        # A/S 정보를 설정값에서 product에 주입 (notice_utils.build_ssg_notice 참조)
        if creds.get("asPhone"):
            product = {**product, "_as_phone": creds["asPhone"]}
        if creds.get("asMessage"):
            product = {**product, "_as_message": creds.get("asMessage", "")}

        # category_id = 전시카테고리 ID, _std_category_id = 표준카테고리 ID
        std_category_id = product.get("_std_category_id", "") or ""
        logger.info(
            f"[SSG] 전시카테고리={category_id!r}, 표준카테고리={std_category_id!r}"
        )

        try:
            data = client.transform_product(
                product,
                category_id,
                std_category_id=std_category_id,
                infra=infra,
                margin_rate=margin_rate,
                shpp_rqrm_dcnt=shpp_rqrm_dcnt,
                day_max_qty=day_max_qty,
                once_min_qty=once_min_qty,
                once_max_qty=once_max_qty,
            )
        except Exception as e:
            import traceback as _tb

            logger.error(f"[SSG] transform_product 예외: {e}\n{_tb.format_exc()}")
            return {
                "success": False,
                "message": f"SSG 상품 데이터 변환 실패: {str(e)[:200]}",
            }

        # 기존 상품번호가 있으면 수정, 없으면 신규등록
        if existing_no:
            data["itemId"] = existing_no
            result = await client.update_product(data)
            # 영구판매중지 상품은 수정 불가 → 상품번호 초기화 후 신규등록
            result_data_chk = result.get("data", {})
            if isinstance(result_data_chk, dict):
                res_chk = result_data_chk.get("result", {})
                if isinstance(res_chk, dict):
                    msg_chk = (
                        res_chk.get("resultDesc", "")
                        or res_chk.get("resultMessage", "")
                        or ""
                    )
                    if "영구판매중지" in msg_chk:
                        logger.info(
                            f"[SSG] 영구판매중지 상품 감지 → 상품번호 초기화 후 신규등록: itemId={existing_no}"
                        )
                        data.pop("itemId", None)
                        result = await client.register_product(data)
                        result["_clear_product_no"] = (
                            True  # 호출자에서 DB 상품번호 초기화
                        )
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
                    msg = (
                        res.get("resultDesc", "")
                        or res.get("resultMessage", "")
                        or f"resultCode={code}"
                    )
                    return {
                        "success": False,
                        "message": f"SSG 등록 실패: {msg}",
                        "data": result_data,
                    }

        action = "수정" if existing_no else "등록"
        return {"success": True, "message": f"SSG {action} 성공", "data": result}
