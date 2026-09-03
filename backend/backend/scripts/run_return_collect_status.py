"""반품 회수상태 자동판정 — 크론용 실행기.

원주문 송장으로 반송장을 찾아(CJ대한통운·한진택배) 집하 여부까지 조회한 뒤
samba_return.status 를 미수거/수거중/수거완료로 자동 갱신한다.
상세 규칙은 backend/domain/samba/returns/collect_status.py 모듈 docstring 참조.

HTTP 를 타지 않고 컨테이너 안에서 DB 세션을 직접 열기 때문에 토큰·게이트웨이 키가
필요 없다. 윈도우 Task Scheduler 가 6시간마다(하루 4회) 이 스크립트를 호출한다.

사용법 (윈도우PC 운영 컨테이너):
    docker exec samba-local-api /app/backend/.venv/bin/python \
        -m backend.scripts.run_return_collect_status

    # 쿨다운 무시하고 전부 다시 보기
    docker exec samba-local-api /app/backend/.venv/bin/python \
        -m backend.scripts.run_return_collect_status --cooldown 0

종료코드: 조회 대상이 하나도 없거나 전부 성공하면 0, 개별 오류가 있으면 0(로그만),
세션/치명적 예외면 1. 크론이 실패로 오인하지 않게 개별 오류로는 죽지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from backend.db.orm import get_write_session


async def _run(cooldown_minutes: int, tenant_id: str | None) -> int:
    from backend.domain.samba.returns.collect_status import refresh_collect_status

    async with get_write_session() as session:
        result = await refresh_collect_status(
            session,
            tenant_id=tenant_id,
            cooldown_minutes=cooldown_minutes,
        )

    # 크론 로그로 남길 한 줄 요약 — 로그 파일에서 바로 읽히도록 한국어 + JSON 병기
    errors = result.get("errors") or []
    print(
        "[회수자동판정] 확인 {checked}건 · 갱신 {updated}건 · 반송장확보 {waybill}건 "
        "· 미지원택배사 {unsup}건 · 쿨다운스킵 {cool}건 · 오류 {err}건".format(
            checked=result.get("checked", 0),
            updated=result.get("updated", 0),
            waybill=result.get("waybill_found", 0),
            unsup=result.get("unsupported_courier", 0),
            cool=result.get("cooldown_skipped", 0),
            err=len(errors),
        )
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="반품 회수상태 자동판정 실행")
    parser.add_argument(
        "--cooldown",
        type=int,
        default=60,
        help="이 분(minute) 안에 이미 조회한 행은 건너뜀. 0이면 쿨다운 없음 (기본 60)",
    )
    parser.add_argument(
        "--tenant",
        default=None,
        help="특정 테넌트만 처리 (미지정 시 전체)",
    )
    args = parser.parse_args()

    try:
        rc = asyncio.run(_run(args.cooldown, args.tenant))
    except Exception as exc:  # noqa: BLE001 — 크론이므로 전체 실패만 비정상 종료
        print(f"[회수자동판정] 실행 실패: {exc}", file=sys.stderr)
        sys.exit(1)
    sys.exit(rc)


if __name__ == "__main__":
    main()
