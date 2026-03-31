"""글로벌 트래픽 부하 표시기 + 프록시 풀 관리.

- 수집/전송 진행 시 오토튠 속도 조절
- 수집/오토튠 시 프록시 로테이션 (전송은 직접 연결)

threading.Event 사용 — 수집은 별도 스레드에서 실행되므로 스레드 간 동기화 필요.
"""

import os
import threading
import logging

logger = logging.getLogger(__name__)

# ── 트래픽 상태 ──

_collect_active = threading.Event()
_transmit_active = threading.Event()


def set_collecting():
  """수집 시작 시 호출."""
  _collect_active.set()
  logger.info("[트래픽] 수집 시작 — 오토튠 속도 조절 활성화")


def clear_collecting():
  """수집 완료 시 호출."""
  _collect_active.clear()
  logger.info("[트래픽] 수집 완료 — 오토튠 속도 조절 해제")


def set_transmitting():
  """전송 시작 시 호출."""
  _transmit_active.set()
  logger.info("[트래픽] 전송 시작 — 오토튠 속도 조절 활성화")


def clear_transmitting():
  """전송 완료 시 호출."""
  _transmit_active.clear()
  logger.info("[트래픽] 전송 완료 — 오토튠 속도 조절 해제")


def is_traffic_busy() -> bool:
  """수집 또는 전송이 진행 중인지 확인."""
  return _collect_active.is_set() or _transmit_active.is_set()


def get_traffic_status() -> dict:
  """현재 트래픽 상태 (프론트 표시용)."""
  return {
    "collecting": _collect_active.is_set(),
    "transmitting": _transmit_active.is_set(),
    "busy": is_traffic_busy(),
  }


# ── 프록시 풀 (라운드 로빈 로테이션) ──

_proxy_list: list[str] = []
_proxy_index = 0
_proxy_lock = threading.Lock()


def _load_proxies():
  """환경변수에서 프록시 목록 로드 (최초 1회)."""
  global _proxy_list
  if _proxy_list:
    return
  raw = os.getenv("PROXY_URLS", "")
  if raw:
    _proxy_list = [p.strip() for p in raw.split(",") if p.strip()]
    logger.info("[프록시] %d개 로드 완료", len(_proxy_list))


def get_next_proxy() -> str | None:
  """라운드 로빈 프록시 로테이션. 프록시 없으면 None."""
  global _proxy_index
  _load_proxies()
  if not _proxy_list:
    return None
  with _proxy_lock:
    proxy = _proxy_list[_proxy_index % len(_proxy_list)]
    _proxy_index += 1
  return proxy


def should_use_proxy() -> bool:
  """수집 또는 오토튠일 때만 프록시 사용. 전송/기타는 직접 연결."""
  _load_proxies()
  if not _proxy_list:
    return False
  # 수집 중이면 프록시
  if _collect_active.is_set():
    return True
  # 오토튠이면 프록시 (transmit은 제외)
  try:
    from backend.domain.samba.collector.refresher import _current_refresh_source
    if _current_refresh_source.get("") == "autotune":
      return True
  except Exception:
    pass
  return False


def get_proxy_if_needed() -> str | None:
  """수집/오토튠이면 다음 프록시 반환, 아니면 None."""
  if should_use_proxy():
    return get_next_proxy()
  return None
