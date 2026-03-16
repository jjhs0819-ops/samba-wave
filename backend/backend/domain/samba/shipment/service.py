"""SambaWave Shipment service."""

import asyncio
import random
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from backend.domain.samba.shipment.model import SambaShipment
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.utils.logger import logger

STATUS_LABELS: Dict[str, str] = {
    "pending": "대기중",
    "updating": "업데이트중",
    "transmitting": "전송중",
    "completed": "완료",
    "partial": "부분완료",
    "failed": "실패",
}


class SambaShipmentService:
    def __init__(self, repo: SambaShipmentRepository):
        self.repo = repo

    # ==================== CRUD ====================

    async def list_shipments(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> List[SambaShipment]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(skip=skip, limit=limit, order_by="-created_at")

    async def get_shipment(self, shipment_id: str) -> Optional[SambaShipment]:
        return await self.repo.get_async(shipment_id)

    async def create_shipment(self, data: Dict[str, Any]) -> SambaShipment:
        return await self.repo.create_async(**data)

    async def update_shipment(
        self, shipment_id: str, data: Dict[str, Any]
    ) -> Optional[SambaShipment]:
        return await self.repo.update_async(shipment_id, **data)

    async def delete_shipment(self, shipment_id: str) -> bool:
        return await self.repo.delete_async(shipment_id)

    async def list_by_product(self, product_id: str) -> List[SambaShipment]:
        return await self.repo.list_by_product(product_id)

    # ==================== Simulation-based Transmit ====================

    async def simulate_transmit(
        self,
        product_id: str,
        target_account_ids: List[str],
        update_items: List[str],
    ) -> SambaShipment:
        """Create a shipment and simulate transmission.

        Ported from js/modules/shipment-manager.js:
        - Creates a shipment record in 'pending' state
        - Simulates product update with 95% success rate per item
        - Simulates market transmission with 90% success rate per account
        - No real API calls (KREAM/LotteHome proxy integration is a separate concern)
        """
        # Create shipment record
        shipment = await self.repo.create_async(
            product_id=product_id,
            target_account_ids=target_account_ids,
            update_items=update_items,
            status="pending",
            update_result={},
            transmit_result={},
        )

        # Simulate product update phase
        await self.repo.update_async(shipment.id, status="updating")
        await asyncio.sleep(0.3 + random.random() * 0.4)

        update_result: Dict[str, str] = {}
        for item in update_items:
            update_result[item] = "success" if random.random() > 0.05 else "failed"

        await self.repo.update_async(
            shipment.id, status="transmitting", update_result=update_result
        )

        # Simulate transmission to each account
        transmit_result: Dict[str, str] = {}
        for account_id in target_account_ids:
            await asyncio.sleep(0.2 + random.random() * 0.3)
            transmit_result[account_id] = (
                "success" if random.random() > 0.10 else "failed"
            )

        # Determine final status
        transmit_values = list(transmit_result.values())
        all_success = (
            len(transmit_values) > 0
            and all(v == "success" for v in transmit_values)
        )
        any_failed = any(v == "failed" for v in transmit_values)
        final_status = "completed" if all_success else ("partial" if any_failed else "completed")

        updated = await self.repo.update_async(
            shipment.id,
            status=final_status,
            transmit_result=transmit_result,
            completed_at=datetime.now(UTC),
        )

        logger.info(
            f"Shipment {shipment.id} completed with status={final_status} "
            f"for product={product_id}"
        )
        return updated or shipment

    @staticmethod
    def get_status_label(status: str) -> str:
        return STATUS_LABELS.get(status, status)
