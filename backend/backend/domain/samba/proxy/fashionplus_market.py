"""패션플러스 판매마켓 API 클라이언트.

전 API 가 POST + JSON 이고 응답은 {"Status": "OK"|"Err-XXX-###", "Message": ...} 로 통일돼 있다.
인증키는 서버 발급이 아니라 CustCode 로 매 호출 로컬 생성한다(fashionplus_auth 참조).

문서: https://api.fashionplus.co.kr/api/help/api2/help/APIIntroduce.asp
"""

from __future__ import annotations

import os
from typing import Any

import httpx

from backend.domain.samba.proxy.fashionplus_auth import build_api_key
from backend.utils.logger import logger

FP_REAL_BASE = "https://api2.fashionplus.co.kr/api/json"
FP_TEST_BASE = "https://tst-api.fashionplus.co.kr/api/json"

# 논리명 → 패플 Op 경로
FP_OPS: dict[str, str] = {
    # 상품
    "goods_add": "GoodsAdd",
    "option_add": "OptionAdd",
    "goods_upt": "GoodsUpt",
    "option_upt": "OptionUpt",
    "scm_option_upt": "ScmOptionUpt",
    "scm_price_chg": "ScmPriceChg",
    "goods_dsp": "GoodsDsp",
    "goods_dsp_batch": "GoodsDsp_batch",
    "goods_delete": "GoodsDelete",
    "goods_qry": "GoodsQry",
    "option_qry": "OptionQry",
    # 브랜드·발송처
    "brand_list": "BrandList",
    "sender_add": "SenderAdd",
    "sender_upt": "SenderUpt",
    # 주문·배송
    "delivery_list": "DeliveryList",
    "delivery_proc": "DeliveryProc",
    "invoice_proc": "InvoiceProc",
    "out_of_stock_proc": "OutOfStockProc",
    "order_cancel_list": "OrderCancelList",
    "order_cancel_proc": "OrderCancelProc",
    # 반품·교환
    "recall_list": "RecallList",
    "recall_approval": "RecallApproval",
    "exchange_list": "ExchangeList",
    "exchange_invoice": "ExchangeInvoice",
    # 정산
    "bi_reckoning_sales": "BiReckoningSales",
}

# ── 미확정: 인증값을 body 에 넣는지 헤더에 넣는지 패플 회신 대기 중 ──
# 회신이 오면 이 상수 하나만 "header" 로 바꾸면 전 호출에 반영된다.
AUTH_PLACEMENT = os.environ.get("FASHIONPLUS_AUTH_PLACEMENT", "body")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def endpoint(op: str, use_test: bool = False) -> str:
    """논리명으로 전체 URL 을 만든다. 모르는 op 은 KeyError 로 즉시 터뜨린다."""
    base = FP_TEST_BASE if use_test else FP_REAL_BASE
    return f"{base}/{FP_OPS[op]}"


def extract_credentials(account: Any) -> tuple[str, str]:
    """계정에서 (CustCode, PartnerLoginID) 를 꺼낸다.

    저장 필드명이 경로마다 달라 등록만 되고 주문 폴러가 조용히 실패하는 사고가
    다른 마켓에서 반복됐다. 모든 경로가 이 함수 하나를 쓴다.
    """
    extras = getattr(account, "additional_fields", None) or {}
    cust = str(extras.get("custCode") or getattr(account, "api_key", "") or "")
    partner = str(extras.get("partnerLoginID") or getattr(account, "seller_id", "") or "")
    return cust, partner


def is_ok(payload: dict) -> bool:
    status = str(payload.get("Status") or payload.get("status") or "")
    return status.upper() == "OK"


def classify_error(status: str) -> str:
    """에러코드를 재시도 판단용 유형으로 분류한다."""
    s = (status or "").upper()
    # 인증 실패는 명시적 코드 프리픽스만 인정한다.
    # ("AUTH" 부분일치는 무관한 코드까지 인증실패로 오분류해 불필요한 재시도를 유발)
    if s.startswith("ERR-ADD-001") or s.startswith("ERR-AUTH-"):
        return "auth_failed"
    if s.startswith("ERR-DAT-") or s.startswith("ERR-UPT-"):
        return "validation"
    if s.startswith("ERR-IMG-"):
        return "image"
    if s.startswith("ERR-QRY-"):
        return "not_found"
    return "unknown"


class FashionPlusMarketClient:
    """패션플러스 판매마켓 클라이언트. 요청마다 인증키를 새로 만든다."""

    def __init__(
        self, cust_code: str, partner_login_id: str = "", use_test: bool = False
    ) -> None:
        self.cust_code = cust_code
        self.partner_login_id = partner_login_id
        self.use_test = use_test

    def build_body(self, payload: dict) -> dict:
        """요청 봉투 — 업무 파라미터에 인증값을 얹는다."""
        body = dict(payload)
        body["CustCode"] = self.cust_code
        body["ApiKey"] = build_api_key(self.cust_code)
        if self.partner_login_id:
            body["PartnerLoginID"] = self.partner_login_id
        return body

    def build_headers(self) -> dict:
        if AUTH_PLACEMENT != "header":
            return {"Content-Type": "application/json"}
        return {
            "Content-Type": "application/json",
            "CustCode": self.cust_code,
            "ApiKey": build_api_key(self.cust_code),
        }

    async def call(self, op: str, payload: dict) -> dict:
        """패플 API 1회 호출.

        인증 실패는 인증키의 시각 경계 문제일 수 있어 키 재생성 후 1회만 재시도한다.
        인증 실패 판정은 두 경로:
        ① HTTP 401/403 — 2회째에도 401/403 이면 httpx.HTTPStatusError 를 그대로 올린다
           (호출측이 계정/키 문제로 구분 처리할 수 있게 예외 전파를 택함).
        ② 응답 본문 Status 가 auth_failed 로 분류 — 2회째에도 실패면 그 실패 응답 dict 를
           그대로 반환한다(패플 규약상 Status/Message 가 실패 사유를 담고 있음).
        401/403 이 아닌 HTTP 에러는 재시도 없이 즉시 전파한다.
        """
        url = endpoint(op, self.use_test)
        data: dict = {}
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.post(
                        url, json=self.build_body(payload), headers=self.build_headers()
                    )
                    resp.raise_for_status()
                    data = resp.json()
            except httpx.HTTPStatusError as exc:
                # 401/403 만 인증 실패로 간주해 1회 재시도. 그 외 HTTP 에러는 그대로 전파.
                if exc.response.status_code not in (401, 403) or attempt == 2:
                    raise
                logger.warning(
                    f"[패션플러스] {op} HTTP {exc.response.status_code} 인증 실패 — 키 재생성 후 1회 재시도"
                )
                continue
            if is_ok(data) or classify_error(str(data.get("Status", ""))) != "auth_failed":
                return data
            if attempt == 1:
                logger.warning(f"[패션플러스] {op} 인증 실패 — 키 재생성 후 1회 재시도")
        return data
