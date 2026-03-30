"""SambaWave Collector 공통 모듈 — 상수, 헬퍼 함수, 팩토리 메서드."""

import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import cast, String as _StrType
from sqlmodel.ext.asyncio.session import AsyncSession
from backend.domain.samba.collector.grouping import generate_group_key, parse_color_from_name


# ── 상수 ──

# HTML 태그 및 불필요 문자 정제 (상품명/브랜드/옵션 등에서 제거)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

# 스크롤/목록 조회 시 제외할 무거운 필드 (source_url은 가볍고 목록에서 필요하므로 제외 안 함)
_HEAVY_FIELDS = {"price_history", "detail_html", "detail_images", "last_sent_data", "extra_data"}


# ── 블랙리스트 캐시 ──

# 수집 블랙리스트 캐시 (서버 수명 동안 유지, 변경 시 갱신)
_blacklist_cache: set[str] | None = None


async def _load_blacklist(session: AsyncSession) -> set[str]:
  """블랙리스트를 DB에서 로드하여 캐시."""
  global _blacklist_cache
  if _blacklist_cache is not None:
    return _blacklist_cache
  from backend.domain.samba.forbidden.repository import SambaSettingsRepository
  repo = SambaSettingsRepository(session)
  row = await repo.find_by_async(key="collection_blacklist")
  items = row.value if row and isinstance(row.value, list) else []
  _blacklist_cache = {f"{b['source_site']}:{b['site_product_id']}" for b in items if b.get("source_site") and b.get("site_product_id")}
  return _blacklist_cache


def _invalidate_blacklist_cache():
  """블랙리스트 캐시 무효화."""
  global _blacklist_cache
  _blacklist_cache = None


async def _is_blacklisted(session: AsyncSession, source_site: str, site_product_id: str) -> bool:
  """블랙리스트 체크 — 캐시 없으면 자동 로드."""
  if _blacklist_cache is None:
    await _load_blacklist(session)
  return f"{source_site}:{site_product_id}" in (_blacklist_cache or set())


# ── 텍스트 정제 ──

def _clean_text(value: str) -> str:
  """HTML 태그 제거 + 연속 공백 정리."""
  if not value:
    return value
  cleaned = _HTML_TAG_RE.sub(" ", value)
  cleaned = _WHITESPACE_RE.sub(" ", cleaned)
  return cleaned.strip()


# ── 상품 데이터 빌드 ──

# _build_product_data에서 명시적으로 매핑하는 프록시 키 목록
# 여기에 없는 키는 extra_data에 자동 저장됨
_KNOWN_PROXY_KEYS = {
  "name", "brand", "images", "detailImages", "options",
  "sourceUrl", "category", "manufacturer", "origin", "material",
  "color", "style_code", "sex", "season", "care_instructions",
  "quality_guarantee", "saleStatus", "freeShipping", "sameDayDelivery",
  "originalPrice", "salePrice", "cost", "detail_html", "video_url",
  "kreamData", "collectedAt", "updatedAt",
}


def _build_product_data(
  detail: dict, goods_no: str, filter_id: str, site: str,
  cost: float, sale_price: float, original_price: float,
  raw_cat: str, cat_parts: list, raw_detail_html: str,
) -> dict:
  """수집 상품 데이터 빌드 (collect_by_url / collect_by_filter 공통).

  프록시에서 보내는 모든 데이터를 보존:
  - 명시 매핑 필드 → DB 컬럼에 직접 저장
  - sourceUrl → source_url 컬럼에 저장
  - 미매핑 필드 → extra_data JSON에 자동 저장
  """
  initial_snapshot = {
    "date": datetime.now(timezone.utc).isoformat(),
    "sale_price": sale_price,
    "original_price": original_price,
    "cost": cost,
    "options": detail.get("options", []),
  }
  # 옵션 정제 (옵션명에서도 HTML 태그 제거)
  raw_options = detail.get("options", [])
  cleaned_options = []
  for opt in raw_options:
    if isinstance(opt, dict):
      cleaned_opt = {**opt}
      for k in ("name", "value", "label"):
        if k in cleaned_opt and isinstance(cleaned_opt[k], str):
          cleaned_opt[k] = _clean_text(cleaned_opt[k])
      cleaned_options.append(cleaned_opt)
    else:
      cleaned_options.append(opt)

  # 미매핑 필드 → extra_data에 자동 보존
  extra = {k: v for k, v in detail.items() if k not in _KNOWN_PROXY_KEYS}
  extra_data = extra if extra else None

  return {
    "source_site": site,
    "site_product_id": goods_no,
    "search_filter_id": filter_id,
    "source_url": detail.get("sourceUrl", ""),
    "name": _clean_text(detail.get("name", "")),
    "brand": _clean_text(detail.get("brand", "")),
    "original_price": original_price,
    "sale_price": sale_price,
    "cost": cost,
    "images": detail.get("images", []),
    "detail_images": detail.get("detailImages") or [],
    "options": cleaned_options,
    "category": raw_cat,
    "category1": cat_parts[0] if len(cat_parts) > 0 else None,
    "category2": cat_parts[1] if len(cat_parts) > 1 else None,
    "category3": cat_parts[2] if len(cat_parts) > 2 else None,
    "category4": cat_parts[3] if len(cat_parts) > 3 else None,
    "manufacturer": _clean_text(detail.get("manufacturer") or "") or _clean_text(detail.get("brand") or ""),
    "origin": _clean_text(detail.get("origin") or ""),
    "material": _clean_text(detail.get("material") or ""),
    "color": _clean_text(detail.get("color") or "") or parse_color_from_name(detail.get("name", "")),
    "sex": detail.get("sex", ""),
    "season": detail.get("season", ""),
    "care_instructions": _clean_text(detail.get("care_instructions", "")),
    "quality_guarantee": _clean_text(detail.get("quality_guarantee", "")),
    "similar_no": str(detail.get("similarNo", "0")),
    "style_code": _clean_text(detail.get("styleNo", "") or detail.get("style_code", "")),
    "group_key": generate_group_key(
      brand=detail.get("brand", ""),
      similar_no=str(detail.get("similarNo", "0")),
      style_code=detail.get("styleNo", "") or detail.get("style_code", ""),
      name=detail.get("name", ""),
    ),
    "detail_html": raw_detail_html,
    "status": "collected",
    "sale_status": detail.get("saleStatus", "in_stock"),
    "free_shipping": detail.get("freeShipping", False),
    "same_day_delivery": detail.get("sameDayDelivery", False),
    "price_history": [initial_snapshot],
    "extra_data": extra_data,
  }


def _trim_history(history: list) -> list:
  """price_history를 최초 수집 1개 + 최근 4개 = 최대 5개로 제한."""
  if len(history) <= 5:
    return history
  # history[0]이 최신, history[-1]이 최초
  return history[:4] + [history[-1]]


# ── KREAM 가격이력 스냅샷 ──

def _build_kream_price_snapshot(sale_price, original_price, cost, options):
  """KREAM 전용 가격이력 스냅샷 — 빠른배송/일반배송 최저가 포함."""
  fast_prices = [o.get("kreamFastPrice", 0) for o in (options or []) if o.get("kreamFastPrice", 0) > 0]
  general_prices = [o.get("kreamGeneralPrice", 0) for o in (options or []) if o.get("kreamGeneralPrice", 0) > 0]

  return {
    "date": datetime.now(timezone.utc).isoformat(),
    "sale_price": sale_price,
    "original_price": original_price,
    "cost": cost,
    "kream_fast_min": min(fast_prices) if fast_prices else 0,
    "kream_general_min": min(general_prices) if general_prices else 0,
    "options": [
      {
        "name": o.get("name", ""),
        "price": o.get("price", 0),
        "stock": o.get("stock", 0),
        "kreamFastPrice": o.get("kreamFastPrice", 0),
        "kreamGeneralPrice": o.get("kreamGeneralPrice", 0),
      }
      for o in (options or [])
    ],
  }


# ── 서비스 팩토리 ──

def _get_services(session: AsyncSession):
  """CollectorService 인스턴스 생성 팩토리."""
  from backend.domain.samba.collector.repository import (
    SambaCollectedProductRepository,
    SambaSearchFilterRepository,
  )
  from backend.domain.samba.collector.service import SambaCollectorService

  return SambaCollectorService(
    SambaSearchFilterRepository(session),
    SambaCollectedProductRepository(session),
  )


# ── 무신사 쿠키 조회 ──

async def get_musinsa_cookie(session: AsyncSession | None = None) -> str:
  """DB에서 무신사 쿠키를 조회하여 반환.

  session이 주어지면 해당 세션으로 조회하고,
  없으면 새 읽기 세션을 열어 조회한다.
  """
  from backend.domain.samba.forbidden.model import SambaSettings
  from sqlmodel import select as _sel

  if session is not None:
    try:
      result = await session.execute(
        _sel(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
      )
      row = result.scalar_one_or_none()
      return (row.value if row and row.value else "") or ""
    except Exception:
      logger.warning("[get_musinsa_cookie] 쿠키 조회 실패 (세션 전달)", exc_info=True)
      return ""

  # 세션이 없으면 새 읽기 세션 생성
  try:
    from backend.db.orm import get_read_session
    async with get_read_session() as new_session:
      result = await new_session.execute(
        _sel(SambaSettings).where(SambaSettings.key == "musinsa_cookie")
      )
      row = result.scalar_one_or_none()
      return (row.value if row and row.value else "") or ""
  except Exception:
    logger.warning("[get_musinsa_cookie] 쿠키 조회 실패 (신규 세션)", exc_info=True)
    return ""


# ── 마켓등록상품 필터 조건 ──

def build_market_registered_conditions(model_class: Any) -> list:
  """마켓등록상품 판별 SQLAlchemy 조건 리스트 반환.

  registered_accounts IS NOT NULL / != 'null' / != '[]'
  AND market_product_nos IS NOT NULL / != 'null' / != '{}'
  """
  return [
    model_class.registered_accounts.isnot(None),
    cast(model_class.registered_accounts, _StrType) != 'null',
    cast(model_class.registered_accounts, _StrType) != '[]',
    model_class.market_product_nos.isnot(None),
    cast(model_class.market_product_nos, _StrType) != 'null',
    cast(model_class.market_product_nos, _StrType) != '{}',
  ]
