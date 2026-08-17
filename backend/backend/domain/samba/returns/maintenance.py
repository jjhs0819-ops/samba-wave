"""반품 레코드 정합 유지보수 — stale 종결 + 중복 정리.

반품 수집 경로가 둘(returns_sync = returns.py, order_sync = order.py 내부 클레임
생성)이고 dedup 키가 경로별로 달라(order_number vs order_id vs order_id+type)
중복이 반복 생성된다. 또 마켓에서 종결(취소/반품완료)돼 원주문 status 가 넘어가도
반품 종결 API 재조회 실패 시 반품 레코드가 진행중에 방치된다.

두 수집 경로 모두 완료 직후 이 함수를 호출해 자가치유한다:
    - returns.py  sync_returns_from_markets finalize
    - order_sync 잡 핸들러 (account 순회 완료 후)

멱등 벌크 SQL 이며 samba_return 은 참조 FK 가 없어 삭제해도 고아가 없다.
operator 입력(확인/메모/정산/환수/확인일)이 있는 행은 절대 삭제/오종결하지 않는다.
"""

from __future__ import annotations

import logging

from sqlalchemy import text as _sa_text
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


async def finalize_returns_consistency(session: AsyncSession) -> dict[str, int]:
    """stale 종결 + 중복 정리. 각 단계는 독립 커밋(한 단계 실패가 다른 단계를
    막지 않게). 반환: 각 단계 처리 건수."""
    result = {"restored": 0, "cancel_closed": 0, "return_closed": 0, "dup_deleted": 0}

    # 0) 오분류 복원 — 반품/교환 레코드가 종결(취소/완료/거부)됐는데 마켓 실제 상태
    #    (원주문 shipping_status)는 여전히 '반품요청/교환요청'이면 진행중으로 되살린다.
    #    롯데ON 처럼 order.status 가 cancelled(→취소 오분류, 이용철·이재희) 또는
    #    returned(→반품완료 조기종결, 김석열) 로 굳어 auto-close 에 잘못 닫힌 건을
    #    shipping_status 우선으로 교정(SSG 474a732a 와 동일 원칙). operator 확인
    #    (confirmed) 건은 건드리지 않는다. 아래 종결 가드와 짝 — shipping='반품요청'
    #    이면 재종결하지 않으므로 복원↔종결 무한루프 없음.
    try:
        _rs = await session.execute(
            _sa_text("""
            UPDATE samba_return r
            SET status = 'requested',
                completion_detail = '진행중',
                completion_date = NULL
            FROM samba_order o
            WHERE r.order_id = o.id
              AND r.type IN ('return', 'exchange')
              AND r.status IN ('cancelled', 'completed', 'rejected')
              AND r.confirmed IS NOT TRUE
              AND o.shipping_status IN ('반품요청', '교환요청')
              -- 원주문이 이미 종결(반품완료/교환완료)이면 되살리지 않는다. 롯데ON은
              -- 반품완료(step27) 후에도 shipping_status 가 '반품요청'에 stale 하게 남는데
              -- (order-list 가 종결건을 안 돌려줘 갱신 못 함), returns 동기화가 정상
              -- 종결한 반품을 이 복원이 다시 진행중으로 되돌려 완료건이 영구 진행중으로
              -- 고착되던 버그(김무신·김민수·김지수 관측). order.status 종결이 shipping
              -- stale 보다 신뢰 가능한 완료 신호 — 취소로 오분류된 건(이용철: status=
              -- cancelled/return_requested)만 계속 복원 대상.
              AND o.status NOT IN ('returned', 'exchanged')
        """)
        )
        await session.commit()
        result["restored"] = _rs.rowcount or 0
        if _rs.rowcount:
            logger.info(
                f"[반품정합] 취소로 오분류된 반품/교환 {_rs.rowcount}건 진행중 복원(shipping 우선)"
            )
    except Exception as _e:
        logger.warning(f"[반품정합] 오분류 복원 실패(무시): {_e}")

    # 1) 취소완료 주문(status='cancelled')의 stale 활성 반품 → cancelled 종결.
    #    단, shipping_status(마켓 실제 상태)가 '반품요청/교환요청'이면 취소로 닫지
    #    않는다 — 롯데ON 반품이 order.status=cancelled 로 굳어도(취소 API 에 반품이
    #    섞여 나와 취소완료 step 으로 오분류) 실제론 진행중 반품이라, status 만 보고
    #    취소 종결하면 반품교환 뷰에서 사라진다(SSG 474a732a 와 동일 클래스, 롯데ON
    #    이용철·이재희 관측). shipping 이 '취소*'거나 없을 때만 취소로 종결한다.
    try:
        _ac = await session.execute(
            _sa_text("""
            UPDATE samba_return r
            SET status = 'cancelled',
                completion_detail = '취소'
            FROM samba_order o
            WHERE r.order_id = o.id
              AND o.status = 'cancelled'
              AND r.status NOT IN ('completed', 'cancelled', 'rejected')
              AND (o.shipping_status IS NULL OR o.shipping_status LIKE '취소%')
        """)
        )
        await session.commit()
        result["cancel_closed"] = _ac.rowcount or 0
        if _ac.rowcount:
            logger.info(
                f"[반품정합] 취소완료 주문 stale samba_return {_ac.rowcount}건 auto-close"
            )
    except Exception as _e:
        logger.warning(f"[반품정합] 취소 stale close 실패(무시): {_e}")

    # 2) 반품/교환완료 주문(returned/exchanged)의 stale 활성 반품 → completed 종결
    try:
        _rc = await session.execute(
            _sa_text("""
            UPDATE samba_return r
            SET status = 'completed',
                completion_detail = CASE r.type
                    WHEN 'exchange' THEN '교환'
                    WHEN 'cancel' THEN '취소'
                    ELSE '반품' END,
                completion_date = COALESCE(r.completion_date, now())
            FROM samba_order o
            WHERE r.order_id = o.id
              AND o.status IN ('returned', 'exchanged')
              AND r.status NOT IN ('completed', 'cancelled', 'rejected')
              -- shipping 이 아직 '반품요청/교환요청'이면 조기종결 금지(shipping 우선).
              -- 롯데ON 이 order.status=returned 로 조기 마킹해도 마켓은 회수지시
              -- 진행중인 경우(김석열) 진행중 유지 → ShopMine 회수지시와 정합.
              AND (o.shipping_status IS NULL
                   OR o.shipping_status NOT IN ('반품요청', '교환요청'))
        """)
        )
        await session.commit()
        result["return_closed"] = _rc.rowcount or 0
        if _rc.rowcount:
            logger.info(
                f"[반품정합] 반품/교환완료 주문 stale samba_return {_rc.rowcount}건 auto-close"
            )
    except Exception as _e:
        logger.warning(f"[반품정합] 반품완료 stale close 실패(무시): {_e}")

    # 3) 중복 정리 — 같은 (order_id, type)은 단일 상품·단일 클레임이라 1건이어야
    #    한다. 가장 진행된/데이터 있는 1건만 남기고 operator 입력 없는 잉여만 삭제.
    try:
        _dc = await session.execute(
            _sa_text("""
            WITH ranked AS (
                SELECT id,
                    row_number() OVER (
                        PARTITION BY order_id, type
                        ORDER BY
                            (confirmed IS TRUE) DESC,
                            (memo IS NOT NULL AND memo <> '') DESC,
                            (settlement_amount IS NOT NULL) DESC,
                            (recovery_amount IS NOT NULL) DESC,
                            CASE status
                                WHEN 'completed' THEN 3 WHEN 'rejected' THEN 3
                                WHEN 'cancelled' THEN 3 WHEN 'approved' THEN 2
                                WHEN 'requested' THEN 1 ELSE 0 END DESC,
                            updated_at DESC NULLS LAST,
                            created_at DESC
                    ) AS rn
                FROM samba_return
                WHERE order_id IS NOT NULL
            )
            DELETE FROM samba_return
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
              AND confirmed IS NOT TRUE
              AND (memo IS NULL OR memo = '')
              AND settlement_amount IS NULL
              AND recovery_amount IS NULL
              AND check_date IS NULL
        """)
        )
        await session.commit()
        result["dup_deleted"] = _dc.rowcount or 0
        if _dc.rowcount:
            logger.info(
                f"[반품정합] 중복 samba_return {_dc.rowcount}건 정리(가장 진행된 1건만 유지)"
            )
    except Exception as _e:
        logger.warning(f"[반품정합] 중복 정리 실패(무시): {_e}")

    return result
