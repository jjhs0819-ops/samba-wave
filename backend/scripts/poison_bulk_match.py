"""POIZON 품번 벌크 매칭 — 매칭 가능 소싱처만, resumable + 레이트리밋.

소싱처 ABCmart/FashionPlus/LOTTEON/manual 의 고유 품번을 POIZON 카탈로그에 조회,
매칭되면 같은 style_code 의 모든 상품에 resell_matches.poison 저장.

- resumable: 이미 poison 매칭 있는 상품 제외
- 레이트리밋: 호출당 SLEEP 초
- 서킷브레이커: 연속 실패 N회 시 중단 (IP차단/레이트리밋 보호)
- 진행: 매 50건 로그

사용: python poison_bulk_match.py [LIMIT]   (LIMIT=처리할 고유품번 수, 미지정=전체)
"""

import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.core.config import settings  # noqa: E402
from backend.db.orm import get_read_session, get_write_session  # noqa: E402
from backend.domain.samba.proxy.poison import PoisonClient  # noqa: E402

# 전 소싱처 전수 시도 (POIZON 카탈로그가 매칭여부 판정 — 미취급 브랜드는 자동 miss)
SLEEP = 0.1  # 한도 상향됨(20/s·864k/day) — 0.1s+HTTP지연이면 ~2/s로 충분히 안전
CIRCUIT_FAIL = 30  # 연속 진짜에러/레이트리밋 시 중단
RL_BACKOFF = 5.0  # 레이트리밋(400010007)/연결에러 기본 대기초
MAX_RETRY = 6  # 재시도 횟수


def _parse_skus(data):
    """SPU 응답 → 사이즈별 globalSkuId 추출."""
    out = []
    for spu in data or []:
        for sku in spu.get("skuInfoList") or []:
            gid = sku.get("globalSkuId")
            if not gid:
                continue
            sv = ""
            for pv in sku.get("regionSalePvInfoList") or []:
                if pv.get("level") == 2 and pv.get("value"):
                    sv = str(pv["value"]).strip()
            out.append({"globalSkuId": int(gid), "sizeValue": sv})
    return out


async def fetch_with_backoff(client, article):
    """레이트리밋·연결에러 백오프 포함 품번 조회 → (status, skus).

    status: 'hit'(매칭), 'miss'(진짜 무매칭), 'ratelimited'(재시도소진), 'error'.
    400010007(빈도초과)·연결throttle은 miss로 안 셈 — 대기 후 재시도.
    """
    import httpx

    for attempt in range(MAX_RETRY):
        try:
            raw = await client._post(
                client.PATH_SKU_BY_ARTICLE,
                {"articleNumber": article, "region": "KR", "language": "ko"},
            )
        except httpx.HTTPError:
            # 연결 throttle/타임아웃/네트워크 → 백오프 재시도(miss 아님)
            await asyncio.sleep(RL_BACKOFF * (attempt + 1))
            continue
        code = raw.get("code")
        if code == 200:
            skus = _parse_skus(raw.get("data") or [])
            return ("hit" if skus else "miss", skus)
        if str(code) == "400010007":  # 빈도초과 → 백오프 재시도
            await asyncio.sleep(RL_BACKOFF * (attempt + 1))
            continue
        await asyncio.sleep(2)  # 기타 에러 → 짧게 재시도
    return ("ratelimited", [])


async def load_creds():
    """프로덕션 플러그인과 동일 경로(PoisonPlugin._load_auth)로 인증 로드.

    poison 마켓 계정의 additional_fields 에서 app_key/secret 을 가져온다.
    (시크릿 출력/노출 없음 — 클라이언트 생성에만 사용)
    """
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


async def fetch_articles(limit=None):
    """매칭 대상 고유 품번 — 매칭이력 브랜드(=POIZON 매칭되는 브랜드) 집중, 미처리만.

    레이트리밋 예산을 hit율 높은 브랜드에 집중(나이키/아디다스/노스페이스 등).
    매칭이 늘면 브랜드 집합도 자동 확장(다음 실행 시 재계산).
    """
    async with get_read_session() as s:
        # POIZON 매칭이력 있는 브랜드 집합
        mb = (
            await s.execute(
                text(
                    "SELECT DISTINCT btrim(brand) b FROM samba_collected_product "
                    "WHERE resell_matches -> 'poison' ->> 'product_id' <> '' "
                    "AND brand IS NOT NULL AND btrim(brand) <> ''"
                )
            )
        ).all()
        brands = [x.b for x in mb]
        if not brands:
            return [], []
        sql = """
            SELECT btrim(style_code) AS code, COUNT(*) AS n
            FROM samba_collected_product
            WHERE btrim(brand) = ANY(:brands)
              AND style_code IS NOT NULL AND btrim(style_code) <> ''
              AND (resell_matches IS NULL OR resell_matches -> 'poison' IS NULL)
            GROUP BY btrim(style_code)
            ORDER BY n DESC
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = (await s.execute(text(sql), {"brands": brands})).all()
        return [(r.code, r.n) for r in rows], brands


async def build_code_to_ids(brands):
    """품번(btrim style_code) → [상품 id] 맵 1회 구축.

    btrim(style_code) 는 인덱스가 없어 매 UPDATE마다 풀스캔(5s/건)이라 느림.
    시작 시 단 1회 스캔으로 맵을 만들고, 이후 UPDATE는 id(PK)로 빠르게 처리.
    """
    code_map = {}
    async with get_read_session() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, btrim(style_code) sc FROM samba_collected_product "
                    "WHERE btrim(brand) = ANY(:brands) "
                    "AND style_code IS NOT NULL AND btrim(style_code) <> ''"
                ),
                {"brands": brands},
            )
        ).all()
    for r in rows:
        code_map.setdefault(r.sc, []).append(r.id)
    return code_map


async def save_match(ids, payload_json):
    """주어진 상품 id들에 resell_matches.poison 병합 저장 (id=PK 인덱스, 빠름)."""
    if not ids:
        return 0
    async with get_write_session() as s:
        # CAST(:p AS jsonb) — ':p::jsonb' placeholder 충돌 금지(CLAUDE.md)
        sql = text(
            """
            UPDATE samba_collected_product
            SET resell_matches =
                COALESCE(resell_matches, '{}'::jsonb)
                || jsonb_build_object('poison', CAST(:p AS jsonb))
            WHERE id = ANY(:ids)
            """
        )
        res = await s.execute(sql, {"p": payload_json, "ids": ids})
        await s.commit()
        return res.rowcount


async def main():
    import json
    import time as _time

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    articles, brands = await fetch_articles(limit)
    total = len(articles)
    print(f"매칭 대상 고유 품번: {total:,} (집중 브랜드, 미처리만)")
    if not total:
        print("처리할 품번 없음 (전부 매칭 완료 or 대상 없음)")
        return

    # 품번→[id] 맵 1회 구축 (UPDATE를 PK로 빠르게 — btrim 풀스캔 회피)
    code_map = await build_code_to_ids(brands)
    print(f"품번→id 맵 구축 완료 ({len(code_map):,} 품번)")

    app_key, app_secret = await load_creds()
    client = PoisonClient(app_key=app_key, app_secret=app_secret)
    hit = miss = rl = updated_rows = 0
    consec_rl = 0

    for i, (code, n) in enumerate(articles, 1):
        article = code.split(",")[0].strip()  # manual 콤마 다건 → 첫 품번
        status, skus = await fetch_with_backoff(client, article)

        # 레이트리밋/연결throttle(재시도 소진) → 마킹 안 함(다음 실행 재시도), 길게 쉼
        if status == "ratelimited":
            rl += 1
            consec_rl += 1
            if consec_rl >= CIRCUIT_FAIL:
                print(f"!! 레이트리밋 {CIRCUIT_FAIL}회 연속 — 중단(나중 재실행)")
                break
            await asyncio.sleep(RL_BACKOFF * 3)
            continue
        consec_rl = 0

        if status == "hit":
            # POIZON 카탈로그(사이즈→globalSkuId) 저장
            catalog = {}
            for sk in skus:
                sv = (sk.get("sizeValue") or "").strip()
                if sv and sk.get("globalSkuId"):
                    catalog[sv] = sk["globalSkuId"]
            payload = json.dumps(
                {
                    "product_id": article,
                    "confidence": 100,
                    "articleNumber": article,
                    "catalog": catalog,
                    "matched_at": int(_time.time()),
                },
                ensure_ascii=False,
            )
            hit += 1
        else:
            # 미매칭도 마킹 — 재실행 시 재시도 방지(수렴 보장). product_id 없음 → UI '미매칭'
            payload = json.dumps(
                {
                    "confidence": 0,
                    "no_match": True,
                    "articleNumber": article,
                    "matched_at": int(_time.time()),
                },
                ensure_ascii=False,
            )
            miss += 1
        rc = await save_match(code_map.get(code, []), payload)
        updated_rows += rc

        if i % 50 == 0:
            print(
                f"  [{i:,}/{total:,}] hit={hit:,} miss={miss:,} rl={rl:,} "
                f"갱신상품={updated_rows:,}"
            )
        await asyncio.sleep(SLEEP)

    print(
        f"\n완료: 처리 {hit + miss:,} / 매칭 {hit:,} / 미매칭 {miss:,} "
        f"/ 레이트리밋스킵 {rl:,} / 갱신상품 {updated_rows:,}"
    )


if __name__ == "__main__":
    print(f"DB write host: {settings.write_db_host}")
    asyncio.run(main())
