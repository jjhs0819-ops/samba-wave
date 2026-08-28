"""buyma_backfill 로컬 검증 — 테스트 DB 에 실제와 같은 모양을 만들고 돌려본다.

운영 DB 는 로컬에서 접근이 안 되고, 백필은 4,753건을 한 번에 UPDATE 하는
작업이라 잘못 돌리면 되돌리기 어렵다. 특히 market_product_nos 는 크림·포이즌
등록번호가 같이 사는 dict 라, 바이마를 넣으면서 남의 값을 날리면 그 마켓의
수정·삭제가 전부 실패한다.

검증 항목:
  1. 정상 연결
  2. dry-run 이 DB 를 건드리지 않는가
  3. 다른 마켓 등록번호 보존
  4. 재실행 시 '이미 연결됨'
  5. 수집상품이 없는 매핑 건 처리
  6. registered_accounts 중복 추가 안 함
  7. buyma 아닌 계정 거부
  8. list 형태로 저장된 레코드(운영에 105건 존재) 복구
  9. 일문 상품명(name_ja) 채움 / --skip-name-ja
 10. --exclude 로 지정한 상품은 연결하지 않는다

usage:
  docker compose up -d test-db && python -m alembic upgrade head
  python -m scripts.buyma_backfill_verify

이 스크립트는 자기 테넌트의 데이터를 지우고 다시 만든다. 테스트 DB 가 아니면
시작하지 않는다.
"""

from __future__ import annotations

import asyncio
import csv
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import select, text

TENANT = "tn_test_backfill"
ACC_BUYMA = "ma_test_buyma"
ACC_OTHER = "ma_test_kream"
CSV = Path(__file__).parent / "_backfill_verify.csv"


def guard() -> None:
    """테스트 DB 가 아니면 멈춘다 — 이 스크립트는 DELETE 로 시작한다."""
    from backend.core.config import settings

    name = (settings.write_db_name or "").lower()
    if "test" not in name:
        print(f"중단: 테스트 DB 가 아니다 (write_db_name={name!r}).")
        print(
            "      docker compose up -d test-db 후 WRITE_DB_* 를 테스트 DB 로 지정할 것."
        )
        raise SystemExit(2)


# (site_product_id, 기존 market_product_nos, 기존 registered_accounts)
SEED = [
    ("7000001", {}, []),  # 정상
    ("7000002", {ACC_OTHER: "K-111"}, [ACC_OTHER]),  # 타 마켓 보존
    ("7000003", {ACC_BUYMA: "999"}, [ACC_BUYMA]),  # 값이 바뀌는 경우
    ("7000004", {ACC_BUYMA: "136000004"}, [ACC_BUYMA]),  # 이미 연결됨
    ("7000005", [None, {ACC_OTHER: "K-555"}], [ACC_OTHER]),  # list 형태 레코드
]
MAPPING = [
    ("136000001", "7000001", "COVERNAT ロゴ スウェット ブラック"),
    ("136000002", "7000002", "COVERNAT ニット アイボリー"),
    ("136000003", "7000003", "mahagrid スウェット ネイビー"),
    ("136000004", "7000004", "KODAK グラフィック スウェット グレー"),
    ("136000005", "7000005", "LMC クルーネック ニット ベージュ"),
    ("136000009", "7999999", "없는상품"),  # 수집된 적 없는 상품
]

FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(f"  {'OK  ' if cond else 'FAIL'}  {msg}")
    if not cond:
        FAIL.append(msg)


async def seed() -> None:
    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.account.model import SambaMarketAccount
    from backend.domain.samba.collector.model import SambaCollectedProduct

    Session = get_write_sessionmaker()
    async with Session() as s:
        await s.execute(
            text("DELETE FROM samba_collected_product WHERE tenant_id = :t"),
            {"t": TENANT},
        )
        await s.execute(
            text("DELETE FROM samba_market_account WHERE tenant_id = :t"),
            {"t": TENANT},
        )
        s.add(
            SambaMarketAccount(
                id=ACC_BUYMA,
                tenant_id=TENANT,
                market_type="buyma",
                market_name="바이마",
                account_label="테스트 바이마",
            )
        )
        s.add(
            SambaMarketAccount(
                id=ACC_OTHER,
                tenant_id=TENANT,
                market_type="kream",
                market_name="크림",
                account_label="테스트 크림",
            )
        )
        for spid, nos, accs in SEED:
            s.add(
                SambaCollectedProduct(
                    tenant_id=TENANT,
                    source_site="musinsa",
                    site_product_id=spid,
                    name=f"테스트상품 {spid}",
                    market_product_nos=nos,
                    registered_accounts=accs,
                )
            )
        await s.commit()

    with CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["buyma_product_id", "musinsa_goods_no", "buyma_name"])
        w.writerows(MAPPING)


async def snapshot() -> dict:
    from backend.db.orm import get_write_sessionmaker
    from backend.domain.samba.collector.model import (
        SambaCollectedProduct,
        as_market_nos,
    )

    Session = get_write_sessionmaker()
    async with Session() as s:
        rows = (
            (
                await s.execute(
                    select(SambaCollectedProduct).where(
                        SambaCollectedProduct.tenant_id == TENANT
                    )
                )
            )
            .scalars()
            .all()
        )
        return {
            r.site_product_id: (
                as_market_nos(r.market_product_nos),
                sorted(r.registered_accounts or []),
                r.name_ja,
                r.name,
            )
            for r in rows
        }


def run(*args: str) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "scripts.buyma_backfill", "--csv", str(CSV), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    return (r.stdout or "") + (r.stderr or "")


async def main() -> int:
    guard()
    await seed()
    before = await snapshot()
    print(f"시드 {len(before)}건\n")

    print("[1] dry-run")
    out = run("--account", ACC_BUYMA, "--dry-run")
    print("   ", " | ".join(x.strip() for x in out.splitlines() if "  " in x)[:200])
    check(await snapshot() == before, "dry-run 이 DB 를 바꾸지 않는다")
    check("연결" in out and "일문명 채움" in out, "dry-run 이 예정 건수를 보고한다")
    check("수집상품 없음" in out, "수집된 적 없는 매핑을 구분한다")

    print("\n[2] apply")
    out = run("--account", ACC_BUYMA, "--apply")
    print("   ", " | ".join(x.strip() for x in out.splitlines() if "  " in x)[:200])
    after = await snapshot()
    check(after["7000001"][0].get(ACC_BUYMA) == "136000001", "새 상품 연결")
    check(ACC_BUYMA in after["7000001"][1], "registered_accounts 추가")
    check(after["7000002"][0].get(ACC_OTHER) == "K-111", "타 마켓 등록번호 보존")
    check(after["7000002"][0].get(ACC_BUYMA) == "136000002", "타 마켓 있는 상품에 연결")
    check(
        sorted(after["7000002"][1]) == sorted([ACC_OTHER, ACC_BUYMA]),
        "타 마켓 계정 보존 + 바이마 추가",
    )
    check(after["7000003"][0].get(ACC_BUYMA) == "136000003", "잘못된 값 갱신")
    check(after["7000005"][0].get(ACC_OTHER) == "K-555", "list 레코드의 타 마켓 보존")
    check(
        after["7000005"][0].get(ACC_BUYMA) == "136000005", "list 레코드에 바이마 연결"
    )
    check(
        all(len(v[1]) == len(set(v[1])) for v in after.values()),
        "registered_accounts 중복 없음",
    )
    jp = {m[1]: m[2] for m in MAPPING}
    check(
        all(after[k][2] == jp[k] for k in after),
        "일문 상품명(name_ja) 이 바이마 등록명으로 채워짐",
    )
    check(
        all(after[k][3] == before[k][3] for k in after),
        "원 상품명(name) 은 건드리지 않음",
    )

    print("\n[3] 재실행(멱등)")
    out = run("--account", ACC_BUYMA, "--apply")
    line = next((x for x in out.splitlines() if "이미 연결됨" in x), "")
    print("   ", line.strip())
    check(await snapshot() == after, "재실행해도 DB 가 그대로다")
    check("이미 연결됨" in out and "5" in line, "5건 전부 이미 연결됨으로 집계")

    print("\n[4] --exclude")
    ex = CSV.parent / "_backfill_verify_exclude.json"
    ex.write_text(json.dumps(["7000001"]), encoding="utf-8")
    # 이미 연결된 상태라 값은 어차피 그대로다. 확인할 것은 제외 건수를
    # 보고하는지, 그리고 제외한 상품을 건드리지 않는지다.
    out = run("--account", ACC_BUYMA, "--apply", "--exclude", str(ex))
    check("1건 제외" in out, "--exclude 가 제외 건수를 보고한다")
    check(await snapshot() == after, "제외한 상품은 손대지 않는다")
    ex.unlink(missing_ok=True)

    # 옵션을 안 붙여도 기본 목록(scripts/data/buyma_excluded_nos.json)이 걸려야
    # 한다. 사람이 잊는 쪽에 걸면 내렸던 상품이 되살아난다.
    from scripts.buyma_backfill import DEFAULT_EXCLUDE

    out = run("--account", ACC_BUYMA, "--dry-run")
    check(
        DEFAULT_EXCLUDE.exists() and DEFAULT_EXCLUDE.name in out,
        "옵션 없이도 기본 제외목록을 읽는다",
    )

    print("\n[5] --skip-name-ja")
    run("--account", ACC_BUYMA, "--apply", "--skip-name-ja")
    check(await snapshot() == after, "--skip-name-ja 는 일문명을 건드리지 않는다")

    print("\n[6] 잘못된 계정")
    out = run("--account", ACC_OTHER, "--dry-run")
    check("market_type 가 buyma 가 아님" in out, "buyma 아닌 계정 거부")
    out = run("--account", "ma_없는계정", "--dry-run")
    check("계정 없음" in out, "존재하지 않는 계정 거부")

    print()
    if FAIL:
        print(f"실패 {len(FAIL)}건")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    print("전 항목 통과")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
