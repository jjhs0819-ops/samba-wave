"""SambaWave Return DTOs."""

from typing import Optional

from pydantic import BaseModel


class ReturnCreate(BaseModel):
    order_id: str
    type: str  # return, exchange, cancel
    reason: Optional[str] = None
    description: Optional[str] = None
    quantity: int = 1
    requested_amount: Optional[float] = None


class ReturnRejectBody(BaseModel):
    reason: Optional[str] = None


class ReturnNoteBody(BaseModel):
    note: str


class ExchangeActionBody(BaseModel):
    """11번가 교환 처리 요청 DTO."""

    action: str  # "approve" | "reject"
    # 11번가 클레임 식별자 (approve/reject 시 필수)
    clm_req_seq: Optional[str] = None
    ord_no: Optional[str] = None
    ord_prd_seq: Optional[str] = None
    reason: Optional[str] = None  # 거부 사유 (내부 기록용)


class ExchangeTrackingPatchBody(BaseModel):
    """교환 추적 정보 수기 업데이트 DTO.

    11번가 API가 제공하지 않는 정보를 수기로 입력하는 용도.
    """

    # 회수 상태: 미회수 / 회수중 / 회수완료
    exchange_retrieval_status: Optional[str] = None
    # 회수 완료 일자 (ISO 8601 문자열)
    exchange_retrieved_at: Optional[str] = None
    # 소싱처 재출고 택배사
    exchange_reship_company: Optional[str] = None
    # 소싱처 재출고 송장번호
    exchange_reship_tracking: Optional[str] = None
    # 고객 도착 일자 (ISO 8601 문자열)
    exchange_delivered_at: Optional[str] = None
