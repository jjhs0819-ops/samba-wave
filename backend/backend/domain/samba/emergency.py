"""전역 비상정지 스위치 — 전송/오토튠 모든 백그라운드 작업을 즉시 중단.

threading.Event 사용 — 별도 스레드 간 메모리 동기화 보장.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_emergency_event = threading.Event()


def trigger_emergency_stop():
    """비상정지 작동 — 모든 백그라운드 작업 즉시 중단."""
    _emergency_event.set()
    logger.warning("[비상정지] 작동! 모든 전송/오토튠 즉시 중단")


def clear_emergency_stop():
    """비상정지 해제."""
    _emergency_event.clear()
    logger.info("[비상정지] 해제")


def is_emergency_stopped() -> bool:
    """비상정지 상태 확인 (스레드 안전)."""
    return _emergency_event.is_set()
