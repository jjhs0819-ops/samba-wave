"""SambaWave CS 문의 service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.cs_inquiry.model import SambaCSInquiry
from backend.domain.samba.cs_inquiry.repository import SambaCSInquiryRepository
from backend.utils.logger import logger

# CS 답변 기본 템플릿 (contact/service.py SMS 템플릿과 동일 패턴)
CS_REPLY_TEMPLATES: Dict[str, Dict[str, str]] = {
    "shipping_info": {
        "name": "배송안내",
        "content": "안녕하세요 고객님 발주 이후 통상 2~4일 정도 소요됩니다 가급적 빠르게 출고 될 수 있도록 하겠습니다. 조금만 시간 양해 부탁드립니다",
    },
    "out_of_stock": {
        "name": "품절안내",
        "content": "안녕하세요 고객님, 해당 상품은 현재 품절 상태입니다. 불편을 드려 죄송합니다. 빠른 시일 내 재입고 될 수 있도록 하겠습니다.",
    },
    "cancel_done": {
        "name": "취소완료",
        "content": "안녕하세요 고객님 해당주문건 취소완료되었습니다.",
    },
    "size_inquiry": {
        "name": "사이즈문의",
        "content": "안녕하세요 고객님, 혹시 어떤색상의 사이즈 문의 주시는 건지 알려주시면 답변 드리도록하겠습니다.",
    },
    "exchange_return": {
        "name": "교환/반품안내",
        "content": "안녕하세요 고객님, 교환/반품 접수되었습니다. 상품검수가 완료되면 반품승인 부탁드립니다. 처리 완료 후 안내드리겠습니다.",
    },
    "delivery_delay": {
        "name": "배송지연안내",
        "content": "안녕하세요 고객님, 현재 물량이 많아 배송이 다소 지연되고 있습니다. 빠르게 처리될 수 있도록 하겠습니다. 양해 부탁드립니다.",
    },
    "product_info": {
        "name": "상품정보안내",
        "content": "안녕하세요 고객님, 문의주신 상품 관련 확인 후 답변 드리겠습니다. 잠시만 기다려주세요.",
    },
    "thank_you": {
        "name": "감사인사",
        "content": "안녕하세요 고객님, 구매해주셔서 감사합니다. 상품에 문제가 있으시면 언제든 문의 부탁드립니다.",
    },
}


class SambaCSInquiryService:
    def __init__(self, repo: SambaCSInquiryRepository):
        self.repo = repo

    # ==================== 목록/조회 ====================

    async def list_inquiries(
        self,
        skip: int = 0,
        limit: int = 30,
        market: Optional[str] = None,
        inquiry_type: Optional[str] = None,
        reply_status: Optional[str] = None,
        search: Optional[str] = None,
        sort_field: str = "inquiry_date",
        sort_desc: bool = True,
    ) -> Dict[str, Any]:
        """필터링된 문의 목록 + 총 건수 반환."""
        items = await self.repo.list_filtered(
            skip=skip,
            limit=limit,
            market=market,
            inquiry_type=inquiry_type,
            reply_status=reply_status,
            search=search,
            sort_field=sort_field,
            sort_desc=sort_desc,
        )
        total = await self.repo.count_filtered(
            market=market,
            inquiry_type=inquiry_type,
            reply_status=reply_status,
            search=search,
        )
        return {"items": items, "total": total}

    async def get_inquiry(self, inquiry_id: str) -> Optional[SambaCSInquiry]:
        return await self.repo.get_async(inquiry_id)

    # ==================== 생성 ====================

    async def create_inquiry(self, data: Dict[str, Any]) -> SambaCSInquiry:
        return await self.repo.create_async(**data)

    # ==================== 답변 ====================

    async def reply_inquiry(
        self, inquiry_id: str, reply_content: str
    ) -> Optional[SambaCSInquiry]:
        """문의에 답변 등록."""
        inquiry = await self.repo.get_async(inquiry_id)
        if not inquiry:
            return None

        updated = await self.repo.update_async(
            inquiry_id,
            reply=reply_content,
            reply_status="replied",
            replied_at=datetime.now(UTC),
        )
        logger.info(f"CS 문의 {inquiry_id} 답변 완료")
        return updated or inquiry

    # ==================== 삭제 ====================

    async def delete_inquiry(self, inquiry_id: str) -> bool:
        """문의 삭제 (숨김 처리 — 동기화 시 중복 방지)."""
        updated = await self.repo.update_async(inquiry_id, is_hidden=True)
        return updated is not None

    async def delete_batch(self, ids: List[str]) -> int:
        """선택 삭제 (숨김 처리)."""
        count = 0
        for _id in ids:
            result = await self.repo.update_async(_id, is_hidden=True)
            if result:
                count += 1
        logger.info(f"CS 문의 {count}건 숨김 처리")
        return count

    # ==================== 통계 ====================

    async def get_stats(self) -> Dict[str, Any]:
        """문의 통계: 전체/미답변/답변완료/마켓별."""
        all_items = await self.repo.list_async()

        market_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        pending = 0
        replied = 0

        for item in all_items:
            market_counts[item.market] = market_counts.get(item.market, 0) + 1
            type_counts[item.inquiry_type] = type_counts.get(item.inquiry_type, 0) + 1
            if item.reply_status == "replied":
                replied += 1
            else:
                pending += 1

        return {
            "total": len(all_items),
            "pending": pending,
            "replied": replied,
            "by_market": market_counts,
            "by_type": type_counts,
        }

    # ==================== 템플릿 ====================

    @staticmethod
    def get_reply_templates() -> Dict[str, Dict[str, str]]:
        """CS 답변 템플릿 목록 반환."""
        return CS_REPLY_TEMPLATES

    @staticmethod
    def get_template_content(template_key: str) -> Optional[str]:
        """특정 템플릿 내용 반환."""
        tpl = CS_REPLY_TEMPLATES.get(template_key)
        return tpl["content"] if tpl else None
