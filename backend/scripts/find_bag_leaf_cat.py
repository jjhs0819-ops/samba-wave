"""스마트스토어 가방 leaf category 식별."""

import asyncio
from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.proxy.smartstore import SmartStoreClient

CHANOL_ID = "ma_01KQRRXMFD9W4WG81MGRME9YBP"


async def main() -> None:
    async with get_read_session() as session:
        acc = await session.get(SambaMarketAccount, CHANOL_ID)
        extras = getattr(acc, "additional_fields", None) or {}
        cid = extras.get("clientId", "") or ""
        csec = extras.get("clientSecret", "") or ""
    client = SmartStoreClient(cid, csec)
    cats = await client.get_categories(last_only=True)
    print(f"리프 카테고리 총 {len(cats)}건")
    # 검색: '가방'/'보스턴'/'더플' 키워드
    for c in cats:
        nm = c.get("wholeCategoryName") or c.get("name") or ""
        if "가방" in nm and (
            "보스턴" in nm or "더플" in nm or "백팩" in nm or "파우치" in nm
        ):
            print(f"  id={c.get('id') or c.get('categoryId')} name={nm}")


if __name__ == "__main__":
    asyncio.run(main())
