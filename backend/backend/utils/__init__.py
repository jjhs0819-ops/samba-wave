from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_kst() -> datetime:
    """KST(Asia/Seoul) 기준 현재 시간 반환."""
    return datetime.now(KST)


def utc_to_seoul(dt: datetime | None) -> datetime | None:
    """
    Convert a UTC datetime to Asia/Seoul timezone.
    If dt is naive, it is assumed to be UTC.
    Returns an aware datetime in Asia/Seoul timezone.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)
