"""소명/지재권 브랜드 엑셀 → samba_brand_restriction 적재.

쿠팡을 비롯한 마켓은 소명 대상 브랜드를 **수시로 추가한다.** 갱신된 엑셀을
받을 때마다 이 스크립트를 다시 돌리면 된다 — brand_key 기준 멱등이라
기존 행은 갱신되고 새 브랜드만 추가된다.

엑셀 형식 (쇼팡 제공 `쇼팡소명_지재권브랜드.xlsx`):
    A 브랜드 | B 소명대상 | C 지재권 대상 | D 마켓별 금지어 | E 비고

    - B "소명"   : 유통경로 소명 필요 → 차단
    - B "비소명" : 자유 판매 → 허용
    - C "지재권" : 지재권 신고 이력 → 차단
    - C "절대금지": 고발장 접수 등 → 차단
    - D/E        : 근거 기록용 (어느 마켓이 잡았는지, 대응 이력)

    파일 하단(빈 브랜드행 이후)에는 마켓별 금지어 문자열이 붙어 있는데,
    그건 금지어 체계(samba_forbidden_word)의 영역이라 여기서는 건너뛴다.

사용법:
    python -m backend.scripts.import_brand_restrictions --file <경로> --dry-run
    python -m backend.scripts.import_brand_restrictions --file <경로> --apply
"""

import argparse
import asyncio
import logging
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

warnings.filterwarnings("ignore", category=DeprecationWarning)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_FILE = r"D:\_경목\0. Tool\쇼팡소명_지재권브랜드.xlsx"

# 브랜드명이 아니라 구분선/금지어 뭉치인 행을 걸러내는 기준.
# 하단 마켓별 금지어 섹션은 한 셀에 세미콜론으로 수백 자가 들어온다.
_MAX_BRAND_LEN = 40


def _looks_like_brand(name: str) -> bool:
    s = (name or "").strip()
    if not s or len(s) > _MAX_BRAND_LEN:
        return False
    if s.startswith(("-", "*", ";", "■")):  # -쿠팡- 같은 구분선
        return False
    if ";" in s:  # 금지어 뭉치
        return False
    if "금지어" in s or "지재권신고" in s:
        return False
    return True


def _split_markets(cell: Any) -> list[str] | None:
    if not cell:
        return None
    parts = [p.strip() for p in str(cell).replace("/", ",").split(",")]
    out = [p for p in parts if p]
    return out or None


def _decide(soomyeong: str, ipr: str) -> tuple[str, str]:
    """(verdict, 사유) 판정.

    안전 우선 — 하나라도 위험 신호가 있으면 차단한다.
    '비소명'인데 지재권 이력이 있는 브랜드(레노마, 리복, 비비안웨스트우드 등)가
    실제로 존재하므로, 소명 컬럼만 보고 허용하면 안 된다.
    """
    if ipr == "절대금지":
        return "blocked", "절대금지(고발/삭제요청 이력)"
    if ipr == "지재권":
        return "blocked", "지재권 신고 이력"
    if soomyeong == "소명":
        return "blocked", "유통경로 소명 필요"
    if soomyeong == "비소명":
        return "allowed", "비소명 확인"
    return "unknown", "판정 정보 없음"


def parse_excel(path: Path) -> list[dict[str, Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    rows: list[dict[str, Any]] = []
    skipped = 0
    for rownum, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        raw = str(r[0]).strip() if r and r[0] else ""
        if not raw:
            continue
        if not _looks_like_brand(raw):
            skipped += 1
            continue
        soomyeong = str(r[1]).strip() if len(r) > 1 and r[1] else ""
        ipr = str(r[2]).strip() if len(r) > 2 and r[2] else ""
        markets = _split_markets(r[3] if len(r) > 3 else None)
        note = str(r[4]).strip() if len(r) > 4 and r[4] else ""
        verdict, reason = _decide(soomyeong, ipr)
        rows.append({
            "brand": raw,
            "soomyeong": soomyeong or None,
            "ipr": ipr or None,
            "markets": markets,
            "note": note or None,
            "verdict": verdict,
            "reason": reason,
            "rownum": rownum,
        })
    logger.info(f"엑셀 파싱: 브랜드 {len(rows)}건 (금지어·구분선 {skipped}행 건너뜀)")
    return rows


async def main(path: Path, apply: bool) -> int:
    from sqlmodel import select

    from backend.db.orm import get_write_session
    from backend.domain.samba.brand.model import (
        SambaBrandRestriction,
        normalize_brand,
    )

    if not path.exists():
        logger.error(f"파일 없음: {path}")
        return 1

    rows = parse_excel(path)
    if not rows:
        logger.error("적재할 브랜드가 없습니다.")
        return 1

    # 엑셀 안 중복 — 같은 브랜드가 두 번 나오면 위험한 쪽(blocked)을 남긴다
    by_key: dict[str, dict[str, Any]] = {}
    dupes = 0
    for row in rows:
        key = normalize_brand(row["brand"])
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = row
        else:
            dupes += 1
            rank = {"blocked": 0, "unknown": 1, "allowed": 2}
            if rank[row["verdict"]] < rank[prev["verdict"]]:
                by_key[key] = row
    if dupes:
        logger.info(f"중복 브랜드 {dupes}건 — 더 위험한 판정으로 병합")

    now = datetime.now(tz=timezone.utc)
    created = updated = unchanged = 0

    async with get_write_session() as session:
        existing = {
            r.brand_key: r
            for r in (await session.execute(select(SambaBrandRestriction)))
            .scalars()
            .all()
        }

        for key, row in by_key.items():
            detail = {"excel_row": row["rownum"], "file": path.name, "reason": row["reason"]}
            cur = existing.get(key)
            if cur is None:
                session.add(SambaBrandRestriction(
                    brand=row["brand"], brand_key=key, verdict=row["verdict"],
                    soomyeong=row["soomyeong"], ipr=row["ipr"],
                    markets=row["markets"], note=row["note"],
                    source="excel", source_detail=detail,
                    created_at=now, updated_at=now,
                ))
                created += 1
                continue

            changed = (
                cur.verdict != row["verdict"]
                or cur.soomyeong != row["soomyeong"]
                or cur.ipr != row["ipr"]
                or cur.note != row["note"]
                or cur.markets != row["markets"]
            )
            if not changed:
                unchanged += 1
                continue
            if cur.verdict != row["verdict"]:
                logger.info(
                    f"  판정 변경: {cur.brand} {cur.verdict} → {row['verdict']} ({row['reason']})"
                )
            cur.brand = row["brand"]
            cur.verdict = row["verdict"]
            cur.soomyeong = row["soomyeong"]
            cur.ipr = row["ipr"]
            cur.markets = row["markets"]
            cur.note = row["note"]
            cur.source = "excel"
            cur.source_detail = detail
            cur.updated_at = now
            session.add(cur)
            updated += 1

        from collections import Counter

        dist = Counter(r["verdict"] for r in by_key.values())
        logger.info("")
        logger.info("=== 판정 분포 ===")
        for v in ("blocked", "allowed", "unknown"):
            logger.info(f"  {v:8s} {dist.get(v, 0):4d}건")
        logger.info("")
        logger.info(f"신규 {created} / 갱신 {updated} / 변화없음 {unchanged}")

        if not apply:
            await session.rollback()
            logger.info("\n[dry-run] 저장하지 않았습니다. --apply 로 실행하세요.")
            return 0
        await session.commit()
        logger.info("\n저장 완료.")
        return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_FILE, help="엑셀 경로")
    ap.add_argument("--apply", action="store_true", help="실제 저장 (없으면 dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="저장 없이 확인만 (기본값)")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(Path(args.file), apply=args.apply)))
