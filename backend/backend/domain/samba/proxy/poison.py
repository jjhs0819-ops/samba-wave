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
import math
import os
import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import httpx

from backend.utils.logger import logger

# ── 구매자 취소가능 창 ────────────────────────────────────────────────────
# POIZON 은 결제 후 1시간 동안 구매자가 자유롭게 취소할 수 있다. 이 창 안의
# 주문을 삼바에 미리 수집하면 곧바로 취소돼 유령 주문이 남으므로, 수집 경로
# (order_sync·주문폴러)는 창이 지난 주문만 받는다. 시계 오차·경계 대비 여유
# 10분을 더한 70분이 기본값.
POISON_CANCEL_WINDOW_MIN = int(os.environ.get("POISON_CANCEL_WINDOW_MIN", "70"))

# 포이즌 한국 판매수수료 (신발·의류 기준: 요율 10%, 건당 최저 15,000 / 최대 45,000)
# 가방·시계·주얼리는 14%·최저 18,000 이므로 해당 품목을 올릴 땐 정책에서 덮어써야 한다.
POISON_FEE_RATE = float(os.environ.get("POISON_FEE_RATE", "0.10"))
POISON_FEE_MIN = int(os.environ.get("POISON_FEE_MIN", "15000"))
POISON_FEE_MAX = int(os.environ.get("POISON_FEE_MAX", "45000"))
# 건당 순이익 하한(원) — 이 금액을 못 넘기면 등록하지 않는다
POISON_MIN_PROFIT = int(os.environ.get("POISON_MIN_PROFIT", "10000"))


def extract_credentials(account: Any) -> tuple[str, str]:
    """계정에서 app_key/app_secret 을 꺼낸다.

    저장 필드명이 경로마다 달라(appKey/apiKey/app_key, 최상위 api_key) 등록은 되는데
    주문 폴러·송장 전송만 조용히 실패하는 사고가 있었다. 세 경로가 이 함수를 쓴다.
    """
    if account is None:
        return "", ""
    extras = getattr(account, "additional_fields", None)
    if not isinstance(extras, dict):
        extras = {}
    key = (
        extras.get("appKey")
        or extras.get("apiKey")
        or extras.get("app_key")
        or getattr(account, "api_key", "")
        or ""
    )
    secret = (
        extras.get("appSecret")
        or extras.get("apiSecret")
        or extras.get("app_secret")
        or getattr(account, "api_secret", "")
        or ""
    )
    return str(key), str(secret)


# 소싱처가 공식 품번 뒤에 내부코드를 덧붙여 저장하는 경우가 있다
# (KR7598_S_K, KE0662_K). 포이즌은 정확 일치만 지원해서 그대로 조회하면 통째로
# 미매칭이 된다 — 실측에서 아디다스 오리지널 2,564건이 여기 걸렸다.
_ARTICLE_SUFFIX = re.compile(r"(_[A-Z0-9]{1,4})+$")
_ARTICLE_MIN_LEN = 6


def article_number_candidates(style_code: str | None) -> list[str]:
    """조회에 시도할 품번 후보 — 원본 먼저, 접미사를 뗀 정제본을 그 다음.

    정제본이 너무 짧아지면(품번으로 보기 어려우면) 후보에서 뺀다.
    """
    s = (style_code or "").strip().upper()
    if not s:
        return []
    out = [s]
    cleaned = _ARTICLE_SUFFIX.sub("", s)
    if cleaned != s and len(cleaned) >= _ARTICLE_MIN_LEN:
        out.append(cleaned)
    return out


def poizon_fee(
    price: float,
    rate: float = POISON_FEE_RATE,
    fee_min: int = POISON_FEE_MIN,
    fee_max: int = POISON_FEE_MAX,
) -> float:
    """포이즌이 떼는 실제 판매수수료. 정률이지만 최저·최대가 걸린다."""
    return min(max(price * rate, fee_min), fee_max)


@dataclass
class BidDecision:
    """게이트 판정 결과."""

    price: int = 0
    skipped: bool = False
    reason: str = ""
    lowered: bool = False  # 시장가에 맞춰 목표가를 내렸는지


def _min_price_for_profit(
    cost: float,
    min_profit: int,
    rate: float = POISON_FEE_RATE,
    fee_min: int = POISON_FEE_MIN,
    fee_max: int = POISON_FEE_MAX,
) -> int:
    """순이익 min_profit 을 확보하는 최소 판매가.

    수수료가 구간함수(최저/정률/최대)라 구간별로 후보를 구해 실제로 성립하는 값을 쓴다.
    """
    # ① 최저수수료 구간: p - fee_min - cost = min_profit
    cand = cost + fee_min + min_profit
    if cand * rate <= fee_min:
        return math.ceil(cand)
    # ② 정률 구간: p - p*rate - cost = min_profit
    cand = (cost + min_profit) / (1 - rate)
    if cand * rate <= fee_max:
        return math.ceil(cand)
    # ③ 최대수수료 구간: p - fee_max - cost = min_profit
    return math.ceil(cost + fee_max + min_profit)


def decide_bid_price(
    *,
    cost: float,
    target: float,
    market: float | None,
    own_price: float | None = None,
    min_profit: int = POISON_MIN_PROFIT,
    rate: float = POISON_FEE_RATE,
    fee_min: int = POISON_FEE_MIN,
    fee_max: int = POISON_FEE_MAX,
    unit: int = 1,
) -> BidDecision:
    """등록가 결정 — 노출 우선, 순이익 하한 방어.

    포이즌은 입찰 경쟁이라 시장 최저가보다 비싸면 노출조차 되지 않는다. 그래서
    정책이 계산한 목표가가 시장가보다 높으면 **시장가까지 내려서라도 등록**한다
    (마진율이 낮아지는 것은 감수 — 노출이 우선). 다만 시장가로 팔아도 순이익이
    하한에 못 미치면 팔수록 손해이므로 그때는 등록하지 않는다.

    시세가 없으면(입찰 경쟁자 없음) 목표가를 그대로 쓰되 하한은 지킨다.

    unit: 등록가 배수 단위(KRW=1000). 하한은 올림, 상한은 내림해서 단위 보정 뒤에도
    "시장가 이하 + 최소이익 이상"이 동시에 성립하게 한다.
    """
    cost = float(cost or 0)
    if cost <= 0:
        return BidDecision(skipped=True, reason="원가 없음")

    unit = max(int(unit or 1), 1)

    # 자기참조 차단 — 포이즌 시세 API 는 내 입찰을 빼주지 않는다. 내가 최저가면
    # 조회된 "시장 최저가"가 곧 내 가격이라, 그걸 또 시장가로 믿고 맞추면 갱신할수록
    # 값이 내려가는 하향 나선이 생긴다(실측 20건 중 12건이 이 상태였다).
    #
    # 이때 목표가로 올려버리면 실제로는 다른 셀러와 동률이었던 경우 노출을 잃는다.
    # 동률인지 나 혼자인지는 시세만으로 구분할 수 없으므로 **현재 가격을 유지**한다.
    # 하한(최소이익)만 확인해서, 원가가 올라 하한을 깨면 그때만 하한까지 올린다.
    if own_price and market and int(market) == int(own_price):
        floor_now = _min_price_for_profit(cost, min_profit, rate, fee_min, fee_max)
        floor_now = -(-floor_now // unit) * unit
        keep = max(int(own_price), floor_now)
        return BidDecision(
            price=keep,
            reason=(
                "현재가 유지(내 입찰이 최저가)"
                if keep == int(own_price)
                else "원가 상승 — 최소이익 하한으로 상향"
            ),
        )
    floor = _min_price_for_profit(cost, min_profit, rate, fee_min, fee_max)
    floor = -(-floor // unit) * unit  # 올림 — 보정 후에도 최소이익 유지

    if not market or market <= 0:
        price = max(-(-int(math.ceil(target)) // unit) * unit, floor)
        return BidDecision(price=price, reason="시세 없음(경쟁자 없음) — 목표가 적용")

    cap = (int(market) // unit) * unit  # 내림 — 보정 후에도 시장가 이하 유지
    if floor > cap:
        return BidDecision(
            skipped=True,
            reason=(
                f"시장가({cap:,})로 팔아도 최소이익 {min_profit:,}원 미달 "
                f"(필요 {floor:,})"
            ),
        )

    target_u = -(-int(math.ceil(target)) // unit) * unit
    price = min(target_u, cap)
    lowered = price < target_u
    if price < floor:
        price = floor
    return BidDecision(
        price=price,
        lowered=lowered,
        reason="시장가 맞춤" if lowered else "목표가 적용",
    )

# 취소/거래실패 상태 코드 하한 — 7000/8000/8010/8080 (order.py 상태맵과 동일 기준)
_CANCELED_STATUS_MIN = 7000


def is_canceled(order: dict[str, Any]) -> bool:
    """주문이 이미 취소/거래실패 상태(order_status 7000 이상)인지."""
    try:
        return int(order.get("order_status") or 0) >= _CANCELED_STATUS_MIN
    except (TypeError, ValueError):
        return False


def is_buyer_cancelable(order: dict[str, Any], window_min: int | None = None) -> bool:
    """주문이 아직 구매자 취소가능 창(결제 후 1시간) 안인지 판정.

    - order_status 1000(결제대기): 결제 전 → 항상 취소가능으로 본다.
    - 이미 취소된 주문(7000 이상)은 창 판정 대상이 아니다(False) — 수집 여부는
      호출부가 is_canceled 로 별도 판단.
    - pay_time("yyyy-MM-dd HH:mm:ss", 셀러 타임존 KST)이 window_min 분 이내면 True.
    - pay_time 이 없거나 파싱 불가면 기존 동작 유지(False → 수집).
    """
    from datetime import datetime, timedelta, timezone

    win = POISON_CANCEL_WINDOW_MIN if window_min is None else window_min
    try:
        status = int(order.get("order_status") or 0)
    except (TypeError, ValueError):
        status = 0
    if status == 1000:
        return True
    if status >= _CANCELED_STATUS_MIN:
        return False
    raw = str(order.get("pay_time") or "").strip()
    if not raw:
        return False
    kst = timezone(timedelta(hours=9))
    try:
        paid = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=kst)
    except ValueError:
        return False
    return datetime.now(tz=kst) - paid < timedelta(minutes=win)


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
    # 일괄 조회 — 사이즈별 시세를 상품당 1회로 받는다 (rate limit 절약)
    PATH_RECOMMEND_BATCH = "/dop/api/v1/pop/api/v1/recommend-bid/batchPrice"
    # 주문 목록 조회 (Order List — generic_list, create_time 범위 최대 7일)
    PATH_ORDER_LIST = "/dop/api/v1/pop/api/v2/order/generic_list"
    # 내 입찰(listing) 목록 조회 (Query Listing List — offset 페이징)
    PATH_QUERY_LISTING = "/dop/api/v1/pop/api/v1/retrieve-bid/general-type-bidding-list"

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

    async def query_sku_by_article_number_any(
        self, style_code: str, region: str | None = None
    ) -> tuple[list[dict[str, Any]], str]:
        """품번 후보를 순서대로 시도 — (SKU목록, 실제로 맞은 품번).

        소싱처가 붙인 접미사(KR7598_S_K) 때문에 원본으로는 못 찾는 상품이 많다.
        원본 → 접미사 제거본 순으로 시도하고, 어느 품번이 맞았는지 함께 돌려준다.
        """
        for cand in article_number_candidates(style_code):
            skus = await self.query_sku_by_article_number(cand, region)
            if skus:
                return skus, cand
        return [], ""

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

    async def query_listing_page(
        self,
        *,
        bidding_type: int = 20,
        trade_status: int | None = 2,
        offset_id: int = 0,
        page_size: int = 100,
        region: str | None = None,
        spu_id: int | None = None,
    ) -> dict[str, Any]:
        """내 입찰(listing) 목록 1페이지 조회 (Query Listing List).

        tradeStatus: 0=거래중 / 1=취소 / 2=등록성공(활성) / 3=품절.
        실계정 검증(2026-08-01): 활성 입찰은 tradeStatus=2 로 조회된다(0은 빈 목록).
        페이징: exclusiveStartOffsetId 0 시작 → 응답 lastOffsetId 를 다음 호출에 전달.
        Returns: {"list": [...], "lastOffsetId": int} (실패 시 빈 값)
        """
        biz: dict[str, Any] = {
            "language": self.language,
            "timeZone": self.time_zone,
            "biddingType": int(bidding_type),
            "region": region or self.region,
            "exclusiveStartOffsetId": int(offset_id),
            "pageSize": int(page_size),
        }
        if trade_status is not None:
            biz["tradeStatus"] = int(trade_status)
        # spuId 필터 — full 엔드포인트에서만 동작(simple 은 무시함, 2026-08-02 실측)
        if spu_id is not None:
            biz["spuId"] = int(spu_id)
        data = await self._post(self.PATH_QUERY_LISTING, biz)
        if data.get("code") != 200:
            return {"list": [], "lastOffsetId": 0, "error": data}
        d = data.get("data") or {}
        return {
            "list": d.get("list") or [],
            "lastOffsetId": int(d.get("lastOffsetId") or 0),
        }

    async def recommend_price_batch(
        self,
        *,
        global_sku_ids: list[int],
        bidding_type: int = 20,
        currency: str | None = None,
        region: str | None = None,
        chunk: int = 20,
    ) -> dict[int, dict[str, Any]]:
        """추천가 일괄 조회 — {globalSkuId: 파싱결과}.

        사이즈(SKU)마다 시세가 다르므로 등록 전 게이트는 사이즈별 시세가 필요하다.
        단건으로 돌면 상품당 옵션 수만큼 호출이 나가 rate limit(일 20,000)을 넘기므로
        일괄 조회로 상품당 1~2회에 끝낸다.
        """
        out: dict[int, dict[str, Any]] = {}
        ids = [int(i) for i in global_sku_ids if i]
        for i in range(0, len(ids), chunk):
            part = ids[i : i + chunk]
            data = await self._post(
                self.PATH_RECOMMEND_BATCH,
                {
                    "globalSkuIdList": part,
                    "biddingType": int(bidding_type),
                    "currency": currency or self.currency,
                    "region": region or self.region,
                },
            )
            if data.get("code") != 200:
                logger.warning(
                    f"[POIZON] 추천가 일괄조회 실패 code={data.get('code')} "
                    f"msg={data.get('msg') or data.get('message')} n={len(part)}"
                )
                continue
            for row in data.get("data") or []:
                gid = row.get("globalSkuId")
                if gid:
                    out[int(gid)] = self.parse_recommend_payload(row)
        return out

    @staticmethod
    def parse_recommend_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """추천가 응답(data)에서 시세를 뽑는다.

        문서상 minPrice/averagePrice/maxPrice 는 '최근 30일 거래가'라 거래 이력이
        없는 SKU 에서는 응답에서 통째로 빠진다(대부분의 신상/비인기 상품). 그때는
        시장 최저 호가(global/asia/local)와 백분위 구간(priceRangeItems)으로 대체해야
        None 이 되지 않는다.

        경쟁 입찰 기준가는 '실거래가'가 아니라 '내가 이겨야 할 호가'이므로
        globalMinPrice → asiaMinPrice → localMinPrice → 백분위 최저 순으로 채운다.
        """
        prices = sorted(
            int(it["price"])
            for it in (payload.get("priceRangeItems") or [])
            if it.get("price") is not None
        )
        min_price = (
            payload.get("globalMinPrice")
            or payload.get("asiaMinPrice")
            or payload.get("localMinPrice")
            or (prices[0] if prices else None)
        )
        avg_price = payload.get("averagePrice") or (
            prices[len(prices) // 2] if prices else None  # 중간값(≈50% 구간)
        )
        max_price = payload.get("maxPrice") or (
            prices[-1] if prices else None  # 상위(≈90% 구간)
        )
        return {
            "minPrice": min_price,
            "averagePrice": avg_price,
            "maxPrice": max_price,
            # 원본 스펙 필드 — 정책에서 시장별로 골라 쓸 수 있게 그대로 노출
            "globalMinPrice": payload.get("globalMinPrice"),
            "asiaMinPrice": payload.get("asiaMinPrice"),
            "localMinPrice": payload.get("localMinPrice"),
            # 이 가격 이하라야 노출된다는 플랫폼 기준가
            "effectiveExposurePrice": payload.get("effectiveExposurePrice"),
            # {백분위: 가격} — 예: {10: 65000, 50: 92000, 90: 144000}
            "priceRanges": {
                int(it["percentValue"]): int(it["price"])
                for it in (payload.get("priceRangeItems") or [])
                if it.get("price") is not None and it.get("percentValue") is not None
            },
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

        Returns: {success, minPrice, averagePrice, maxPrice, globalMinPrice,
                  asiaMinPrice, localMinPrice, effectiveExposurePrice,
                  priceRanges, data}
        biddingType: 20(일반판매/예약판매), 27(직배송), 25(보관판매).
        가격 단위는 통화 최소단위 정수 (KRW/JPY=원·엔 그대로, 그 외는 1/100).
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
        return {"success": True, **self.parse_recommend_payload(payload), "data": payload}

    # ------------------------------------------------------------------
    # 주문 조회 (Order List — 삼바 주문 수집용)
    # ------------------------------------------------------------------

    async def get_orders(
        self,
        days: int = 7,
        *,
        order_status: int | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """최근 N일(최대 7일) 주문 목록 조회 — generic_list, 페이징 자동 순회.

        POIZON generic_list 는 create_time 범위가 최대 7일. start/end 미지정 시
        셀러 타임존 기준 최근 N일. order_status 미지정 시 전체 상태 조회.
        Returns: 주문 dict 리스트(order_no/article_number/seller_bidding_no/
        order_status/pay_time/properties/qty/delivery_* 등 포함).
        """
        from datetime import datetime, timedelta
        from datetime import timezone as _tz

        kst = _tz(timedelta(hours=9))
        now = datetime.now(tz=kst)
        span = min(max(days, 1), 7)
        end_created = now.strftime("%Y-%m-%d %H:%M:%S")
        start_created = (now - timedelta(days=span)).strftime("%Y-%m-%d %H:%M:%S")

        all_orders: list[dict[str, Any]] = []
        page_no = 1
        while page_no <= 100:  # 안전 상한
            business: dict[str, Any] = {
                "language": self.language,
                "timeZone": self.time_zone,
                "start_created": start_created,
                "end_created": end_created,
                "page_no": page_no,
                "page_size": page_size,
                "order_by_create_time_desc": True,
            }
            if order_status is not None:
                business["order_status"] = order_status
            data = await self._post(self.PATH_ORDER_LIST, business)
            if data.get("code") != 200:
                logger.warning(
                    f"[POIZON] 주문조회 실패 page={page_no} "
                    f"code={data.get('code')} "
                    f"msg={data.get('msg') or data.get('message')}"
                )
                break
            d = data.get("data") or {}
            orders = d.get("orders") or []
            all_orders.extend(orders)
            total = int(d.get("total_results") or 0)
            if not orders or page_no * page_size >= total:
                break
            page_no += 1
        return all_orders

    async def get_delivery_carriers(
        self, region: str = "KR", delivery_type: str = "OFFLINE_EXPRESS_DELIVERY"
    ) -> list[dict[str, Any]]:
        """지원 택배사 목록 조회 ([197]). Returns: [{carrier:int, carrierName:str}]."""
        data = await self._post(
            "/dop/api/v1/pop/api/v1/order/support/delivery/carrier",
            {"region": region, "deliveryType": delivery_type},
        )
        if data.get("code") != 200:
            logger.warning(
                f"[POIZON] 택배사 조회 실패 code={data.get('code')} "
                f"msg={data.get('msg') or data.get('message')}"
            )
            return []
        return (data.get("data") or {}).get("carrierItems") or []

    async def ship_order(
        self,
        order_no_list: list[str],
        express_no: str,
        *,
        carrier: int | None = None,
        carrier_name: str | None = None,
        region: str = "KR",
        delivery_type: str = "OFFLINE_EXPRESS_DELIVERY",
    ) -> dict[str, Any]:
        """주문 발송 처리 ([100] Ship Order) — 송장번호 전송.

        order_no_list 가 배열이라 합배송(여러 주문 + 송장 1개)을 그대로 지원.
        carrier(코드)와 carrier_name(문자열)은 둘 중 하나만 보내야 한다.
        Returns: 원본 응답 dict (code/msg/data.success_order_no_list 등).
        """
        business: dict[str, Any] = {
            "order_no_list": list(order_no_list),
            "express_no": express_no,
            "delivery_region": region,
            "delivery_type": delivery_type,
        }
        if carrier is not None:
            business["carrier"] = carrier
        elif carrier_name:
            business["carrierName"] = carrier_name
        return await self._post("/dop/api/v1/pop/api/v1/order/delivery", business)
