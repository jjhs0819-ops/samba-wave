"""롯데홈쇼핑 주문수집 직접 실행."""

import asyncio
import sys

sys.path.insert(0, "/app/backend")


async def main():
    # 2026-06-26: 인라인 _run_direct_order_sync 제거 → order_sync 잡 발행으로 변경.
    # 발행된 잡은 전송 전용 워커(B)가 처리한다.
    from backend.domain.samba.order.poller import _enqueue_order_sync_jobs

    print("[시작] 롯데홈쇼핑 주문수집 — order_sync 잡 발행(B 워커 처리)")
    await _enqueue_order_sync_jobs(tenant_ids={None})
    print("[완료] 잡 발행됨")


asyncio.run(main())
