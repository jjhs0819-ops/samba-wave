"""1377156 마켓 전송 결과 + 페이로드 덤프."""

import asyncio
import json
from sqlalchemy import select
from backend.db.orm import get_read_session
from backend.domain.samba.collector.model import SambaCollectedProduct as CP


async def main() -> None:
    async with get_read_session() as session:
        row = (
            await session.execute(
                select(CP).where(
                    CP.source_site == "MUSINSA", CP.site_product_id == "1377156"
                )
            )
        ).scalar_one_or_none()
        if not row:
            print("❌ 없음")
            return
        print(f"id={row.id}")
        print(
            f"market_product_nos = {json.dumps(row.market_product_nos or {}, ensure_ascii=False, indent=2)}"
        )
        print(f"registered_accounts = {row.registered_accounts}")
        print("\n[last_sent_data 키별 요약]")
        lsd = row.last_sent_data or {}
        for acc_id, d in lsd.items():
            print(
                f"  계정 {acc_id}: 키={list(d.keys()) if isinstance(d, dict) else type(d).__name__}"
            )
            if isinstance(d, dict):
                opt = d.get("options") or d.get("optionInfo") or d.get("payload")
                if opt:
                    print("    payload-ish 내용 일부:")
                    s = json.dumps(opt, ensure_ascii=False)
                    print(f"    {s[:600]}")
        print(f"\noptions: {len(row.options or [])}건")
        print(f"addon_options: {len(row.addon_options or [])}건")
        print(f"option_group_names: {row.option_group_names}")
        if row.addon_options:
            print("\naddon_options 첫 3건:")
            for a in row.addon_options[:3]:
                print(f"  {a}")


if __name__ == "__main__":
    asyncio.run(main())
