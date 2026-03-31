"""글로벌 트래픽 부하 표시기 — 수집/전송 진행 시 오토튠 속도 조절용.

threading.Event 사용 — 수집은 별도 스레드에서 실행되므로 스레드 간 동기화 필요.
"""

import threading
import logging

logger = logging.getLogger(__name__)

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
