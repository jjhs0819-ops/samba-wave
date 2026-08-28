"""바이마 오토튠 PS-API 계층 로컬 검증 — 샌드박스 왕복 스모크테스트.

오토튠은 재고/가격 변동 시 BuymaPlugin.execute → BuymaApiClient.register_product
(products.json control=publish)로 반영하고, 품절 전멸 시 delete → set_control("delete")
로 내린다. 이 스크립트는 그 PS-API 계층을 **샌드박스**에서 실제 왕복시켜,
"오토튠이 바이마에 제대로 반영되는지"를 실전 상품 손상 없이 로컬 검증한다.

전제(로컬 DB 기준):
  1) market_type=buyma 계정 + 샌드박스 토큰(oauth_access_token, sandbox=True)
     → prep_buyma_autotune.py --set-token 으로 주입 가능
  2) registered_accounts=<buyma acc id> 인 SambaCollectedProduct 최소 1건 (백필 후)

검증 흐름(상품 1건):
  register_product(control=publish) → set_control(suspend) → set_control(delete)
  세 왕복이 200/201 이면 오토튠 PS-API 경로 정상.

사용법(로컬 backend/):
  python scripts/verify_buyma_autotune_local.py                 # 현황 + 검증대상 조회(읽기전용)
  python scripts/verify_buyma_autotune_local.py --go            # 샌드박스 왕복 검증 실행(1건)
  python scripts/verify_buyma_autotune_local.py --go --limit 3  # 3건
  python scripts/verify_buyma_autotune_local.py --go --keep     # delete 생략(샌드박스에 남겨 확인)
⚠️ 안전장치: 계정 sandbox=True 가 아니면 --go 를 거부한다(실전 상품 보호).
"""

import argparse
import asyncio
import sys

try:  # Windows cp949 콘솔에서 이모지/특수문자 print 크래시 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import text as _text
from sqlmodel import select

from backend.db.orm import get_read_session
from backend.domain.samba.account.credentials import buyma_creds
from backend.domain.samba.account.model import SambaMarketAccount
from backend.domain.samba.collector.model import SambaCollectedProduct


async def _buyma_account(session, account_id: str | None):
    stmt = select(SambaMarketAccount).where(SambaMarketAccount.market_type == "buyma")
    if account_id:
        stmt = stmt.where(SambaMarketAccount.id == account_id)
    return list((await session.execute(stmt)).scalars().all())


async def _registered_products(session, acc_id: str, limit: int):
    # registered_accounts(JSONB) @> [acc_id] — GIN 인덱스 활용
    stmt = (
        select(SambaCollectedProduct)
        .where(
            _text("registered_accounts @> jsonb_build_array(:aid)").bindparams(
                aid=acc_id
            )
        )
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


def _is_sandbox(acc) -> bool:
    af = acc.additional_fields if isinstance(acc.additional_fields, dict) else {}
    return bool(af.get("sandbox"))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--go", action="store_true", help="샌드박스 왕복 검증 실행 (없으면 조회만)"
    )
    ap.add_argument("--limit", type=int, default=1, help="검증할 상품 수")
    ap.add_argument("--keep", action="store_true", help="delete 생략(샌드박스에 남김)")
    ap.add_argument("--account-id", default=None)
    args = ap.parse_args()

    async with get_read_session() as session:
        accts = await _buyma_account(session, args.account_id)
        if not accts:
            print("⚠️ market_type=buyma 계정 없음 — 계정 생성 후 토큰 주입 필요.")
            return
        if len(accts) > 1:
            print(f"⚠️ buyma 계정 {len(accts)}개 — --account-id 지정 필요:")
            for a in accts:
                print(f"   {a.id} label={a.account_label!r} sandbox={_is_sandbox(a)}")
            return
        acc = accts[0]
        creds = buyma_creds(acc)
        token = creds.get("accessToken", "")
        sandbox = _is_sandbox(acc)
        prods = await _registered_products(session, acc.id, args.limit)
        # 세션 안에서 dict 추출 — 세션 밖 model_dump/속성접근(DetachedInstanceError) 방지
        prod_data = [
            {"id": p.id, "name": (p.name_ja or p.name or ""), "dump": p.model_dump()}
            for p in prods
        ]

        print("=== 검증 대상 ===")
        print(
            f"  계정: {acc.id} label={acc.account_label!r} sandbox={sandbox} token={'있음' if token else '없음'}"
        )
        print(f"  registered=buyma 상품: {len(prods)}건 (limit={args.limit})")
        for p in prods:
            print(f"    - {p.id} {(p.name_ja or p.name or '')[:30]}")

        if not args.go:
            print("\n(조회만 — 실제 왕복은 --go)")
            return

        # 안전장치: 샌드박스 아니면 거부
        if not sandbox:
            print("\n⛔ 계정이 sandbox=True 가 아님 — 실전 상품 보호를 위해 --go 거부.")
            print(
                "   샌드박스 계정으로 검증하거나 additional_fields.sandbox=true 확인."
            )
            return
        if not token:
            print(
                "\n⛔ 토큰 없음 — prep_buyma_autotune.py --set-token 으로 주입 후 재시도."
            )
            return
        if not prods:
            print("\n⛔ registered=buyma 상품 없음 — 백필(PR #759) 후 재시도.")
            return

    # 왕복 검증 (샌드박스)
    from backend.domain.samba.proxy.buyma import BuymaApiClient

    client = BuymaApiClient(
        token,
        sandbox=True,
        client_id=creds.get("clientId", ""),
        client_secret=creds.get("clientSecret", ""),
    )
    ok = 0
    for it in prod_data:
        pd = it["dump"]
        ref = str(it["id"])
        print(f"\n--- {ref} {it['name'][:30]} ---")
        reg = await client.register_product(pd, control="publish")
        print(
            f"  register(publish): success={reg.get('success')} {reg.get('message', '')[:80]}"
        )
        if not reg.get("success"):
            print(f"    error_type={reg.get('error_type')}")
            continue
        rn = reg.get("reference_number") or ref
        susp = await client.set_control(rn, "suspend")
        print(
            f"  set_control(suspend): {susp.get('success')} {susp.get('message', '')[:60]}"
        )
        if not args.keep:
            dele = await client.set_control(rn, "delete")
            print(
                f"  set_control(delete): {dele.get('success')} {dele.get('message', '')[:60]}"
            )
        if reg.get("success") and susp.get("success"):
            ok += 1

    print(f"\n=== 결과: {ok}/{len(prods)} 왕복 성공 ===")
    print(
        "오토튠 PS-API 경로(register/suspend/delete) 정상"
        if ok == len(prods) and ok
        else "⚠️ 일부 실패 — 위 로그 확인"
    )


if __name__ == "__main__":
    asyncio.run(main())
