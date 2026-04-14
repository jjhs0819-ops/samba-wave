"""Process-wide shutdown state helpers."""

from __future__ import annotations

import asyncio

_shutdown_event = asyncio.Event()


def mark_shutting_down() -> None:
    _shutdown_event.set()


def clear_shutting_down() -> None:
    if _shutdown_event.is_set():
        _shutdown_event.clear()


def is_shutting_down() -> bool:
    return _shutdown_event.is_set()
