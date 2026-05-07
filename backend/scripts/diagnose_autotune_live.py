"""오토튠 실시간 인메모리 상태 진단 — 실행 중 상태 기준."""

import sys

sys.path.insert(0, "/app/backend")

# autotune 모듈의 인메모리 변수 직접 접근
from backend.api.v1.routers.samba.collector_autotune import (
    _pc_allowed_sites,
    _pc_last_seen,
    _site_tasks,
    _site_breaker_tripped,
    _site_empty_skip_until,
    _autotune_running_event,
    get_active_pcs,
    get_union_active_sites,
)
import time

print("=== 오토튠 실시간 인메모리 상태 ===")
print(f"  autotune_running: {_autotune_running_event.is_set()}")
print()

print("=== PC 등록 상태 ===")
print(f"  _pc_allowed_sites: {dict(_pc_allowed_sites)}")
print(f"  _pc_last_seen (키목록): {list(_pc_last_seen.keys())}")
print(f"  get_active_pcs(): {get_active_pcs()}")
print(f"  get_union_active_sites(): {get_union_active_sites()}")
print()

print("=== 소싱처별 태스크 상태 ===")
for site, task in _site_tasks.items():
    print(f"  {site}: done={task.done()}, cancelled={task.cancelled()}")
if not _site_tasks:
    print("  (활성 태스크 없음)")
print()

print("=== 서킷브레이커 ===")
print(f"  {dict(_site_breaker_tripped)}" if _site_breaker_tripped else "  (없음)")
print()

print("=== 빈결과 스킵 상태 ===")
now = time.time()
for site, until in _site_empty_skip_until.items():
    remaining = until - now
    print(f"  {site}: 잔여 {remaining:.0f}초" if remaining > 0 else f"  {site}: 만료됨")
if not _site_empty_skip_until:
    print("  (없음)")
