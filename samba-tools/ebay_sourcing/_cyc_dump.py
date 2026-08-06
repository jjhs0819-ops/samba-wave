"""KV 등록상품 source_url dump (컨테이너 실행) -> /tmp/kv_products.json"""
import asyncio
import json
import sys

sys.path.insert(0, "/app/backend")

KV = "ma_01KXQCB67RZBBE99H8TM2J4K8J"


async def main():
    import backend.main  # noqa: F401
    from backend.db.orm import get_read_session
    from backend.domain.samba.collector.model import SambaCollectedProduct
    from sqlalchemy import text
    from sqlmodel import select

    async with get_read_session() as s:
        rows = (
            await s.execute(
                select(
                    SambaCollectedProduct.id,
                    SambaCollectedProduct.name,
                    SambaCollectedProduct.source_url,
                    SambaCollectedProduct.cost,
                ).where(
                    text("registered_accounts::text LIKE :kv")
                ).params(kv=f"%{KV}%")
            )
        ).all()

    out = [
        {"id": r[0], "name": r[1], "source_url": r[2], "cost": r[3]} for r in rows
    ]
    with open("/tmp/kv_products.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print(f"dumped {len(out)}")


if __name__ == "__main__":
    asyncio.run(main())
