"""전역 비상정지 스위치 — 전송/오토튠 모든 백그라운드 작업을 즉시 중단."""

import logging

logger = logging.getLogger(__name__)

_emergency_stop = False


def trigger_emergency_stop():
  """비상정지 작동 — 모든 백그라운드 작업 즉시 중단."""
  global _emergency_stop
  _emergency_stop = True
  logger.warning("[비상정지] 작동! 모든 전송/오토튠 즉시 중단")


def clear_emergency_stop():
  """비상정지 해제."""
  global _emergency_stop
  _emergency_stop = False
  logger.info("[비상정지] 해제")


def is_emergency_stopped() -> bool:
  """비상정지 상태 확인."""
  return _emergency_stop
