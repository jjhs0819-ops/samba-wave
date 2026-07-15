"""스니덩크↔크림 매칭 반자동 복구 — 백업 jsonl 기반.

안전원칙(오매칭 수정 보존):
  - **삭제돼서 DB에 아예 없는 스니덩 row만** 재생성한다.
  - 스니덩 row 가 현재 존재하면 절대 건드리지 않는다(사용자 수정 보존).
  - 해당 크림id 가 이미 다른 스니덩에 매칭돼 있으면 건드리지 않는다(재매칭 보존).
  - 기본 DRY-RUN. --apply 있을 때만 실제 재생성+주문재연결.

대상 탐지: collected_product_id='DELETED' 인 크림 주문의 product_id → 백업에서 스니덩id 역조회.
컨테이너 안에서 실행(SnkrdunkClient·DB 필요). restore.ps1 이 백업파일을 cp 후 호출.
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import text

from backend.db.orm import get_write_session
from backend.domain.samba.collector.repository import (
    SambaCollectedProductRepository,
    SambaSearchFilterRepository,
)
from backend.domain.samba.collector.service import SambaCollectorService
from backend.domain.samba.proxy.snkrdunk import SnkrdunkClient


def _load_backup(path: str) -> dict[str, dict]:
    """백업 jsonl → {kream_id: {snkr_id, name, ...}}"""
    kmap: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("kream_id") and d.get("snkr_id"):
                kmap[str(d["kream_id"])] = d
    return kmap


async def main(path: str, apply: bool) -> None:
    kmap = _load_backup(path)
    print(f"백업 로드: {len(kmap):,}개 매핑 ({path})")

    async with get_write_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT DISTINCT product_id, tenant_id FROM samba_order "
                    "WHERE source_site='KREAM' AND collected_product_id='DELETED' "
                    "  AND product_id IS NOT NULL"
                )
            )
        ).fetchall()

        targets: list[tuple[str, str, str, str]] = []
        for kream_id, tenant_id in rows:
            kream_id = str(kream_id)
            info = kmap.get(kream_id)
            if not info:
                print(f"[백업없음] 크림 {kream_id} — 백업에 스니덩id 없음(수동 URL 필요)")
                continue
            snkr_id = str(info["snkr_id"])

            # 현재 이 스니덩 row 존재? → 존재하면 보존(건드리지 않음)
            exists = (
                await session.execute(
                    text(
                        "SELECT 1 FROM samba_collected_product "
                        "WHERE source_site='SNKRDUNK' AND site_product_id=:sid"
                    ),
                    {"sid": snkr_id},
                )
            ).first()
            if exists:
                print(f"[스킵] snkr {snkr_id} 이미 존재 — 현재 상태 보존")
                continue

            # 이 크림이 이미 다른 스니덩에 매칭됨? → 재매칭 보존
            other = (
                await session.execute(
                    text(
                        "SELECT site_product_id FROM samba_collected_product "
                        "WHERE source_site='SNKRDUNK' "
                        "  AND resell_matches->'kream'->>'product_id'=:kid"
                    ),
                    {"kid": kream_id},
                )
            ).first()
            if other:
                print(f"[스킵] 크림 {kream_id} 이미 snkr {other[0]} 매칭 — 보존")
                continue

            kname = info.get("kream_name_ko") or info.get("name") or ""
            targets.append((snkr_id, kream_id, kname, str(tenant_id)))

        if not targets:
            print("\n복구 대상 없음.")
            return

        print(f"\n=== 복구 대상 {len(targets)}건 ===")
        for s, k, n, _t in targets:
            print(f"  snkr {s} → 크림 {k} | {n}")

        if not apply:
            print("\n[DRY-RUN] --apply 붙이면 실제 복구. 지금은 미실행.")
            return

        client = SnkrdunkClient()
        now_iso = datetime.now(timezone.utc).isoformat()
        repo = SambaCollectedProductRepository(session)
        svc = SambaCollectorService(SambaSearchFilterRepository(session), repo)

        for snkr_id, kream_id, kname, tenant_id in targets:
            detail = await client.get_trading_card_detail(snkr_id)
            if not detail.get("name") or not detail.get("images"):
                print(f"[실패] snkr {snkr_id} 데이터 부족")
                continue
            detail["tenant_id"] = tenant_id
            detail["lock_delete"] = True
            detail["resell_matches"] = {
                "kream": {
                    "product_id": kream_id,
                    "name_ko": kname,
                    "name_en": detail.get("name_en", ""),
                    "style_code": detail.get("style_code", ""),
                    "verified": True,
                    "confidence": 100,
                    "matched_by": ["backup_restore"],
                    "matched_at": now_iso,
                }
            }
            cp = await svc.create_collected_product(detail)
            if cp is None:
                print(f"[실패] snkr {snkr_id} 생성 실패")
                continue
            await session.commit()
            res = await session.execute(
                text(
                    "UPDATE samba_order SET collected_product_id=:cid "
                    "WHERE source_site='KREAM' AND product_id=:kid "
                    "  AND collected_product_id='DELETED'"
                ),
                {"cid": cp.id, "kid": kream_id},
            )
            await session.commit()
            print(
                f"[복구] snkr {snkr_id} → cp {cp.id} | 크림 {kream_id} | "
                f"주문 {res.rowcount}건 재연결"
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("backup", help="백업 jsonl 경로")
    ap.add_argument("--apply", action="store_true", help="실제 복구 실행(없으면 DRY-RUN)")
    a = ap.parse_args()
    asyncio.run(main(a.backup, a.apply))
