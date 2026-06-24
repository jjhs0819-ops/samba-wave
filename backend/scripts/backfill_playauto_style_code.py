"""플레이오토 미등록 주문 style_code 일괄 백필.

source='playauto' + collected_product_id IS NULL 주문을 상품명 style_code로 매칭.
- 토큰 추출: 영문+숫자 혼합, 길이 6+, 순수숫자 제외
- 전체 토큰 1회 배치 CP 조회
- 가장 긴 토큰부터 단독 고유 매칭 (다중후보 skip)

사용: python backfill_playauto_style_code.py
"""

import asyncio
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app/backend")

from sqlalchemy import text  # noqa: E402

from backend.db.orm import get_write_session  # noqa: E402

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


def _style_tokens(name: str) -> list[str]:
    return [
        t
        for t in _TOKEN_RE.findall(name or "")
        if len(t) >= 6
        and any(c.isdigit() for c in t)
        and any(c.isalpha() for c in t)
    ]


async def main() -> None:
    async with get_write_session() as session:
        # 미등록 플레이오토 주문 조회
        null_rows = (
            await session.execute(
                text(
                    "SELECT id, product_name FROM samba_order "
                    "WHERE source = 'playauto' "
                    "AND collected_product_id IS NULL "
                    "AND product_name IS NOT NULL AND product_name != ''"
                )
            )
        ).fetchall()

        print(f"미등록 플레이오토 주문: {len(null_rows):,}건")
        if not null_rows:
            return

        # 전체 토큰 수집
        all_tokens: set[str] = set()
        order_tokens: list[tuple[str, list[str]]] = []
        for oid, pname in null_rows:
            tokens = _style_tokens(str(pname or ""))
            order_tokens.append((str(oid), tokens))
            all_tokens.update(tokens)

        print(f"고유 style_code 토큰: {len(all_tokens):,}개")
        if not all_tokens:
            print("추출 가능한 토큰 없음 — 종료")
            return

        # 토큰 → CP 배치 조회
        cp_rows = (
            await session.execute(
                text(
                    "SELECT id, style_code FROM samba_collected_product "
                    "WHERE style_code = ANY(:t)"
                ),
                {"t": list(all_tokens)},
            )
        ).fetchall()

        # 토큰 → [cp_id, ...] 인덱스
        token_to_cp: dict[str, list[str]] = {}
        for row in cp_rows:
            sc = str(row[1] or "")
            if sc:
                token_to_cp.setdefault(sc, []).append(str(row[0]))

        print(f"토큰 히트 CP: {len(token_to_cp):,}종")

        # 주문별 매칭
        linked = skipped_ambiguous = no_cp = 0
        for oid, tokens in order_tokens:
            if not tokens:
                no_cp += 1
                continue
            matched_cpid: str | None = None
            for tok in sorted(tokens, key=len, reverse=True):
                cands = token_to_cp.get(tok, [])
                if len(cands) == 1:
                    matched_cpid = cands[0]
                    break
                elif len(cands) > 1:
                    skipped_ambiguous += 1
                    break
            if matched_cpid:
                await session.execute(
                    text(
                        "UPDATE samba_order SET collected_product_id = :cpid "
                        "WHERE id = :oid AND collected_product_id IS NULL"
                    ),
                    {"cpid": matched_cpid, "oid": oid},
                )
                linked += 1
            else:
                no_cp += 1

            if (linked + skipped_ambiguous + no_cp) % 500 == 0:
                print(
                    f"  진행: linked={linked:,} ambiguous={skipped_ambiguous:,} "
                    f"no_cp={no_cp:,}"
                )

        await session.commit()

    print(
        f"\n완료: linked={linked:,} / ambiguous={skipped_ambiguous:,} / "
        f"no_cp={no_cp:,} / total={len(null_rows):,}"
    )


asyncio.run(main())
