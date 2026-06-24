"""POIZON 추천가(시세) 수집 — 매칭 성공 상품의 대표 사이즈 1개, resumable + 레이트리밋.

포이즌 매칭 성공(resell_matches.poison.product_id 있음) 상품의 catalog 에서
대표 사이즈(첫 항목) globalSkuId 1개를 골라 recommend_price(최저/평균/최고가)를 조회,
resell_matches.poison.recommend = {minPrice, averagePrice, maxPrice, ...} 로 저장한다.

- 대표 사이즈 1개만 조회(빠름) — 1차 선별용 '참고 시세'. 실제 등록 시 사이즈별 정밀 조회됨.
- resumable: 이미 recommend 있는 style_code 제외(재실행 시 이어서)
- 레이트리밋: 호출당 SLEEP 초 / 빈도초과(400010007)·연결에러는 백오프 재시도
- 서킷브레이커: 연속 레이트리밋 N회 시 중단(IP차단/throttle 보호)
- 진행: 매 50건 로그

사용: python poison_price_collect.py [LIMIT]   (LIMIT=처리할 고유품번 수, 미지정=전체)
"""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.core.config import settings  # noqa: E402
from backend.db.orm import get_read_session, get_write_session  # noqa: E402
from backend.domain.samba.proxy.poison import PoisonClient  # noqa: E402

SLEEP = 2.5  # 호출 간격 — 21005101(일시 조회예외) 후반 누적 회피 위해 1.5→2.5 상향
CIRCUIT_FAIL = 30  # 연속 레이트리밋 시 중단
RL_BACKOFF = 5.0  # 빈도초과/연결에러 기본 대기초
MAX_RETRY = 6  # 재시도 횟수
BIDDING_TYPE = 20  # 20=일반판매/예약판매 (recommend_price 기준)


async def load_creds():
    """poison_bulk_match.py 와 동일 경로로 인증 로드(시크릿 노출 없음)."""
    from sqlmodel import select

    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.plugins.markets.poison import PoisonPlugin

    async with get_read_session() as s:
        acc = (
            (
                await s.execute(
                    select(SambaMarketAccount)
                    .where(SambaMarketAccount.market_type == "poison")
                    .where(SambaMarketAccount.is_active == True)  # noqa: E712
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        creds = await PoisonPlugin()._load_auth(s, acc)
    if not creds or not creds.get("app_key") or not creds.get("app_secret"):
        raise RuntimeError(
            "poison 계정 인증정보 없음(additional_fields apiKey/apiSecret)"
        )
    return str(creds["app_key"]), str(creds["app_secret"])


async def fetch_targets(limit=None):
    """매칭 성공 + 아직 추천가 없는 style_code → (code, 대표 globalSkuId, 사이즈).

    같은 style_code 는 catalog 동일하므로 style_code 기준 1건씩만 조회.
    """
    async with get_read_session() as s:
        sql = """
            SELECT DISTINCT ON (btrim(style_code))
                   btrim(style_code) AS code,
                   resell_matches -> 'poison' AS pm
            FROM samba_collected_product
            WHERE resell_matches -> 'poison' ->> 'product_id' <> ''
              -- 시세가 제대로 수집된 것(minPrice 값 존재)만 제외.
              -- 미수집 / no_price / 가격 None(이전 파싱버그) 전부 재수집 대상(수렴 회복).
              AND (resell_matches -> 'poison' -> 'recommend' ->> 'minPrice') IS NULL
              AND style_code IS NOT NULL AND btrim(style_code) <> ''
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = (await s.execute(text(sql))).all()

    out = []
    for r in rows:
        pm = r.pm or {}
        catalog = pm.get("catalog") or {}
        gid = None
        size = ""
        # 대표 사이즈 1개 (catalog 첫 유효 항목)
        for sz, v in catalog.items():
            if v:
                gid = int(v)
                size = str(sz)
                break
        if gid:
            out.append((r.code, gid, size))
    return out


async def fetch_price_with_backoff(client, gid):
    """recommend_price 조회 + 백오프. (status, result) 반환.

    status: 'ok'(시세있음), 'miss'(조회실패/시세없음), 'ratelimited'(재시도소진).
    빈도초과(400010007)·연결에러는 miss로 안 셈 — 대기 후 재시도.
    """
    import httpx

    for attempt in range(MAX_RETRY):
        try:
            res = await client.recommend_price(
                global_sku_id=gid, bidding_type=BIDDING_TYPE
            )
        except httpx.HTTPError:
            await asyncio.sleep(RL_BACKOFF * (attempt + 1))
            continue
        if res.get("success"):
            return ("ok", res)
        code = str((res.get("data") or {}).get("code"))
        # 400010007=빈도초과, 21005101=상품정보 일시 조회예외(请稍后重试) → 둘 다 일시 에러,
        # 백오프 후 재시도(영구 실패로 마킹하면 다음 실행에 영영 누락됨)
        if code in ("400010007", "21005101"):
            await asyncio.sleep(RL_BACKOFF * (attempt + 1))
            continue
        return ("miss", res)  # 진짜 실패(시세 없음 등) → 마킹하고 넘어감
    return ("ratelimited", None)


async def save_price(code, recommend_json):
    """같은 style_code 의 (포이즌 매칭된) 모든 상품에 poison.recommend 저장."""
    async with get_write_session() as s:
        # CAST(:p AS jsonb) — ':p::jsonb' placeholder 충돌 금지(CLAUDE.md 규약)
        sql = text(
            """
            UPDATE samba_collected_product
            SET resell_matches = jsonb_set(
                    COALESCE(resell_matches, '{}'::jsonb),
                    '{poison,recommend}',
                    CAST(:p AS jsonb),
                    true
                )
            WHERE btrim(style_code) = :code
              AND resell_matches -> 'poison' ->> 'product_id' <> ''
            """
        )
        res = await s.execute(sql, {"p": recommend_json, "code": code})
        await s.commit()
        return res.rowcount


async def main():
    import json
    import time as _time

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    targets = await fetch_targets(limit)
    total = len(targets)
    print(f"추천가 수집 대상 품번: {total:,} (매칭 성공, 추천가 미수집)")
    if not total:
        print("처리할 품번 없음 (전부 수집 완료 or 대상 없음)")
        return

    app_key, app_secret = await load_creds()
    client = PoisonClient(app_key=app_key, app_secret=app_secret)
    ok = miss = rl = updated_rows = 0
    consec_rl = 0

    for i, (code, gid, size) in enumerate(targets, 1):
        status, res = await fetch_price_with_backoff(client, gid)

        if status == "ratelimited":
            rl += 1
            consec_rl += 1
            if consec_rl >= CIRCUIT_FAIL:
                print(f"!! 레이트리밋 {CIRCUIT_FAIL}회 연속 — 중단(나중 재실행)")
                break
            await asyncio.sleep(RL_BACKOFF * 3)
            continue
        consec_rl = 0

        # 포이즌 recommend_price 실제 응답엔 minPrice/averagePrice/maxPrice 키가 없음.
        # 시세는 data.globalMinPrice/asiaMinPrice(시장 최저) + data.priceRangeItems(백분위)에 들어있음.
        min_price = avg_price = max_price = None
        if status == "ok":
            payload = res.get("data") or {}
            prices = sorted(
                int(it["price"])
                for it in (payload.get("priceRangeItems") or [])
                if it.get("price") is not None
            )
            min_price = (
                payload.get("globalMinPrice")
                or payload.get("asiaMinPrice")
                or (prices[0] if prices else None)
            )
            avg_price = prices[len(prices) // 2] if prices else None  # 중간값(≈50%)
            max_price = prices[-1] if prices else None  # 상위(≈90%)

        if min_price is not None or avg_price is not None:
            recommend = {
                "minPrice": min_price,
                "averagePrice": avg_price,
                "maxPrice": max_price,
                "global_sku_id": gid,
                "size": size,
                "collected_at": int(_time.time()),
            }
            ok += 1
        else:
            # 시세값을 못 얻음(조회 실패 or 가격 비어있음) → no_price 마킹(다음 실행 재시도 대상)
            recommend = {
                "no_price": True,
                "global_sku_id": gid,
                "size": size,
                "collected_at": int(_time.time()),
            }
            miss += 1

        payload = json.dumps(recommend, ensure_ascii=False)
        updated_rows += await save_price(code, payload)

        if i % 50 == 0:
            print(
                f"  [{i:,}/{total:,}] ok={ok:,} miss={miss:,} rl={rl:,} "
                f"갱신상품={updated_rows:,}"
            )
        await asyncio.sleep(SLEEP)

    print(
        f"\n완료: 처리 {ok + miss:,} / 시세수집 {ok:,} / 실패 {miss:,} "
        f"/ 레이트리밋스킵 {rl:,} / 갱신상품 {updated_rows:,}"
    )


if __name__ == "__main__":
    print(f"DB write host: {settings.write_db_host}")
    asyncio.run(main())
