"""반품행 마감(종결) 서비스 (T7 — 2026-09-03).

사장님 흐름: 소싱처 반품완료 확인 → 마켓에서도 완료처리 → 그 건은 완전히 끝
→ 반품탭에서 안 보여야 함. '마감'은 completion_detail(어떻게 끝났나:
취소/반품/교환/거부)과 직교하는 축('내가 처리를 끝냈나')이므로 별도 컬럼
(closed_at/closed_by)으로 관리한다.

설계 원칙 — 자동 마감을 나중에 붙이기 쉽게 이 모듈 한 곳에 몰아둔다:
  - close_returns(..., by='manual')  ← 지금은 반품탭 버튼(수동)만 사용
  - auto_close_candidates(...)       ← 스텁. 몸통만 채우고
    close_returns(..., by='auto') 를 호출하면 자동 마감 완성.

마감행 보호는 각 동기화 경로에 있다:
  - returns.py::_backfill_returns_from_claim_orders — 마감행도 '기존 행'으로
    세어 재생성 안 함 (INSERT 전용이라 갱신 자체가 없음)
  - order.py::_sync_returns_with_order_status — 마감행은 갱신·삭제 제외
  - collect_status.refresh_collect_status — 마감행은 조회 대상 제외
"""

import logging
from typing import Any, Optional

from backend.utils import now_kst

logger = logging.getLogger(__name__)

# 마감 주체 어휘
CLOSED_BY_MANUAL = "manual"  # 사장님이 반품탭에서 직접 마감
CLOSED_BY_AUTO = "auto"  # 향후 자동 마감 (auto_close_candidates 채우면 사용)


def _tenant_clause(stmt: Any, tenant_id: Optional[str]) -> Any:
    """테넌트 격리 — NULL 은 레거시 데이터로 허용 (repository.list_filtered 와 동일)."""
    from sqlalchemy import or_

    from backend.domain.samba.returns.model import SambaReturn

    if tenant_id:
        stmt = stmt.where(
            or_(SambaReturn.tenant_id == tenant_id, SambaReturn.tenant_id.is_(None))
        )
    return stmt


async def close_returns(
    session: Any,
    ids: list[str],
    by: str = CLOSED_BY_MANUAL,
    tenant_id: Optional[str] = None,
) -> int:
    """반품행 마감 — closed_at/closed_by 세팅. 이미 마감된 행은 건너뜀(멱등).

    반환: 실제로 마감 처리한 행 수.
    """
    from sqlmodel import col, select

    from backend.domain.samba.returns.model import SambaReturn

    if not ids:
        return 0

    stmt = select(SambaReturn).where(col(SambaReturn.id).in_(ids))
    stmt = _tenant_clause(stmt, tenant_id)
    rows = list((await session.execute(stmt)).scalars().all())

    now = now_kst()
    closed = 0
    for ret in rows:
        if ret.closed_at is not None:
            # 이미 마감된 행 — 재마감 스킵 (멱등. closed_at/closed_by 원본 보존)
            continue
        ret.closed_at = now
        ret.closed_by = by
        ret.updated_at = now
        session.add(ret)
        closed += 1

    if closed:
        await session.commit()
        logger.info("[반품마감] %s건 마감 (by=%s)", closed, by)
    return closed


async def reopen_returns(
    session: Any,
    ids: list[str],
    tenant_id: Optional[str] = None,
) -> int:
    """마감 해제 — closed_at/closed_by 를 NULL 로 되돌린다. 미마감 행은 건너뜀(멱등).

    반환: 실제로 해제한 행 수.
    """
    from sqlmodel import col, select

    from backend.domain.samba.returns.model import SambaReturn

    if not ids:
        return 0

    stmt = select(SambaReturn).where(col(SambaReturn.id).in_(ids))
    stmt = _tenant_clause(stmt, tenant_id)
    rows = list((await session.execute(stmt)).scalars().all())

    now = now_kst()
    reopened = 0
    for ret in rows:
        if ret.closed_at is None:
            # 마감된 적 없는 행 — 스킵 (멱등)
            continue
        ret.closed_at = None
        ret.closed_by = None
        ret.updated_at = now
        session.add(ret)
        reopened += 1

    if reopened:
        await session.commit()
        logger.info("[반품마감] %s건 마감 해제", reopened)
    return reopened


async def auto_close_candidates(
    session: Any,
    tenant_id: Optional[str] = None,
    older_than_days: int = 14,
) -> list[str]:
    """자동 마감 후보 반품행 id 목록 — ★현재는 스텁(항상 빈 리스트)★.

    향후 자동 마감 조건 (사장님 흐름을 그대로 코드화할 것):
      1) completion_detail = '반품'          — 반품으로 종결 확정된 건
      2) status = 'collected'                — 회수(수거)까지 완료된 건
      3) 마켓 클레임 종결 확인               — 마켓 API 로 해당 클레임이
         실제 '반품완료/환불완료' 상태인지 확인 (마켓에서도 완료처리됐어야
         진짜 끝. 삼바 내부 상태만 보고 마감하면 마켓 잔여 클레임을 놓친다)
      4) 완료 후 older_than_days(기본 14)일 경과 — completion_date 기준.
         정산·환수 금액 확인 여유 기간을 두고 나서 자동으로 치운다.
      (+ 이미 마감된 행(closed_at IS NOT NULL)은 당연히 제외)

    구현 시 이 함수 몸통만 채우고, 호출부(스케줄러/엔드포인트)에서
      ids = await auto_close_candidates(session, tenant_id)
      await close_returns(session, ids, by=CLOSED_BY_AUTO, tenant_id=tenant_id)
    로 연결하면 자동 마감이 완성된다.
    """
    # TODO(자동마감): 위 주석의 4개 조건으로 SELECT — 지금은 수동 마감만 운영
    _ = (session, tenant_id, older_than_days)  # 시그니처 고정용 (미사용 경고 방지)
    return []
