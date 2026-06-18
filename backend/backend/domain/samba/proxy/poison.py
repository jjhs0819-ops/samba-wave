"""POIZON(得物 Dewu) 오픈 플랫폼 셀러 API 클라이언트 — httpx 기반.

공식 문서:
- 워크플로우: https://open.poizon.com/doc/list/documentationDetail/15
- 인증/서명: https://open.poizon.com/doc/list/documentationDetail/9 (Step 4)

POIZON은 KREAM과 동일한 카탈로그형 리셀 마켓이다.
1. 브랜드 공식품번(article number)으로 카탈로그 SKU를 조회해 globalSkuId를 얻고
2. 사이즈별로 Manual Listing(Ship-to-verify) 판매 등록을 한다.

인증은 app_key + app_secret 기반 MD5 서명 방식 (access_token 불필요).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any
from urllib.parse import quote_plus

import httpx

from backend.utils.logger import logger


class PoisonClient:
    """POIZON 셀러 오픈 API 클라이언트 (카탈로그 조회 + 판매 등록)."""

    BASE = "https://open.poizon.com"
    # 브랜드 공식품번 → 카탈로그 SKU(globalSkuId) 조회
    PATH_SKU_BY_ARTICLE = "/dop/api/v1/pop/api/v1/intl-commodity/intl/sku/sku-basic-info/by-article-number"
    # Manual Listing (Ship-to-verify) — 사이즈별 판매 등록
    PATH_MANUAL_LISTING = "/dop/api/v1/pop/api/v1/submit-bid/normal-autonomous-bidding"
    # 입찰가/재고 수정 (Update Manual Listing)
    PATH_UPDATE_LISTING = "/dop/api/v1/pop/api/v1/update-bid/normal-autonomous-bidding"
    # 입찰 취소 (Cancel Listing)
    PATH_CANCEL_LISTING = "/dop/api/v1/pop/api/v1/cancel-bid/cancel-bidding"
    # 추천 입찰가(최저가) 조회
    PATH_RECOMMEND_PRICE = "/dop/api/v1/pop/api/v1/recommend-bid/price"

    # POIZON sizeType 허용값
    _ALLOWED_SIZE_TYPES = {"EU", "US", "UK", "CN", "JP"}

    def __init__(
        self,
        app_key: str,
        app_secret: str,
        *,
        language: str = "ko",
        time_zone: str = "Asia/Seoul",
        region: str = "KR",
        currency: str = "KRW",
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.language = language
        self.time_zone = time_zone
        self.region = region  # 셀러 출고지 (KR)
        self.currency = currency

    # ------------------------------------------------------------------
    # 서명 (공식 Python 알고리즘 포팅)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_str(obj: Any, is_sub: bool = False) -> str:
        """서명용 값 직렬화 — 중첩 list/dict 지원 (공식 getStr 포팅)."""
        if isinstance(obj, bool):
            # JSON 직렬화와 동일하게 소문자 (str(False)='False' 불일치 방지)
            return "true" if obj else "false"
        if isinstance(obj, (list, tuple)):
            if obj and isinstance(obj[0], str):
                return ",".join(str(x) for x in obj)
            value_str = ",".join(PoisonClient._get_str(x, True) for x in obj)
            return f"[{value_str}]" if is_sub else value_str
        if isinstance(obj, dict):
            inner = ""
            for sub_key in sorted(obj.keys()):
                inner += (
                    f'"{sub_key}":' + PoisonClient._get_str(obj[sub_key], True) + ","
                )
            return "{" + inner[:-1] + "}"
        if isinstance(obj, str) and is_sub:
            return f'"{obj}"'
        return str(obj)

    def _sign(self, params: dict[str, Any]) -> str:
        """전송 필드 전체 → MD5 32자 대문자 서명.

        키를 ASCII 오름차순 정렬 → URL 인코딩한 k=v&... 문자열 끝에
        app_secret을 붙여 MD5 후 대문자로 변환한다. 빈 값은 서명에서 제외.
        """
        sign_str = ""
        for key in sorted(params.keys()):
            value = params[key]
            if value is None or value == "":
                continue
            value_str = quote_plus(self._get_str(value), encoding="utf-8")
            sign_str += f"{key}={value_str}&"
        sign_str = sign_str[:-1] + self.app_secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    async def _post(self, path: str, business: dict[str, Any]) -> dict[str, Any]:
        """공통 파라미터(app_key/timestamp/sign) 주입 후 POST 요청."""
        import time as _time

        params: dict[str, Any] = {
            k: v for k, v in business.items() if v is not None and v != ""
        }
        params["app_key"] = self.app_key
        params["timestamp"] = int(_time.time() * 1000)
        params["sign"] = self._sign(params)

        url = f"{self.BASE}{path}"
        timeout = httpx.Timeout(20.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, json=params, headers={"Content-Type": "application/json"}
            )
        try:
            return resp.json()
        except Exception:
            return {"code": resp.status_code, "message": resp.text[:300]}

    # ------------------------------------------------------------------
    # 카탈로그 조회
    # ------------------------------------------------------------------

    async def query_sku_by_article_number(
        self, article_number: str, region: str | None = None
    ) -> list[dict[str, Any]]:
        """브랜드 공식품번으로 카탈로그 SKU 조회 → 사이즈별 globalSkuId 목록.

        Returns: [{globalSkuId, skuId, sizeValue, sizeCandidates}]
        """
        business = {
            "articleNumber": article_number,
            "region": region or self.region,
            "language": self.language,
        }
        data = await self._post(self.PATH_SKU_BY_ARTICLE, business)
        if data.get("code") != 200:
            logger.warning(
                f"[POIZON] SKU 조회 실패: {article_number} → "
                f"code={data.get('code')} msg={data.get('msg') or data.get('message')}"
            )
            return []

        results: list[dict[str, Any]] = []
        for spu in data.get("data") or []:
            for sku in spu.get("skuInfoList") or []:
                global_sku_id = sku.get("globalSkuId")
                if not global_sku_id:
                    continue
                # 사이즈 후보 추출 (regionSalePvInfoList의 Size 속성 sizeInfos)
                size_candidates: dict[str, str] = {}
                rep_size = ""
                for pv in sku.get("regionSalePvInfoList") or []:
                    for si in pv.get("sizeInfos") or []:
                        size_key = (si.get("sizeKey") or "").strip()
                        size_val = (si.get("value") or "").strip()
                        if size_key and size_val:
                            size_candidates[size_key] = size_val
                    # level==2 가 사이즈 속성 (level1=색상, level3=구성)
                    if pv.get("level") == 2 and pv.get("value"):
                        rep_size = str(pv.get("value")).strip()
                results.append(
                    {
                        "globalSkuId": int(global_sku_id),
                        "skuId": int(sku["skuId"]) if sku.get("skuId") else None,
                        "sizeValue": rep_size,
                        "sizeCandidates": size_candidates,
                    }
                )
        return results

    # ------------------------------------------------------------------
    # 판매 등록 (Manual Listing — Ship-to-verify)
    # ------------------------------------------------------------------

    async def manual_listing(
        self,
        *,
        global_sku_id: int,
        price: int,
        quantity: int,
        size_type: str | None = None,
        country_code: str = "KR",
        currency: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Manual Listing (Ship-to-verify) — 사이즈별 판매 등록.

        price 는 통화 최소단위 정수 (KRW=원). 응답에서 sellerBiddingNo 추출.
        """
        business: dict[str, Any] = {
            "language": self.language,
            "timeZone": self.time_zone,
            "countryCode": country_code,
            "deliveryCountryCode": country_code,
            "currency": currency or self.currency,
            "price": int(price),
            "quantity": int(quantity),
            "refererSource": "pop",
            "requestId": request_id or str(uuid.uuid4()),
            "globalSkuId": int(global_sku_id),
        }
        if size_type and size_type.upper() in self._ALLOWED_SIZE_TYPES:
            business["sizeType"] = size_type.upper()

        data = await self._post(self.PATH_MANUAL_LISTING, business)
        if data.get("code") == 200:
            payload = data.get("data") or {}
            return {
                "success": True,
                "sellerBiddingNo": str(payload.get("sellerBiddingNo") or ""),
                "message": payload.get("tips") or "POIZON 등록 진행 중",
                "data": data,
            }
        return {
            "success": False,
            "message": (
                data.get("msg")
                or data.get("message")
                or f"POIZON 등록 실패(code={data.get('code')})"
            ),
            "data": data,
        }

    # ------------------------------------------------------------------
    # 입찰 수정 / 취소 / 최저가 조회 (오토튠 변동 대응용)
    # ------------------------------------------------------------------

    async def update_listing(
        self,
        *,
        seller_bidding_no: str,
        price: int,
        quantity: int,
        global_sku_id: int | None = None,
        old_quantity: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """기존 입찰(sellerBiddingNo)의 가격/재고 수정 (Update Manual Listing).

        price 는 통화 최소단위 정수 (KRW=원).
        """
        business: dict[str, Any] = {
            "requestId": request_id or str(uuid.uuid4()),
            "sellerBiddingNo": str(seller_bidding_no),
            "price": int(price),
            "quantity": int(quantity),
        }
        if global_sku_id is not None:
            business["globalSkuId"] = int(global_sku_id)
        if old_quantity is not None:
            business["oldQuantity"] = int(old_quantity)

        data = await self._post(self.PATH_UPDATE_LISTING, business)
        if data.get("code") == 200:
            return {"success": True, "message": "POIZON 입찰 수정 완료", "data": data}
        return {
            "success": False,
            "message": (
                data.get("msg")
                or data.get("message")
                or f"POIZON 입찰 수정 실패(code={data.get('code')})"
            ),
            "data": data,
        }

    async def cancel_listing(self, seller_bidding_no: str) -> dict[str, Any]:
        """입찰 취소 (Cancel Listing) — sellerBiddingNo 단일 필드."""
        data = await self._post(
            self.PATH_CANCEL_LISTING, {"sellerBiddingNo": str(seller_bidding_no)}
        )
        if data.get("code") == 200:
            return {"success": True, "message": "POIZON 입찰 취소 완료", "data": data}
        return {
            "success": False,
            "message": (
                data.get("msg")
                or data.get("message")
                or f"POIZON 입찰 취소 실패(code={data.get('code')})"
            ),
            "data": data,
        }

    async def recommend_price(
        self,
        *,
        global_sku_id: int,
        bidding_type: int = 20,
        currency: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """추천 입찰가(최저/평균/최고) 조회 — 경쟁가 정책용.

        Returns: {success, minPrice, averagePrice, maxPrice, data}
        biddingType: 20(일반판매/예약판매), 27(직배송), 25(보관판매).
        """
        business: dict[str, Any] = {
            "globalSkuId": int(global_sku_id),
            "biddingType": int(bidding_type),
            "currency": currency or self.currency,
            "region": region or self.region,
        }
        data = await self._post(self.PATH_RECOMMEND_PRICE, business)
        if data.get("code") != 200:
            logger.warning(
                f"[POIZON] 추천가 조회 실패: globalSkuId={global_sku_id} "
                f"code={data.get('code')} msg={data.get('msg') or data.get('message')}"
            )
            return {"success": False, "data": data}
        payload = data.get("data") or {}
        return {
            "success": True,
            "minPrice": payload.get("minPrice"),
            "averagePrice": payload.get("averagePrice"),
            "maxPrice": payload.get("maxPrice"),
            "data": payload,
        }
