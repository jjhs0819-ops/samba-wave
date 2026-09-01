"""바이마 오토튠 가동 준비 — 백필(PR #759) 배포 후 프로덕션에서 실행.

오토튠이 바이마 재고/가격을 자동반영하려면 3가지가 필요하다:
  1) 백필: registered_accounts=buyma (← PR #759, 이 스크립트 밖)
  2) 오토튠 설정에 buyma 켜기       (← 이 스크립트 --enable)
  3) 바이마 계정에 PS-API 토큰       (← 이 스크립트 --set-token)
코드 배선(BuymaPlugin.execute/delete)은 이미 완성돼 있어 이 3개만 채우면 가동된다.

사용법(프로덕션 backend/ 에서):
  python scripts/prep_buyma_autotune.py                      # 현황 조회(읽기전용, 안전)
  python scripts/prep_buyma_autotune.py --enable             # autotune_enabled_markets에 buyma 추가
  python scripts/prep_buyma_autotune.py --set-token-file token.json   # 토큰 주입(파일: {"access_token": "..."})
  python scripts/prep_buyma_autotune.py --set-token "eyJ..."          # 토큰 직접 주입
  # 계정이 여러 개면 --account-id ma_xxx 로 지정
"""

import argparse
import asyncio
import json
import sys

try:  # Windows cp949 콘솔에서 이모지/특수문자 print 크래시 방지
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlmodel import select

from backend.api.v1.routers.samba.proxy import _get_setting, _set_setting
from backend.db.orm import get_read_session, get_write_session
from backend.domain.samba.account.model import SambaMarketAccount

MARKETS_KEY = "autotune_enabled_markets"


async def _buyma_accounts(session):
    stmt = select(SambaMarketAccount).where(SambaMarketAccount.market_type == "buyma")
    return list((await session.execute(stmt)).scalars().all())


async def show_status() -> None:
    async with get_read_session() as s:
        markets = await _get_setting(s, MARKETS_KEY)
        accts = await _buyma_accounts(s)
        # 세션 안에서 스칼라값을 모두 추출 — 세션 밖 lazy-load(DetachedInstanceError) 방지
        acct_rows = [
            {
                "id": a.id,
                "label": a.account_label,
                "active": a.is_active,
                "default": a.is_default,
                "tenant": a.tenant_id,
                "sandbox": bool((a.additional_fields or {}).get("sandbox"))
                if isinstance(a.additional_fields, dict)
                else False,
                "token": a.oauth_access_token or "",
            }
            for a in accts
        ]

    print("=== 오토튠 마켓 필터 (autotune_enabled_markets) ===")
    if markets is None:
        print(
            "  value=None → '전체 허용' 상태. buyma 이미 대상에 포함됨 (--enable 불필요)."
        )
    elif isinstance(markets, list):
        has = "buyma" in markets
        print(f"  {markets}")
        print(f"  buyma 포함: {'예 (OK)' if has else '아니오 → --enable 필요'}")
    else:
        print(f"  ⚠️ 예상밖 형식: {markets!r}")

    print(f"\n=== 바이마 계정 (market_type=buyma) {len(acct_rows)}개 ===")
    if not acct_rows:
        print("  ⚠️ 계정 없음 — 먼저 바이마 마켓 계정을 만들어야 토큰 주입/등록 가능.")
    for a in acct_rows:
        tok = a["token"]
        print(
            f"  id={a['id']} label={a['label']!r} active={a['active']} default={a['default']} "
            f"tenant={a['tenant']} sandbox={a['sandbox']} "
            f"token={'있음(' + str(len(tok)) + '자)' if tok else '없음 → --set-token 필요'}"
        )


async def enable_market() -> None:
    async with get_write_session() as s:
        cur = await _get_setting(s, MARKETS_KEY)
        if cur is None:
            print("필터=None(전체 허용) → buyma 이미 포함. 변경 불필요.")
            return
        if not isinstance(cur, list):
            print(f"⚠️ 예상밖 형식이라 중단: {cur!r}")
            return
        if "buyma" in cur:
            print(f"이미 포함됨: {cur}")
            return
        new = list(cur) + ["buyma"]  # 새 리스트로 할당(JSON 변경감지 보장)
        await _set_setting(s, MARKETS_KEY, new)
        await s.commit()
        print(f"✅ buyma 추가: {cur} → {new}")


async def set_token(token: str, account_id: str | None) -> None:
    token = (token or "").strip()
    if not token:
        print("⚠️ 토큰이 비어있음 — 중단.")
        return
    async with get_write_session() as s:
        accts = await _buyma_accounts(s)
        if account_id:
            accts = [a for a in accts if a.id == account_id]
        if not accts:
            print("⚠️ 대상 바이마 계정 없음 (계정 생성 또는 --account-id 확인).")
            return
        if len(accts) > 1:
            print(f"⚠️ 바이마 계정 {len(accts)}개 — --account-id 로 지정 필요:")
            for a in accts:
                print(f"   {a.id}  label={a.account_label!r} default={a.is_default}")
            return
        acc = accts[0]
        aid, alabel = (
            acc.id,
            acc.account_label,
        )  # commit 후 expired 접근 방지: 미리 저장
        acc.oauth_access_token = token
        s.add(acc)
        await s.commit()
        print(f"✅ 토큰 주입 완료: id={aid} label={alabel!r} ({len(token)}자)")


def _read_token_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        raw = f.read().strip()
    try:
        data = json.loads(raw)
        return data.get("access_token") or data.get("accessToken") or ""
    except json.JSONDecodeError:
        return raw  # 순수 토큰 문자열


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--enable", action="store_true", help="autotune_enabled_markets에 buyma 추가"
    )
    ap.add_argument("--set-token", default=None, help="PS-API 액세스 토큰 직접 주입")
    ap.add_argument(
        "--set-token-file",
        default=None,
        help='토큰 파일 경로({"access_token":"..."} 또는 순수 토큰)',
    )
    ap.add_argument(
        "--account-id", default=None, help="바이마 계정 여러 개일 때 대상 id (ma_...)"
    )
    args = ap.parse_args()

    did = False
    if args.enable:
        await enable_market()
        did = True
    if args.set_token or args.set_token_file:
        tok = args.set_token or _read_token_file(args.set_token_file)
        await set_token(tok, args.account_id)
        did = True
    if not did:
        await show_status()
    else:
        print("\n--- 실행 후 현황 ---")
        await show_status()


if __name__ == "__main__":
    asyncio.run(main())
