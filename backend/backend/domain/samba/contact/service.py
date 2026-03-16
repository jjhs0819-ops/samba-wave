"""SambaWave Contact service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.contact.model import SambaContactLog
from backend.domain.samba.contact.repository import SambaContactLogRepository
from backend.utils.logger import logger

# 기본 템플릿 (js/modules/contacts.js 포팅)
DEFAULT_TEMPLATES: Dict[str, Dict[str, str]] = {
    "sms": {
        "order_confirm": "[삼바웨이브] {customer_name}님, 주문이 확인되었습니다. 주문번호: {order_number}",
        "shipping_start": "[삼바웨이브] {customer_name}님, 상품이 발송되었습니다. 운송장번호: {tracking_number}",
        "delivery_complete": "[삼바웨이브] {customer_name}님, 상품이 배송완료되었습니다. 감사합니다.",
        "return_confirm": "[삼바웨이브] {customer_name}님, 반품/교환 요청이 접수되었습니다.",
        "cancel_confirm": "[삼바웨이브] {customer_name}님, 주문 취소가 완료되었습니다.",
    },
    "kakao": {
        "order_confirm": "[삼바웨이브] 주문 확인 알림\n\n{customer_name}님, 주문이 정상적으로 접수되었습니다.\n\n주문번호: {order_number}\n상품명: {product_name}\n결제금액: {sale_price}원\n\n감사합니다.",
        "shipping_start": "[삼바웨이브] 배송 시작 알림\n\n{customer_name}님, 상품이 발송되었습니다.\n\n택배사: {shipping_company}\n운송장번호: {tracking_number}\n\n배송 조회는 택배사 홈페이지에서 가능합니다.",
        "delivery_complete": "[삼바웨이브] 배송 완료 알림\n\n{customer_name}님, 상품이 배송완료되었습니다.\n\n상품에 문제가 있으시면 고객센터로 연락 부탁드립니다.\n감사합니다.",
        "return_confirm": "[삼바웨이브] 반품/교환 접수 알림\n\n{customer_name}님, 반품/교환 요청이 접수되었습니다.\n\n처리 현황은 마이페이지에서 확인 가능합니다.",
    },
    "email": {
        "order_confirm": "주문 확인 안내\n\n안녕하세요 {customer_name}님,\n\n주문이 정상적으로 접수되었습니다.\n\n주문번호: {order_number}\n상품명: {product_name}\n수량: {quantity}\n결제금액: {sale_price}원\n\n감사합니다.\n삼바웨이브 드림",
        "shipping_start": "배송 시작 안내\n\n안녕하세요 {customer_name}님,\n\n주문하신 상품이 발송되었습니다.\n\n택배사: {shipping_company}\n운송장번호: {tracking_number}\n\n감사합니다.\n삼바웨이브 드림",
    },
}


def parse_template(template_str: str, variables: Dict[str, Any]) -> str:
    """템플릿 문자열의 {변수} 자리를 치환합니다."""
    result = template_str
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


class SambaContactService:
    def __init__(self, repo: SambaContactLogRepository):
        self.repo = repo

    # ==================== CRUD ====================

    async def list_contacts(
        self,
        skip: int = 0,
        limit: int = 50,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[SambaContactLog]:
        if order_id:
            return await self.repo.list_by_order(order_id)
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_contact(self, contact_id: str) -> Optional[SambaContactLog]:
        return await self.repo.get_async(contact_id)

    async def create_contact(self, data: Dict[str, Any]) -> SambaContactLog:
        return await self.repo.create_async(**data)

    async def delete_contact(self, contact_id: str) -> bool:
        return await self.repo.delete_async(contact_id)

    # ==================== Send ====================

    async def send_contact(self, data: Dict[str, Any]) -> SambaContactLog:
        """연락 발송: pending 상태로 생성 후 sent로 변경 (시뮬레이션)."""
        data["status"] = "pending"
        contact = await self.repo.create_async(**data)

        # 시뮬레이션: 실제 SMS/카카오/이메일 연동 시 이 부분을 대체
        updated = await self.repo.update_async(
            contact.id,
            status="sent",
            sent_at=datetime.now(UTC),
        )

        logger.info(
            f"Contact {contact.id} sent via {contact.type} to {contact.recipient}"
        )
        return updated or contact

    # ==================== Query ====================

    async def get_contacts_by_order(self, order_id: str) -> List[SambaContactLog]:
        return await self.repo.list_by_order(order_id)

    async def get_contact_stats(self) -> Dict[str, Any]:
        """상태별/유형별 연락 통계."""
        all_contacts = await self.repo.list_async()

        status_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}

        for contact in all_contacts:
            status_counts[contact.status] = status_counts.get(contact.status, 0) + 1
            type_counts[contact.type] = type_counts.get(contact.type, 0) + 1

        return {
            "total": len(all_contacts),
            "by_status": status_counts,
            "by_type": type_counts,
        }

    # ==================== Templates ====================

    @staticmethod
    def get_default_templates() -> Dict[str, Dict[str, str]]:
        return DEFAULT_TEMPLATES

    @staticmethod
    def render_template(
        contact_type: str, template_name: str, variables: Dict[str, Any]
    ) -> Optional[str]:
        """템플릿 렌더링. 해당 타입/이름이 없으면 None 반환."""
        type_templates = DEFAULT_TEMPLATES.get(contact_type)
        if not type_templates:
            return None
        template_str = type_templates.get(template_name)
        if not template_str:
            return None
        return parse_template(template_str, variables)
