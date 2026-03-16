from datetime import datetime, timezone
from zoneinfo import ZoneInfo


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
    seoul_tz = ZoneInfo("Asia/Seoul")
    return dt.astimezone(seoul_tz)
