"""패션플러스 판매마켓 플러그인.

등록: GoodsAdd → 응답의 OptID 맵을 결과에 담아 상위가 last_sent_data 에 보관
수정: 가격은 GoodsUpt, 재고·옵션가는 ScmOptionUpt(일괄)
삭제: GoodsDelete 가 '임시보관' 이라 재고0 → 노출해제 → 삭제 3단으로 진행
"""

from __future__ import annotations

from typing import Any

from backend.domain.samba.plugins.market_base import MarketPlugin
from backend.domain.samba.plugins.markets.fashionplus_payload import (
    build_goods_add,
    build_scm_option_upt,
    normalize_prices,
    option_key,
)
from backend.domain.samba.proxy.fashionplus_market import (
    FashionPlusMarketClient,
    classify_error,
    extract_credentials,
    is_ok,
)
from backend.utils.logger import logger

_SELF_SOURCE = "FASHIONPLUS"


def is_self_sourced(product: dict) -> bool:
    """패플에서 수집한 상품을 패플에 되파는 자기순환인지 판정."""
    return str(product.get("source") or "").strip().upper() == _SELF_SOURCE


def extract_option_ids(response: dict) -> dict[str, int]:
    """GoodsAdd 응답에서 색상|사이즈 → OptID 맵을 만든다."""
    ids: dict[str, int] = {}
    for row in response.get("Options") or []:
        opt_id = row.get("OptID")
        if not opt_id:
            continue
        key = option_key({"color": row.get("Color"), "size": row.get("Size")})
        try:
            ids[key] = int(opt_id)
        except (TypeError, ValueError):
            # GoodsAdd 가 원격에서 이미 성공한 뒤다 — 여기서 예외를 내보내면
            # 상위가 "등록 실패"로 오판해 재시도 → 중복등록 위험. 건너뛰고 기록만 한다.
            logger.warning(
                f"[패션플러스] OptID 정수 해석 불가 — 매핑 제외: {opt_id!r} (key={key})"
            )
    return ids


def _fail(message: str, status: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {"success": False, "message": message}
    if status:
        result["error_type"] = classify_error(status)
    return result


class FashionPlusPlugin(MarketPlugin):
    """패션플러스 판매마켓 플러그인."""

    market_type = "fashionplus"
    policy_key = "패션플러스"
    required_fields = ["name", "sale_price"]

    def transform(self, product: dict, category_id: str, **kwargs) -> dict:
        return build_goods_add(
            product,
            category_id,
            kwargs.get("brand_id", ""),
            kwargs.get("sender_code", ""),
        )

    def _build_client(self, account) -> FashionPlusMarketClient | None:
        cust_code, partner_login_id = extract_credentials(account)
        if not cust_code:
            return None
        extras = getattr(account, "additional_fields", None) or {}
        use_test = bool(extras.get("useTestServer"))
        return FashionPlusMarketClient(cust_code, partner_login_id, use_test=use_test)

    async def execute(
        self, session, product, creds, category_id, account, existing_no
    ) -> dict[str, Any]:
        if is_self_sourced(product):
            return _fail("패션플러스 소싱 상품은 자기순환이라 전송하지 않습니다")

        client = self._build_client(account)
        if client is None:
            return _fail("패션플러스 인증정보(custCode) 없음")

        extras = getattr(account, "additional_fields", None) or {}
        sender_code = str(extras.get("senderCode") or "")
        brand_id = str(product.get("_fp_brand_id") or extras.get("brandId") or "")

        try:
            if existing_no:
                return await self._update(client, product, existing_no)
            return await self._create(
                client, product, category_id, brand_id, sender_code
            )
        except ValueError as e:
            # 매핑·필수값 누락은 재시도해도 소용없다 — 즉시 실패시켜 사유를 남긴다
            return _fail(str(e))

    async def _create(
        self, client, product: dict, category_id: str, brand_id: str, sender_code: str
    ) -> dict[str, Any]:
        body = build_goods_add(product, category_id, brand_id, sender_code)
        resp = await client.call("goods_add", body)
        if not is_ok(resp):
            return _fail(
                f"패션플러스 등록 실패: {resp.get('Message') or resp.get('Status')}",
                str(resp.get("Status", "")),
            )
        item_id = str(resp.get("ItemID") or resp.get("ItemId") or "")
        option_ids = extract_option_ids(resp)
        if not option_ids:
            logger.warning(
                f"[패션플러스] 등록 응답에 OptID 없음 — "
                f"OptionQry 역조회 필요 ItemID={item_id}"
            )
        return {
            "success": True,
            "message": "패션플러스 등록 완료",
            "product_no": item_id,
            "option_ids": option_ids,
        }

    async def _update(self, client, product: dict, item_id: str) -> dict[str, Any]:
        prices = normalize_prices(
            product.get("sale_price"), product.get("consumer_price")
        )
        if prices is None:
            return _fail(f"패션플러스 전송 불가 판매가: {product.get('sale_price')!r}")
        sale, consumer = prices

        price_resp = await client.call(
            "goods_upt",
            {"ItemID": item_id, "SalePrice": sale, "ConsumerPrice": consumer},
        )
        if not is_ok(price_resp):
            return _fail(
                f"패션플러스 가격수정 실패: "
                f"{price_resp.get('Message') or price_resp.get('Status')}",
                str(price_resp.get("Status", "")),
            )

        options = product.get("options") or []
        option_ids = product.get("_fp_option_ids") or {}
        rows = build_scm_option_upt(item_id, option_ids, options, update_price=False)
        if options and not rows:
            # 가격만 갱신되고 재고는 하나도 못 건드렸다 — 성공으로 보고하면
            # 품절 반영이 안 된 채 "수정 완료"로 박제되는 유령이 생긴다.
            return _fail(
                f"패션플러스 가격은 갱신됨 / 재고 미갱신 — "
                f"OptID 매핑 없음 (옵션 {len(options)}건)"
            )
        for row in rows:
            stock_resp = await client.call("scm_option_upt", row)
            if not is_ok(stock_resp):
                logger.warning(
                    f"[패션플러스] 재고 갱신 실패 OptID={row['OptID']} "
                    f"{stock_resp.get('Message') or stock_resp.get('Status')}"
                )
        return {
            "success": True,
            "message": f"패션플러스 수정 완료 (옵션 {len(rows)}건)",
            "product_no": item_id,
        }

    async def delete_with_client(
        self, client, item_id: str, options: list[dict]
    ) -> dict[str, Any]:
        """재고0 → 노출해제 → 임시보관 3단 삭제.

        GoodsDelete 는 물리삭제가 아니라 '임시보관' 이라, 이것만 부르면
        패플에서 계속 팔릴 수 있다. 앞 두 단계가 실제로 판매를 멈춘다.
        중간 단계가 실패해도 다음 단계는 계속 진행하되, 실패를 전부 모아
        최종 success 에 반영한다 — 재고·노출이 남은 '유령'을 성공으로 박제하지 않는다.
        """
        failures: list[str] = []

        # 호출측 dict 를 오염시키지 않게 얕은 복사로 재고 0 을 만든다
        zeroed = [{**o, "stock": 0} for o in (options or [])]
        rows = build_scm_option_upt(
            item_id,
            {option_key(o): o["opt_id"] for o in zeroed if o.get("opt_id")},
            zeroed,
            update_price=False,
        )
        skipped = len(zeroed) - len(rows)
        if skipped > 0:
            # 매핑 없는 옵션은 재고0 요청이 못 나가 패플에서 계속 팔린다
            failures.append(f"옵션 {skipped}건 재고0 미전송(OptID 매핑 없음)")

        # 옵션 정보가 없어도 3단 순서는 지킨다 (재고0 요청 1건으로 단계를 표시)
        fallback = [{"ItemId": str(item_id), "StockQty": 0, "IsOptionPriceUpdate": 0}]
        stock_fail = 0
        for row in rows or fallback:
            try:
                stock_resp = await client.call("scm_option_upt", row)
                if not is_ok(stock_resp):
                    stock_fail += 1
            except Exception as e:
                logger.warning(f"[패션플러스] 삭제 1단(재고0) 실패(계속 진행): {e}")
                stock_fail += 1
        if stock_fail:
            failures.append(f"1단(재고0) 실패 {stock_fail}건")

        try:
            dsp_resp = await client.call(
                "goods_dsp", {"ItemID": item_id, "DisplayYN": "N"}
            )
            if not is_ok(dsp_resp):
                failures.append(
                    f"2단(노출해제) 실패: "
                    f"{dsp_resp.get('Message') or dsp_resp.get('Status')}"
                )
        except Exception as e:
            logger.warning(f"[패션플러스] 삭제 2단(노출해제) 실패(계속 진행): {e}")
            failures.append("2단(노출해제) 실패")

        resp = await client.call("goods_delete", {"ItemID": item_id})
        if not is_ok(resp):
            failures.append(
                f"3단(임시보관) 실패: {resp.get('Message') or resp.get('Status')}"
            )
            return _fail(
                "패션플러스 삭제 실패: " + " · ".join(failures),
                str(resp.get("Status", "")),
            )
        if failures:
            # 3단(임시보관)은 됐지만 앞 단계가 남아 패플에 살아있을 수 있다
            return _fail("패션플러스 삭제 미완료: " + " · ".join(failures))
        return {"success": True, "message": "패션플러스 삭제 완료(임시보관)"}

    async def delete(self, session, product_no: str, account) -> dict[str, Any]:
        client = self._build_client(account)
        if client is None:
            return _fail("패션플러스 인증정보(custCode) 없음")
        return await self.delete_with_client(client, product_no, options=[])

    async def test_auth(self, session, account) -> bool:
        """GoodsQry 1건으로 인증 통과 여부만 확인한다."""
        client = self._build_client(account)
        if client is None:
            return False
        try:
            resp = await client.call("goods_qry", {"ItemNo": "__auth_probe__"})
        except Exception as e:
            logger.warning(f"[패션플러스] 인증 테스트 실패: {e}")
            return False
        # 인증이 통과하면 '없는 상품' 응답이 온다. 인증 실패만 False.
        return classify_error(str(resp.get("Status", ""))) != "auth_failed"
