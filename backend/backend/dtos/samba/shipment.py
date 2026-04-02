"""SambaWave Shipment DTOs."""

from typing import List, Optional

from pydantic import BaseModel


class ShipmentCreate(BaseModel):
    product_id: str
    target_account_ids: Optional[List[str]] = None
    update_items: Optional[List[str]] = None
    status: str = "pending"


class ShipmentStartRequest(BaseModel):
    """Request body for starting a batch shipment (transmit) operation."""

    product_ids: List[str]
    update_items: List[str]  # ['price', 'stock', 'image', 'description']
    target_account_ids: List[str]
