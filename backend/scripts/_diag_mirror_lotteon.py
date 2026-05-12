"""푸마 LE1219202563 이미지를 mirror_external_to_r2가 R2로 치환하는지 확인."""

import asyncio
import logging
logging.basicConfig(level=logging.INFO)

from backend.db.orm import get_write_sessionmaker

URLS = [
    "https://contents.lotteon.com/itemimage/20260312164110/LE/12/19/20/25/63/_1/31/44/64/92/4/LE1219202563_1314464924_1.jpg/dims/optimize/resizemc/400x400",
]

async def main():
    from backend.domain.samba.image.service import ImageTransformService
    Session = get_write_sessionmaker()
    async with Session() as session:
        svc = ImageTransformService(session)
        new_urls, mapping = await svc.mirror_external_to_r2(URLS)
        print("=== new_urls ===")
        for u in new_urls:
            print(f"  {u}")
        print(f"\n=== mapping ({len(mapping)} entries) ===")
        for k, v in mapping.items():
            print(f"  {k}\n   -> {v}")

asyncio.run(main())
