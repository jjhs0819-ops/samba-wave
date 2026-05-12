"""오토튠 실시간 인메모리 상태 진단 — 실행 중 상태 기준."""

import sys

sys.path.insert(0, "/app/backend")

# autotune 모듈의 인메모리 변수 직접 접근 (PC별 인스턴스 모델)
from backend.api.v1.routers.samba.collector_autotune import (
    _pc_allowed_sites,
    _pc_last_seen,
    _pc_running,
    _pc_site_tasks,
    _site_breaker_tripped,
    _site_empty_skip_until,
    any_pc_running,
    get_active_pcs,
)
import time

print("=== 오토튠 실시간 인메모리 상태 ===")
print(f"  any_pc_running: {any_pc_running()}")
print(f"  running_pcs: {[d for d, ev in _pc_running.items() if ev.is_set()]}")
print()

print("=== PC 등록 상태 ===")
print(f"  _pc_allowed_sites: {dict(_pc_allowed_sites)}")
print(f"  _pc_last_seen (키목록): {list(_pc_last_seen.keys())}")
print(f"  get_active_pcs(): {get_active_pcs()}")
print()

print("=== PC별 소싱처 태스크 상태 ===")
for dev, site_tasks in _pc_site_tasks.items():
    print(f"  [{dev[:8]}]")
    for site, task in site_tasks.items():
        print(f"    {site}: done={task.done()}, cancelled={task.cancelled()}")
if not _pc_site_tasks:
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
