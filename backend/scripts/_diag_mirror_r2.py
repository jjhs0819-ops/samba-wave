"""mirror_oversized_to_r2가 leecom01.kr 6MB 이미지를 실제로 미러하는지 직접 호출 검증."""

import asyncio
import logging

logging.basicConfig(level=logging.DEBUG)

from backend.core.config import settings
from backend.db.orm import get_write_sessionmaker

URLS = [
    "https://www.leecom01.kr/img/img/CJmall(NEW)/page/2030274229.jpg",
    "https://image.msscdn.net/images/goods_img/20241028/4563277/4563277_17618937442846_500.jpg",
]


async def main():
    from backend.domain.samba.image.service import ImageTransformService

    Session = get_write_sessionmaker()
    async with Session() as session:
        svc = ImageTransformService(session)

        # R2 관련 설정 확인
        print(f"settings.is_production={settings.is_production}")
        for attr in dir(settings):
            if "r2" in attr.lower() or "cloudflare" in attr.lower() or "bucket" in attr.lower():
                v = getattr(settings, attr, None)
                if not callable(v):
                    print(f"  settings.{attr}={v!r}")

        # import os 환경변수 R2 관련
        import os
        for k in sorted(os.environ.keys()):
            if "r2" in k.lower() or "cloudflare" in k.lower() or "bucket" in k.lower() or "s3" in k.lower():
                val = os.environ[k]
                if "secret" in k.lower() or "key" in k.lower() or "password" in k.lower():
                    val = val[:6] + "***" if val else val
                print(f"  ENV {k}={val}")

        print("\n=== mirror_oversized_to_r2 호출 ===")
        try:
            new_urls, mapping = await svc.mirror_oversized_to_r2(URLS)
            print(f"\n결과 new_urls:")
            for u in new_urls:
                print(f"  {u}")
            print(f"\nmapping (원본 -> 미러):")
            for k, v in (mapping or {}).items():
                print(f"  {k}\n   -> {v}")
        except Exception as e:
            import traceback
            print(f"\nERROR: {type(e).__name__}: {e}")
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
