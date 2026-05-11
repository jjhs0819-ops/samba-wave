"""마스마룰즈 잔존 마켓 계정 + 검색필터 확인."""

import asyncio
from sqlalchemy import select, func

from backend.db.orm import get_read_session
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.collector.model import (
    SambaCollectedProduct as CP,
    SambaSearchFilter as SF,
)


async def main() -> None:
    async with get_read_session() as session:
        acc_id = "ma_01KQRRXMFD9W4WG81MGRME9YBP"
        acc = await session.get(SambaMarketAccount, acc_id)
        if acc:
            print(f"[마켓계정] {acc_id}")
            print(f"  market_type={acc.market_type}")
            print(f"  market_name={acc.market_name}")
            print(f"  account_label={acc.account_label}")
            print(f"  seller_id={acc.seller_id}")
        else:
            print(f"계정 {acc_id} 없음!")

        like = func.btrim(CP.brand).ilike("%마스마룰즈%") | func.btrim(CP.brand).ilike(
            "%masmarulez%"
        )

        # search_filter_id 분포
        stmt_sf = (
            select(CP.search_filter_id, func.count(CP.id))
            .where(like)
            .group_by(CP.search_filter_id)
        )
        sf_rows = (await session.execute(stmt_sf)).all()
        print("\n[search_filter_id 분포]")
        for sf_id, c in sf_rows:
            sf = await session.get(SF, sf_id) if sf_id else None
            print(f"  {sf_id}: {c}건  filter={(sf.name if sf else None)}")

        # 무신사 측 brand_id (style_code prefix 등)
        stmt_brand = (
            select(CP.brand_id, func.count(CP.id)).where(like).group_by(CP.brand_id)
        )
        brand_rows = (await session.execute(stmt_brand)).all()
        print("\n[brand_id 분포]")
        for bid, c in brand_rows:
            print(f"  {bid}: {c}건")


if __name__ == "__main__":
    asyncio.run(main())
