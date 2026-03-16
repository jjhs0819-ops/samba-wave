"""SambaWave Return service."""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.returns.model import SambaReturn
from backend.domain.samba.returns.repository import SambaReturnRepository
from backend.utils.logger import logger

# 반품 사유 (js/modules/returns.js 포팅)
RETURN_REASONS: Dict[str, List[str]] = {
    "return": [
        "단순 변심",
        "사이즈 불일치",
        "색상 차이",
        "상품 불량",
        "오배송",
        "상품 파손",
        "기타",
    ],
    "exchange": [
        "사이즈 교환",
        "색상 교환",
        "상품 불량 교환",
        "오배송 교환",
        "기타",
    ],
    "cancel": [
        "단순 변심",
        "배송 지연",
        "가격 변동",
        "중복 주문",
        "품절",
        "기타",
    ],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_timeline_entry(status: str, message: str) -> Dict[str, str]:
    return {
        "date": _now_iso(),
        "status": status,
        "message": message,
    }


class SambaReturnService:
    def __init__(self, repo: SambaReturnRepository):
        self.repo = repo

    # ==================== CRUD ====================

    async def list_returns(
        self,
        skip: int = 0,
        limit: int = 50,
        order_id: Optional[str] = None,
        status: Optional[str] = None,
        type: Optional[str] = None,
    ) -> List[SambaReturn]:
        if order_id:
            return await self.repo.list_by_order(order_id)
        if status:
            return await self.repo.list_by_status(status)
        if type:
            return await self.repo.list_by_type(type)
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_return(self, return_id: str) -> Optional[SambaReturn]:
        return await self.repo.get_async(return_id)

    # ==================== Business Logic ====================

    async def create_return(self, data: Dict[str, Any]) -> SambaReturn:
        """반품/교환/취소 생성 + 초기 타임라인 엔트리."""
        return_type = data.get("type", "return")
        initial_timeline = [
            _make_timeline_entry("requested", f"{return_type} 요청이 접수되었습니다.")
        ]
        data["timeline"] = initial_timeline
        data["notes"] = data.get("notes") or []
        data["status"] = "requested"

        ret = await self.repo.create_async(**data)
        logger.info(f"Return {ret.id} created for order {ret.order_id} type={return_type}")
        return ret

    async def approve_return(self, return_id: str) -> Optional[SambaReturn]:
        """반품 승인."""
        ret = await self.repo.get_async(return_id)
        if not ret:
            return None

        now = datetime.now(UTC)
        timeline = list(ret.timeline or [])
        timeline.append(_make_timeline_entry("approved", "요청이 승인되었습니다."))

        return await self.repo.update_async(
            return_id,
            status="approved",
            approval_date=now,
            timeline=timeline,
        )

    async def reject_return(
        self, return_id: str, reason: Optional[str] = None
    ) -> Optional[SambaReturn]:
        """반품 거절."""
        ret = await self.repo.get_async(return_id)
        if not ret:
            return None

        message = f"요청이 거절되었습니다. 사유: {reason}" if reason else "요청이 거절되었습니다."
        timeline = list(ret.timeline or [])
        timeline.append(_make_timeline_entry("rejected", message))

        return await self.repo.update_async(
            return_id,
            status="rejected",
            timeline=timeline,
        )

    async def complete_return(self, return_id: str) -> Optional[SambaReturn]:
        """반품 완료 처리."""
        ret = await self.repo.get_async(return_id)
        if not ret:
            return None

        now = datetime.now(UTC)
        timeline = list(ret.timeline or [])
        timeline.append(_make_timeline_entry("completed", "처리가 완료되었습니다."))

        return await self.repo.update_async(
            return_id,
            status="completed",
            completion_date=now,
            timeline=timeline,
        )

    async def cancel_return(self, return_id: str) -> Optional[SambaReturn]:
        """반품 요청 취소."""
        ret = await self.repo.get_async(return_id)
        if not ret:
            return None

        timeline = list(ret.timeline or [])
        timeline.append(_make_timeline_entry("cancelled", "요청이 취소되었습니다."))

        return await self.repo.update_async(
            return_id,
            status="cancelled",
            timeline=timeline,
        )

    async def add_note(self, return_id: str, note: str) -> Optional[SambaReturn]:
        """메모 추가."""
        ret = await self.repo.get_async(return_id)
        if not ret:
            return None

        notes = list(ret.notes or [])
        notes.append({
            "date": _now_iso(),
            "message": note,
        })

        return await self.repo.update_async(return_id, notes=notes)

    # ==================== Stats ====================

    async def get_return_stats(self) -> Dict[str, Any]:
        """상태별/유형별 반품 통계 + 총 환불 금액."""
        all_returns = await self.repo.list_async()

        status_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        total_refund: float = 0.0

        for ret in all_returns:
            status_counts[ret.status] = status_counts.get(ret.status, 0) + 1
            type_counts[ret.type] = type_counts.get(ret.type, 0) + 1
            if ret.requested_amount and ret.status in ("approved", "completed"):
                total_refund += ret.requested_amount

        return {
            "total": len(all_returns),
            "by_status": status_counts,
            "by_type": type_counts,
            "total_refund_amount": total_refund,
        }

    # ==================== Reasons ====================

    @staticmethod
    def get_return_reasons() -> Dict[str, List[str]]:
        return RETURN_REASONS
