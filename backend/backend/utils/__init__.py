import re
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


def kst_str_to_utc(
    s: str | None,
    fmts: tuple[str, ...] = (
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y%m%d",
        "%Y-%m-%d",
    ),
) -> datetime | None:
    """마켓 API KST 날짜 문자열 → UTC aware datetime 변환.
    파싱 실패 시 None 반환.
    """
    if not s:
        return None
    s = str(s).strip()[:19]
    for fmt in fmts:
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=KST)
            return dt.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def kst_date_range_to_utc(start: str, end: str) -> tuple[datetime, datetime]:
    """사용자 KST 날짜 범위('YYYY-MM-DD') → UTC datetime 쌍 변환.
    start '2026-04-10' → 2026-04-09T15:00:00+00:00 (KST 00:00)
    end   '2026-04-10' → 2026-04-10T14:59:59+00:00 (KST 23:59:59)
    """
    start_dt = (
        datetime.strptime(start, "%Y-%m-%d")
        .replace(hour=0, minute=0, second=0, tzinfo=KST)
        .astimezone(timezone.utc)
    )
    end_dt = (
        datetime.strptime(end, "%Y-%m-%d")
        .replace(hour=23, minute=59, second=59, tzinfo=KST)
        .astimezone(timezone.utc)
    )
    return start_dt, end_dt


_IMG_LAZY_PAT = re.compile(r"(<img)(\s)", re.I)


def add_lazy_loading(html: str) -> str:
    """상세페이지 HTML의 모든 <img>에 loading="lazy" 속성을 추가한다.
    이미 loading 속성이 있는 태그는 건드리지 않는다.
    """
    if not html or "loading=" in html:
        # 이미 loading 속성이 하나라도 있으면 그냥 반환 (부분 중복 방지용 간단 처리)
        # 더 정확하게 처리하려면 태그별 파싱이 필요하지만 성능상 여기서 충분
        return html

    def _inject(m: re.Match) -> str:
        return f'{m.group(1)} loading="lazy"{m.group(2)}'

    return _IMG_LAZY_PAT.sub(_inject, html)


def kst_iso_to_utc(s: str | None) -> datetime | None:
    """프론트엔드 ISO 날짜(KST 가정) → UTC aware datetime 변환.
    '2026-04-10' 또는 '2026-04-10T15:30:00' → UTC datetime.
    이미 timezone 정보가 있으면 그대로 UTC 변환.
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None
