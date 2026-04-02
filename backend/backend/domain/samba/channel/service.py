"""SambaWave Channel service."""

from typing import Any, Dict, List, Optional

from backend.domain.samba.channel.model import SambaChannel
from backend.domain.samba.channel.repository import SambaChannelRepository


DEFAULT_FEE_RATES = {
    "open-market": 8.5,
    "mall": 4.5,
    "resale": 10,
    "overseas": 15,
}

PLATFORM_INFO = {
    "coupang": {"name": "쿠팡", "type": "open-market"},
    "11st": {"name": "11번가", "type": "open-market"},
    "ssg": {"name": "SSG", "type": "mall"},
    "lotte": {"name": "롯데온", "type": "mall"},
    "musinsa": {"name": "무신사", "type": "resale"},
    "amazon": {"name": "아마존", "type": "overseas"},
    "ebay": {"name": "이베이", "type": "overseas"},
}


class SambaChannelService:
    def __init__(self, repo: SambaChannelRepository):
        self.repo = repo

    async def list_channels(self, skip: int = 0, limit: int = 50) -> List[SambaChannel]:
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def get_channel(self, channel_id: str) -> Optional[SambaChannel]:
        return await self.repo.get_async(channel_id)

    async def create_channel(self, data: Dict[str, Any]) -> SambaChannel:
        if "fee_rate" not in data or data["fee_rate"] is None:
            data["fee_rate"] = DEFAULT_FEE_RATES.get(data.get("type", ""), 0)
        return await self.repo.create_async(**data)

    async def update_channel(
        self, channel_id: str, data: Dict[str, Any]
    ) -> Optional[SambaChannel]:
        return await self.repo.update_async(channel_id, **data)

    async def delete_channel(self, channel_id: str) -> bool:
        return await self.repo.delete_async(channel_id)

    @staticmethod
    def get_platform_info(platform: str) -> Dict[str, str]:
        return PLATFORM_INFO.get(platform, {"name": "기타", "type": "other"})
