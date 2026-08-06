"""no_match.json(14) + price_changed.json(16) id들 price_locked 확인 [컨테이너]."""
import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")


async def main():
    import backend.main  # noqa: F401
    from backend.db.orm import get_read_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlmodel import select

    with open("/tmp/no_match.json", "r", encoding="utf-8") as f:
        no_match = json.load(f)
    with open("/tmp/price_changed.json", "r", encoding="utf-8") as f:
        price_changed = json.load(f)

    ids = [x["id"] for x in no_match] + [x["id"] for x in price_changed]
    async with get_read_session() as s:
        rows = (
            await s.execute(
                select(
                    SambaCollectedProduct.id,
                    SambaCollectedProduct.price_locked,
                    SambaCollectedProduct.stock_quantities,
                    SambaCollectedProduct.sale_status,
                ).where(SambaCollectedProduct.id.in_(ids))
            )
        ).all()
    out = {
        r[0]: {"price_locked": r[1], "stock_quantities": r[2], "sale_status": r[3]}
        for r in rows
    }
    with open("/tmp/locked_check.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    locked = [k for k, v in out.items() if v["price_locked"]]
    print(f"조회 {len(out)}건, 고정가(price_locked) {len(locked)}건: {locked}")


if __name__ == "__main__":
    asyncio.run(main())
