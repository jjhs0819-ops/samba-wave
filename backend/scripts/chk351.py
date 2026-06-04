"""#351 라이브 재확인 (READ-ONLY): 롯데홈 현재 SalePrc vs DB last_sent."""

import asyncio
import json

from sqlalchemy import text

from backend.db.orm import get_read_session
from backend.domain.samba.proxy.lottehome import LotteHomeClient

GOODS = "3334859759"
ACC = "ma_01KRFTY8GJHBBDWJAQ33FXB3GK"
PID = "cp_01KR3BXBEGMHHQ6VTK90X8P22J"


async def main():
    async with get_read_session() as s:
        r = (
            await s.execute(
                text(
                    "select seller_id, additional_fields "
                    "from samba_market_account where id=:a"
                ),
                {"a": ACC},
            )
        ).mappings().first()
        ex = r["additional_fields"] or {}
        c = LotteHomeClient(
            ex.get("userId") or r["seller_id"] or "",
            ex.get("password", ""),
            ex.get("agncNo", ""),
            ex.get("env", "prod"),
        )
        v = await c.search_goods_view(GOODS)
        d = v.get("data", {})
        res = d.get("Result", d)
        gi = res.get("GoodsInfo", res)
        if isinstance(gi, list):
            gi = gi[0] if gi else {}
        keys = [
            "GoodsNo",
            "SalePrc",
            "OrgSalePrc",
            "MrgnRt",
            "SaleStatCd",
            "ConfStatCd",
            "GoodsStatCd",
        ]
        print("LIVE:", json.dumps({k: gi.get(k) for k in keys}, ensure_ascii=False))
        p = (
            await s.execute(
                text(
                    "select last_sent_data->:a as lsd, sale_price, cost "
                    "from samba_collected_product where id=:p"
                ),
                {"a": ACC, "p": PID},
            )
        ).mappings().first()
        if p:
            print(
                "DB:",
                json.dumps(
                    {
                        "last_sent": p["lsd"],
                        "sale_price": p["sale_price"],
                        "cost": p["cost"],
                    },
                    ensure_ascii=False,
                    default=str,
                )[:500],
            )


if __name__ == "__main__":
    asyncio.run(main())
