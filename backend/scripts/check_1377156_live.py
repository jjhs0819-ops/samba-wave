"""무신사 1377156 라이브 API 응답 점검 (DB 안 씀)."""

import asyncio


async def main() -> None:
    from backend.domain.samba.proxy.musinsa import MusinsaClient

    client = MusinsaClient()
    detail = await client.get_goods_detail("1377156")
    if not detail:
        print("detail = None / empty")
        return
    keys = [
        "style_code",
        "sex",
        "season",
        "manufacturer",
        "origin",
        "color",
        "material",
        "name",
        "brand",
        "care_instructions",
        "quality_guarantee",
        "category",
    ]
    for k in keys:
        v = detail.get(k, "<missing>")
        if isinstance(v, str) and len(v) > 80:
            v = v[:80] + "..."
        print(f"  {k}={v!r}")


if __name__ == "__main__":
    asyncio.run(main())
