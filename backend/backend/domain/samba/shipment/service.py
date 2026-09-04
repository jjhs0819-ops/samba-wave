"""SambaWave Shipment service — 실제 마켓 API 연동 상품 전송."""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urlparse

from sqlmodel.ext.asyncio.session import AsyncSession

from backend.domain.samba.exchange_rate_service import convert_cost_by_source_site
from backend.domain.samba.policy.brand_en import brand_en as _brand_en
from backend.domain.samba.shipment.model import SambaShipment
from backend.domain.samba.shipment.repository import SambaShipmentRepository
from backend.utils.logger import logger

import math
from backend.domain.samba.collector.model import as_market_nos


# 마켓타입(영문 코드) → 정책키(한글 표시명) 매핑
# 마켓 계정의 market_type 필드 값을 정책 설정의 per_market 키로 변환할 때 사용
MARKET_TYPE_TO_POLICY_KEY: dict[str, str] = {
    "coupang": "쿠팡",
    "ssg": "신세계몰(전시)",
    "smartstore": "스마트스토어",
    "11st": "11번가",
    "gmarket": "G마켓",
    "auction": "옥션",
    "gsshop": "GS샵",
    "lotteon": "롯데ON",
    "lottehome": "롯데홈쇼핑",
    "homeand": "홈앤쇼핑",
    "hmall": "HMALL",
    "kream": "KREAM",
    # eBay 누락 시 calc_market_price가 policy_key=""로 market_policies["eBay"]를
    # 못 찾아 수수료(feeRate)·마켓마진 그로스업을 통째로 스킵 → 전 eBay 리스팅이
    # 원가+공통마진만 반영된 저가로 등록됨. (2026-07-21 냐옹ex $28.32 저가등록 사고)
    "ebay": "eBay",
    "playauto": "플레이오토",
    # 토스도 같은 누락이었다 — 정책에 토스 feeRate 12%(판매 8% + 결제 3% + 버퍼 1%p)가
    # 설정돼 있는데 이 맵에 없어서 전혀 반영되지 않았다. 실측(2026-08-15, 첫 업로드 직전):
    #   원가 235,000 → 270,900(1.15배)  … 수수료 미반영
    #   원가 235,000 → 307,800(1.31배)  … 12% 반영
    # 건당 36,900원(원가의 15.7%)을 덜 받는 저가등록이 될 뻔했다. 등록 0건 상태에서
    # 발견해 기존 리스팅 영향은 없다.
    "toss": "토스",
}

# ── 이 맵에 일부러 넣지 않는 마켓 ──
# 플러그인이 자체적으로 정책 수수료를 읽어 가격을 만드는 마켓은 여기 넣으면 안 된다.
# calc_market_price 가 한 번, 플러그인이 또 한 번 그로스업해서 수수료가 이중 반영된다.
#   포이즌 — plugins/markets/poison.py 가 market_policies["포이즌"].feeRate 를 직접 읽는다.
# 새 마켓을 붙일 때는 그 플러그인이 feeRate 를 자체로 읽는지 먼저 확인하고,
# 읽지 않으면(=토스처럼) 반드시 이 맵에 등록해야 한다.

# 저재고 오버셀 방지 캡 (#703) — 옵션 stock이 이 값 이하면 전송값만 0으로 캡.
# 무재고 판매 특성상 재고 갱신 간격이 수십 시간이라, 마지막 1~2개는 그 사이
# 팔릴 위험이 커 품절취소로 이어짐. DB 원본 재고는 건드리지 않음(다음 갱신 때 자연 복원).
_LOW_STOCK_SEND_CAP_TH = 2

# 저재고 캡 적용 마켓 — 리셀 플랫폼 전용 (2026-08-14 팀장 결정).
# 크림/포이즌은 낙찰 후 미발송이 곧 페널티·정산차감으로 직결돼 마지막 1~2개를
# 내리는 편이 이득이다. 반면 오픈마켓(롯데ON/쿠팡/스마트스토어 등)은 품절취소
# 리스크보다 노출 SKU 축소 손실이 커서 실재고 그대로 보낸다.
# (실측 사례: 브룩스러닝 글리세린22 는 재고 있는 5개 사이즈 중 240 하나만
#  노출되고 230/235/245/250 이 전부 캡에 걸려 숨겨져 있었다.)
_LOW_STOCK_SEND_CAP_MARKETS = frozenset({"kream", "poison"})

# 마켓별 상품명 최대 바이트 — 상품명 폴백 체인(_compose_product_name) 판정용.
# 각 마켓 플러그인이 실제로 자르는 값과 같아야 한다:
#   11번가  proxy/elevenst.py  _truncate_to_bytes(name, 99)
#   롯데ON  proxy/lotteon/api_client.py  _truncate_to_bytes(name, 149)
# 여기 없는 마켓은 폴백 없이 첫 조합을 그대로 쓴다(기존 동작).
_MARKET_NAME_MAX_BYTES: dict[str, int] = {
    "11st": 99,
    "lotteon": 149,
}


class _NameRuleWithComposition:
    """name_composition 만 교체한 name_rule 프록시 — 폴백 체인 후보 조립용.

    원본 name_rule 은 SQLModel 인스턴스라 속성을 직접 바꾸면 세션에 dirty 로 잡혀
    의도치 않은 UPDATE 가 나갈 수 있다. 읽기 전용 위임으로 그 위험을 없앤다.
    """

    def __init__(self, base: Any, composition: list) -> None:
        self._base = base
        self.name_composition = composition
        # 마켓별 조합을 다시 타지 않도록 비운다 — 후보 조합을 그대로 쓰게 한다.
        self.market_name_compositions = None

    def __getattr__(self, item: str) -> Any:
        return getattr(self._base, item)


def is_account_full_error(err: str | None) -> bool:
    """마켓 등록 '한도 초과'(계정 슬롯 만석) 거부인지 판정.

    상품 데이터 문제가 아니라 마켓 계정에 등록 가능한 상품 수가 꽉 찬 경우다.
    이 경우 failure_count를 올려 동결하면 안 된다(상품 잘못이 아니므로). 슬롯이
    비면 다음 사이클에 정상 등록돼야 한다. 잡 워커(_is_account_blocking_error)와
    동일한 패턴을 쓰는 단일 출처 — 두 곳 매처가 갈라지지 않도록 여기서만 정의한다.
    """
    if not err:
        return False
    # 11번가: "판매 중인 상품은 최대 5,000개까지 등록할 수 있습니다"
    # 스마트스토어: "상품 등록 한도를 초과했습니다. 판매중/판매대기/품절 상품수를 ..."
    # 롯데ON: "판매중 상태의 상품수가 N개를 초과하였습니다"
    patterns = (
        "판매 중인 상품은 최대",
        "최대 5,000개",
        "최대 5000개",
        "상품을 판매중지",
        "상품 등록 한도를 초과",
        "판매중 상태의 상품수",
    )
    if any(p in err for p in patterns):
        return True
    # 쿠팡 일일 한도 — 단어 AND 매칭으로 false-positive 차단
    if ("오늘 등록할 수 있는" in err) and ("초과" in err):
        return True
    return False


def real_market_no(value):
    """market_product_nos 값에서 실제 마켓 상품번호만 반환.

    coupang/lotteon 신규등록 중복방지가 `__claiming__<epoch>` 임시 마커를
    같은 필드에 CAS 기록하는데(#562), 크래시로 마커가 잔류하면 읽기 경로가
    이를 실제 번호로 오인해 오삭제/오매칭 위험 (이슈 #579). 마커면 None.
    """
    if isinstance(value, str) and value.startswith("__claiming__"):
        return None
    return value


def available_stock(options: list | None) -> int:
    """옵션 리스트의 가용재고 합 — 품절(isSoldOut/is_sold_out/sold_out) 옵션 제외.

    수집 표준 키는 isSoldOut(camelCase)이나 일부 경로가 snake_case 를 쓰므로 모두 인식.
    stock 이 문자열("5")·실수("5.0")로 저장된 레거시 행도 안전 변환.
    """
    total = 0
    for o in options or []:
        if not isinstance(o, dict):
            continue
        if o.get("isSoldOut") or o.get("is_sold_out") or o.get("sold_out"):
            continue
        try:
            total += int(float(o.get("stock") or 0))
        except (TypeError, ValueError):
            continue
    return total


def _resolve_margin_rate(cost: float, pricing: dict) -> float:
    """원가 기반 범위 마진율 반환. useRangeMargin이면 해당 구간 rate 사용."""
    if pricing.get("useRangeMargin") and pricing.get("rangeMargins"):
        for r in pricing["rangeMargins"]:
            max_val = r.get("max") or 9999999999
            if cost >= r.get("min", 0) and cost < max_val:
                return r.get("rate", 15)
    return pricing.get("marginRate", 15)


def _get_source_site_margin(pricing: dict, source_site: str) -> dict:
    margins = pricing.get("sourceSiteMargins", {}) or {}
    if not source_site:
        return {}
    if source_site in margins:
        return margins[source_site] or {}

    aliases = {
        "GSShop": ("GSSHOP",),
        "GSSHOP": ("GSShop",),
    }
    for alias in aliases.get(source_site, ()):
        if alias in margins:
            return margins[alias] or {}
    return {}


def resolve_cost_for_policy(
    product: Any,
    policy_pricing: dict | None,
    source_site: str = "",
) -> float:
    """정책 토글에 따라 product.cost 또는 cost_excl_held_point 선택.

    excludeHeldPoint=True 이고 cost_excl_held_point 값이 있으면 그것을 반환,
    그 외에는 cost 반환.
    """
    cost = getattr(product, "cost", None) or 0
    if not policy_pricing or not source_site:
        return cost
    ssm = _get_source_site_margin(policy_pricing, source_site)
    if not bool(ssm.get("excludeHeldPoint")):
        return cost
    excl = getattr(product, "cost_excl_held_point", None)
    if excl and excl > 0:
        return excl
    return cost


# 마켓 전송가/원가 상한 — 이 금액 이상이면 가격 오염으로 보고 전송을 차단한다(#625 보완).
# 2026-07-11 SSG 스크랩 오염으로 원가가 조 단위로 저장 → 조 단위 판매가가 롯데홈/롯데ON/
# 플레이오토에 실전송된 사고의 최후 방어선. 원인이 무엇이든(스크랩·정책·데이터) 이상 가격이
# 마켓 API로 나가는 것 자체를 막는다. 취급 상품(패션)은 1억을 넘지 않는다.
PRICE_SANITY_CAP = 100_000_000


def exceeds_price_cap(*values) -> bool:
    """전송가/원가 후보 중 상한(1억) 이상이 있으면 True — 전송 차단용."""
    for v in values:
        try:
            if v is not None and float(v) >= PRICE_SANITY_CAP:
                return True
        except (TypeError, ValueError):
            continue
    return False


# 짧은 한글 금지어는 부분매칭 오탐이 압도적이라 정확일치만 적용하는 길이 상한.
# 실측(2026-07-25): '리지'→'오리지널' 2,789건, '람'→'바람막이' 726건,
# '리프'→'브리프' 459건 … SSG 등록분의 9.3%가 오탐으로 전송 차단됐다.
_FORBIDDEN_SHORT_KO_MAXLEN = 3
_HANGUL_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")

# 금지어 목록 → 매처 캐시. 목록은 전송 1회 동안 고정이라 매 상품마다 재컴파일하면
# 상품당 수백 회 regex 컴파일이 발생한다(금지어 1,544개 실측) → 전송 지연.
_forbidden_matcher_cache: dict[tuple[str, ...], tuple] = {}


def _get_forbidden_matcher(words: list[str]) -> tuple:
    """(라틴 단어경계 정규식, 짧은한글 {소문자: 원본}, 긴한글 [(소문자, 원본)]) 반환."""
    key = tuple(words)
    cached = _forbidden_matcher_cache.get(key)
    if cached is not None:
        return cached

    latin: list[str] = []
    short_ko: dict[str, str] = {}
    long_ko: list[tuple[str, str]] = []
    for w in words:
        if not w:
            continue
        if not _HANGUL_RE.search(w):
            latin.append(w)
        elif len(w) <= _FORBIDDEN_SHORT_KO_MAXLEN:
            short_ko.setdefault(w.lower(), w)
        else:
            long_ko.append((w.lower(), w))

    latin_re = None
    latin_map: dict[str, str] = {}
    if latin:
        for w in latin:
            latin_map.setdefault(w.lower(), w)
        # 긴 단어 우선 매칭 — 짧은 대안이 먼저 걸려 원본 복원이 어긋나지 않게.
        alt = "|".join(re.escape(w) for w in sorted(latin_map, key=len, reverse=True))
        latin_re = re.compile(rf"(?<![0-9a-z])({alt})(?![0-9a-z])")

    result = (latin_re, latin_map, short_ko, long_ko)
    # 캐시 폭주 방지 — 금지어 목록은 사실상 1~2종이라 여유 상한으로 충분
    if len(_forbidden_matcher_cache) > 32:
        _forbidden_matcher_cache.clear()
    _forbidden_matcher_cache[key] = result
    return result


def _forbidden_hit(words: list[str], product: dict[str, Any]) -> str | None:
    """금지어 게이트 판정 — 걸린 단어를 반환, 없으면 None.

    haystack = **실제 마켓에 나가는 등록상품명** + brand + 영문명.

    (a) `_original_name`(원상품명)을 haystack 에서 뺀다.
        삭제어(type=deletion)로 상품명에서 지운 단어가 원상품명에 남아 금지어로
        되살아나 전송이 막히던 결함(실측 725건). 예: '아디다스오리지널'은 삭제어라
        등록명엔 없는데 원상품명 때문에 금지어 '리지'에 매칭됐다.
        마켓에 나가지 않는 문자열로 전송을 막을 이유가 없다.
        brand/name_en 은 #414①(브랜드명을 금지어로 등록한 경우) 취지대로 유지.

    (b) 부분매칭 오탐 차단:
        - 라틴문자 금지어: 단어경계 일치. 'SENTI'가 'Essentials' 에, 'pat'이
          'patagonia' 에 걸리던 오탐 제거.
        - 한글 3글자 이하: brand 정확일치 또는 상품명의 공백단위 토큰 정확일치만.
          ('람'이 '바람막이'에 안 걸리되, brand='람' 이나 "람 자켓"은 계속 차단)
        - 한글 4글자 이상: 종전대로 부분매칭.
    """
    _name = product.get("name") or ""
    _brand = (product.get("brand") or "").strip()
    _name_en = product.get("name_en") or ""
    _hay = " ".join(s for s in (_name, _brand, _name_en) if s).lower()

    latin_re, latin_map, short_ko, long_ko = _get_forbidden_matcher(words)

    if latin_re is not None:
        m = latin_re.search(_hay)
        if m:
            return latin_map.get(m.group(1), m.group(1))

    if short_ko:
        if _brand.lower() in short_ko:
            return short_ko[_brand.lower()]
        for t in re.split(r"\s+", _name.lower()):
            if t in short_ko:
                return short_ko[t]

    for wl, w in long_ko:
        if wl in _hay:
            return w
    return None


# 상세 이미지 최소 가로를 요구하는 마켓.
# 토스: 600 미만이면 검수에서 "상세 이미지 가로 크기가 최소 600 이상이어야
# 합니다" 로 전량 반려된다(2026-09-04 파일럿 17건 실측). 무신사 원본이 500 이라
# 그대로 나가면 통과하지 못한다. 대표 썸네일 정사각 보정(dispatcher)과는 별개로,
# 상세에 들어가는 이미지 전체를 확대 미러링해야 한다.
_MIN_DETAIL_IMAGE_WIDTH: dict[str, int] = {"toss": 600}


def detail_image_min_width(market_type: str) -> int:
    """마켓이 요구하는 상세 이미지 최소 가로(px). 요구가 없으면 0."""
    return _MIN_DETAIL_IMAGE_WIDTH.get((market_type or "").lower(), 0)


async def ensure_detail_image_min_width(
    image_service: Any, market_type: str, product: dict[str, Any]
) -> dict[str, Any]:
    """상세 HTML 생성 전에 상품 이미지를 마켓 최소 가로로 확대 미러링한다.

    상세 이미지는 잘라내지 않는다(crop_square=False) — 정사각으로 만들면
    상세페이지에 흰 여백이 낀다.
    """
    min_dim = detail_image_min_width(market_type)
    images = product.get("images") or []
    if not min_dim or not images:
        return product

    try:
        mirrored, _, _ = await image_service.mirror_oversized_to_r2(
            images,
            max_dim=5000,
            min_dim=min_dim,
            crop_square=False,
        )
    except Exception as e:  # 보정 실패로 전송 자체가 죽으면 안 된다
        logger.warning(f"[전송] {market_type} 상세 이미지 확대 실패 — 원본 유지: {e}")
        return product

    if mirrored:
        product = dict(product)
        product["images"] = mirrored
    return product


def filter_accounts_by_policy(
    target_account_ids: list[str],
    accounts_by_id: dict[str, Any],
    policy_market_data: dict[str, Any],
) -> tuple[list[str], dict[str, str]]:
    """정책의 마켓 설정 기준으로 전송 대상 계정을 거른다.

    반환: (허용된 계정ID 목록, {정책에 설정이 없어 차단된 계정ID: 마켓 정책키})

    차단 규칙 두 가지:
      1. 정책의 해당 마켓에 accountId(s) 가 지정돼 있는데 대상 계정이 그 목록에
         없으면 차단 — 브랜드가 사업자 계정 사이에 흩어지는 것을 막는다.
      2. 정책에 그 마켓 설정 자체가 없으면 차단 — calc_market_price(219)가
         빈 dict 를 받아 feeRate·마켓 배송비를 통째로 건너뛰고 원가+공통마진만
         반영된 저가로 등록되기 때문이다. 계정이 "다르게" 지정된 경우는 막으면서
         "아예 없는" 경우만 통과시키는 건 앞뒤가 안 맞는다.
         실사고 2건:
           2026-07-21 eBay $28.32 저가등록 (policy_key 매핑 누락, 27~44 주석)
           2026-08-15 포이즌 전용(포이즌 키만 있는) 정책의 푸마 185건이 11번가로
                      나가 리셀가(원가 1.1~1.5배)로 등록 — 11번가 수수료 31.2%
                      감안하면 팔릴수록 손해였다.

    정책키가 어느 쪽에도 없는 마켓은 정책으로 판단할 근거가 없으므로 그대로 허용한다.
    """
    # 정책키 출처가 둘이다 — 이 모듈의 하드코딩 맵(27~44)과 플러그인이 자동 생성하는
    # plugins.MARKET_TYPE_TO_POLICY_KEY. 하드코딩 맵에는 poison/toss/amazon 등이
    # 빠져 있어 그것만 보면 포이즌 계정이 무조건 통과한다(이번 사고의 반대 방향 구멍).
    # 가드는 둘을 합쳐서 판단한다. 충돌 키는 없음(2026-08-15 실측).
    from backend.domain.samba.plugins import (
        MARKET_TYPE_TO_POLICY_KEY as _PLUGIN_POLICY_KEYS,
    )

    _policy_keys = {**_PLUGIN_POLICY_KEYS, **MARKET_TYPE_TO_POLICY_KEY}

    allowed: list[str] = []
    unconfigured: dict[str, str] = {}
    for aid in target_account_ids:
        acc = accounts_by_id.get(aid)
        if not acc:
            continue
        policy_key = _policy_keys.get(getattr(acc, "market_type", ""))
        if not policy_key:
            allowed.append(aid)
            continue
        mp = (policy_market_data or {}).get(policy_key) or {}
        if not mp:
            unconfigured[aid] = policy_key
            continue
        policy_acc_ids = mp.get("accountIds") or []
        if not policy_acc_ids and mp.get("accountId"):
            policy_acc_ids = [mp["accountId"]]
        # 정책에 계정 목록이 있으면 해당 계정만, 없으면 모두 허용
        if policy_acc_ids and aid not in policy_acc_ids:
            logger.warning(
                f"[전송] 계정 {aid} 정책 필터링됨 — policy_acc_ids={policy_acc_ids}, "
                f"market_type={getattr(acc, 'market_type', '')}"
            )
            continue
        allowed.append(aid)
    return allowed, unconfigured


def calc_market_price(
    cost: float,
    policy_pricing: dict,
    market_type: str,
    market_policies: dict | None = None,
    source_site: str = "",
    is_point_restricted: Optional[bool] = None,
) -> int:
    """정책 기반 마켓 최종 판매가 계산.

    원가 + 마진 + 배송비 → 소싱처 추가 마진 → 수수료 역산 → 추가요금.
    마켓별 오버라이드 적용. 범위 마진 지원. 소싱처별 추가 마진 지원.
    pointOnly=true 옵션이면 적립금 사용 가능 상품(is_point_restricted=False)에만 추가 마진 적용.
    """
    if not policy_pricing:
        return int(cost)
    pr = policy_pricing
    common_margin_rate = _resolve_margin_rate(cost, pr)
    common_shipping = pr.get("shippingCost", 0)
    common_extra = pr.get("extraCharge", 0)
    common_fee = pr.get("feeRate", 0)
    min_margin = pr.get("minMarginAmount", 0)

    policy_key = MARKET_TYPE_TO_POLICY_KEY.get(market_type, "")
    mp = (market_policies or {}).get(policy_key, {}) if policy_key else {}
    m_margin_rate = common_margin_rate
    m_shipping = mp.get("shippingCost") or common_shipping
    m_fee = mp.get("feeRate") or common_fee
    # 롯데홈쇼핑: marginRate 가 위탁수수료율로 쓰이는 구성(feeRate 없이 marginRate만) 대응 —
    # 정책마진 가드는 marginRate 를 수수료 fallback 으로 보는데 calc 는 feeRate 만 봐
    # gross-up 누락 → 비대칭. 가드와 동일하게 feeRate or marginRate or common_fee 순(#435).
    # mp.marginRate 는 calc 의 margin(common pr 기반)과 별개라 중복 차감 없음.
    if market_type == "lottehome":
        m_fee = mp.get("feeRate") or mp.get("marginRate") or common_fee

    margin_amt = round(cost * m_margin_rate / 100)
    if min_margin > 0 and margin_amt < min_margin:
        margin_amt = min_margin
    calc_price = cost + margin_amt + m_shipping

    # 소싱처별 추가 마진 (수수료 역산 전 적용 — 수수료에도 자동 반영됨)
    if source_site:
        _ssm = _get_source_site_margin(pr, source_site)
        _ss_rate = _ssm.get("marginRate", 0)
        _ss_amount = _ssm.get("marginAmount", 0)
        # pointOnly=true: 적립금 사용 가능 상품(is_point_restricted=False)에만 적용
        _point_only = bool(_ssm.get("pointOnly"))
        _apply_ssm = (not _point_only) or (is_point_restricted is False)
        # costThreshold>0이면 원가가 기준 미만일 때만 추가 마진 적용 (예: SSG 3만원 미만 배송비)
        _cost_threshold = _ssm.get("costThreshold", 0) or 0
        if _cost_threshold > 0 and cost >= _cost_threshold:
            _apply_ssm = False
        if _apply_ssm:
            if _ss_rate != 0:
                calc_price += round(cost * _ss_rate / 100)
            if _ss_amount != 0:
                calc_price += _ss_amount

    # General 광고(adEnabled) 사용 시 adRate(판매당 광고비)도 그로스업에 포함한다.
    # 안 그러면 광고로 팔릴 때 그 %만큼 마진에서 그대로 까인다(구매자 전가 X).
    # adRate/adEnabled 는 eBay 등 market_policies(mp)에만 존재 — 없으면 0이라 무영향.
    m_ad = float(mp.get("adRate", 0) or 0) if mp.get("adEnabled") else 0.0
    total_fee = m_fee + m_ad
    if total_fee > 0 and calc_price > 0:
        calc_price = math.ceil(calc_price / (1 - total_fee / 100))
    if common_extra > 0:
        calc_price += common_extra
    # 롯데홈쇼핑: 100원 단위 올림 — 내림 시 수수료 gross-up 결과가 정책마진 가드
    # 임계 바로 아래로 떨어져 마진미달 차단되는 비대칭 방지(#435).
    if market_type == "lottehome":
        return math.ceil(int(calc_price) / 100) * 100
    # 그 외: 100원 단위 내림 (111 → 100)
    return (int(calc_price) // 100) * 100


# 그룹상품 동시성 제어 락 (account_id별)
_group_locks: dict[str, asyncio.Lock] = {}

# 상품별 전송 락 — 동일 상품+동일 계정 조합 중복 전송 방지
_transmitting_products: set[tuple] = set()


# 전송 중단 플래그 — job_id별 분리 (멀티유저 격리)
import threading as _threading

_cancel_events: dict[str, _threading.Event] = {}
_cancel_lock = _threading.Lock()


def request_cancel_transmit(job_id: str | None = None):
    """전송 취소 요청.

    job_id가 주어지면 해당 잡만, None이면 모든 잡을 취소한다.
    """
    with _cancel_lock:
        if job_id is None:
            # 전체 취소 — 기존 이벤트 모두 set + 글로벌 마커
            for evt in _cancel_events.values():
                evt.set()
            _cancel_events.setdefault("__all__", _threading.Event()).set()
        else:
            evt = _cancel_events.setdefault(job_id, _threading.Event())
            evt.set()


def clear_cancel_transmit(job_id: str | None = None):
    """취소 플래그 해제.

    job_id가 주어지면 해당 잡만, None이면 모든 이벤트를 제거한다.
    """
    with _cancel_lock:
        if job_id is None:
            _cancel_events.clear()
        else:
            _cancel_events.pop(job_id, None)
            # __all__ 은 제거하지 않음 — 다른 잡이 아직 감지하지 못했을 수 있음
            # __all__ 해제는 clear_cancel_transmit(None)으로만 가능


def is_cancel_requested(job_id: str | None = None) -> bool:
    """취소가 요청되었는지 확인.

    job_id가 주어지면 해당 잡 또는 글로벌 취소를 확인,
    None이면 아무 이벤트라도 set이면 True.
    """
    with _cancel_lock:
        if job_id is None:
            return any(evt.is_set() for evt in _cancel_events.values())
        # 해당 job_id 이벤트 또는 글로벌(__all__) 이벤트 확인
        evt = _cancel_events.get(job_id)
        if evt and evt.is_set():
            return True
        global_evt = _cancel_events.get("__all__")
        return bool(global_evt and global_evt.is_set())


def _get_group_lock(account_id: str) -> asyncio.Lock:
    if account_id not in _group_locks:
        _group_locks[account_id] = asyncio.Lock()
    return _group_locks[account_id]


def clear_account_semaphores():
    """별도 스레드 실행 시 이전 이벤트 루프의 계정 차선 정리."""
    _account_lanes.clear()


# ────────────────────────────────────────────
# 계정 차선 우선순위 (부분 양보)
# ────────────────────────────────────────────
# 대량 신규전송과 오토튠 가격/재고 업데이트가 같은 계정 세마포어(동시 1건)를 나눠 쓰면서,
# 오토튠 부하가 클 때 신규등록 1건이 오토튠 update 뒤에 밀려 건당 수십초~수분까지 지연되던
# 문제(shared lane)를 완화한다. 신규등록(high)이 대기 중이면 수정(low)은 양보하되, floor 만큼
# 신규등록이 지나가면 강제 통과시켜 오토튠이 굶지 않게 한다(부분 양보 → 역마진/품절 긴급
# 갱신은 계속 흐름). 우선순위는 획득 지점의 is_update 로 판정. 기본 OFF → 켜기 전 동작 불변.

# 부분 양보 활성 여부 (기본 OFF — 켜기 전 동작 불변)
_LANE_PRIORITY_ENABLED = os.environ.get(
    "SSG_TRANSMIT_PRIORITY_ENABLED", "false"
).lower() in ("1", "true", "yes", "on")
# high 전송이 이만큼 처리되는 동안 low는 양보, 그 뒤엔 강제 통과 → 오토튠 최소 ~1/(FLOOR+1) 몫
_LANE_PRIORITY_FLOOR = int(os.environ.get("SSG_TRANSMIT_PRIORITY_FLOOR", "4"))
# 양보 폴링 간격(초)
_LANE_PRIORITY_SLICE = float(os.environ.get("SSG_TRANSMIT_PRIORITY_SLICE", "0.1"))
# low 가 양보할 수 있는 최대 시간(초) — 초과 시 무조건 경쟁 획득(안전 상한, 굶주림 방지)
_LANE_PRIORITY_MAX_YIELD_SEC = float(
    os.environ.get("SSG_TRANSMIT_PRIORITY_MAX_YIELD_SEC", "45")
)


# 계정 차선 동시성 (2026-08-04) — 기본 1(직렬). 무상태 REST 마켓은 동일 계정
# 병렬이 안전하므로 마켓별로 넓힐 수 있다. SSG 는 계정이 하나뿐이라 직렬 1건이
# 전체 처리량 상한(시간당 ~3천)이 되어, 오토튠 SSG 대기열이 2천대에 고착되던
# 병목 — 2부터 시작해 에러율 보며 단계 상향 (env ACCOUNT_LANE_CONCURRENCY 로
# "ssg=4,coupang=2" 형식 덮어쓰기 가능).
_ACCOUNT_LANE_CAP_DEFAULTS: dict[str, int] = {"ssg": 2, "ssg_std": 2}


def _account_lane_cap(market_type: str) -> int:
    caps = dict(_ACCOUNT_LANE_CAP_DEFAULTS)
    _env = os.environ.get("ACCOUNT_LANE_CONCURRENCY", "")
    for _pair in _env.split(","):
        if "=" in _pair:
            _mt, _, _v = _pair.partition("=")
            try:
                caps[_mt.strip()] = max(1, int(_v))
            except ValueError:
                pass
    return caps.get((market_type or "").strip(), 1)


class _AccountLane:
    """계정별 차선(기본 동시 1건, 마켓별 확장 가능) + 우선순위 부분양보 상태."""

    __slots__ = ("lock", "hp_waiting", "hp_served")

    def __init__(self, cap: int = 1) -> None:
        # BoundedSemaphore(1) == 기존 Lock 과 동일 시맨틱, cap>1 이면 병렬 허용
        self.lock = asyncio.BoundedSemaphore(max(1, cap))
        self.hp_waiting = 0  # 현재 대기/보유 중인 high(전송) 수
        self.hp_served = 0  # 누적 high 획득 수(양보 floor 계산용)


_account_lanes: dict[str, _AccountLane] = {}


def _get_account_lane(account_id: str, market_type: str = "") -> _AccountLane:
    lane = _account_lanes.get(account_id)
    if lane is None:
        lane = _AccountLane(cap=_account_lane_cap(market_type))
        _account_lanes[account_id] = lane
    return lane


async def _acquire_account_lane(
    account_id: str, priority: str, timeout: float, market_type: str = ""
) -> _AccountLane:
    """계정 차선을 획득한다. priority='low'는 high 전송이 대기 중이면 부분 양보한다.

    반환된 lane 은 반드시 _release_account_lane 으로 해제해야 한다.
    TimeoutError 발생 시 호출자가 처리(기존 세마포어와 동일 시맨틱).
    """
    lane = _get_account_lane(account_id, market_type)
    is_high = priority == "high"
    is_low = priority == "low"

    if is_high:
        lane.hp_waiting += 1
    try:
        # low: high 전송이 대기 중이면 양보(폴링). floor(누적 high 획득)와 시간 상한으로
        # 굶주림 방지 — 둘 중 하나라도 충족되면 즉시 경쟁 획득으로 넘어간다.
        if is_low and _LANE_PRIORITY_ENABLED and lane.hp_waiting > 0:
            _start_served = lane.hp_served
            _yield_deadline = time.monotonic() + _LANE_PRIORITY_MAX_YIELD_SEC
            while (
                lane.hp_waiting > 0
                and (lane.hp_served - _start_served) < _LANE_PRIORITY_FLOOR
                and time.monotonic() < _yield_deadline
            ):
                await asyncio.sleep(_LANE_PRIORITY_SLICE)
        await asyncio.wait_for(lane.lock.acquire(), timeout=timeout)
    finally:
        if is_high:
            lane.hp_waiting -= 1
    if is_high:
        lane.hp_served += 1
    return lane


def _release_account_lane(lane: _AccountLane) -> None:
    # BoundedSemaphore: 초과 해제 시 ValueError — 기존 locked() 가드의
    # 이중해제 방어를 예외 흡수로 대체 (cap>1 에선 locked() 가드가 오히려
    # 정상 해제를 건너뛰어 permit 누수를 만들기 때문).
    try:
        lane.lock.release()
    except ValueError:
        pass


STATUS_LABELS: dict[str, str] = {
    "pending": "대기중",
    "updating": "업데이트중",
    "transmitting": "전송중",
    "completed": "완료",
    "partial": "부분완료",
    "failed": "실패",
}


# 소싱처(쇼핑몰)가 직접 운영하는 이미지 CDN.
# 여기 올라온 사진은 소싱처가 직접 찍거나 검수해 올린 상품컷이다.
# 이 목록 **밖**의 호스트는 대부분 브랜드 자사몰이며(헬리한센 cafe24, 라코스테
# pdpcloud, 디스커버리·데상트·스노우피크 자사 CDN 등) 브랜드가 제작한 홍보물이라
# 그대로 재게시하면 지재권 문제가 된다.
# 실측(2026-07-22, 수집분 1,212장): 목록 밖 363장 = 30%.
#   SSG 217/217·롯데온 158/158 은 전량 자사 CDN(영향 없음),
#   GS 174/633, 무신사 194/204 가 목록 밖이다. 무신사는 브랜드 입점 마켓이라
#   상세를 브랜드가 올리는 구조 — 제거돼도 대표/추가(image.msscdn.net)는 남는다.
_SOURCING_CDN_HOSTS: tuple[str, ...] = (
    "ssgcdn.com",  # SSG
    "ssg.com",
    "lotteon.com",  # 롯데온
    "lotteimall.com",  # 롯데아이몰
    "ellotte.com",  # 롯데백화점
    "lotteeps.com",
    "m-gs.kr",  # GS샵
    "gsshop.com",
    "hmall.com",  # 현대홈쇼핑
    "thehyundai.com",  # 현대백화점
    "29cm.co.kr",  # 29CM
    "img.29cm.co.kr",
    "musinsa.com",  # 무신사
    "msscdn.net",
    "elandrs.com",  # 이랜드
)
# akamaized.net(공용 가속 CDN)은 넣지 않는다 — 브랜드 자사몰도 같은 CDN을 쓰므로
# 화이트리스트에 두면 정작 걸러야 할 브랜드 홍보물이 통과한다. 수집분 실측
# (2026-07-23, samba_collected_product.detail_images) 결과 akamaized 호스트를 쓰는
# 상품은 0건이라 제외해도 걸러지는 소싱처 이미지가 없다.


def _is_sourcing_cdn(url: str) -> bool:
    """소싱처 자체 CDN 이미지인지 (호스트 기준).

    정확일치 또는 서브도메인만 인정한다. 부분문자열 매칭(`d in host`)은
    `ssg.com.brand-cdn.example` 같은 무관한 호스트를 소싱처로 오인해 통과시킨다.
    """
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    # 포트·userinfo 제거 (netloc 은 'host:443' / 'user@host' 형태일 수 있다)
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in _SOURCING_CDN_HOSTS)


def _drop_brand_host_images(urls: list[str]) -> tuple[list[str], int]:
    """브랜드 자사몰 호스트 이미지를 제거. (남은 URL, 제거 수) 반환.

    AI 분류와 달리 결정적이라 같은 입력이면 항상 같은 결과다. 지재권 위험이
    가장 큰 부류(브랜드 제작 홍보물)를 판단 없이 확실하게 걷어낸다.
    소싱처 CDN 안에 있는 배너("24SS 신상품" 텍스트 이미지 등)는 이 규칙으로는
    걸러지지 않는다 — 그건 이미지 분류기(ImageFilterService)의 몫이다.
    """
    kept = [u for u in urls if _is_sourcing_cdn(u)]
    return kept, len(urls) - len(kept)


def _usable_image_urls(urls: Any) -> list[str]:
    """마켓에 URL 로 넘길 수 있는 이미지만 남긴다 (순서·중복 유지).

    마켓은 이미지를 URL 로 받아 자기 서버가 직접 가지러 간다. 따라서 http(s)
    절대 URL 이 아닌 것은 전송하면 그대로 등록 실패 또는 깨진 상세가 된다.
    실측(수집분 174개): `detail_images` 에 base64 `data:image/png;...` 가 5건
    섞여 있었다 — 소싱처 상세 HTML 을 파싱할 때 인라인 이미지가 그대로 들어온 것.

    프로토콜 상대경로(`//host/x.jpg`)는 버리지 않고 https 로 보정한다.
    """
    out: list[str] = []
    for u in urls or []:
        if not isinstance(u, str):
            continue
        u = u.strip()
        if not u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith(("http://", "https://")):
            continue
        out.append(u)
    return out


def _normalize_composition(raw: Any) -> list[str]:
    """상품명 조합 배열을 문자열 리스트로 정규화한다.

    name_composition / market_name_compositions 는 JSON 컬럼이라 스키마 강제가 없다.
    실측으로 market_name_compositions["11st"] 가 후보 배열의 배열
    `[["{브랜드명}","{상품명}"], ["{브랜드명}"]]` 로 저장된 사례가 있었고, 이 상태로
    _resolve_tag 에 들어가면 `tag in tag_map` 이 unhashable type: 'list' 로 터진다
    (= 해당 마켓 전송이 상품명 조합 단계에서 통째로 실패).

    다만 "후보 배열의 배열"은 손상이 아니라 의도된 형태다 — 11번가 상품명
    폴백 체인(_MARKET_NAME_MAX_BYTES / _compose_product_name)이 앞에서부터
    한도(99byte) 안에 들어가는 첫 조합을 고르는 데 쓴다. 그래서 중첩은 평탄화하지
    않고 각 후보만 정규화해 형태를 보존한다. 평탄화하면 첫 후보가 한도를 넘겨도
    그대로 나가 뒤쪽 상품번호가 잘린다(폴백이 존재하는 이유).
    그 외 비문자열은 버린다.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    if any(isinstance(t, (list, tuple)) for t in raw):
        cands = [_normalize_composition(t) for t in raw if isinstance(t, (list, tuple))]
        return [c for c in cands if c]
    return [t for t in raw if isinstance(t, str)]


class SambaShipmentService:
    def __init__(self, repo: SambaShipmentRepository, session: AsyncSession):
        self.repo = repo
        self.session = session

    @staticmethod
    def _extract_market_product_no(result: dict[str, Any] | None) -> str:
        """Scan nested success payloads and recover a market product number."""
        if not isinstance(result, dict):
            return ""

        candidate_keys = (
            "product_no",
            "spdNo",
            "epdNo",
            "originProductNo",
            "smartstoreChannelProductNo",
            "productNo",
            "sellerProductId",
            "itemId",
            "supPrdCd",
            "prdNo",
            "goodsNo",
            "product_id",
            "productId",
        )
        queue: list[Any] = [result]
        seen: set[int] = set()

        while queue:
            current = queue.pop(0)
            obj_id = id(current)
            if obj_id in seen:
                continue
            seen.add(obj_id)

            if isinstance(current, dict):
                for key in candidate_keys:
                    value = current.get(key)
                    if value not in (None, ""):
                        return str(value)
                for value in current.values():
                    if isinstance(value, (dict, list)):
                        queue.append(value)
            elif isinstance(current, list):
                queue.extend(
                    value for value in current if isinstance(value, (dict, list))
                )

        return ""

    @staticmethod
    def _apply_option_name_rules(options: list, name_rule: Any) -> list:
        """옵션명 치환 규칙 적용.

        name_rule.option_rules: [{"from": "원본", "to": "대체"}] 순서대로 치환.
        options 항목이 dict이면 'name'/'option_name' 키, str이면 값 자체를 치환.
        """
        rules: list[dict] = getattr(name_rule, "option_rules", []) or []
        if not rules:
            return options

        def _replace(text: str) -> str:
            for rule in rules:
                src, dst = rule.get("from", ""), rule.get("to", "")
                if src:
                    text = text.replace(src, dst)
            return text

        result = []
        for opt in options:
            if isinstance(opt, dict):
                opt = dict(opt)
                for key in ("name", "option_name"):
                    if key in opt and isinstance(opt[key], str):
                        opt[key] = _replace(opt[key])
                result.append(opt)
            elif isinstance(opt, str):
                result.append(_replace(opt))
            else:
                result.append(opt)
        return result

    async def _apply_name_rule_effects(
        self,
        product_row: Any,
        product_dict: dict,
        policy: Any,
    ) -> None:
        """정책의 명칭 규칙을 상품 옵션에 선적용하고 _name_rule 을 캐시."""
        if not policy:
            return
        name_rule_id = (getattr(policy, "extras", None) or {}).get("name_rule_id")
        if not name_rule_id:
            return
        from sqlmodel import select

        from backend.domain.samba.policy.model import SambaNameRule

        result = await self.session.exec(
            select(SambaNameRule).where(SambaNameRule.id == name_rule_id)
        )
        name_rule = result.first()
        if not name_rule:
            return
        # greenlet 방지: name_rule 을 세션에서 분리(expunge).
        # 이 객체는 product_dict["_name_rule"] 로 per-account 전송 루프 깊은 곳(_dispatch_one
        # 1680 .market_name_compositions)까지 운반되는데, 그 사이 rollback() 이 ORM 을 expire
        # 시키면 expired 컬럼 reload(SELECT)가 sync getattr 컨텍스트에서 발생 → MissingGreenlet.
        # 방금 SELECT 로 모든 컬럼이 로드된 상태이므로 detached 로도 접근 안전.
        self.session.expunge(name_rule)
        if product_dict.get("options"):
            product_dict["options"] = self._apply_option_name_rules(
                product_dict["options"], name_rule
            )
        product_dict["_name_rule"] = name_rule

    # ==================== CRUD ====================

    async def list_shipments(
        self, skip: int = 0, limit: int = 50, status: Optional[str] = None
    ) -> list[SambaShipment]:
        if status:
            return await self.repo.list_by_status(status)
        return await self.repo.list_async(
            skip=skip, limit=limit, order_by="-created_at"
        )

    async def list_by_status(self, status: str) -> list[SambaShipment]:
        return await self.repo.list_by_status(status)

    async def get_shipment(self, shipment_id: str) -> Optional[SambaShipment]:
        return await self.repo.get_async(shipment_id)

    async def create_shipment(self, data: dict[str, Any]) -> SambaShipment:
        return await self.repo.create_async(**data)

    async def update_shipment(
        self, shipment_id: str, data: dict[str, Any]
    ) -> Optional[SambaShipment]:
        return await self.repo.update_async(shipment_id, **data)

    async def delete_shipment(self, shipment_id: str) -> bool:
        return await self.repo.delete_async(shipment_id)

    async def list_by_product(self, product_id: str) -> list[SambaShipment]:
        return await self.repo.list_by_product(product_id)

    # ==================== 실제 상품 전송 ====================

    async def start_update(
        self,
        product_ids: list[str],
        update_items: list[str],
        target_account_ids: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
        skip_policy_account_filter: bool = False,
        on_account_done: Optional[
            Callable[[str, dict[str, Any]], Awaitable[None]]
        ] = None,
    ) -> dict[str, Any]:
        """여러 상품을 대상 마켓 계정으로 실제 전송. 마켓별 결과 반환."""

        # 이전 취소 플래그 잔존 방지는 워커가 잡 단위로 처리 (clear_cancel_transmit(job.id))
        # 여기서 인자 없이 호출하면 일시정지 글로벌 마커(__all__)까지 지워져서
        # 일시정지 누른 직후 다음 PENDING 잡이 즉시 클레임됨 — 절대 추가 금지

        processed = 0
        skipped = 0
        cancelled = 0
        results: list[dict[str, Any]] = []
        for product_id in product_ids:
            if False:
                logger.info("[마켓삭제] 클라이언트 연결 종료 감지 - 추가 삭제 중단")
            # 중단 체크
            if is_cancel_requested():
                cancelled = len(product_ids) - processed
                logger.info(
                    f"[전송] 강제 중단 — {processed}건 완료, {cancelled}건 취소"
                )
                # 일시정지 글로벌 마커(__all__) 유지 — 워커가 잡 단위로 해제
                break
            try:
                shipment = await self._transmit_product(
                    product_id,
                    target_account_ids,
                    update_items,
                    skip_unchanged=skip_unchanged,
                    skip_refresh=skip_refresh,
                    skip_policy_account_filter=skip_policy_account_filter,
                    on_account_done=on_account_done,
                )
                results.append(
                    {
                        "product_id": product_id,
                        "status": shipment.status,
                        "transmit_result": shipment.transmit_result or {},
                        "transmit_error": shipment.transmit_error or {},
                        "update_result": shipment.update_result or {},
                        "error": shipment.error,
                    }
                )
                processed += 1
            except Exception as exc:
                logger.error(f"상품 {product_id} 전송 실패: {exc}", exc_info=True)
                results.append(
                    {
                        "product_id": product_id,
                        "status": "failed",
                        "error": str(exc),
                    }
                )

        return {
            "processed": processed,
            "skipped": skipped,
            "cancelled": cancelled,
            "results": results,
        }

    # ==================== 그룹상품 전송 ====================

    async def transmit_group(self, product_ids: list[str], account_id: str) -> dict:
        """그룹상품을 스마트스토어에 등록."""

        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        from backend.domain.samba.proxy.smartstore import SmartStoreClient

        product_repo = SambaCollectedProductRepository(self.session)
        account_repo = SambaMarketAccountRepository(self.session)

        # 상품 조회
        products = []
        for pid in product_ids:
            p = await product_repo.get_async(pid)
            if p:
                products.append(p)
        if len(products) < 2:
            raise ValueError("그룹상품은 2개 이상의 상품이 필요합니다")

        # 계정 조회
        account = await account_repo.get_async(account_id)
        if not account:
            raise ValueError(f"계정을 찾을 수 없습니다: {account_id}")

        additional = account.additional_fields or {}
        client_id = additional.get("clientId") or account.api_key
        client_secret = additional.get("clientSecret") or account.api_secret
        client = SmartStoreClient(client_id, client_secret)

        # 카테고리 매핑 조회 — product.category(전체 경로) 우선
        first = products[0]
        raw_category = first.category or ""
        if not raw_category:
            cat_parts = [
                first.category1,
                first.category2,
                first.category3,
                first.category4,
            ]
            raw_category = " > ".join(c for c in cat_parts if c)

        mapped = await self._resolve_category_mappings(
            first.source_site or "",
            raw_category,
            [account_id],
        )
        category_id = mapped.get("smartstore", "")
        if not category_id:
            raise ValueError("카테고리 매핑을 찾을 수 없습니다")

        # 정책 조회 (가격 계산용)
        MARKET_TYPE_TO_POLICY_KEY = {
            "coupang": "쿠팡",
            "ssg": "신세계몰(전시)",
            "smartstore": "스마트스토어",
            "11st": "11번가",
            "gmarket": "G마켓",
            "auction": "옥션",
            "gsshop": "GS샵",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL",
            "kream": "KREAM",
            "ebay": "eBay",
            "playauto": "플레이오토",
        }
        policy = None
        policy_market_data: dict[str, Any] = {}
        if first.applied_policy_id:
            pol_repo = SambaPolicyRepository(self.session)
            policy = await pol_repo.get_async(first.applied_policy_id)
            if policy and policy.market_policies:
                policy_market_data = policy.market_policies

        # account_id별 동시성 락
        lock = _get_group_lock(account_id)
        async with lock:
            # guideId 조회
            guides = await client.get_purchase_option_guides(category_id)
            if not guides:
                # 카테고리 미지원 → 단일상품 폴백
                logger.info(
                    f"카테고리 {category_id} 그룹상품 미지원, 단일상품으로 전송"
                )
                for p in products:
                    await self._transmit_product(
                        p.id, [account_id], ["price", "stock", "image", "description"]
                    )
                return {
                    "group_product_no": None,
                    "product_count": len(products),
                    "deleted_count": 0,
                    "fallback": True,
                }
            guide_id = guides[0].get("guideId")

            # 기존 단일상품 삭제
            deleted_nos = []
            for p in products:
                market_nos = as_market_nos(p.market_product_nos)
                existing_no = real_market_no(market_nos.get(account_id))
                origin_no = real_market_no(market_nos.get(f"{account_id}_origin"))
                delete_no = origin_no or existing_no
                if delete_no:
                    try:
                        if isinstance(delete_no, dict):
                            delete_no = delete_no.get("originProductNo", delete_no)
                        await client.delete_product(str(delete_no))
                        deleted_nos.append(delete_no)
                    except Exception as exc:
                        logger.warning(
                            f"[전송] 그룹전송 기존 단일상품 삭제 실패 (no={delete_no}): {exc}"
                        )

            # 상품 데이터 준비 (가격 계산, 이미지 업로드)
            product_dicts = []
            for p in products:
                # OOM 방지: 전송에 불필요한 대용량 필드 제외
                pd = p.model_dump(exclude={"last_sent_data", "extra_data"})
                # 실측 사이즈표 — extra_data는 제외되므로 row에서 직접 주입 (#실측표)
                pd["actual_size"] = (p.extra_data or {}).get("actualSize")

                # 상세 HTML 재생성
                pd["detail_html"] = await self._build_detail_html(pd)

                # 정책 기반 판매가 계산 (기존 _transmit_product 라인 313-341 동일 패턴)
                if policy and policy.pricing:
                    # 토글 excludeHeldPoint=True 이면 보유적립금 제외 cost 사용
                    _resolved_cost = resolve_cost_for_policy(
                        p, policy.pricing, p.source_site or ""
                    )
                    cost = (
                        _resolved_cost
                        or pd.get("sale_price")
                        or pd.get("original_price")
                        or 0
                    )
                    cost_info = await convert_cost_by_source_site(
                        self.session, cost, p.source_site or "", p.tenant_id
                    )
                    effective_cost = cost_info["convertedCost"]
                    calc_price = calc_market_price(
                        effective_cost,
                        policy.pricing,
                        "smartstore",
                        policy_market_data,
                        source_site=p.source_site or "",
                        is_point_restricted=getattr(p, "is_point_restricted", None),
                    )

                    # 가격 이상치 방어: 원가가 정상가의 5% 미만이면 전송 차단
                    _orig_price = pd.get("original_price") or pd.get("sale_price") or 0
                    if _orig_price > 0 and cost > 0 and cost < _orig_price * 0.05:
                        logger.error(
                            f"[가격방어] 그룹전송 차단 — 원가 이상치: "
                            f"원가={int(cost):,}, 정상가={int(_orig_price):,}, "
                            f"계산가={calc_price:,}"
                        )
                        continue

                    # 가격 이상치 방어(상한): 원가/계산가 1억 이상은 오염으로 보고 차단(#625 보완)
                    if exceeds_price_cap(cost, calc_price):
                        logger.error(
                            f"[가격방어] 그룹전송 차단 — 가격 상한 초과: "
                            f"원가={int(cost):,}, 계산가={calc_price:,}"
                        )
                        continue

                    pd["_final_sale_price"] = calc_price
                    logger.info(
                        f"[그룹전송] 가격 계산: 원가={cost} → 판매가={calc_price}"
                    )

                # 이미지 업로드
                uploaded_images = []
                for img_url in (pd.get("images") or [])[:5]:
                    try:
                        naver_url = await client.upload_image_from_url(img_url)
                        uploaded_images.append(naver_url)
                    except Exception as exc:
                        logger.warning(
                            f"[전송] 그룹전송 이미지 업로드 실패, 원본 URL 사용: {exc}"
                        )
                        uploaded_images.append(img_url)
                pd["images"] = uploaded_images
                product_dicts.append(pd)

            # 페이로드 변환
            payload = SmartStoreClient.transform_group_product(
                products=product_dicts,
                category_id=category_id,
                guide_id=guide_id,
                account_settings=additional,
            )

            # 그룹상품 등록
            await client.register_group_product(payload)

            # 폴링
            try:
                poll_result = await client.poll_group_status(max_wait=120)
            except Exception as e:
                # 그룹 등록 실패 → 삭제된 상품 롤백 (단일상품 재등록)
                logger.error(f"그룹등록 실패, 단일상품으로 롤백: {e}")
                for p in products:
                    try:
                        await self._transmit_product(
                            p.id,
                            [account_id],
                            ["price", "stock", "image", "description"],
                        )
                    except Exception as rollback_exc:
                        logger.warning(
                            f"[전송] 그룹등록 실패 후 단일상품 롤백 실패 (pid={p.id}): {rollback_exc}"
                        )
                raise e

            # 결과 저장
            group_product_no = poll_result.get("groupProductNo")
            product_nos = poll_result.get("productNos", [])

            for i, p in enumerate(products):
                updates: dict[str, Any] = {"group_product_no": group_product_no}
                if i < len(product_nos):
                    pno = product_nos[i]
                    market_nos = dict(as_market_nos(p.market_product_nos))
                    market_nos[account_id] = {
                        "originProductNo": pno.get("originProductNo"),
                        "smartstoreChannelProductNo": pno.get(
                            "smartstoreChannelProductNo"
                        ),
                        "groupProductNo": group_product_no,
                    }
                    updates["market_product_nos"] = market_nos
                    registered = list(p.registered_accounts or [])
                    if account_id not in registered:
                        registered.append(account_id)
                    updates["registered_accounts"] = registered
                    updates["status"] = "registered"
                await product_repo.update_async(p.id, **updates)

            return {
                "group_product_no": group_product_no,
                "product_count": len(products),
                "deleted_count": len(deleted_nos),
            }

    async def _transmit_product(
        self,
        product_id: str,
        target_account_ids: list[str],
        update_items: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
        skip_policy_account_filter: bool = False,
        on_account_done: Optional[
            Callable[[str, dict[str, Any]], Awaitable[None]]
        ] = None,
    ) -> SambaShipment:
        """단일 상품에 대한 실제 마켓 전송."""

        # 상품 전송 락 — 동일 상품 + 동일 계정 조합 중복 전송 방지
        # (마켓이 다르면 같은 상품이라도 동시 전송 허용)
        _lock_key = (product_id, frozenset(target_account_ids))
        if _lock_key in _transmitting_products:
            shipment = await self.repo.create_async(
                product_id=product_id,
                target_account_ids=target_account_ids,
                update_items=update_items,
                status="failed",
                update_result={},
                transmit_result={},
                transmit_error={"_all": "이미 전송 중인 상품입니다."},
            )
            return shipment
        _transmitting_products.add(_lock_key)

        try:
            return await asyncio.wait_for(
                self._transmit_product_inner(
                    product_id,
                    target_account_ids,
                    update_items,
                    skip_unchanged,
                    skip_refresh,
                    skip_policy_account_filter,
                    on_account_done=on_account_done,
                ),
                timeout=300,  # 상품 1건당 최대 300초 (ESM 이미지 propagation 재시도 포함)
            )
        except asyncio.TimeoutError:
            logger.warning(f"[전송] 상품 {product_id} 전송 300초 타임아웃 — 스킵")
            shipment = await self.repo.create_async(
                product_id=product_id,
                target_account_ids=target_account_ids,
                update_items=update_items,
                status="failed",
                update_result={},
                transmit_result={},
                transmit_error={"_all": "전송 300초 타임아웃"},
            )
            return shipment
        finally:
            _transmitting_products.discard(_lock_key)

    async def _transmit_product_inner(
        self,
        product_id: str,
        target_account_ids: list[str],
        update_items: list[str],
        skip_unchanged: bool = False,
        skip_refresh: bool = False,
        skip_policy_account_filter: bool = False,
        on_account_done: Optional[
            Callable[[str, dict[str, Any]], Awaitable[None]]
        ] = None,
    ) -> SambaShipment:
        """상품 전송 실제 구현 (락 획득 후 호출)."""

        def _mem_mb():
            try:
                with open("/proc/self/status") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) // 1024
            except Exception as exc:
                logger.debug(f"[전송] 메모리 측정 실패 (비Linux 환경): {exc}")
                return -1

        logger.info(f"[메모리] 전송시작: {_mem_mb()}MB")

        # greenlet_spawn 방지: account 객체를 아래 expunge로 세션에서 분리하는 것이 진짜 픽스.
        # expire_on_commit=False는 sessionmaker(orm.py:195) 에서 이미 전역 설정되어 있어 여기선 no-op.
        # (삭제하지 않고 명시적으로 남겨 의도를 표시)

        from backend.domain.samba.account.model import SambaMarketAccount
        from backend.domain.samba.account.repository import SambaMarketAccountRepository
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import dispatch_to_market

        # 강제 중단 체크
        if is_cancel_requested():
            raise Exception("전송 강제 중단됨")

        # 1. shipment 레코드 생성
        shipment = await self.repo.create_async(
            product_id=product_id,
            target_account_ids=target_account_ids,
            update_items=update_items,
            status="pending",
            update_result={},
            transmit_result={},
            transmit_error={},
        )
        # greenlet 방지: shipment.id 를 plain 값으로 스냅샷. 전송 루프 내부의
        # connection-refresh rollback(_dispatch_one 시작부) 이 shipment ORM 을 expire
        # 시킨 뒤 루프 이후(merge 단계 update_async(shipment.id) 등)에서 shipment.id
        # 접근 시 reload→MissingGreenlet 발생(잔여 전송실패 원인). 불변 PK 라 스냅샷 안전.
        _shipment_id = shipment.id

        # 2. 상품 데이터 조회
        product_repo = SambaCollectedProductRepository(self.session)
        product_row = await product_repo.get_async(product_id)
        if not product_row:
            await self.repo.update_async(
                shipment.id, status="failed", error="상품을 찾을 수 없습니다."
            )
            return shipment

        # 이미지 없는 상품 전송 차단 — 마켓 등록 시 이미지 누락으로 오류/빈 이미지 등록 방지
        if not (product_row.images or []):
            _no_img_msg = "이미지 없음 — 전송 차단"
            logger.warning(
                f"[전송차단] 이미지 없음: {product_id} "
                f"({product_row.source_site} / {product_row.name[:40] if product_row.name else ''})"
            )
            await self.repo.update_async(
                shipment.id,
                status="failed",
                transmit_error={"_all": _no_img_msg},
            )
            return shipment

        # 롯데온/SSG의 '나이키' 브랜드 상품만 — AI 이미지 변환된 상품만 전송 허용
        # (다이나핏 등 다른 브랜드는 영향 없음)
        _AI_REQUIRED_SOURCE_SITES = {"LOTTEON", "SSG"}
        _AI_REQUIRED_BRANDS = {"NIKE", "나이키", "JORDAN", "조던"}
        _src_norm = (product_row.source_site or "").upper()
        _brand_norm = (product_row.brand or "").strip().upper().replace(" ", "")
        if (
            _src_norm in _AI_REQUIRED_SOURCE_SITES
            and _brand_norm in _AI_REQUIRED_BRANDS
        ):
            if not product_row.ai_image_transformed:
                # 예외: 타깃이 전부 플레이오토(EMP 솔루션)면 AI 변환 없이 허용.
                # 가드 취지는 마켓 직접 등록 시 원본 이미지 노출 차단 — 플레이오토
                # 단독 전송까지 막을 필요는 없다는 운영 판단(2026-07-23).
                _tgt_types: set[str] = set()
                _tgt_ids = {str(a) for a in (target_account_ids or []) if a}
                _resolved = 0
                if _tgt_ids:
                    from sqlmodel import select as _ai_sel

                    from backend.domain.samba.account.model import (
                        SambaMarketAccount as _AI_SMA,
                    )

                    _ai_res = await self.session.execute(
                        _ai_sel(_AI_SMA.id, _AI_SMA.market_type).where(
                            _AI_SMA.id.in_(_tgt_ids)
                        )
                    )
                    _ai_rows = _ai_res.all()
                    _resolved = len({str(r[0]) for r in _ai_rows})
                    _tgt_types = {str(r[1]) for r in _ai_rows}
                # 조회로 해석되지 않은 계정이 하나라도 있으면 차단한다.
                # 삭제·비활성 등으로 행이 빠지면 남은 타입이 {playauto} 뿐이라
                # 실제로는 다른 마켓이 섞인 전송인데 예외가 열린다(가드 무력화).
                if _resolved != len(_tgt_ids):
                    logger.warning(
                        f"[전송] AI 가드 예외 판정 불가 — 계정 {len(_tgt_ids)}건 중 "
                        f"{_resolved}건만 조회됨, 차단 유지: {product_id}"
                    )
                    _tgt_types = set()
                if _tgt_types and _tgt_types <= {"playauto"}:
                    logger.info(
                        f"[전송] AI 변환 미완료지만 플레이오토 단독 전송 → 허용: "
                        f"{product_id} ({product_row.source_site}/{product_row.brand})"
                    )
                else:
                    _msg = (
                        f"{product_row.source_site} 나이키 상품은 "
                        f"AI 이미지 변환 후에만 등록 가능합니다."
                    )
                    logger.info(
                        f"[전송] AI 변환 미완료 차단: {product_id} "
                        f"({product_row.source_site}/{product_row.brand})"
                    )
                    await self.repo.update_async(
                        shipment.id,
                        status="failed",
                        transmit_error={"_all": _msg},
                    )
                    return shipment

        # OOM 방지: 전송에 불필요한 대용량 필드 제외
        product_dict = product_row.model_dump(exclude={"last_sent_data", "extra_data"})
        # 실측 사이즈표 — extra_data는 제외되므로 row에서 직접 주입 (#실측표)
        product_dict["actual_size"] = (product_row.extra_data or {}).get("actualSize")

        # 수동등록 상품의 계정별 카테고리 (extra_data.manual_market_categories: {account_id: category_id})
        # extra_data는 product_dict에서 제외되므로 product_row에서 직접 읽음
        _raw_manual_cats: dict = (product_row.extra_data or {}).get(
            "manual_market_categories"
        ) or {}
        _manual_market_categories: dict[str, str] = {
            str(k): str(v) for k, v in _raw_manual_cats.items()
        }

        # 업데이트 항목이 체크되어 있으면 소싱처 최신화 먼저 실행
        # skip_refresh=True면 오토튠에서 이미 최신화 완료 → 건너뜀
        # 품절 상품만 최신화 — 재고 있는 상품은 불필요한 소싱처 API 호출 차단
        has_update = bool(update_items) and len(update_items) > 0
        _opts_for_sold = product_dict.get("options") or []
        _is_sold_out = (product_row.sale_status == "sold_out") or (
            bool(_opts_for_sold)
            and all(
                (o.get("stock") or 0) <= 0
                for o in _opts_for_sold
                if isinstance(o, dict)
            )
        )
        refresh_status = ""  # 프론트 로그용
        pending_refresh_updates: dict[str, Any] = {}  # 최종 업데이트에 통합
        # 신규등록 대상 여부 — 대상 계정 중 하나라도 이 상품의 마켓번호가 없으면 True.
        # (2026-08-14 에잇세컨즈 실사고) 기존 로직은 'DB가 품절일 때만' 전송 직전
        # 최신화를 해서, DB 재고가 낡아 있으면 그 값이 그대로 마켓에 등록된다 —
        # 실재고 1~2개 상품 11건이 재고 0(품절)으로 쿠팡 등록됨. 신규등록만큼은
        # DB를 신뢰하지 않고 실재고를 다시 읽는다. 끄기: TRANSMIT_FRESH_ON_REGISTER=0
        _fresh_on_register = os.environ.get("TRANSMIT_FRESH_ON_REGISTER", "1") != "0"
        _nos_for_fresh = product_row.market_product_nos
        if not isinstance(_nos_for_fresh, dict):
            _nos_for_fresh = {}
        _has_new_target = any(
            not real_market_no(_nos_for_fresh.get(_aid))
            and not any(
                real_market_no(_v)
                for _k, _v in _nos_for_fresh.items()
                if _k.startswith(f"{_aid}_")
            )
            for _aid in (target_account_ids or [])
        )
        if (
            ((has_update and _is_sold_out) or (_fresh_on_register and _has_new_target))
            and not skip_refresh
            and product_row.source_site
            and product_row.site_product_id
        ):
            try:
                from backend.domain.samba.collector.refresher import refresh_product

                refresh_result = await asyncio.wait_for(
                    refresh_product(product_row, source="transmit"),
                    timeout=60,  # 갱신이 전송 전체를 막지 않도록 60초 제한
                )
                # [순단 방어] 재수집이 '가용재고 0'을 반환했는데 직전 DB엔 재고가
                # 있었다면 일시 오류 가능성 — 3초 후 1회 재조회로 확정한다.
                # (2026-08-13 실측: 240 재고 1 상품이 전송 순간만 전량 0으로 읽혀
                # 쿠팡에 품절 등록, 2분 뒤 갱신에서 정상 복원)
                if (
                    not refresh_result.error
                    and refresh_result.new_options is not None
                    and available_stock(refresh_result.new_options) <= 0
                    and available_stock(product_row.options) > 0
                ):
                    logger.warning(
                        f"[전송] 재고 전량 0 응답 — DB엔 재고 있음, 3초 후 재검증: "
                        f"{(product_row.name or '')[:30]}"
                    )
                    await asyncio.sleep(3)
                    _second = await asyncio.wait_for(
                        refresh_product(product_row, source="transmit"),
                        timeout=60,
                    )
                    if not _second.error and _second.new_options is not None:
                        refresh_result = _second
                if refresh_result.error:
                    refresh_status = f"최신화실패:{refresh_result.error[:30]}"
                    logger.warning(f"[전송] 소싱처 최신화 실패: {refresh_result.error}")
                else:
                    # DB 반영
                    refresh_updates: dict[str, Any] = {
                        "last_refreshed_at": datetime.now(UTC),
                    }
                    if refresh_result.new_sale_price is not None:
                        refresh_updates["sale_price"] = refresh_result.new_sale_price
                    if refresh_result.new_original_price is not None:
                        refresh_updates["original_price"] = (
                            refresh_result.new_original_price
                        )
                    if refresh_result.new_cost is not None:
                        refresh_updates["cost"] = refresh_result.new_cost
                    if refresh_result.new_options is not None:
                        refresh_updates["options"] = refresh_result.new_options
                    if refresh_result.new_sale_status:
                        refresh_updates["sale_status"] = refresh_result.new_sale_status
                        # is_sold_out 제거 → sale_status로 통일
                    # 이미지 갱신: update_items에 "image"가 명시적으로 체크된 경우만.
                    # 단 AI 변환/편집된 이미지는 절대 소싱처 원본으로 되돌리지 않는다.
                    # 변환본은 images 컬럼을 in-place 덮어쓰므로 원본 백업이 없고,
                    # 여기서 원본으로 갈아치우면 지재권 신고 브랜드(데상트/엠엘비)나
                    # 마크비전 신고 브랜드(마뗑킴)의 원본 이미지가 그대로 마켓에 나간다.
                    # collector_refresh.py 의 갱신 경로에는 이미 같은 가드가 있는데
                    # 전송 경로에만 빠져 있었다(2026-08-14 확인, 경로별 보호 비대칭).
                    _img_locked = bool(
                        getattr(product_row, "ai_image_transformed", False)
                    ) or bool(
                        {"__ai_image__", "__img_edited__", "__img_filtered__"}
                        & set(product_row.tags or [])
                    )
                    _update_image = (
                        bool(update_items and "image" in update_items)
                        and not _img_locked
                    )
                    if _img_locked and update_items and "image" in update_items:
                        logger.info(
                            f"[전송] 이미지 갱신 skip — AI변환/편집 이미지 보호 "
                            f"(product={product_row.id})"
                        )
                    if refresh_result.new_images and _update_image:
                        refresh_updates["images"] = refresh_result.new_images
                    if refresh_result.new_detail_images and _update_image:
                        refresh_updates["detail_images"] = (
                            refresh_result.new_detail_images
                        )
                    # 가격/재고 이력 스냅샷 기록
                    snapshot: dict[str, Any] = {
                        "date": datetime.now(UTC).isoformat(),
                        "source": "transmit_refresh",
                        "sale_price": (
                            refresh_result.new_sale_price
                            if refresh_result.new_sale_price is not None
                            else product_row.sale_price
                        ),
                        "original_price": (
                            refresh_result.new_original_price
                            if refresh_result.new_original_price is not None
                            else product_row.original_price
                        ),
                        "cost": (
                            refresh_result.new_cost
                            if refresh_result.new_cost is not None
                            else product_row.cost
                        ),
                        "sale_status": refresh_result.new_sale_status or "in_stock",
                        "changed": refresh_result.changed,
                    }
                    # 옵션이 없어도 현재 옵션 스냅샷 기록
                    snap_opts = refresh_result.new_options or (
                        product_row.options if product_row.options else None
                    )
                    if snap_opts:
                        snapshot["options"] = snap_opts
                    history = list(product_row.price_history or [])
                    history.insert(0, snapshot)
                    # 최초 수집 1개 + 최근 4개 = 최대 5개
                    if len(history) <= 5:
                        refresh_updates["price_history"] = history
                    else:
                        refresh_updates["price_history"] = history[:4] + [history[-1]]
                    # 최종 업데이트에서 통합 저장
                    pending_refresh_updates = refresh_updates
                    for k, v in refresh_updates.items():
                        product_dict[k] = v
                    # 가격/재고 변동 각각 판단
                    old_cost = getattr(product_row, "cost", None)
                    new_cost = refresh_result.new_cost
                    cost_changed = new_cost is not None and new_cost != old_cost
                    old_opts = getattr(product_row, "options", None) or []
                    new_opts = refresh_result.new_options
                    stock_changed = False
                    stock_change_count = 0
                    if new_opts is not None:
                        old_stocks = {
                            o.get("name", ""): o.get("stock", 0) for o in old_opts
                        }
                        new_stocks = {
                            o.get("name", ""): o.get("stock", 0) for o in new_opts
                        }
                        stock_changes = [
                            k
                            for k in set(
                                list(old_stocks.keys()) + list(new_stocks.keys())
                            )
                            if old_stocks.get(k) != new_stocks.get(k)
                        ]
                        stock_changed = len(stock_changes) > 0
                        stock_change_count = len(stock_changes)
                    cur_cost_val = (
                        int(new_cost)
                        if new_cost is not None
                        else (int(old_cost) if old_cost else 0)
                    )
                    old_cost_int = int(old_cost) if old_cost else 0
                    new_cost_int = (
                        int(new_cost) if new_cost is not None else old_cost_int
                    )
                    refresh_status = f"원가 {old_cost_int:,}>{new_cost_int:,}, 재고변동 {stock_change_count}건"
                    logger.info(f"[전송] 소싱처 최신화 완료 — {refresh_status}")
            except asyncio.TimeoutError:
                refresh_status = "최신화실패:60초 타임아웃"
                logger.warning("[전송] 소싱처 최신화 타임아웃 (60초) — 갱신 건너뜀")
            except Exception as ref_e:
                refresh_status = f"최신화예외:{str(ref_e)[:30]}"
                logger.warning(f"[전송] 소싱처 최신화 예외: {ref_e}")
        # 최신화를 안 했어도 현재 원가 표시
        if not refresh_status:
            _cur_cost = int(product_row.cost or product_row.sale_price or 0)
            _opt_count = len(product_row.options or [])
            refresh_status = f"원가 {_cur_cost:,}, 옵션 {_opt_count}건"

        # 조기 스킵: 이미 등록된 상품 + 가격재고 업데이트 모드 + 변동 없음 → 나머지 로직 전부 건너뜀
        # 단, target 계정이 전부 이미 마켓에 등록돼 있을 때만. 미등록 계정이 섞이면
        # 신규 등록이 필요하므로 조기 스킵 금지 → 계정별 스킵 로직(아래 1849)이 처리한다.
        # (상품 status="registered"는 "어떤 계정엔가 등록됨"일 뿐, target 계정 등록을 보장 안 함)
        _raw_nos = product_row.market_product_nos
        _existing_nos_map = _raw_nos if isinstance(_raw_nos, dict) else {}

        def _acct_already_registered(_aid: str) -> bool:
            # 계정별 스킵과 동일한 키 규칙 (smartstore _origin, gmarket/auction _master)
            # __claiming__ 잔류 마커는 미등록 취급 — 등록으로 오인하면 영구 유령 (이슈 #579)
            if real_market_no(_existing_nos_map.get(_aid)):
                return True
            for _suf in ("_origin", "_master"):
                if real_market_no(_existing_nos_map.get(f"{_aid}{_suf}")):
                    return True
            return False

        _all_targets_registered = bool(target_account_ids) and all(
            _acct_already_registered(_aid) for _aid in target_account_ids
        )
        _is_registered = product_row.status == "registered" and bool(
            product_row.registered_accounts
        )
        if skip_unchanged and has_update and _is_registered and _all_targets_registered:
            # 소싱처 최신화에서 변동이 없었으면 즉시 스킵
            if not pending_refresh_updates or refresh_status.startswith("최신화실패"):
                pass  # 최신화 안 했거나 실패 → 스킵 판정 불가, 계속 진행
            else:
                _old_cost = product_row.cost or 0
                _new_cost = pending_refresh_updates.get("cost", _old_cost)
                _old_opts = product_row.options or []
                _new_opts = pending_refresh_updates.get("options", _old_opts)
                if _new_cost == _old_cost and _new_opts == _old_opts:
                    logger.info(
                        f"[전송] 조기 스킵 — 소싱처 변동 없음 (원가 {int(_old_cost):,})"
                    )
                    shipment = SambaShipment(
                        product_id=product_id,
                        status="skipped",
                        update_result=(
                            {"refresh": refresh_status} if refresh_status else None
                        ),
                        transmit_result={},
                        transmit_error={"_all": "소싱처 변동 없음 — 전송 생략"},
                    )
                    self.session.add(shipment)
                    await self.session.flush()
                    return shipment

        # 옵션 미수집 방어 — 옵션 그룹(option_group_names)이 있는데 옵션이 비어 있으면
        # 아직 수집이 안 된 상태다. 그대로 전송하면 EMP/마켓이 옵션 없는 상품으로 등록해
        # 대표단품(=상품명)이 옵션 자리에 들어가는 사고가 난다(11번가 "기본" 단일옵션
        # 사고와 동일 뿌리). 옵션이 수집된 뒤 전송되도록 이번 회차는 보류(skip)한다.
        _ogn = product_row.option_group_names or []
        _price_stock_only = bool(update_items) and set(update_items) <= {
            "price",
            "stock",
        }
        if _ogn and not (product_row.options or []) and not _price_stock_only:
            logger.warning(
                f"[전송] 옵션 미수집 — 전송 보류: {(product_row.name or '')[:30]} "
                f"(옵션그룹={_ogn})"
            )
            shipment = SambaShipment(
                product_id=product_id,
                status="skipped",
                update_result={"refresh": refresh_status} if refresh_status else None,
                transmit_result={},
                transmit_error={
                    "_all": f"옵션 미수집(그룹 {_ogn}) — 옵션 수집 후 재전송"
                },
            )
            self.session.add(shipment)
            await self.session.flush()
            return shipment

        # 옵션 0건 + 미갱신 방어 — SSG처럼 option_group_names 를 채우지 않는 소싱처는
        # 위 가드가 잡지 못한다(실사례: SSG 수집 직후 옵션 파싱이 빈 상태로 전송돼
        # 롯데홈에 단일상품 등록 — 이후 갱신에서 옵션 6건 회복). 파싱이 정상이면
        # 진짜 단일상품도 대표단품 1개는 있으므로(filter_daepyo_options) 옵션 0건은
        # 수집 미확정 신호다. 전송 직전 실시간 재조회가 옵션을 회복했으면 통과,
        # 아니면 첫 갱신(last_refreshed_at)으로 확정될 때까지 신규 등록을 보류한다.
        _eff_opts = (pending_refresh_updates or {}).get("options") or (
            product_row.options or []
        )
        if (
            not _eff_opts
            and product_row.last_refreshed_at is None
            and not _price_stock_only
        ):
            logger.warning(
                f"[전송] 옵션 0건·미갱신 — 전송 보류: {(product_row.name or '')[:30]} "
                f"({product_row.source_site})"
            )
            # 보류하더라도 이번 회차 갱신 결과(last_refreshed_at/options)는 반드시
            # 저장한다. 이 return 은 아래 통합 저장(update_data) 지점을 건너뛰므로,
            # 저장 없이 빠지면 last_refreshed_at 이 영원히 NULL → 다음 회차도 같은
            # 조건으로 보류되는 무한 루프가 된다. 미등록 상품은 오토튠 갱신 대상이
            # 아니라(registered_accounts 필터) 이 경로 말고는 채워줄 곳이 없어,
            # 진짜 단일상품(옵션 0건 확정)이 영구 미등록으로 남는다.
            if pending_refresh_updates:
                try:
                    await product_repo.update_async(
                        product_id,
                        **pending_refresh_updates,
                        updated_at=datetime.now(UTC),
                    )
                except Exception as _persist_e:
                    logger.warning(f"[전송] 보류 시 갱신결과 저장 실패: {_persist_e}")
            shipment = SambaShipment(
                product_id=product_id,
                status="skipped",
                update_result={"refresh": refresh_status} if refresh_status else None,
                transmit_result={},
                transmit_error={
                    "_all": "옵션 0건(수집 미확정) — 소싱처 갱신으로 확정 후 재전송"
                },
            )
            self.session.add(shipment)
            await self.session.flush()
            return shipment

        # 이미지/상세페이지 전송 판단
        is_price_stock_only = bool(update_items) and set(update_items) <= {
            "price",
            "stock",
        }
        needs_image = not is_price_stock_only

        # price/stock만 업데이트 시 이미지 다운로드/업로드 완전 스킵
        if is_price_stock_only:
            product_dict["_skip_image_upload"] = True

        # 상세 HTML은 항상 정책 기반으로 재생성 (원문 상세이미지 유출 방지)
        # 정책이 있는 경우 아래 1037에서 _apply_name_rule_effects 후 다시 빌드하므로
        # 여기서는 정책 없을 때만 빌드 (중복 호출 제거 — issue #249)
        if not is_price_stock_only and not product_row.applied_policy_id:
            product_dict["detail_html"] = await self._build_detail_html(product_dict)

        # 3. 카테고리 매핑 자동 조회 — product.category(전체 경로) 우선
        #    category1~4 개별 필드는 일부 소싱처에서 불완전할 수 있으므로
        #    전체 경로 문자열을 1순위로 사용
        policy = None
        policy_market_data: dict[str, Any] = {}
        if product_row.applied_policy_id:
            from backend.domain.samba.policy.repository import SambaPolicyRepository

            policy_repo = SambaPolicyRepository(self.session)
            policy = await policy_repo.get_async(product_row.applied_policy_id)
            if policy and policy.market_policies:
                policy_market_data = policy.market_policies
            await self._apply_name_rule_effects(product_row, product_dict, policy)
            if not is_price_stock_only:
                product_dict["detail_html"] = await self._build_detail_html(
                    product_dict
                )

        raw_category = product_row.category or ""
        if not raw_category:
            cat_parts = [
                product_row.category1,
                product_row.category2,
                product_row.category3,
                product_row.category4,
            ]
            raw_category = " > ".join(c for c in cat_parts if c)

        # 성별 prefix는 의류 카테고리일 때만 추가 (신발/가방 등은 제외)
        sex_prefix = ""
        cat1 = (product_row.category1 or "").strip()
        clothing_categories = {
            "상의",
            "하의",
            "아우터",
            "원피스",
            "니트",
            "셔츠",
            "팬츠",
            "의류",
        }
        if cat1 in clothing_categories:
            kream = (
                product_row.kream_data if hasattr(product_row, "kream_data") else None
            )
            if isinstance(kream, dict):
                sex_list = kream.get("sex", [])
                if isinstance(sex_list, list) and sex_list:
                    sex = sex_list[0]
                    if "남" in sex:
                        sex_prefix = "남성의류"
                    elif "여" in sex:
                        sex_prefix = "여성의류"

        source_category = (
            f"{sex_prefix} > {raw_category}"
            if sex_prefix and raw_category
            else raw_category
        )

        # 검색필터명 조회 (플레이오토 임의분류용)
        if product_row.search_filter_id:
            from backend.domain.samba.collector.repository import (
                SambaSearchFilterRepository,
            )

            sf_repo = SambaSearchFilterRepository(self.session)
            sf = await sf_repo.get_async(product_row.search_filter_id)
            logger.info(
                f"[전송] 검색필터 조회: search_filter_id={product_row.search_filter_id}, "
                f"found={sf is not None}, name={getattr(sf, 'name', None)}"
            )
            if sf and sf.name:
                product_dict["_search_filter_name"] = sf.name
        else:
            logger.warning(
                f"[전송] 상품 {product_row.id} search_filter_id 없음 → 임의분류 불가"
            )

        mapped_categories = await self._resolve_category_mappings(
            product_row.source_site or "",
            source_category,
            target_account_ids,
        )
        # 성별 prefix 포함 시 매핑 못 찾으면 prefix 없이 재시도
        if sex_prefix and not mapped_categories:
            mapped_categories = await self._resolve_category_mappings(
                product_row.source_site or "",
                raw_category,
                target_account_ids,
            )
        await self.repo.update_async(shipment.id, mapped_categories=mapped_categories)

        # 4. 업데이트 단계
        await self.repo.update_async(shipment.id, status="updating")
        update_result: dict[str, str] = {}
        for item in update_items:
            update_result[item] = "success"
        await self.repo.update_async(
            shipment.id, status="transmitting", update_result=update_result
        )

        # 5. 계정 정보 조회 및 마켓별 전송
        account_repo = SambaMarketAccountRepository(self.session)

        # 정책 기반 계정 필터링: 정책이 있으면 참조하되, 사용자 선택 계정은 보존
        MARKET_TYPE_TO_POLICY_KEY = {
            "coupang": "쿠팡",
            "ssg": "신세계몰(전시)",
            "smartstore": "스마트스토어",
            "11st": "11번가",
            "gmarket": "G마켓",
            "auction": "옥션",
            "gsshop": "GS샵",
            "lotteon": "롯데ON",
            "lottehome": "롯데홈쇼핑",
            "homeand": "홈앤쇼핑",
            "hmall": "HMALL",
            "kream": "KREAM",
            "ebay": "eBay",
            "lazada": "Lazada",
            "qoo10": "Qoo10",
            "shopee": "Shopee",
            "shopify": "Shopify",
            "zoom": "Zum(줌)",
            "toss": "토스",
            "rakuten": "라쿠텐",
            "amazon": "아마존",
            "buyma": "바이마",
            "playauto": "플레이오토",
        }
        if not product_row.applied_policy_id:
            logger.warning(f"[전송] 상품 {product_id} 정책 미설정 — 전송 차단")
            await self.repo.update_async(
                shipment.id,
                status="failed",
                error="정책 미적용 상품은 전송할 수 없습니다.",
            )
            return await self.repo.get_async(shipment.id) or shipment

        from backend.domain.samba.policy.repository import SambaPolicyRepository

        policy_repo = SambaPolicyRepository(self.session)
        policy = await policy_repo.get_async(product_row.applied_policy_id)
        if policy and policy.market_policies:
            policy_market_data = policy.market_policies
        # greenlet 방지: policy 도 세션에서 분리(expunge).
        # _dispatch_one 내부(1705 policy.extras / 1720 policy.pricing 등)에서 접근되는데
        # connection refresh rollback 이후면 expired reload → MissingGreenlet.
        # get_async 는 defer 없이 전 컬럼 로드 → detached 접근 안전.
        if policy is not None:
            try:
                self.session.expunge(policy)
            except Exception as _exp_pol:
                logger.debug(f"[전송] policy expunge 실패 (계속 진행): {_exp_pol}")

        # 글로벌 삭제어 조회 (compose 전에 미리 로드)
        from backend.domain.samba.forbidden.repository import (
            SambaForbiddenWordRepository,
        )

        fw_repo = SambaForbiddenWordRepository(self.session)
        _all_deletion = await fw_repo.list_active("deletion")
        _all_forbidden = await fw_repo.list_active("forbidden")
        # 공통(market=None) 삭제어 — 마켓 미확정 단계(기본 compose)에서 사용
        deletion_words = [
            w.word for w in (_all_deletion or []) if w.word and w.market is None
        ]
        # 마켓별 추가 삭제어 맵 {market_id: [words]} (공통은 기본 compose에서 이미 처리됨)
        _market_deletion_map: dict[str, list[str]] = {}
        for _w in _all_deletion or []:
            if _w.word and _w.market:
                _market_deletion_map.setdefault(_w.market, []).append(_w.word)
        # 금지어(상품 제외) — 공통 + 마켓별, _dispatch_one 의 마켓별 제외 게이트에서 사용
        _forbidden_common: list[str] = [
            w.word for w in (_all_forbidden or []) if w.word and w.market is None
        ]
        _market_forbidden_map: dict[str, list[str]] = {}
        for _w in _all_forbidden or []:
            if _w.word and _w.market:
                _market_forbidden_map.setdefault(_w.market, []).append(_w.word)

        # 금지어/삭제어 미적용 설정 로드 — 판매처(마켓)/소싱처 단위.
        # 설정값은 마켓 id 또는 source_site 문자열 배열. (SambaSettings key-value, 마이그레이션 불필요)
        # 테넌트 네임스페이스: 라우터가 f"{tenant_id}:{key}" 로 저장하므로 동일 규칙 + bare 키 폴백.
        from backend.domain.samba.forbidden.model import SambaSettings as _SambaSettings
        from sqlmodel import select as _sel_setting

        async def _load_exempt_set(_key: str) -> set[str]:
            _tid = product_row.tenant_id
            _candidates = [f"{_tid}:{_key}", _key] if _tid else [_key]
            for _ek in _candidates:
                _sr = await self.session.execute(
                    _sel_setting(_SambaSettings).where(_SambaSettings.key == _ek)
                )
                _srow = _sr.scalars().first()
                if _srow and isinstance(_srow.value, list):
                    return {str(_x) for _x in _srow.value if _x}
            return set()

        _exempt_markets = await _load_exempt_set("forbidden_exempt_markets")
        _exempt_sources = await _load_exempt_set("forbidden_exempt_sources")
        # 소싱처 미적용이면 모든 마켓에서 금지어/삭제어 전부 스킵
        _source_exempt = (product_row.source_site or "") in _exempt_sources

        def _strip_words_from_name(_name: str, _words: list[str]) -> str:
            """상품명에서 단어 목록 제거 (대소문자 무시 + 공백 정리). clean_product_name 미러."""
            _out = _name
            for _ww in _words:
                if _ww:
                    _out = re.sub(re.escape(_ww), "", _out, flags=re.IGNORECASE)
            return re.sub(r"\s+", " ", _out).strip()

        # 정책의 상품명 규칙(name_rule) 기반 상품명 조합 적용
        if policy and policy.extras:
            name_rule_id = (policy.extras or {}).get("name_rule_id")
            if name_rule_id:
                from backend.domain.samba.policy.model import SambaNameRule
                from sqlmodel import select

                stmt = select(SambaNameRule).where(SambaNameRule.id == name_rule_id)
                result = await self.session.exec(stmt)
                name_rule = result.first()
                if name_rule:
                    # greenlet 방지: 세션 분리 — 이후 _dispatch_one 1680
                    # .market_name_compositions 접근 시 expired reload 차단 (위 _apply_name_rule_effects 동일 사유)
                    self.session.expunge(name_rule)
                    product_dict["name"] = self._compose_product_name(
                        product_dict,
                        name_rule,
                        deletion_words=(None if _source_exempt else deletion_words),
                    )
                    # 마켓별 상품명 조합이 있으면 _dispatch_one에서 덮어쓸 수 있도록 name_rule 보관
                    product_dict["_name_rule"] = name_rule
                    product_dict["_original_name"] = product_row.name or ""
                    product_dict["_deletion_words"] = deletion_words

        # 정책이 있으면 계정 필터링, 없으면 사용자 선택 전체 유지
        # skip_policy_account_filter=True(테트리스 매칭 ON)이면 건너뜀 —
        # 테트리스 블럭이 계정을 결정하므로 정책 accountIds 필터 불필요
        #
        # 게이트 조건이 policy_market_data(내용) 가 아니라 policy(존재) 인 이유:
        # market_policies 가 통째로 비어 있으면 필터를 건너뛰던 예전 동작은
        # "마켓 설정이 하나도 없는 정책 = 전 마켓 무조건 허용" 이라 아래 미설정 차단을
        # 그대로 우회한다. 정책이 있으면 마켓 설정 유무와 무관하게 검사한다.
        unconfigured_markets: dict[str, str] = {}
        if policy is not None and not skip_policy_account_filter:
            # 배치 조회 (N+1 → 1회)
            from sqlmodel import select as _sel
            from backend.domain.samba.account.model import SambaMarketAccount

            _stmt = _sel(SambaMarketAccount).where(
                SambaMarketAccount.id.in_(target_account_ids)
            )
            _res = await self.session.execute(_stmt)
            _account_map = {a.id: a for a in _res.scalars().all()}

            filtered_ids, unconfigured_markets = filter_accounts_by_policy(
                target_account_ids, _account_map, policy_market_data
            )
            if unconfigured_markets:
                logger.warning(
                    f"[전송] 상품 {product_id} — 정책에 설정 없는 마켓 차단: "
                    f"{sorted(set(unconfigured_markets.values()))} "
                    f"(계정 {list(unconfigured_markets)}, "
                    f"policy_id={product_row.applied_policy_id}). "
                    f"수수료 미반영 저가등록 방지."
                )
            target_account_ids = filtered_ids
            if not target_account_ids:
                logger.warning(
                    f"[전송] 상품 {product_id} — 정책 accountIds 필터링으로 전송 계정 없음 "
                    f"(정책ID: {product_row.applied_policy_id}). "
                    f"테트리스 매칭 ON 상태에서 발생 시 skip_policy_account_filter 미전달 의심"
                )
                if unconfigured_markets:
                    _mk = ", ".join(dict.fromkeys(unconfigured_markets.values()))
                    _err = (
                        f"정책에 {_mk} 마켓 설정이 없어 전송 불가 — "
                        f"수수료·마진이 반영되지 않아 저가로 등록됩니다. "
                        f"정책({getattr(policy, 'name', '') or product_row.applied_policy_id})에 "
                        f"{_mk} 설정을 추가하거나, 해당 마켓을 판매하는 정책으로 상품을 옮기세요."
                    )
                else:
                    _err = (
                        "정책에 해당 계정이 없어 전송 불가 (정책 > 마켓 계정 설정 확인)"
                    )
                await self.repo.update_async(
                    shipment.id,
                    status="failed",
                    error=_err,
                )
                return await self.repo.get_async(shipment.id) or shipment
            logger.info(f"[전송] 정책 필터링 후 계정: {len(target_account_ids)}개")

        transmit_result: dict[str, str] = {}
        transmit_error: dict[str, str] = {}
        # 일부 계정만 차단된 경우(다른 마켓은 정상 전송) — 로그만 남기면 화면에서
        # "왜 이 마켓만 안 갔는지" 알 수 없다. 결과에 사유를 남긴다. (silent fail 금지)
        for _blocked_aid, _mk in unconfigured_markets.items():
            transmit_error[_blocked_aid] = (
                f"정책에 {_mk} 마켓 설정이 없어 전송하지 않음 — "
                f"수수료·마진 미반영 저가등록 방지"
            )
        plugin_messages: dict[str, str] = {}
        update_mode_accounts: set[str] = (
            set()
        )  # PATCH 모드였던 계정 (실패해도 등록정보 보존)
        logger.info(
            f"[전송] 상품 {product_id} 전송 대상 계정: {target_account_ids} / "
            f"매핑된 마켓: {list(mapped_categories.keys())}"
        )

        # 전송 대상 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel2
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA

        _stmt2 = _sel2(_SMA).where(_SMA.id.in_(target_account_ids))
        _res2 = await self.session.execute(_stmt2)
        _dispatch_account_map = {a.id: a for a in _res2.scalars().all()}
        # account 객체를 세션에서 분리 — 이후 commit이 ORM 객체를 expired로 만들어
        # _dispatch_one 내 account.market_type 접근 시 lazy load → greenlet_spawn 에러 발생.
        # expunge로 세션 분리 시 이미 로드된 컬럼 속성은 그대로 유지됨.
        for _acc_obj in _dispatch_account_map.values():
            try:
                self.session.expunge(_acc_obj)
            except Exception as _exp_e:
                logger.debug(f"[전송] account expunge 실패 (계속 진행): {_exp_e}")

        # 배치 읽기 완료 — soldout refresh(최대 30초) 전 커밋으로 idle in transaction 방지
        # commit 실패 시 rollback으로 SessionTransaction PREPARED 고착 차단(이슈#276)
        try:
            await self.session.commit()
        except Exception:
            try:
                await self.session.rollback()
            except Exception:
                pass

        # 전 옵션 품절 시 소싱처 1회 최신화 시도 (30초 타임아웃)
        _all_opts = product_dict.get("options") or []
        _all_sold = _all_opts and all(
            (o.get("isSoldOut", False) or (o.get("stock") or 0) <= 0)
            for o in _all_opts
            if isinstance(o, dict)
        )
        if (
            _all_sold
            and not pending_refresh_updates
            and product_row.source_site
            and product_row.site_product_id
        ):
            logger.info(
                f"[전송] 상품 {product_id} 전 옵션 품절 → 소싱처 1회 최신화 시도 (30초)"
            )
            try:
                from backend.domain.samba.collector.refresher import (
                    refresh_product as _refresh_sold,
                )

                _sold_refresh = await asyncio.wait_for(
                    _refresh_sold(product_row, source="transmit"),
                    timeout=30,
                )
                if not _sold_refresh.error and _sold_refresh.new_options is not None:
                    # 옵션/가격 업데이트
                    product_dict["options"] = _sold_refresh.new_options
                    if _sold_refresh.new_sale_price is not None:
                        product_dict["sale_price"] = _sold_refresh.new_sale_price
                    if _sold_refresh.new_original_price is not None:
                        product_dict["original_price"] = (
                            _sold_refresh.new_original_price
                        )
                    if _sold_refresh.new_cost is not None:
                        product_dict["cost"] = _sold_refresh.new_cost
                    if _sold_refresh.new_sale_status:
                        product_dict["sale_status"] = _sold_refresh.new_sale_status
                    # pending_refresh_updates에도 반영 (최종 DB 저장용)
                    pending_refresh_updates.update(
                        {
                            "options": _sold_refresh.new_options,
                            "last_refreshed_at": datetime.now(UTC),
                        }
                    )
                    if _sold_refresh.new_sale_price is not None:
                        pending_refresh_updates["sale_price"] = (
                            _sold_refresh.new_sale_price
                        )
                    if _sold_refresh.new_original_price is not None:
                        pending_refresh_updates["original_price"] = (
                            _sold_refresh.new_original_price
                        )
                    if _sold_refresh.new_cost is not None:
                        pending_refresh_updates["cost"] = _sold_refresh.new_cost
                    if _sold_refresh.new_sale_status:
                        pending_refresh_updates["sale_status"] = (
                            _sold_refresh.new_sale_status
                        )
                    # 가격/재고 변동 계산 (기존 최신화와 동일 포맷)
                    _old_cost = getattr(product_row, "cost", None) or 0
                    _new_cost = (
                        _sold_refresh.new_cost
                        if _sold_refresh.new_cost is not None
                        else _old_cost
                    )
                    # 재고변동 건수 — 품절↔재고 전환(무↔유)만 카운트 (단순 수량변화 제외)
                    from backend.domain.samba.collector.refresher import (
                        count_stock_transitions,
                    )

                    _old_opts = getattr(product_row, "options", None) or []
                    _stock_change_count = count_stock_transitions(
                        _old_opts, _sold_refresh.new_options
                    )
                    # 가격/재고 이력 스냅샷 기록
                    _snap = {
                        "date": datetime.now(UTC).isoformat(),
                        "source": "transmit_soldout_refresh",
                        "sale_price": (
                            _sold_refresh.new_sale_price
                            if _sold_refresh.new_sale_price is not None
                            else product_row.sale_price
                        ),
                        "original_price": (
                            _sold_refresh.new_original_price
                            if _sold_refresh.new_original_price is not None
                            else product_row.original_price
                        ),
                        "cost": (
                            _sold_refresh.new_cost
                            if _sold_refresh.new_cost is not None
                            else product_row.cost
                        ),
                        "sale_status": _sold_refresh.new_sale_status or "in_stock",
                        "changed": _sold_refresh.changed,
                        "options": _sold_refresh.new_options,
                    }
                    _history = list(product_row.price_history or [])
                    _history.insert(0, _snap)
                    if len(_history) <= 5:
                        pending_refresh_updates["price_history"] = _history
                    else:
                        pending_refresh_updates["price_history"] = _history[:4] + [
                            _history[-1]
                        ]
                    logger.info(
                        f"[전송] 품절 최신화 완료 — 원가 {int(_old_cost):,}>{int(_new_cost):,}, 재고변동 {_stock_change_count}건"
                    )
                    if not refresh_status:
                        refresh_status = f"원가 {int(_old_cost):,}>{int(_new_cost):,}, 재고변동 {_stock_change_count}건"
                else:
                    _err = (
                        _sold_refresh.error
                        if _sold_refresh.error
                        else "옵션 데이터 없음"
                    )
                    logger.info(f"[전송] 품절 최신화 실패 — {_err}")
                    if not refresh_status:
                        refresh_status = f"최신화실패:{_err[:50]}"
            except asyncio.TimeoutError:
                logger.warning("[전송] 전 옵션 품절 소싱처 최신화 타임아웃 (30초)")
            except Exception as _sold_e:
                logger.warning(f"[전송] 전 옵션 품절 소싱처 최신화 예외: {_sold_e}")

        # 모든 pre-read 완료 — asyncio.gather 전 커밋으로 idle in transaction 방지
        # (policy/name_rule/account 읽기가 여기까지 모두 완료됨)
        # commit 실패 시 rollback으로 SessionTransaction PREPARED 고착 차단(이슈#276)
        try:
            await self.session.commit()
        except Exception:
            try:
                await self.session.rollback()
            except Exception:
                pass

        # 계정별 전송을 병렬 코루틴으로 실행

        async def _dispatch_one(account_id: str) -> dict[str, Any]:
            """단일 계정 전송 — 결과 dict 반환."""
            res: dict[str, Any] = {
                "account_id": account_id,
                "status": "failed",
                "error": "",
                "plugin_message": "",
                "product_nos": {},
                "sent_snapshot": None,
                "is_update": False,
                "clear_nos": [],
                "db_update_failed": False,
            }
            # connection refresh: pool_recycle 후 만료된 연결 사전 교체.
            # account 객체는 expunge로 분리, product_row 필드는 _row_* 스냅샷으로 보존됨.
            try:
                from sqlalchemy import text as _gc_text

                await self.session.execute(_gc_text("SELECT 1"))
                await self.session.rollback()
            except Exception:
                pass
            try:
                # 전송 시작 전 취소 체크
                if is_cancel_requested():
                    res["error"] = "전송 취소됨"
                    res["status"] = "cancelled"
                    return res

                account = _dispatch_account_map.get(account_id)
                if not account:
                    logger.warning(
                        f"[전송] 계정 {account_id} DB에 없음 (dispatch_account_map 키: {list(_dispatch_account_map.keys())})"
                    )
                    # 삭제된 마켓 계정 — 해당 상품 registered_accounts 에서 자동 제거
                    # (legacy 루프가 동일 잡 무한 재생성하는 사고 방지)
                    res["error"] = f"계정을 찾을 수 없습니다 (삭제됨): {account_id}"
                    res["status"] = "failed"
                    try:
                        from sqlalchemy import text as _sa_text

                        await self.session.execute(
                            _sa_text(
                                "UPDATE samba_collected_product "
                                "SET registered_accounts = registered_accounts - :aid "
                                "WHERE id = :pid AND registered_accounts::jsonb ? :aid"
                            ),
                            {"aid": account_id, "pid": product_id},
                        )
                        await self.session.commit()
                        logger.warning(
                            f"[전송] 삭제계정 자동정리 — product={product_id} "
                            f"account={account_id} (registered_accounts -= 1)"
                        )
                    except Exception as _e:
                        logger.warning(
                            f"[전송] 삭제계정 registered_accounts 정리 실패: {_e}"
                        )
                    return res

                market_type = account.market_type
                logger.info(
                    f"[전송] {market_type}({account_id}) 시작 — category_id_in_map={mapped_categories.get(market_type, '없음')}"
                )

                # 0순위: 수동등록 상품의 판매처별 명시 카테고리
                # manual_market_categories는 {market_type: category_id} 구조
                # (구버전 호환: account_id 키도 fallback으로 조회)
                category_id = _manual_market_categories.get(
                    market_type, ""
                ) or _manual_market_categories.get(str(account_id), "")
                if category_id:
                    logger.info(
                        f"[전송] 수동등록 카테고리 사용: {market_type} account={account_id} → {category_id}"
                    )
                # 수동카테고리 없으면 기존 매핑 카테고리 사용
                if not category_id:
                    category_id = mapped_categories.get(market_type, "")

                # ESM Plus 크로스매핑: 지마켓↔옥션 자동 변환
                if not category_id and market_type in ("gmarket", "auction"):
                    other = "auction" if market_type == "gmarket" else "gmarket"
                    other_id = mapped_categories.get(other, "")
                    if other_id and str(other_id).isdigit():
                        from backend.domain.samba.proxy.esmplus import esm_map_category

                        category_id = esm_map_category(other_id, other, market_type)
                        if category_id:
                            logger.info(
                                f"[ESM 크로스매핑] {other}({other_id}) → {market_type}({category_id})"
                            )
                        else:
                            logger.warning(
                                f"[ESM 크로스매핑] {other}({other_id}) → {market_type} 변환 실패 (JSON 매핑 없음)"
                            )
                    else:
                        logger.warning(
                            f"[ESM 크로스매핑] {market_type}: {other} 매핑 없거나 비숫자 "
                            f"(other_id={other_id!r}, mapped={list(mapped_categories.keys())})"
                        )

                # 카페24/롯데홈쇼핑/GS샵은 플러그인 내부에서 자체 카테고리를 결정하므로 매핑 없어도 허용.
                # (GS샵: execute()가 소싱카테고리 기반 gsshop_category_map으로 prdClsCd|sectId 자동매칭)
                # 포이즌/크림은 카탈로그형 리셀 — 브랜드 품번(globalSkuId)으로 매칭하므로
                # 마켓 카테고리 자체가 불필요(plugin._validate_category가 "0" 반환). 매핑 게이트 면제.
                if not category_id and market_type not in (
                    "playauto",
                    "cafe24",
                    "lottehome",
                    "gsshop",
                    "poison",
                    "kream",
                ):
                    # 환경설정 미비(카테고리 매핑 부재)는 신규등록 실패가 아니라 skip —
                    # "failed" 로 두면 removable_failed 에 잡혀 등록 연결(market_product_nos)이
                    # 삭제된다 (이슈 #721)
                    res["status"] = "skipped"
                    res["error"] = "카테고리 매핑 없음"
                    logger.warning(
                        f"[전송] 상품 {product_id} → {market_type} 카테고리 매핑 없음 (스킵)"
                    )
                    return res

                # 롯데ON은 BC 접두사 카테고리 코드 사용 (BC41030100 형식)
                _lotteon_like = market_type in ("lotteon", "ssg")
                if (
                    market_type
                    not in (
                        "coupang",
                        "playauto",
                        "cafe24",
                        "lottehome",
                        "gsshop",
                        "poison",
                        "kream",
                    )
                    and not _lotteon_like
                    and not str(category_id).isdigit()
                ):
                    res["error"] = f"최하단 카테고리 매핑 필요 (현재: {category_id})"
                    logger.warning(
                        f"[전송] 상품 {product_id} → {market_type} 최하단 카테고리 미매핑: '{category_id}' (스킵)"
                    )
                    return res

                # 전 옵션 품절 체크 — 마켓 등록 상품이면 마켓 삭제, 미등록이면 스킵
                _opts = product_dict.get("options") or []
                if _opts and all(
                    (o.get("isSoldOut", False) or (o.get("stock") or 0) <= 0)
                    for o in _opts
                    if isinstance(o, dict)
                ):
                    # 이미 마켓 등록된 상품이면 삭제 처리
                    _reg_accs = product_dict.get("registered_accounts") or []
                    # 전옵션 품절 처리: 마켓 등록 여부에 따라 삭제 시도
                    if account_id in _reg_accs:
                        # 등록된 계정 → 마켓 삭제 시도
                        try:
                            from backend.domain.samba.shipment.dispatcher import (
                                delete_from_market,
                            )

                            # 디스패처는 product["market_product_no"][market_type] 키를 읽음
                            # product_dict는 model_dump 결과라 market_product_nos(복수형)만 있고
                            # market_product_no(단수형)는 없음 → 명시적으로 주입 필요.
                            # 스마트스토어는 삭제 API가 originProductNo를 요구하므로
                            # {account_id}_origin 키 우선 (delete_from_markets 2347-2363과 동일 패턴)
                            _m_nos_raw = product_row.market_product_nos
                            _m_nos = _m_nos_raw if isinstance(_m_nos_raw, dict) else {}
                            if market_type == "smartstore":
                                _pno = _m_nos.get(f"{account_id}_origin", "")
                                if not _pno:
                                    _raw = _m_nos.get(account_id, "")
                                    if isinstance(_raw, dict):
                                        _pno = (
                                            _raw.get("originProductNo")
                                            or _raw.get("smartstoreChannelProductNo")
                                            or _raw.get("groupProductNo")
                                            or ""
                                        )
                                    else:
                                        _pno = _raw
                                _pno = str(_pno) if _pno else ""
                            elif market_type in ("gmarket", "auction"):
                                # ESM 삭제 API는 마스터 goodsNo 필요 — _master 우선
                                _pno = _m_nos.get(f"{account_id}_master") or _m_nos.get(
                                    account_id, ""
                                )
                            else:
                                _pno = _m_nos.get(account_id, "")
                            _del_pd = {
                                **product_dict,
                                "market_product_no": {market_type: _pno},
                            }

                            # HTTP 마켓 삭제 전 커밋 — idle in transaction 방지
                            # commit 실패 시 rollback으로 SessionTransaction PREPARED 고착 차단(이슈#276)
                            try:
                                await self.session.commit()
                            except Exception:
                                try:
                                    await self.session.rollback()
                                except Exception:
                                    pass
                            del_result = await delete_from_market(
                                self.session, market_type, _del_pd, account=account
                            )
                        except Exception as _api_e:
                            logger.warning(
                                f"[전송] 전옵션 품절 마켓 삭제 API 예외: {_api_e}"
                            )
                            res["error"] = "전 옵션 품절 (마켓삭제 실패)"
                        else:
                            # API 호출 성공 → DB 업데이트는 best-effort
                            if del_result.get("success") and not del_result.get(
                                "soldout_fallback"
                            ):
                                # 실제 삭제(DELETE 200) 시에만 registered_accounts 제거
                                # ★포이즌 제외 — 입찰 취소일 뿐 상품 삭제가 아니다.
                                # 등록에서 빼면 오토튠 스캔 대상에서 사라져 재입고 시
                                # 자동 재등록(manual_listing)이 영영 안 걸린다.
                                try:
                                    _prod = (
                                        None
                                        if market_type == "poison"
                                        else await SambaCollectedProductRepository(
                                            self.session
                                        ).get_async(product_id)
                                    )
                                    if _prod:
                                        new_reg = [
                                            a
                                            for a in (_prod.registered_accounts or [])
                                            if a != account_id
                                        ]
                                        _prod.registered_accounts = (
                                            new_reg if new_reg else None
                                        )
                                        await self.session.commit()
                                except Exception as _db_e:
                                    logger.warning(
                                        f"[전송] DB 업데이트 실패 (마켓삭제는 성공): {_db_e}"
                                    )
                                    res["db_update_failed"] = True
                                # DB 실패 무관하게 API 성공은 "completed" 처리
                                res["status"] = "completed"
                                res["results"] = {account_id: "deleted"}
                                logger.info(
                                    f"[전송] 상품 {product_id} → {market_type} 전 옵션 품절 → 마켓 삭제 완료"
                                )
                                return res
                            else:
                                # API 호출은 성공했으나 soldout_fallback=True 또는 success=False
                                res["error"] = "전 옵션 품절 (마켓삭제 실패)"

                    # 품절 스킵 케이스: status를 skipped로 명시, error 기본값 보정
                    # (res.status=="completed"는 마켓삭제 완료 → 이미 return된 상태이므로 여기 도달 안함)
                    res["status"] = "skipped"
                    if not res.get("error"):
                        res["error"] = "전 옵션 품절"
                    logger.info(
                        f"[전송] 상품 {product_id} → {market_type} 전 옵션 품절 스킵"
                    )
                    return res

                # 마켓별 판매가 계산 (product_dict 원본 보호를 위해 복사본 사용)
                acct_product = dict(product_dict)
                # GS샵 등 부분수정 플러그인용 — 요청된 필드(재고/가격)만 전송하도록 전달
                acct_product["_update_items"] = update_items

                # SSG 신규등록 전 동일상품명 선점 검사 (중복수집 충돌 사전차단).
                #
                # ★2026-07-27: SSG 는 같은 상품명이 이미 등록돼 있으면 "동일한 상품이 이미
                # 존재"로 신규등록을 거부한다. 롯데온 수집이 같은 소싱처 상품을 회차마다
                # 새 수집상품으로 만들어(유니크 제약 없음 + 서브키워드 모드에서 중복필터
                # 비활성) 동일 상품명 형제가 최대 11개까지 생겼고, 그 결과 첫 건만 등록되고
                # 나머지는 매 전송마다 거부당했다(허수 등록기록 13,609건의 81%).
                # 거부가 뻔한 전송은 시도 자체를 하지 않는다 — SSG API 부하·잡 시간 낭비 방지.
                if market_type == "ssg" and not real_market_no(
                    (product_row.market_product_nos or {}).get(account_id)
                    if isinstance(product_row.market_product_nos, dict)
                    else None
                ):
                    _dup_owner = await self._find_ssg_name_owner(
                        product_id, product_row.name or "", account_id
                    )
                    if _dup_owner:
                        res["status"] = "skipped"
                        res["error"] = (
                            f"동일 상품명이 이미 등록됨(중복 수집분 {_dup_owner} 선점) — "
                            "중복 상품 정리 필요"
                        )
                        logger.info(
                            f"[SSG] 동일상품명 선점 → 전송 스킵: product={product_id} "
                            f"owner={_dup_owner}"
                        )
                        return res

                # SSG 표준카테고리(stdCtgId) 주입 — ssg_std 매핑값을 _std_category_id로 전달
                if market_type == "ssg":
                    _std_cat = mapped_categories.get("ssg_std", "")
                    if _std_cat:
                        acct_product["_std_category_id"] = _std_cat
                        logger.info(
                            f"[SSG] 표준카테고리 주입: dispCtgId={mapped_categories.get('ssg', '')!r}, stdCtgId={_std_cat!r}"
                        )
                    else:
                        logger.warning("[SSG] ssg_std 매핑 없음 — 표준카테고리 미전송")

                # 마켓별 상세페이지 템플릿 오버라이드
                # 프론트엔드는 market_type(영문 ID: "playauto")을 키로 저장
                # 금지어/삭제어 미적용 판단 — 소싱처 미적용이거나 이 판매처가 미적용 목록이면 스킵
                _skip_filter = _source_exempt or (market_type in _exempt_markets)

                # 마켓별 상품명 조합 덮어쓰기
                _nr = product_dict.get("_name_rule")
                # 미적용이면 삭제어 없이 조합
                _del_for_market = (
                    None if _skip_filter else product_dict.get("_deletion_words")
                )
                _has_market_comp = bool(
                    _nr
                    and getattr(_nr, "market_name_compositions", None)
                    and _nr.market_name_compositions.get(market_type)
                )
                if _has_market_comp:
                    # 원본 상품 데이터로 마켓별 조합 실행
                    _orig = dict(product_dict)
                    _orig["name"] = product_dict.get(
                        "_original_name", product_dict.get("name", "")
                    )
                    acct_product["name"] = self._compose_product_name(
                        _orig,
                        _nr,
                        market_type=market_type,
                        deletion_words=_del_for_market,
                    )
                elif _skip_filter and _nr:
                    # 미적용 마켓: 공통 삭제어가 base compose 단계에서 이미 박혔으므로
                    # 삭제어 없이 재조합해 원복(원본 상품명 기준).
                    _orig = dict(product_dict)
                    _orig["name"] = product_dict.get(
                        "_original_name", product_dict.get("name", "")
                    )
                    acct_product["name"] = self._compose_product_name(
                        _orig,
                        _nr,
                        market_type=market_type,
                        deletion_words=None,
                    )

                # 마켓별 추가 삭제어 제거 (공통은 _compose 단계서 이미 처리됨)
                _mkt_del_words = (
                    None if _skip_filter else _market_deletion_map.get(market_type)
                )
                if _mkt_del_words and acct_product.get("name"):
                    acct_product["name"] = _strip_words_from_name(
                        acct_product["name"], _mkt_del_words
                    )

                # 마켓별 금지어 제외 게이트 — 공통 + 마켓 전용 금지어가 상품명에
                # 포함되면 해당 마켓 전송에서 제외(실패/동결 아님 → skipped).
                # 가격/재고 전용(오토튠) 갱신은 이미 등록된 상품 대상이므로 제외하지 않음
                # (제외 시 기존 등록분이 가격 갱신에서 영영 누락됨).
                _fb_words = (
                    list(_forbidden_common)
                    + (_market_forbidden_map.get(market_type) or [])
                    if (not is_price_stock_only and not _skip_filter)
                    else []
                )
                if _fb_words:
                    _hit = _forbidden_hit(_fb_words, acct_product)
                    if _hit:
                        res["status"] = "skipped"
                        res["error"] = f"금지어 '{_hit}' 포함 — {market_type} 전송 제외"
                        res["_clear_failed_at"] = True
                        logger.info(
                            f"[전송] 금지어 제외 — product={product_id} "
                            f"market={market_type} word={_hit}"
                        )
                        return res

                # ── 위험 브랜드 인식(경고 전용, 전송과 무관) ──
                # 전송을 막지 않는다 — status/return 을 건드리지 않고 로그만 남긴다.
                # 쿠팡은 plugins/markets/coupang.py 에 이미 자체 BrandGuardService
                # 체크(API 실시간 판별 포함, 실제 차단함)가 있어 여기서 건드리지
                # 않는다. 다른 마켓은 그 판별 수단이 없으므로 "명시적으로 위험하다고
                # 이미 확인된 브랜드"(verdict=blocked)만 로그로 알리고, unknown(미확인)
                # 은 아예 조용히 지나간다 — 검토 안 된 브랜드까지 알리면 노이즈만 커진다.
                if (
                    not is_price_stock_only
                    and not _skip_filter
                    and market_type != "coupang"
                ):
                    _risk_brand = acct_product.get("brand") or ""
                    if _risk_brand:
                        from backend.domain.samba.brand.model import VERDICT_BLOCKED
                        from backend.domain.samba.brand.service import (
                            BrandGuardService,
                        )

                        _guard = BrandGuardService(self.session)
                        _risk_result = await _guard.check(
                            _risk_brand,
                            coupang_client=None,  # 이 마켓엔 실시간 API 판별 수단 없음
                            tenant_id=getattr(product_row, "tenant_id", None),
                            record=False,  # 조회만 — DB 기록 없음(인식만)
                        )
                        if _risk_result.verdict == VERDICT_BLOCKED:
                            logger.warning(
                                f"[위험브랜드 경고] product={product_id} "
                                f"market={market_type} brand={_risk_brand} "
                                f"reason={_risk_result.reason} — 전송은 그대로 진행됨"
                            )
                        # status/return 미변경 — 전송 흐름 계속 진행

                if not is_price_stock_only:
                    # 상세 이미지 최소 가로 보정(토스 600) — 상세 HTML 생성 전에 교체
                    if detail_image_min_width(market_type):
                        from backend.domain.samba.image.service import (
                            ImageTransformService,
                        )

                        acct_product = await ensure_detail_image_min_width(
                            ImageTransformService(self.session),
                            market_type,
                            acct_product,
                        )
                    _detail_tpl_id = ""
                    if policy and policy.extras:
                        _detail_tpl_id = (
                            policy.extras.get("market_detail_templates") or {}
                        ).get(market_type) or ""
                    if _detail_tpl_id:
                        logger.info(
                            f"[전송] 마켓별 상세 템플릿 적용: market={market_type}, tpl_id={_detail_tpl_id}"
                        )
                    acct_product["detail_html"] = await self._build_detail_html(
                        acct_product,
                        template_id_override=_detail_tpl_id,
                    )
                # 토글 excludeHeldPoint=True 이면 보유적립금 제외 cost 사용
                _resolved_cost = resolve_cost_for_policy(
                    product_row,
                    policy.pricing if policy else None,
                    product_row.source_site or "",
                )
                cost = (
                    _resolved_cost
                    or acct_product.get("sale_price")
                    or acct_product.get("original_price")
                    or 0
                )
                if policy and policy.pricing:
                    cost_info = await convert_cost_by_source_site(
                        self.session,
                        cost,
                        product_row.source_site or "",
                        product_row.tenant_id,
                    )
                    effective_cost = cost_info["convertedCost"]
                    # 계정 설정탭 feeRate 우선 — policy market_policies.feeRate 오버라이드
                    _acct_extras = (account.additional_fields or {}) if account else {}
                    _acct_fee_rate = int(_acct_extras.get("feeRate") or 0)
                    _pkey = MARKET_TYPE_TO_POLICY_KEY.get(market_type, "")
                    # GS샵: 정책의 계정별 설정(gsSettingsByAccount[account.id].feeRate)이
                    # 있으면 그 계정 판매수수료를 판매가 형성에 적용 (마놀 25% / 캐논 13% 등).
                    # 한 정책에 GS 계정이 여러 개 묶여 계정마다 수수료가 다른 경우 대응.
                    _acc_id = str(getattr(account, "id", "") or "") if account else ""
                    if _pkey and _acc_id:
                        _gs_by_acc = (policy_market_data.get(_pkey, {}) or {}).get(
                            "gsSettingsByAccount"
                        ) or {}
                        _gs_acc_cfg = _gs_by_acc.get(_acc_id)
                        if isinstance(_gs_acc_cfg, dict) and _gs_acc_cfg.get("feeRate"):
                            _acct_fee_rate = int(_gs_acc_cfg["feeRate"])
                    _effective_market_data = policy_market_data
                    if _acct_fee_rate and _pkey:
                        _mp_copy = dict(policy_market_data.get(_pkey, {}))
                        _mp_copy["feeRate"] = _acct_fee_rate
                        _effective_market_data = {
                            **policy_market_data,
                            _pkey: _mp_copy,
                        }
                    # 이베이 배송비($)는 원화 계산에서 제외 — 환율 곱하지 않고
                    # ebay.py에서 USD 그대로 수수료만 그로스업해서 최종 가격에 더함.
                    if market_type == "ebay" and _pkey:
                        _ebay_mp_zeroed = dict(_effective_market_data.get(_pkey, {}))
                        _ebay_mp_zeroed["shippingCost"] = 0
                        _effective_market_data = {
                            **_effective_market_data,
                            _pkey: _ebay_mp_zeroed,
                        }
                    # 고정가 등록 — price_locked=True면 정책 공식 재계산 없이
                    # locked_prices[account_id] 그대로 사용 (오토튠 가격갱신 제외 요청 대응).
                    _locked_price = None
                    if getattr(product_row, "price_locked", False):
                        _locked_prices = (
                            getattr(product_row, "locked_prices", None) or {}
                        )
                        _locked_price = _locked_prices.get(_acc_id)

                    if _locked_price is not None:
                        calc_price = _locked_price
                    else:
                        calc_price = calc_market_price(
                            effective_cost,
                            policy.pricing,
                            market_type,
                            _effective_market_data,
                            source_site=product_row.source_site or "",
                            is_point_restricted=getattr(
                                product_row, "is_point_restricted", None
                            ),
                        )

                    # 가격 이상치 방어: 원가가 정상가의 5% 미만이면 전송 차단
                    _orig_price = int(acct_product.get("original_price") or 0)
                    if _orig_price > 0 and cost > 0 and cost < _orig_price * 0.05:
                        logger.error(
                            f"[가격방어] 전송 차단 — 원가 이상치: "
                            f"원가={int(cost):,}, 정상가={_orig_price:,}, "
                            f"계산가={calc_price:,}"
                        )
                        res["error"] = (
                            f"원가 이상치 감지 "
                            f"(원가 {int(cost):,}원 < 정상가 {_orig_price:,}원의 5%)"
                        )
                        return res

                    acct_product["sale_price"] = calc_price
                    logger.info(
                        f"[전송] 정책 가격 계산: 원가={cost} → 판매가={calc_price}"
                    )
                    logger.info(f"[메모리] 가격계산 후: {_mem_mb()}MB")

                # 스킵 판단
                cur_price = int(acct_product.get("sale_price") or 0)
                cur_cost_int = int(acct_product.get("cost") or 0)
                # 가격 이상치 방어(상한): 판매가/원가가 1억 이상이면 오염으로 보고 전송 차단.
                # 정책 유무와 무관하게 최종 전송값 기준으로 검사하는 최후 게이트(#625 보완,
                # 2026-07-11 조 단위 가격 실전송 사고 재발 방지).
                if exceeds_price_cap(cur_price, cur_cost_int):
                    logger.error(
                        f"[가격방어] 전송 차단 — 가격 상한 초과: "
                        f"판매가={cur_price:,}, 원가={cur_cost_int:,}"
                    )
                    res["error"] = (
                        f"가격 이상치 감지 — 판매가 {cur_price:,}원 / "
                        f"원가 {cur_cost_int:,}원 (1억 이상, 원가 오염 의심)"
                    )
                    return res
                # last_sent_data 가 dict 아닌 오염값(과거 jsonb 병합 버그로 배열/JSON null
                # 저장된 경우)이면 빈 dict 취급 — .get() 크래시 방지
                _lsd_raw = product_row.last_sent_data
                last_sent = (
                    _lsd_raw.get(account_id) if isinstance(_lsd_raw, dict) else None
                )
                if last_sent:
                    last_price = (int(last_sent.get("sale_price") or 0) // 100) * 100
                    last_cost_sent = int(last_sent.get("cost") or 0)
                    last_opts = last_sent.get("options", [])
                    cur_opts = [
                        {
                            "name": o.get("name", ""),
                            "price": o.get("price"),
                            "stock": o.get("stock"),
                        }
                        for o in (acct_product.get("options") or [])
                    ]
                    opts_changed = last_opts != cur_opts
                else:
                    last_price = 0
                    last_cost_sent = 0
                    opts_changed = False

                # 기존 상품번호 확인 — skip_unchanged 판단 전에 먼저 수행
                # (미등록 상품은 last_sent_data가 있어도 스킵하면 안 됨)
                _enos_raw = product_row.market_product_nos
                existing_nos = _enos_raw if isinstance(_enos_raw, dict) else {}
                if market_type == "smartstore":
                    existing_product_no = existing_nos.get(f"{account_id}_origin", "")
                    if not existing_product_no:
                        raw_existing = existing_nos.get(account_id, "")
                        if isinstance(raw_existing, dict):
                            existing_product_no = (
                                raw_existing.get("originProductNo")
                                or raw_existing.get("smartstoreChannelProductNo")
                                or raw_existing.get("groupProductNo")
                                or ""
                            )
                        else:
                            existing_product_no = raw_existing
                elif market_type in ("gmarket", "auction"):
                    # 수정/판매상태 API는 마스터 goodsNo 필요 — _master 우선,
                    # 없으면(레거시) siteGoodsNo. plugin이 siteGoodsNo→master 변환 백업.
                    existing_product_no = existing_nos.get(
                        f"{account_id}_master", ""
                    ) or existing_nos.get(account_id, "")
                else:
                    existing_product_no = existing_nos.get(account_id, "")
                if existing_product_no:
                    res["is_update"] = True
                    logger.info(
                        f"[전송] 기존 상품번호 발견 → 수정 모드: {market_type} #{existing_product_no}"
                    )
                else:
                    # [가드] 전량품절 신규등록 보류 — 재고변동 자동전송이 품절 이벤트를
                    # 미등록 상품의 신규등록으로 둔갑시켜 재고 0짜리 상품이 마켓에
                    # 깔리던 문제(2026-08-13 쿠팡 에잇세컨즈 실측). 갱신(existing_no
                    # 있음)은 통과 — 기존 등록의 품절 전파는 오버셀 방지에 필수.
                    # 옵션 0건은 별도 가드(#690, 옵션 미갱신 보류)가 담당하므로
                    # 여기서는 옵션이 있는데 가용재고가 0인 경우만 막는다.
                    # 입고 전환도 재고변동 이벤트로 재전송되므로 영구 누락은 없다.
                    _guard_opts = product_dict.get("options") or []
                    if _guard_opts and available_stock(_guard_opts) <= 0:
                        res["status"] = "skipped"
                        res["error"] = "신규등록 보류: 전 옵션 품절(가용재고 0)"
                        logger.info(
                            f"[전송] {market_type} 신규등록 보류 — 전 옵션 품절: "
                            f"{(product_row.name or '')[:30]}"
                        )
                        return res

                # 마켓에 실제 등록된 상품번호가 있는 경우에만 skip_unchanged 적용
                # existing_product_no 없으면 미등록 상품 → 반드시 신규 등록 시도
                if skip_unchanged and has_update and last_sent and existing_product_no:
                    if (
                        last_price == cur_price
                        and last_cost_sent == cur_cost_int
                        and not opts_changed
                    ):
                        res["status"] = "skipped"
                        res["error"] = "이미 등록됨, 변동 없음"
                        logger.info(
                            f"[전송] {market_type} 스킵 (이미 등록됨, 변동 없음)"
                        )
                        return res

                # 마켓 API 호출 (계정별 차선 — 300초 대기, 부분양보 우선순위 적용)
                # httpx 타임아웃과 차등화하여 한 건이 느려도 동반 타임아웃 폭주 방지
                # 신규등록(사용자가 대기하는 대량전송)=high, 수정(오토튠 백그라운드 갱신)=low.
                # 대량전송 중 오토튠 update 가 차선을 양보해 배치가 빠르게 완주(부분양보).
                _lane_priority = "low" if res.get("is_update") else "high"
                try:
                    account_lane = await _acquire_account_lane(
                        account_id,
                        _lane_priority,
                        timeout=300,
                        market_type=market_type,
                    )
                except asyncio.TimeoutError:
                    res["error"] = f"계정 사용 중 (300초 타임아웃, {market_type})"
                    logger.warning(f"[전송] 계정 {account_id} 세마포어 300초 타임아웃")
                    return res
                try:
                    # 취소 체크 — 세마포어 대기 중 취소됐을 수 있음
                    if is_cancel_requested():
                        res["error"] = "전송 취소됨"
                        res["status"] = "cancelled"
                        logger.info(
                            f"[전송] 취소 감지 → {market_type} 전송 스킵 (계정 {account_id})"
                        )
                        return res
                    # 등록상품명 계정별 중복 등록 차단
                    _mkt_names = product_dict.get("market_names") or {}
                    _reg_name = _mkt_names.get(account.market_name)
                    if _reg_name:
                        _dup = await product_repo.find_by_market_name_and_account(
                            tenant_id=product_row.tenant_id,
                            market_key=account.market_name,
                            product_name=_reg_name,
                            account_id=account_id,
                            exclude_product_id=product_row.id,
                        )
                        if _dup:
                            res["error"] = (
                                f"등록상품명 중복 차단: '{_reg_name}' 이(가) "
                                f"이미 상품 ID={_dup.id}({_dup.name[:20]})에 등록됨"
                            )
                            logger.warning(
                                f"[중복등록 차단] 등록상품명={_reg_name!r} "
                                f"계정={account.account_label}({account_id}) "
                                f"기등록 상품 ID={_dup.id}"
                            )
                            return res

                    # 모든 DB 읽기 완료 — HTTP 전송 전 트랜잭션 종료 (idle in transaction 방지)
                    # commit 실패 시 rollback으로 SessionTransaction PREPARED 고착 차단(이슈#276)
                    try:
                        await self.session.commit()
                    except Exception:
                        try:
                            await self.session.rollback()
                        except Exception:
                            pass
                    # 저재고 오버셀 방지 캡 (#703) — 전송값만 0으로, DB 원본 재고는 보존.
                    # 리셀 플랫폼(크림/포이즌)에만 적용 — _LOW_STOCK_SEND_CAP_MARKETS 참고.
                    # 전 옵션 품절→마켓삭제 판정(위쪽)보다 반드시 뒤에 위치 — 캡이
                    # 삭제 오발동을 유발하지 않도록. options는 새 리스트로 교체(깊은 복사) —
                    # 얕은 복사(dict(product_dict))로 원본 product_dict/DB 오염 방지.
                    if market_type in _LOW_STOCK_SEND_CAP_MARKETS and acct_product.get(
                        "options"
                    ):
                        _capped_opts = []
                        for _opt in acct_product["options"]:
                            _opt_copy = dict(_opt) if isinstance(_opt, dict) else _opt
                            if isinstance(_opt_copy, dict):
                                try:
                                    if (
                                        int(_opt_copy.get("stock") or 0)
                                        <= _LOW_STOCK_SEND_CAP_TH
                                    ):
                                        _opt_copy["stock"] = 0
                                except (TypeError, ValueError):
                                    pass
                            _capped_opts.append(_opt_copy)
                        acct_product["options"] = _capped_opts
                        # [신규등록 보류] 캡 결과 전 옵션이 0이면 마켓엔 '품절 상품'이
                        # 깔린다 — 팔 수 없는 상품이 심사 슬롯과 목록만 차지한다.
                        # (2026-08-14 에잇세컨즈: 재고 1~2개뿐인 상품 913건이 캡으로
                        # 전량 0 → 쿠팡에 품절 등록) 신규등록 가드(위쪽)는 캡 '이전'
                        # 값을 보므로 통과해버린다 — 캡 직후에 다시 판정한다.
                        # 갱신은 그대로 전송 — 기존 등록의 품절 전파는 오버셀 방지에 필수.
                        if (
                            not res.get("is_update")
                            and available_stock(_capped_opts) <= 0
                            and available_stock(product_dict.get("options")) > 0
                        ):
                            res["status"] = "skipped"
                            res["error"] = (
                                "신규등록 보류: 저재고 캡(재고 "
                                f"{_LOW_STOCK_SEND_CAP_TH}개 이하)으로 전송재고 0 — "
                                "재고 회복 후 자동 등록"
                            )
                            logger.info(
                                f"[전송] {market_type} 신규등록 보류 — 저재고 캡: "
                                f"{(product_row.name or '')[:30]}"
                            )
                            return res

                    logger.info(f"[메모리] 마켓전송 전: {_mem_mb()}MB")
                    start_time = time.time()
                    result = await dispatch_to_market(
                        self.session,
                        market_type,
                        acct_product,
                        category_id,
                        account=account,
                        existing_product_no=existing_product_no,
                    )
                    elapsed = time.time() - start_time
                    logger.info(
                        f"[마켓전송완료] {market_type} 소요시간: {elapsed:.1f}초 (상품: {product_row.name[:40]})"
                    )
                finally:
                    _release_account_lane(account_lane)

                # 404 → 상품번호 초기화
                if result.get("_clear_product_no"):
                    res["clear_nos"] = [
                        account_id,
                        f"{account_id}_origin",
                        f"{account_id}_master",
                        f"{account_id}_site",
                    ]
                    logger.info(
                        f"[전송] 404 상품번호 초기화: {market_type} (계정: {account_id})"
                    )

                if result.get("success"):
                    res["status"] = "success"
                    # 중복등록 차단 시 pre-check에서 추출한 원상품번호 직접 사용
                    if result.get("_already_registered") and result.get("_origin_no"):
                        _pre_origin = str(result["_origin_no"])
                        res["product_nos"] = {
                            account_id: _pre_origin,
                            f"{account_id}_origin": _pre_origin,
                        }
                        logger.info(
                            f"[전송] 스마트스토어 중복등록 차단 — 기존 originProductNo={_pre_origin} 연결"
                        )
                        res["sent_snapshot"] = {
                            "sale_price": math.ceil(
                                int(acct_product.get("sale_price") or 0) / 300
                            )
                            * 300,
                            "cost": int(acct_product.get("cost") or 0),
                            "options": [
                                {
                                    "name": o.get("name", ""),
                                    "price": o.get("price"),
                                    "stock": o.get("stock"),
                                }
                                for o in (acct_product.get("options") or [])
                            ],
                            "sent_at": datetime.now(UTC).isoformat(),
                        }
                        return res
                    # 상품번호 추출
                    # product_no: 플러그인이 "product_no" 키로 반환 (롯데ON 등)
                    # spdNo: 이전 방식 또는 일부 마켓 직접 반환 — 둘 다 확인
                    product_no = self._extract_market_product_no(result)
                    # 스마트스토어 origin/channel 분리를 위해 api_data 는 항상 추출
                    # (기존: product_no 가 비어있을 때만 → smartstore 도 origin 만 저장하던 버그)
                    api_data: dict[str, Any] = {}
                    result_data = result.get("data", {})
                    if isinstance(result_data, dict):
                        api_data = result_data.get("data", result_data)
                        if isinstance(api_data, list) and api_data:
                            api_data = (
                                api_data[0] if isinstance(api_data[0], dict) else {}
                            )
                        if not isinstance(api_data, dict):
                            api_data = {}
                        if not product_no and api_data:
                            product_no = self._extract_market_product_no(api_data)
                    # "0"/"0.0" 무효 상품번호 차단(이슈#278) — ESM 옥션/G마켓 중복등록 silent fail 응답
                    # 검증 통과시 기존 유효 market_product_no가 "0"으로 덮어써져 PUT /goods/0 404 무한
                    if product_no and str(product_no).strip() not in ("0", "0.0"):
                        nos: dict[str, str] = {account_id: str(product_no)}
                        if market_type == "smartstore" and isinstance(api_data, dict):
                            origin_no = api_data.get("originProductNo") or ""
                            channel_no = (
                                api_data.get("smartstoreChannelProductNo") or ""
                            )
                            # _origin 키가 없으면 삭제 API 실패 — 항상 저장 (있으면 덮어씀)
                            if origin_no:
                                nos[f"{account_id}_origin"] = str(origin_no)
                                nos[account_id] = str(channel_no or product_no)
                            elif channel_no:
                                # origin 없이 channel 만 온 경우 channel 로 fallback
                                nos[account_id] = str(channel_no)
                            logger.info(
                                f"[전송] 스마트스토어 상품번호 — channel={channel_no or product_no}, origin={origin_no}"
                            )
                        # 쿠팡 — vp/products URL 은 {productId}?vendorItemId={vendorItemId} 형식.
                        # plugin 이 register 후 GET 으로 추출한 값을 별도 sub-key 로 저장.
                        if market_type == "coupang":
                            _cpid = str(result.get("coupang_product_id", "") or "")
                            _cvid = str(result.get("coupang_vendor_item_id", "") or "")
                            if _cpid:
                                nos[f"{account_id}_pid"] = _cpid
                            if _cvid:
                                nos[f"{account_id}_vid"] = _cvid
                        # GS샵 — bare 키(account_id)에는 supPrdCd(수정·삭제 API용)가 들어간다.
                        # 판매페이지 URL(prd.gs?prdid=)은 GS 부여 prdCd 가 필요하므로 _pid 로 분리 저장.
                        if market_type == "gsshop":
                            _gs_prd_cd = str(result.get("gsshop_prd_cd", "") or "")
                            if _gs_prd_cd and _gs_prd_cd.strip() not in ("0", "0.0"):
                                nos[f"{account_id}_pid"] = _gs_prd_cd
                        if market_type in ("gmarket", "auction"):
                            # result.data.data 에서 siteGoodsNo(구매페이지 URL용) / sellerProductId(수정·삭제 API용) 분리 저장
                            _esm_d: dict = {}
                            _rd = result.get("data", {})
                            if isinstance(_rd, dict):
                                _esm_d = _rd.get("data", _rd)
                            if not isinstance(_esm_d, dict):
                                _esm_d = {}
                            _site_goods_no = str(_esm_d.get("siteGoodsNo", "") or "")
                            _seller_pid = str(_esm_d.get("sellerProductId", "") or "")
                            # 마스터 goodsNo — 수정/삭제/판매상태 API 가 마스터번호 요구.
                            # 저장 안 하면 siteGoodsNo로 호출돼 404 (오토튠 가격/재고 실패).
                            _master_no = str(_esm_d.get("goodsNo", "") or "")
                            # "0"/"0.0" 무효값 차단(이슈#278) — 기존 유효 ID 덮어쓰기 방지
                            _sgn_valid = bool(
                                _site_goods_no
                                and _site_goods_no.strip() not in ("0", "0.0")
                            )
                            if _sgn_valid:
                                nos[account_id] = _site_goods_no
                                nos[f"{account_id}_site"] = _site_goods_no
                            else:
                                # siteGoodsNo 미포함(수정 응답) — bare 키를 nos에서 제거해
                                # merged_nos.update(nos)가 기존 bare(siteGoodsNo)를 보존하게 함
                                nos.pop(account_id, None)
                            if _seller_pid and _seller_pid.strip() not in (
                                "0",
                                "0.0",
                            ):
                                nos[f"{account_id}_origin"] = _seller_pid
                            if _master_no and _master_no.strip() not in ("0", "0.0"):
                                nos[f"{account_id}_master"] = _master_no
                            if _site_goods_no or _seller_pid or _master_no:
                                logger.info(
                                    f"[전송] {market_type} 상품번호 — siteGoodsNo={_site_goods_no}, "
                                    f"sellerProductId={_seller_pid}, master={_master_no}"
                                )
                        res["product_nos"] = nos
                        logger.info(f"[전송] {market_type} 상품번호: {product_no}")

                    # 스냅샷 준비 (스마트스토어는 300원 올림 반영)
                    _snap_price = int(acct_product.get("sale_price") or 0)
                    if market_type == "smartstore":
                        _snap_price = math.ceil(_snap_price / 300) * 300
                    res["sent_snapshot"] = {
                        "sale_price": _snap_price,
                        "cost": int(acct_product.get("cost") or 0),
                        "options": [
                            {
                                "name": o.get("name", ""),
                                "price": o.get("price"),
                                "stock": o.get("stock"),
                            }
                            for o in (acct_product.get("options") or [])
                        ],
                        "sent_at": datetime.now(UTC).isoformat(),
                    }

                    # _already_exists: SSG 동일상품 존재로 itemId 미확인 — "__exists__" 마커 저장
                    if result.get("_already_exists"):
                        res["product_nos"] = {account_id: "__exists__"}
                        logger.warning(
                            f"[전송] {market_type} 이미 등록됨(itemId 미확인) — __exists__ 마커 저장: "
                            f"상품={product_id}, 계정={account_id}"
                        )

                    # 등록/수정 성공 직후 즉시 DB 저장 (transmitting stuck + greenlet 에러 방지):
                    # 프로세스가 최종 업데이트 전에 종료돼도 아래 3가지 보존:
                    # 1) registered_accounts + product_no (신규 등록 시)
                    # 2) last_sent_data.sent_at (성공 기록 → 다음 사이클 재시도 방지)
                    # 3) last_sent_data.failed_at 제거 (preemptive 마킹 즉시 해소)
                    _imm_nos = res.get("product_nos") or {}
                    _imm_snap = res.get("sent_snapshot")
                    # 즉시저장 게이트(#542): 별도 세션이 메인 전송 세션과 같은 상품 행을
                    # 두고 락 경합 → self-deadlock(상품당 ~90s). 대량 쿠팡 전송에서 극심.
                    # DISABLE_IMMEDIATE_SAVE=1 이면 스킵 — 최종 writeback 이
                    # registered_accounts/product_no 를 기록하므로 데이터 손실 없음.
                    import os as _imm_os  # noqa: F811

                    _imm_disabled = _imm_os.getenv("DISABLE_IMMEDIATE_SAVE", "") == "1"
                    if (_imm_nos or _imm_snap) and not _imm_disabled:
                        # 즉시저장은 별도 세션에서 — self.session commit 시
                        # 세션 내 모든 ORM 객체(account 등)가 expired되어
                        # 이후 account.market_type 접근 시 greenlet_spawn 에러 발생.
                        try:
                            import json as _imm_j  # noqa: F811
                            from backend.db.orm import (
                                get_write_session as _get_imm_session,
                            )
                            from backend.domain.samba.collector.repository import (
                                SambaCollectedProductRepository as _ImmCPRepo,
                            )
                            from sqlalchemy import text as _imm_sa_text  # noqa: F811

                            async with _get_imm_session() as _imm_s:
                                if _imm_nos:
                                    _pr_now = await _ImmCPRepo(_imm_s).get_async(
                                        product_id
                                    )
                                    if _pr_now:
                                        _imm_reg = [
                                            a
                                            for a in set(
                                                (_pr_now.registered_accounts or [])
                                                + ([account_id] if account_id else [])
                                            )
                                            if a is not None
                                        ]
                                        _imm_mpn = dict(
                                            as_market_nos(_pr_now.market_product_nos)
                                        )
                                        _imm_mpn.update(_imm_nos)
                                        from sqlalchemy import update as _imm_upd

                                        from backend.domain.samba.collector.model import (
                                            SambaCollectedProduct as _ImmCP,
                                        )

                                        await _imm_s.execute(
                                            _imm_upd(_ImmCP)
                                            .where(_ImmCP.id == product_id)
                                            .values(
                                                registered_accounts=_imm_reg,
                                                market_product_nos=_imm_mpn,
                                                status="registered",
                                            )
                                        )
                                # _imm_nos 먼저 커밋 — _imm_snap 실패해도 등록번호/registered_accounts 보존
                                await _imm_s.commit()
                                if _imm_snap:
                                    await _imm_s.execute(
                                        _imm_sa_text(
                                            "UPDATE samba_collected_product"
                                            " SET last_sent_data = ("
                                            "  CASE WHEN jsonb_typeof(CAST(last_sent_data AS jsonb)) = 'object'"
                                            "       THEN CAST(last_sent_data AS jsonb) ELSE '{}'::jsonb END"
                                            "  || CAST(:updates AS jsonb))::json,"
                                            " updated_at = NOW()"
                                            " WHERE id = :pid"
                                        ),
                                        {
                                            "updates": _imm_j.dumps(
                                                {account_id: _imm_snap}
                                            ),
                                            "pid": product_id,
                                        },
                                    )
                                    await _imm_s.commit()  # _imm_snap 별도 커밋
                        except Exception as _ie:
                            logger.warning(
                                f"[전송] {market_type} 즉시저장 실패 (무시): {_ie}"
                            )

                    action = "수정" if existing_product_no else "등록"
                    _plugin_msg = result.get("message", "")
                    res["plugin_message"] = _plugin_msg
                    logger.info(
                        f"[전송] {market_type} {action} 성공 - 상품: {product_id}, 계정: {account_id}"
                        + (f" - {_plugin_msg}" if _plugin_msg else "")
                    )
                else:
                    # _skip_retry: 플레이오토 미등록 상품코드 — 재시도/신규등록 차단
                    if result.get("_skip_retry"):
                        res["status"] = "skipped"
                        res["_clear_failed_at"] = True
                    _msg = result.get("message", "알 수 없는 오류")
                    res["error"] = str(_msg) if not isinstance(_msg, str) else _msg
                    logger.warning(f"[전송] {market_type} 실패 - {_msg}")

            except Exception as exc:
                _err = str(exc)
                # asyncio 내부 객체 누출 방지
                if "<asyncio" in _err or "Semaphore" in _err:
                    _err = f"전송 타임아웃 또는 동시성 오류 ({market_type})"
                    logger.error(f"[전송] 계정 {account_id} 세마포어 누출: {exc}")
                else:
                    logger.error(f"[전송] 계정 {account_id} 예외: {exc}", exc_info=True)
                res["error"] = _err
                try:
                    await self.session.rollback()
                except Exception:
                    pass
            return res

        # product_row 필드 스냅샷 — _dispatch_one 내 connection refresh rollback 후에도
        # ORM lazy load 없이 안전하게 참조할 수 있도록 순수 Python 타입으로 추출
        _mpn_raw = product_row.market_product_nos
        _row_mpn = dict(_mpn_raw) if isinstance(_mpn_raw, dict) else {}
        _row_reg = list(product_row.registered_accounts or [])
        # last_sent_data 가 dict 아닌 오염값(과거 jsonb 병합 버그로 배열/JSON null
        # 저장)이면 빈 dict 취급 — dict() 크래시로 전송 전체가 막히는 것 방지
        _lsd_src = product_row.last_sent_data
        _row_lsd = dict(_lsd_src) if isinstance(_lsd_src, dict) else {}
        # greenlet 방지: product_row 도 세션에서 분리(expunge).
        # _dispatch_one 시작부 connection refresh(SELECT 1 + rollback)가 세션 내 모든
        # ORM 을 expire 시키는데, product_row.name/source_site/tenant_id/market_product_nos 등을
        # 그 이후(1586/1721/1784/1805/1910 등) 직접 접근하면 expired reload → MissingGreenlet.
        # get_async 는 defer 없이 전 컬럼 로드하므로 detached 상태로도 접근 안전.
        try:
            self.session.expunge(product_row)
        except Exception as _exp_pr:
            logger.debug(f"[전송] product_row expunge 실패 (계속 진행): {_exp_pr}")

        # 계정별 순차 전송 — 동일 세션 병렬 사용 시 asyncpg 연결 오염 방지
        # 한 계정 끝나는 즉시 on_account_done 콜백을 발사해 호출자가 진행 로그를
        # 실시간으로 흘릴 수 있도록 한다(오토튠 워룸 로그 패널이 활용).
        account_results = []
        for _aid in target_account_ids:
            _ar = await _dispatch_one(_aid)
            account_results.append(_ar)
            if on_account_done is not None:
                try:
                    await on_account_done(_aid, _ar)
                except Exception as _cb_exc:
                    logger.warning(
                        f"[전송] on_account_done 콜백 실패 (무시): {_cb_exc}"
                    )

        # 결과 병합 + DB 일괄 업데이트
        merged_nos = dict(_row_mpn)
        # A칸(registered_accounts) 동기화: 정상 전송 성공 경로에서도 함께 갱신
        # — 기존엔 스마트스토어 group 등록·삭제·재시도 경로만 A칸을 갱신해서
        #   11번가/쿠팡/롯데홈 등 일반 마켓은 B칸만 채워지고 A칸은 backfill 루프가
        #   채워줄 때까지(때로는 1시간+) 비어있어, 테트리스 sync가 같은 상품을
        #   '미등록'으로 오판해 헛걸음 잡을 반복 생성했음 → 'skipped(이미 등록됨, 변동 없음)' 로그 발생.
        merged_reg = list(_row_reg)
        # 이번 그룹의 변경분(delta)만 별도 추적 — market_product_nos/registered_accounts도
        # DB write 시점엔 in-memory snapshot(_row_mpn/_row_reg) 기준 full-replace가 아니라
        # 이 delta를 atomic JSONB merge/remove로 적용한다 (이슈 #588 — 동시 전송 그룹 간
        # race condition으로 서로의 market_product_nos/registered_accounts 덮어써 소실되던 버그).
        nos_add: dict[str, str] = {}
        nos_clear: set[str] = set()
        reg_add: set[str] = set()
        reg_remove: set[str] = set()
        # lsd_updates: 이번 그룹에서 처리한 계정들의 last_sent_data 변경분만 수집
        # (전체 snapshot 덮어쓰기 → 동시 실행 그룹 간 race condition 발생하므로 계정별 atomic merge로 변경)
        _prev_lsd = _row_lsd
        lsd_updates: dict[str, Any] = {}
        for ar in account_results:
            if isinstance(ar, Exception):
                continue
            aid = ar["account_id"]
            transmit_result[aid] = ar["status"]
            if ar["error"]:
                transmit_error[aid] = ar["error"]
            if ar.get("plugin_message"):
                plugin_messages[aid] = ar["plugin_message"]
            if ar["is_update"]:
                update_mode_accounts.add(aid)
            # 404 초기화 — B칸과 A칸에서 동시 제거
            for key in ar.get("clear_nos", []):
                merged_nos.pop(key, None)
                nos_clear.add(key)
                nos_add.pop(key, None)
                if key == aid and aid in merged_reg:
                    merged_reg.remove(aid)
                    reg_remove.add(aid)
                    reg_add.discard(aid)
            # 상품번호 병합 — B칸에 account_id 키가 채워지면 A칸도 동기화
            _new_nos = ar.get("product_nos", {}) or {}
            merged_nos.update(_new_nos)
            for _nk, _nv in _new_nos.items():
                nos_add[_nk] = _nv
                nos_clear.discard(_nk)
            # 수정 모드(is_update) 성공도 A칸 backfill 대상에 포함:
            # 마켓이 수정 응답에 상품번호를 안 돌려주면(예: lottehome) product_nos가
            # 비어 _new_nos.get(aid)=None → A칸 미반영 → 테트리스가 '미등록' 오판으로
            # 매 사이클 같은 상품 헛전송(churn). is_update=True는 기존 상품번호(B칸) 존재
            # = 실제 마켓 등록됨을 의미하므로 번호 미반환이어도 A칸에 계정 추가해야 함.
            # 404 초기화 경로는 status!=success 라 여기 진입 안 함(충돌 없음).
            if (
                aid
                and ar.get("status") == "success"
                and (
                    _new_nos.get(aid)
                    or ar.get("_already_exists")
                    or ar.get("is_update")
                )
                and aid not in merged_reg
            ):
                merged_reg.append(aid)
                reg_add.add(aid)
                reg_remove.discard(aid)
            # last_sent_data 변경분 수집 (atomic merge용)
            if ar.get("sent_snapshot"):
                # 전송 성공 — sent_snapshot(sent_at 포함, failed_at 없음)으로 교체
                lsd_updates[aid] = ar["sent_snapshot"]
            elif ar.get("status") == "failed":
                # 계정 등록 한도 초과(마켓 슬롯 만석)는 상품 잘못이 아님 — fc 증가/동결 금지.
                # 잡 워커가 계정 차단으로 헛 재시도는 막고, 슬롯이 비면 다음 사이클에 정상 등록된다.
                if is_account_full_error(ar.get("error") or ""):
                    pass  # last_sent_data 미변경 — failed_at/failure_count 마킹 안 함
                else:
                    # 전송 실패 — 기존 last_sent 보존 + failed_at 마킹
                    _existing = dict(_prev_lsd.get(aid, {}) or {})
                    _existing["failed_at"] = datetime.now(UTC).isoformat()
                    # 안전망: 동일 (cp, account) 전송 실패 누적 — 3회 도달 시 테트리스 sync에서 제외
                    _existing["failure_count"] = (
                        int(_existing.get("failure_count") or 0) + 1
                    )
                    lsd_updates[aid] = _existing
            elif ar.get("_clear_failed_at") and aid in _prev_lsd:
                # _skip_retry 케이스 (플레이오토 미등록 상품코드): failed_at 제거
                _existing = dict(_prev_lsd[aid] or {})
                _existing.pop("failed_at", None)
                lsd_updates[aid] = _existing

        # DB 업데이트 ①: market_product_nos + registered_accounts — 계정별 atomic
        # add/remove로 적용 (이슈 #588 — in-memory snapshot 기준 full-replace가
        # 동시 전송 그룹 간 race condition으로 서로의 갱신분을 덮어써 소실시키던 버그 수정).
        # 변경분이 전혀 없으면(nos_add/nos_clear/reg_add/reg_remove 전부 빈 상태) 스킵.
        if nos_add or nos_clear or reg_add or reg_remove:
            try:
                import json as _mpn_j  # noqa: F811
                from sqlalchemy import text as _mpn_sa_text  # noqa: F811

                await self.session.execute(
                    _mpn_sa_text(
                        # ★registered_accounts 가 JSON null 인 행(신규 수집분 다수,
                        # 2026-08-06 실측 40,801건)에서 COALESCE 는 SQL NULL 만 잡고
                        # JSON null 은 통과시켜 `null - text[]` →
                        # InvalidParameterValueError: cannot delete from scalar 로
                        # UPDATE 전체가 롤백됐다. 그 결과 마켓엔 등록됐는데 상품번호·
                        # 등록기록이 저장되지 않아 링크분실(중복등록/주문 미이행)이 생겼다.
                        # market_product_nos 처럼 jsonb_typeof 로 타입을 확인해 방어한다.
                        "UPDATE samba_collected_product SET"
                        "  market_product_nos = ("
                        "    (CASE WHEN jsonb_typeof(CAST(market_product_nos AS jsonb)) = 'object'"
                        "          THEN CAST(market_product_nos AS jsonb) ELSE '{}'::jsonb END)"
                        "    - CAST(:nos_clear AS text[])"
                        "  ) || CAST(:nos_add AS jsonb),"
                        "  registered_accounts = COALESCE(("
                        "    SELECT jsonb_agg(DISTINCT val) FROM jsonb_array_elements_text("
                        "      ((CASE WHEN jsonb_typeof(CAST(registered_accounts AS jsonb)) = 'array'"
                        "             THEN CAST(registered_accounts AS jsonb) ELSE '[]'::jsonb END)"
                        "        - CAST(:reg_remove AS text[]))"
                        "      || CAST(:reg_add AS jsonb)"
                        "    ) AS val"
                        "  ), '[]'::jsonb),"
                        "  updated_at = NOW()"
                        " WHERE id = CAST(:pid AS text)"
                    ),
                    {
                        "nos_clear": list(nos_clear),
                        "nos_add": _mpn_j.dumps(nos_add),
                        "reg_remove": list(reg_remove),
                        "reg_add": _mpn_j.dumps(list(reg_add)),
                        "pid": product_id,
                    },
                )
                await self.session.commit()
            except Exception as _db_e:
                logger.warning(
                    f"[전송] market_product_nos/registered_accounts atomic 갱신 실패: {_db_e}"
                )
                try:
                    await self.session.rollback()
                except Exception:
                    pass

        # DB 업데이트 ②: last_sent_data — 계정별 atomic JSONB merge (race condition 방지)
        # json 컬럼이므로 CAST AS jsonb 후 :: 연산자 적용, 결과를 ::json으로 저장
        if lsd_updates:
            try:
                import json as _lsd_j  # noqa: F811
                from sqlalchemy import text as _lsd_sa_text  # noqa: F811

                await self.session.execute(
                    _lsd_sa_text(
                        "UPDATE samba_collected_product"
                        " SET last_sent_data = ("
                        "  CASE WHEN jsonb_typeof(CAST(last_sent_data AS jsonb)) = 'object'"
                        "       THEN CAST(last_sent_data AS jsonb) ELSE '{}'::jsonb END"
                        "  || CAST(:updates AS jsonb))::json,"
                        " updated_at = NOW()"
                        " WHERE id = :pid"
                    ),
                    {"updates": _lsd_j.dumps(lsd_updates), "pid": product_id},
                )
                await self.session.commit()
            except Exception as _lsd_e:
                logger.warning(f"[전송] last_sent_data atomic merge 실패: {_lsd_e}")
                try:
                    await self.session.rollback()
                except Exception:
                    pass

        # 마켓삭제 성공 + DB 업데이트 실패 계정 → 새 세션으로 registered_accounts 재시도
        _failed_db_accs = [
            ar["account_id"]
            for ar in account_results
            if isinstance(ar, dict) and ar.get("db_update_failed")
        ]
        if _failed_db_accs:
            from backend.db.orm import get_write_session

            try:
                async with get_write_session() as _retry_s:
                    _retry_prod = await SambaCollectedProductRepository(
                        _retry_s
                    ).get_async(product_id)
                    if _retry_prod:
                        new_reg = [
                            a
                            for a in (_retry_prod.registered_accounts or [])
                            if a not in _failed_db_accs
                        ]
                        _retry_prod.registered_accounts = new_reg if new_reg else None
                        # last_sent_data도 함께 정리 (issue #206 유령 등록상품 방지)
                        _new_sent = dict(_retry_prod.last_sent_data or {})
                        for _fa in _failed_db_accs:
                            _new_sent.pop(_fa, None)
                        _retry_prod.last_sent_data = _new_sent or None
                        await _retry_s.commit()
                        logger.info(
                            f"[전송] DB 재시도 성공 — registered_accounts 갱신: {_failed_db_accs}"
                        )
            except Exception as _retry_e:
                logger.error(
                    f"[전송] DB 재시도도 실패 — 상품관리 배지 불일치 가능: {_retry_e}"
                )

        # 6. 최종 상태 결정
        values = list(transmit_result.values())
        non_skip = [v for v in values if v != "skipped"]
        all_skipped = len(values) > 0 and len(non_skip) == 0
        all_success = len(non_skip) > 0 and all(
            v in ("success", "completed") for v in non_skip
        )
        all_failed = len(non_skip) > 0 and all(v == "failed" for v in non_skip)

        if all_skipped:
            final_status = "skipped"
        elif all_success:
            final_status = "completed"
        elif all_failed:
            final_status = "failed"
        else:
            final_status = "partial"

        final_update: dict[str, Any] = {
            "status": final_status,
            "transmit_result": transmit_result,
            "transmit_error": transmit_error if transmit_error else None,
            "completed_at": datetime.now(UTC),
        }
        _update_result: dict[str, Any] = {}
        if refresh_status:
            _update_result["refresh"] = refresh_status
        if plugin_messages:
            _update_result["plugin_messages"] = plugin_messages
        if _update_result:
            final_update["update_result"] = _update_result
        updated = await self.repo.update_async(_shipment_id, **final_update)

        # 6. 상품 상태 업데이트 (등록된 계정 목록)
        # 성공한 계정은 추가, 실패한 계정은 제거
        # 단, PATCH(수정) 모드에서 실패한 계정은 등록정보 보존 (404 케이스는 이미 위에서 처리됨)
        success_accounts = [
            aid for aid, status in transmit_result.items() if status == "success"
        ]
        # 신규등록(POST) 실패만 제거 대상 — 수정(PATCH) 실패/스킵은 기존 등록정보 유지
        removable_failed = [
            aid
            for aid, status in transmit_result.items()
            if status not in ("success", "skipped") and aid not in update_mode_accounts
        ]
        # DB에서 최신 상태 다시 읽기 (전송 중 market_product_nos가 업데이트되었을 수 있음)
        refreshed = await product_repo.get_async(product_id)
        existing = (refreshed.registered_accounts if refreshed else _row_reg) or []
        existing_nos = dict(
            (refreshed.market_product_nos if refreshed else _row_mpn) or {}
        )
        # 성공 추가 + 신규등록 실패만 제거
        new_accounts = list(
            set([a for a in existing if a not in removable_failed] + success_accounts)
        )
        # 신규등록 실패한 계정의 상품번호만 제거
        new_nos = {k: v for k, v in existing_nos.items() if k not in removable_failed}
        # 최신화 실패 시에는 상품 데이터 변경하지 않음 (updated_at 유지)
        if refresh_status and (
            refresh_status.startswith("최신화실패")
            or refresh_status.startswith("최신화예외")
        ):
            logger.info("[전송] 최신화 실패 → 상품 데이터 변경 안 함")
        else:
            # ★registered_accounts/market_product_nos 는 여기서 full-replace 하지 않는다.
            # 위 "DB 업데이트 ①" 이 계정별 atomic delta 로 이미 반영했는데, in-memory
            # 스냅샷(existing/existing_nos) 기준으로 다시 통째 덮어쓰면 ① 이후 ~ 여기
            # 사이에 다른 전송 그룹이 기록한 상품번호까지 날아간다. 특히 빈 dict 를
            # None 으로 저장해 **컬럼 자체를 null 로 만드는** 경로가 치명적이었다
            # (2026-07-27 685건 링크분실 사고: 마커 null → 주문동기화 역매핑 실패로
            #  원가 0 허수주문 + 마커 없는 상품이 오토튠 스캔에서도 통째 제외).
            # 신규등록(POST) 실패 계정 정리는 아래에서 delta 로만 적용한다.
            update_data: dict[str, Any] = {
                "status": "registered" if new_accounts else "collected",
                "updated_at": datetime.now(UTC),
            }
            # 소싱처 최신화 결과도 통합 저장
            if pending_refresh_updates:
                update_data.update(pending_refresh_updates)
            await product_repo.update_async(product_id, **update_data)

            # 신규등록 실패 계정만 B칸(market_product_nos)/A칸(registered_accounts)에서
            # 제거 — 다른 계정 키는 건드리지 않는 계정별 atomic 삭제.
            if removable_failed:
                # ★별도 세션에서 실행한다. 여기서 예외가 나면 메인 세션이 오염돼
                # 이후 ORM 접근이 전부 MissingGreenlet 으로 죽는다(2026-08-01 실측:
                # 파일럿 30건 중 26건이 이 연쇄로 실패). 마커 정리는 부수작업이므로
                # 실패해도 전송 본류에 영향을 주면 안 된다.
                try:
                    from sqlalchemy import text as _rf_sa_text  # noqa: F811
                    from backend.db.orm import (  # noqa: F811
                        get_write_session as _rf_session,
                    )

                    _rf_keys: list[str] = []
                    for _rf_aid in removable_failed:
                        _rf_keys += [
                            _rf_aid,
                            f"{_rf_aid}_origin",
                            f"{_rf_aid}_master",
                            f"{_rf_aid}_site",
                        ]
                    async with _rf_session() as _rf_s:
                        await _rf_s.execute(
                            _rf_sa_text(
                                # ★jsonb 스칼라 가드는 두 컬럼 모두에 필요하다.
                                # COALESCE 는 SQL NULL 만 막고 **JSON null 스칼라는
                                # 통과**시켜 `jsonb - text[]` 가
                                # "cannot delete from scalar" 로 터진다
                                # (미등록 상품은 registered_accounts 가 JSON null).
                                "UPDATE samba_collected_product SET"
                                "  market_product_nos = ("
                                "    (CASE WHEN jsonb_typeof(market_product_nos) = 'object'"
                                "          THEN market_product_nos ELSE '{}'::jsonb END)"
                                "    - CAST(:nos_keys AS text[])"
                                "  ),"
                                "  registered_accounts = ("
                                "    (CASE WHEN jsonb_typeof(registered_accounts) = 'array'"
                                "          THEN registered_accounts ELSE '[]'::jsonb END)"
                                "    - CAST(:reg_keys AS text[])"
                                "  )"
                                " WHERE id = CAST(:pid AS text)"
                            ),
                            {
                                "nos_keys": _rf_keys,
                                "reg_keys": list(removable_failed),
                                "pid": product_id,
                            },
                        )
                        await _rf_s.commit()
                except Exception as _rf_e:
                    logger.warning(f"[전송] 신규등록 실패 계정 정리 실패: {_rf_e}")

        # 전 옵션 품절 + 마켓에 남은 등록 없음 → 수집상품 자체 DB 삭제.
        # 첫등록 전송잡에서 전옵션 품절 상품은 등록을 안 하므로(위 1595 블록에서
        # 미등록은 스킵), 매 잡마다 같은 품절 상품을 다시 시도하게 된다.
        # 마켓에 남은 등록이 하나도 없으면(new_accounts 빈 값) 수집행을 정리해
        # 반복 시도를 끊는다. lock_delete 보호 상품은 제외. 품절 최신화가
        # 재입고(sale_status=in_stock)로 뒤집은 경우는 삭제하지 않는다.
        _restocked = pending_refresh_updates.get("sale_status") == "in_stock"
        if (
            _all_sold
            and not _restocked
            and not new_accounts
            and refreshed is not None
            and not getattr(refreshed, "lock_delete", False)
        ):
            from sqlalchemy import delete as _del_sa
            from backend.db.orm import get_write_session as _get_del_session
            from backend.domain.samba.collector.model import (
                SambaCollectedProduct as _DEL_CP,
            )

            try:
                async with _get_del_session() as _del_s:
                    await _del_s.execute(
                        _del_sa(_DEL_CP).where(_DEL_CP.id == product_id)
                    )
                    await _del_s.commit()
                logger.info(
                    f"[전송] 상품 {product_id} 전 옵션 품절 + 미등록 → 수집상품 DB 삭제 완료"
                )
            except Exception as _del_e:
                logger.warning(f"[전송] 전 옵션 품절 수집상품 DB 삭제 실패: {_del_e}")

        logger.info(
            f"Shipment {_shipment_id} 완료 status={final_status} "
            f"product={product_id} 성공={sum(1 for v in values if v == 'success')}/{len(values)}"
        )
        if not updated:
            logger.warning(f"Shipment {_shipment_id} 업데이트 실패, DB 재조회")
            updated = await self.repo.get_async(_shipment_id)
        return updated or shipment

    # ==================== 상품명 조합 ====================

    def _compose_product_name(
        self,
        product: dict[str, Any],
        name_rule: Any,
        *,
        market_type: str | None = None,
        deletion_words: list[str] | None = None,
    ) -> str:
        """정책의 상품명 규칙(name_composition)에 따라 상품명을 조합.

        market_type이 지정되고 market_name_compositions에 해당 마켓 설정이 있으면 마켓별 조합 사용.

        **폴백 체인**: market_name_compositions 값이 "리스트의 리스트"이면 앞에서부터
        시도해 마켓 상품명 한도(_MARKET_NAME_MAX_BYTES) 안에 들어가는 첫 조합을 쓴다.
        전부 초과하면 마지막(가장 짧은) 조합을 쓰고 마켓 플러그인의 자름에 맡긴다.
        11번가처럼 한도가 짧은(99byte) 마켓에서 브랜드는 살리고 부가정보만 단계적으로
        떨어뜨리기 위한 것 — 무조건 자르면 뒤쪽 상품번호가 잘려 추적이 끊긴다.
        """
        # 마켓별 조합이 있으면 우선 사용
        composition = None
        if market_type and getattr(name_rule, "market_name_compositions", None):
            composition = name_rule.market_name_compositions.get(market_type)
        if not composition:
            composition = name_rule.name_composition
        composition = _normalize_composition(composition)
        if not composition:
            return product.get("name", "")

        # 폴백 체인이면 한도에 맞는 첫 조합을 고른다 (각 후보를 끝까지 조립해 실측 —
        # 치환/접두접미/중복제거가 길이를 바꾸므로 태그만 보고 판단하면 어긋난다).
        if isinstance(composition[0], (list, tuple)):
            _chain = [list(c) for c in composition if c]
            _limit = _MARKET_NAME_MAX_BYTES.get(market_type or "", 0)
            for _cand in _chain:
                _built = self._compose_product_name(
                    product,
                    _NameRuleWithComposition(name_rule, _cand),
                    market_type=market_type,
                    deletion_words=deletion_words,
                )
                if not _limit or len(_built.encode("utf-8")) <= _limit:
                    return _built
            composition = _chain[-1]

        # SEO 검색키워드: seo_keywords 배열을 공백 연결
        seo_kws = product.get("seo_keywords") or []
        # ★단어 단위 중복 제거 — SEO 키워드가 카테고리 leaf명을 그대로 쓰면
        # ("바지 > 숏 팬츠" → ["여성 숏 팬츠","바지 숏 팬츠","스포츠 숏 팬츠"])
        # 앞 2개만 이어붙여도 같은 단어가 반복돼 마켓 상품명이 오염된다
        # (2026-08-01 실측: "여성 숏 팬츠 바지 숏 - 숏 숏 - 숏 숏 …" 47건 노출).
        # 키워드 자체를 고치는 것과 별개로, 조합 단계에서 한 번 더 막는다.
        # 슬래시는 카테고리 leaf 구분자라 단어 경계로 취급해야 중복이 잡힌다
        # ("숏 패딩/숏 헤비 아우터" → 숏·패딩·숏·헤비·아우터).
        _seo_raw = " ".join(seo_kws[:2]).replace("/", " ")
        # ★2026-08-04 — 상품명·브랜드·모델명에 이미 있는 단어도 제외.
        # SEO 내부 dedup만으로는 "{검색키워드} {상품명}" 조합에서 상품명 단어가
        # 그대로 반복됐다("남성 반소매 티셔츠 + ... 남성 반팔티" 전수조사 42,948건).
        _seo_seen: set[str] = set()
        for _src in (
            product.get("name", ""),
            product.get("brand", ""),
            product.get("style_code", ""),
        ):
            for _w in re.split(r"[\s/\-_()\[\]]+", str(_src or "")):
                _w = _w.strip().lower()
                if _w:
                    _seo_seen.add(_w)
        _seo_words: list[str] = []
        for _w in _seo_raw.split():
            _key = _w.strip().lower()
            if not _key or _key in _seo_seen:
                continue
            _seo_seen.add(_key)
            _seo_words.append(_w)
        seo_text = " ".join(_seo_words)

        # ★2026-08-18 — 모델명이 상품명에 이미 들어 있으면 조합에서 생략한다.
        # 롯데온은 소싱처 상품명 끝에 품번이 붙어 오는 경우가 대부분이라
        # ({상품명} = "프로플레이어 테니스 심리스 반팔티 FS2RSH2391X_FGR"),
        # style_code 를 채운 뒤 {모델명} 을 그대로 붙이면 같은 코드가 두 번 노출된다.
        # 구분자(_ - 공백) 표기가 마켓에서 뒤바뀌므로 정규화해 비교한다.
        _model_raw = str(product.get("style_code", "") or "")

        def _norm_code(v: str) -> str:
            return re.sub(r"[\s_.\-]+", "", str(v or "")).upper()

        _model_val = _model_raw
        if _model_raw and _norm_code(_model_raw) in _norm_code(product.get("name", "")):
            _model_val = ""

        tag_map = {
            "{상품명}": product.get("name", ""),
            "{브랜드명}": product.get("brand", ""),
            "{브랜드명_영문}": _brand_en(product.get("brand", "")),
            "{모델명}": _model_val,
            "{사이트명}": product.get("source_site", ""),
            "{상품번호}": product.get("site_product_id", ""),
            "{검색키워드}": seo_text,
        }

        # 조합 태그 순서대로 값 치환 (빈 값이면 태그 자체 제거)
        def _resolve_tag(tag: str) -> str:
            if tag in tag_map:
                return tag_map[tag]
            # {태그} 패턴인데 미등록 — 공백/언더스코어 혼용 정규화 시도
            # (UI가 "{브랜드명 영문}" 공백으로 저장 → "{브랜드명_영문}" 키와 미매칭 방지)
            if tag.startswith("{") and tag.endswith("}"):
                norm = tag.replace(" ", "_")
                if norm in tag_map:
                    return tag_map[norm]
                return ""  # 치환 실패한 미등록 태그는 마켓 상품명에 노출 금지
            return tag  # 일반 리터럴 텍스트는 유지

        parts = [_resolve_tag(tag) for tag in composition]
        composed = " ".join(p for p in parts if p and p.strip())

        # 치환어 적용 (동시치환/순차치환 분기)

        replacements = name_rule.replacements or []
        if replacements:
            replace_mode = getattr(name_rule, "replace_mode", "simultaneous")
            if replace_mode == "sequential":
                # 순차치환: 위에서 아래로 순서대로 치환
                for r in replacements:
                    fr = (
                        r.get("from", "")
                        if isinstance(r, dict)
                        else getattr(r, "from_", "")
                    )
                    to = (
                        r.get("to", "") if isinstance(r, dict) else getattr(r, "to", "")
                    )
                    if not fr:
                        continue
                    case_insensitive = (
                        r.get("caseInsensitive", True)
                        if isinstance(r, dict)
                        else getattr(r, "caseInsensitive", True)
                    )
                    flags = re.IGNORECASE if case_insensitive else 0
                    composed = re.sub(re.escape(fr), to or "", composed, flags=flags)
            else:
                # 동시치환(기본): 모든 규칙을 한번에 적용, 긴 문자열 우선
                composed = self._simultaneous_replace(composed, replacements)

        # 삭제어 적용 (dedup 전에 적용하여 중복 단어 감지 가능하게)
        if deletion_words:
            for dw in deletion_words:
                composed = re.sub(re.escape(dw), " ", composed, flags=re.IGNORECASE)
            composed = re.sub(r"\s{2,}", " ", composed).strip()

        # prefix/suffix 적용 — 마켓별 값이 있으면 전역 대신 사용(없으면 전역 폴백).
        # 중복 제거(dedup)보다 먼저 적용한다 — 접두/접미어가 원본 상품명에 이미
        # 들어있는 단어("매장정품" 등)와 겹쳐도 아래 dedup 단계에서 한 번만 남도록.
        prefix = name_rule.prefix
        suffix = name_rule.suffix
        if market_type:
            mp = getattr(name_rule, "market_prefixes", None)
            if isinstance(mp, dict) and market_type in mp:
                prefix = mp[market_type]
            ms = getattr(name_rule, "market_suffixes", None)
            if isinstance(ms, dict) and market_type in ms:
                suffix = ms[market_type]
        if prefix:
            composed = f"{prefix} {composed}"
        if suffix:
            composed = f"{composed} {suffix}"

        # 중복 단어 제거 — 구두점 안에 묶인 부분단어까지 감지
        # (prefix/suffix 적용 후라, 접두어가 원본과 겹치면 여기서 하나로 합쳐진다)
        if name_rule.dedup_enabled:
            seen: set[str] = set()

            def _dedup_replace(m: re.Match) -> str:
                word = m.group(0)
                lower = word.lower()
                if lower in seen:
                    return ""
                seen.add(lower)
                return word

            # 2자 이상 단어 토큰(한글/영문/숫자 혼합 포함) + 하이픈 연결 숫자.
            # 영문+숫자 품번(예 OQ2DE112)을 글자/숫자로 쪼개지 않고 한 토큰으로 처리 —
            # 쪼개면 중복 품번이 통째로 안 지워지고 숫자 파편("2 2")이 남던 버그 방지.
            composed = re.sub(
                r"[^\W_]{2,}|\d+(?:-\d+)+",
                _dedup_replace,
                composed,
                flags=re.UNICODE,
            )
            # 연속 공백 정리
            composed = re.sub(r"\s+", " ", composed).strip()

        # 방어: 데이터(style_code/name)에 섞인 <p> 등 HTML 태그가 상품명에 흘러나오지
        # 않도록 최종 단계에서 제거 + 공백 정리
        composed = re.sub(r"<[^>]*>", "", composed)
        # 방어: 치환되지 못한 {태그} 잔여물 제거 (쿠팡 등 마켓 상품명에 "{브랜드명 영문}" 노출 방지)
        composed = re.sub(r"\{[^{}]*\}", "", composed)
        composed = re.sub(r"\s{2,}", " ", composed)

        return composed.strip()

    @staticmethod
    def _simultaneous_replace(text: str, replacements: list) -> str:
        """동시치환: 모든 치환규칙의 매칭을 한번에 수집 → 긴 문자열 우선 → 비겹침 선택."""

        # (start, end, to_val, from_len, priority)
        all_matches: list[tuple[int, int, str, int, int]] = []

        for i, r in enumerate(replacements):
            fr = r.get("from", "") if isinstance(r, dict) else getattr(r, "from_", "")
            to_val = r.get("to", "") if isinstance(r, dict) else getattr(r, "to", "")
            if not fr:
                continue
            case_insensitive = (
                r.get("caseInsensitive", True)
                if isinstance(r, dict)
                else getattr(r, "caseInsensitive", True)
            )
            flags = re.IGNORECASE if case_insensitive else 0
            pattern = re.compile(re.escape(fr), flags)
            for m in pattern.finditer(text):
                all_matches.append(
                    (m.start(), m.end(), to_val or "", m.end() - m.start(), i)
                )

        if not all_matches:
            return text

        # 위치(ASC) → 길이(DESC, 긴 것 우선) → 규칙순서(ASC)
        all_matches.sort(key=lambda x: (x[0], -x[3], x[4]))

        # 겹치지 않는 매칭만 선택 (greedy left-to-right)
        selected = []
        last_end = 0
        for match in all_matches:
            if match[0] >= last_end:
                selected.append(match)
                last_end = match[1]

        # 결과 문자열 조립
        parts: list[str] = []
        pos = 0
        for start, end, to_val, _, _ in selected:
            parts.append(text[pos:start])
            parts.append(to_val)
            pos = end
        parts.append(text[pos:])
        return "".join(parts)

    # ==================== 상세페이지 HTML 생성 ====================

    async def _build_detail_html(
        self, product: dict[str, Any], template_id_override: str = ""
    ) -> str:
        """정책의 상세 템플릿(상단/하단 이미지)과 상품 이미지를 조합하여 상세 HTML 생성.

        구조: 상단이미지 → 대표이미지 → 추가이미지 → 하단이미지
        template_id_override: 마켓별 전용 템플릿 ID (있으면 기본 템플릿 대신 사용)
        """
        from backend.domain.samba.policy.repository import SambaPolicyRepository
        from backend.domain.samba.policy.model import SambaDetailTemplate
        from backend.domain.shared.base_repository import BaseRepository

        parts: list[str] = []
        img_tag = '<div style="text-align:center;"><img src="{url}" style="max-width:860px;width:100%;" /></div>'

        def _extract_url(value: str) -> str:
            """img 태그가 저장된 경우 src URL만 추출."""
            if not value:
                return value
            if value.strip().startswith("<img"):
                import re as _re

                m = _re.search(r'src=["\']([^"\']+)["\']', value)
                return m.group(1) if m else value
            return value

        # 정책에서 상세 템플릿 조회
        policy_id = product.get("applied_policy_id")
        top_img = ""
        bottom_img = ""
        main_image_index = 0  # 대표이미지 번호(0-base) — 템플릿에서 로드 (#309)
        # 마켓 썸네일/갤러리(Image1~N) 추가이미지 포함 여부 — 상세 sub와 독립 (#342)
        # 기본 False = 갤러리에 대표이미지 1장만(템플릿 없어도 추가이미지 미전송 방침)
        gallery_include_sub = False
        # 이미지 포함 설정 (기본값: 상단/대표/추가/상세/하단 포함)
        img_checks: dict[str, bool] = {
            "topImg": True,
            "main": True,
            "sub": True,
            "title": False,
            "option": False,
            "detail": False,
            "sizeChart": True,  # 실측 사이즈표 (무신사 의류) — 기본 켬
            "bottomImg": True,
        }
        img_order: list[str] = [
            "topImg",
            "main",
            "sub",
            "title",
            "option",
            "detail",
            "sizeChart",
            "bottomImg",
        ]

        # 템플릿 ID 결정: 마켓별 오버라이드 → 정책 기본값 순
        # template_id_override는 policy_id 유무와 무관하게 항상 적용
        template_id = template_id_override
        if not template_id and policy_id:
            policy_repo = SambaPolicyRepository(self.session)
            policy = await policy_repo.get_async(policy_id)
            if policy and policy.extras:
                template_id = policy.extras.get("detail_template_id")
                logger.info(f"[상세HTML] 정책 {policy_id} 템플릿ID: {template_id}")
            else:
                logger.info(
                    f"[상세HTML] 정책 {policy_id} extras 없음 또는 정책 조회 실패"
                )
        elif not template_id:
            logger.info("[상세HTML] applied_policy_id 없음 — 템플릿 미적용")

        if template_id_override:
            logger.info(
                f"[상세HTML] 마켓별 오버라이드 템플릿 적용: {template_id_override}"
            )

        if template_id:
            tpl_repo = BaseRepository(self.session, SambaDetailTemplate)
            tpl = await tpl_repo.get_async(template_id)
            if tpl:
                top_img = _extract_url(tpl.top_image_s3_key or "")
                bottom_img = _extract_url(tpl.bottom_image_s3_key or "")
                if tpl.img_checks:
                    img_checks.update(tpl.img_checks)
                    # 실측표 토글 신규 — 기존 템플릿엔 키 없음 → 기본 켬 유지
                    img_checks.setdefault("sizeChart", True)
                if tpl.img_order:
                    img_order = list(tpl.img_order)
                    # 실측표는 신규 항목 — 기존 순서엔 없으므로 하단이미지 앞에 보강
                    if "sizeChart" not in img_order:
                        if "bottomImg" in img_order:
                            img_order.insert(img_order.index("bottomImg"), "sizeChart")
                        else:
                            img_order.append("sizeChart")
                main_image_index = int(getattr(tpl, "main_image_index", 0) or 0)
                gallery_include_sub = bool(getattr(tpl, "gallery_include_sub", False))
                logger.info(
                    f"[상세HTML] 템플릿 로드 — 상단:{bool(top_img)}, 하단:{bool(bottom_img)}, "
                    f"checks:{img_checks}, gallery_sub:{gallery_include_sub}"
                )
            else:
                logger.warning(f"[상세HTML] 템플릿 {template_id} 조회 실패")

        # 원본 이미지 보존 — 아래에서 product["images"] 를 gallery_include_sub 에 맞춰
        # 잘라 덮어쓰는데, 이 함수는 상품당 두 번 호출된다(1466 기본 템플릿 → 2282
        # 마켓별 템플릿). 잘린 목록을 소스로 다시 자르면 마켓별 템플릿의
        # gallery_include_sub 가 통째로 무시된다.
        # 2026-08-15 토스 첫 등록 실패가 이 경로였다: 기본 템플릿이 false 라 8장 →
        # 1장으로 줄어든 뒤, 토스 전용 템플릿(true)을 적용해도 1장뿐이라 상세 이미지가
        # 0장이 되어 [COMMON_ERROR] 상세 이미지 또는 html을 찾을 수 없음 으로 거부됐다.
        # 첫 호출 때 원본을 보관하고 이후 항상 그걸 소스로 쓴다.
        if "_gallery_source_images" not in product:
            product["_gallery_source_images"] = list(product.get("images") or [])
        images = _usable_image_urls(product["_gallery_source_images"])
        # 대표이미지 선택 (#309) — main_image_index가 가리키는 이미지를 맨 앞으로.
        # 상세HTML main / 마켓 썸네일 대표이미지 일치. 갤러리·상세 공통 적용.
        if images and 0 < main_image_index < len(images):
            images = (
                [images[main_image_index]]
                + images[:main_image_index]
                + images[main_image_index + 1 :]
            )

        # 마켓 썸네일/갤러리(Image1~N) 소스 — gallery_include_sub 토글만 따름 (#342).
        # 상세페이지 img_checks.sub 와 분리 → "상세는 1장, 갤러리는 추가이미지 전부"가
        # 표현 가능. False면 #309처럼 대표 1장으로 단일화.
        if images:
            product["images"] = images if gallery_include_sub else images[:1]

        # 상세페이지 Content 용 이미지 (#342) — img_checks.sub 만 따름.
        # product["images"](갤러리 소스)는 건드리지 않고 로컬 복사본으로만 단일화.
        detail_imgs = images if img_checks.get("sub", False) else images[:1]

        detail_images = _usable_image_urls(product.get("detail_images"))
        # 브랜드 자사몰 이미지 제거 (지재권) — 상세에 들어가는 detail_images 에만
        # 적용한다. images(대표/추가)는 소싱처 CDN 이라 영향이 없고, 만에 하나
        # 걸리면 상품이 대표이미지 0장이 되어 등록 자체가 깨지므로 건드리지 않는다.
        if detail_images:
            detail_images, _dropped = _drop_brand_host_images(detail_images)
            if _dropped:
                logger.info(
                    f"[상세HTML] 브랜드 자사몰 이미지 {_dropped}장 제거 "
                    f"(남은 상세이미지 {len(detail_images)}장)"
                )

        # main/sub 에서 출력될 URL을 추적 → detail에서 중복 제외
        # 단, 실제로 출력되는 항목만 넣는다(detail만 단독 사용일 때 무필터 정상 노출).
        # main 을 빼먹으면 GS처럼 images == detail_images 인 소싱처에서 대표이미지가
        # 상세에 두 번 박힌다(실측: 라코스테 쇼퍼백 — 2번째와 8번째가 동일 URL).
        sub_set: set[str] = set()
        if img_checks.get("main", False) and detail_imgs:
            sub_set.add(detail_imgs[0])
        if img_checks.get("sub", False) and len(detail_imgs) > 1:
            sub_set.update(detail_imgs[1:])

        # img_order 순서대로, img_checks가 True인 항목만 생성
        for item_id in img_order:
            if not img_checks.get(item_id, False):
                continue
            if item_id == "topImg" and top_img:
                parts.append(img_tag.format(url=top_img))
            elif item_id == "main" and detail_imgs:
                parts.append(img_tag.format(url=detail_imgs[0]))
            elif item_id == "sub":
                for sub_img in detail_imgs[1:]:
                    parts.append(img_tag.format(url=sub_img))
            elif item_id == "title":
                name = product.get("name", "")
                if name:
                    parts.append(
                        f'<div style="text-align:center;padding:1rem 0;"><h2 style="color:#333;font-size:1.25rem;">{name}</h2></div>'
                    )
            elif item_id == "detail":
                detail_emitted = 0
                for d_img in detail_images:
                    if d_img in sub_set:
                        continue
                    parts.append(img_tag.format(url=d_img))
                    detail_emitted += 1
                # 폴백: detail에 1장도 안 들어갔으면 추가이미지(detail_imgs[1:])로 채움
                # — detail_images 가 비어있는 경우 대비.
                # 이미 main/sub 로 나간 이미지는 제외한다. 안 그러면 detail_images 가
                # images 의 부분집합일 때(전부 걸러져 detail_emitted==0) 폴백이 방금
                # 출력한 이미지를 그대로 다시 붙여 중복을 만든다.
                if detail_emitted == 0:
                    fallback_imgs = [
                        u
                        for u in (detail_imgs[1:] or detail_imgs[:1])
                        if u not in sub_set
                    ]
                    for s_img in fallback_imgs:
                        parts.append(img_tag.format(url=s_img))
                    if fallback_imgs:
                        logger.info(
                            f"[상세HTML] detail 비어있음 → 추가이미지 {len(fallback_imgs)}장 폴백"
                        )
            elif item_id == "sizeChart":
                size_html = self._build_size_chart_html(product.get("actual_size"))
                if size_html:
                    parts.append(size_html)
            elif item_id == "bottomImg" and bottom_img:
                parts.append(img_tag.format(url=bottom_img))

        if not parts:
            return f"<p>{product.get('name', '')}</p>"

        return "\n".join(parts)

    @staticmethod
    def _build_size_chart_html(actual_size: Optional[dict[str, Any]]) -> str:
        """실측 사이즈표 데이터 → 상세페이지용 HTML 테이블.

        무신사 actual-size 구조:
            {typeName, description, sizes: [{name, items: [{name, value}]}]}
        데이터 없거나(신발/타소싱처) 형식 불일치면 빈 문자열 반환 → 토글 켜도 무해.
        """
        import html as _html

        if not actual_size or not isinstance(actual_size, dict):
            return ""
        sizes = actual_size.get("sizes") or []
        if not sizes or not isinstance(sizes, list):
            return ""

        # 컬럼(부위명) 순서 — 첫 사이즈의 items 순서 기준
        first_items = (sizes[0] or {}).get("items") or []
        col_names: list[str] = [
            str(it.get("name", "")).strip()
            for it in first_items
            if isinstance(it, dict) and str(it.get("name", "")).strip()
        ]
        if not col_names:
            return ""

        def _fmt(v: Any) -> str:
            # 60.0 → "60", 17.5 → "17.5"
            try:
                f = float(v)
                return str(int(f)) if f == int(f) else str(f)
            except (TypeError, ValueError):
                return _html.escape(str(v)) if v is not None else "-"

        th_style = (
            "border:1px solid #ddd;padding:8px 10px;background:#f5f5f5;"
            "font-weight:600;color:#333;white-space:nowrap;"
        )
        td_style = (
            "border:1px solid #ddd;padding:8px 10px;color:#444;"
            "text-align:center;white-space:nowrap;"
        )

        header_cells = f'<th style="{th_style}">사이즈</th>' + "".join(
            f'<th style="{th_style}">{_html.escape(c)}</th>' for c in col_names
        )
        rows_html: list[str] = []
        for sz in sizes:
            if not isinstance(sz, dict):
                continue
            sz_name = _html.escape(str(sz.get("name", "")).strip())
            item_map = {
                str(it.get("name", "")).strip(): it.get("value")
                for it in (sz.get("items") or [])
                if isinstance(it, dict)
            }
            cells = f'<td style="{td_style}">{sz_name}</td>' + "".join(
                f'<td style="{td_style}">{_fmt(item_map.get(c))}</td>'
                for c in col_names
            )
            rows_html.append(f"<tr>{cells}</tr>")

        if not rows_html:
            return ""

        type_name = _html.escape(str(actual_size.get("typeName", "")).strip())
        description = _html.escape(str(actual_size.get("description", "")).strip())
        title = "실측 사이즈" + (f" ({type_name})" if type_name else "")

        return (
            '<div style="max-width:860px;width:100%;margin:1.5rem auto;'
            'font-family:inherit;">'
            f'<h3 style="font-size:1.1rem;font-weight:700;color:#333;'
            f'margin:0 0 0.75rem;text-align:center;">{title}</h3>'
            '<table style="border-collapse:collapse;width:100%;'
            'font-size:0.9rem;"><thead><tr>'
            f"{header_cells}</tr></thead><tbody>"
            f"{''.join(rows_html)}</tbody></table>"
            + (
                f'<p style="font-size:0.8rem;color:#888;margin:0.5rem 0 0;'
                f'text-align:center;">{description} (단위: cm)</p>'
                if description
                else '<p style="font-size:0.8rem;color:#888;margin:0.5rem 0 0;'
                'text-align:center;">단위: cm</p>'
            )
            + "</div>"
        )

    # ==================== 카테고리 매핑 자동 조회 ====================

    async def _find_ssg_name_owner(
        self, product_id: str, name: str, account_id: str
    ) -> str:
        """이 SSG 계정에 이미 등록된 '동일 소싱처 상품' 형제의 id (없으면 "").

        SSG 는 동일 상품명 재등록을 "동일한 상품이 이미 존재"로 거부한다. 그런데 이름만
        같아도 카테고리가 다르면 전송 상품명(itemNm)이 달라져 SSG가 받아주는 경우가 있어
        (실측: 정상 등록분 10건 중 4건이 동일 이름 형제 보유), 이름 기준 차단은 등록 가능한
        상품까지 막는다. 그래서 **같은 소싱처의 같은 상품코드(site_product_id)** = 논란 없는
        중복수집분만 차단한다(롯데온 충돌의 79%). 이름만 같은 케이스는 전송을 시도하고,
        거부되면 플러그인이 실패로 정직하게 기록한다(_duplicate_name_conflict).
        """
        from sqlalchemy import text

        name = (name or "").strip()
        if not name:
            return ""

        def _real(alias: str = "") -> str:
            """해당 계정에 '실제 itemId'가 기록된 상품인지 (마커/빈값 제외)."""
            col = f"{alias}.market_product_nos" if alias else "market_product_nos"
            return (
                f"{col} ->> cast(:acc as text) IS NOT NULL "
                f"AND {col} ->> cast(:acc as text) "
                "NOT IN ('__exists__', '__claiming__', '')"
            )

        try:
            row = (
                await self.session.execute(
                    text(
                        "SELECT s.id FROM samba_collected_product s "
                        "JOIN samba_collected_product p ON p.id = cast(:pid as text) "
                        " AND s.source_site = p.source_site "
                        " AND s.site_product_id = p.site_product_id "
                        "WHERE s.id <> cast(:pid as text) AND s.site_product_id <> '' "
                        f"AND {_real('s')} LIMIT 1"
                    ),
                    {"pid": product_id, "acc": account_id},
                )
            ).first()
            return str(row[0]) if row else ""
        except Exception as e:
            # 조회 실패 시엔 게이트를 열어둔다(전송 시도) — 과차단보다 안전
            logger.warning(f"[SSG] 동일상품명 선점 조회 실패(무시): {e}")
            return ""

    async def _resolve_category_mappings(
        self,
        source_site: str,
        source_category: str,
        target_account_ids: list[str],
    ) -> dict[str, str]:
        """수집 상품의 소싱처 카테고리 → 각 마켓 카테고리 자동 매핑.

        카테고리매핑 페이지에서 설정한 DB 매핑만 사용. 없으면 해당 마켓 전송 제외.
        """
        from backend.domain.samba.category.repository import (
            SambaCategoryMappingRepository,
        )
        from backend.domain.samba.category.service import SambaCategoryService

        if not source_category:
            return {}

        # DB에서 매핑 조회
        mapping_repo = SambaCategoryMappingRepository(self.session)
        mapping = (
            await mapping_repo.find_mapping(source_site, source_category)
            if source_category
            else None
        )

        result: dict[str, str] = {}

        # 대상 계정의 마켓 타입 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_cat
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_cat

        _stmt_cat = _sel_cat(_SMA_cat).where(_SMA_cat.id.in_(target_account_ids))
        _res_cat = await self.session.execute(_stmt_cat)
        _cat_accounts = _res_cat.scalars().all()
        market_types = {a.market_type for a in _cat_accounts}

        # ssg 계정이 있으면 ssg_std 카테고리 매핑도 함께 조회
        mapping_market_types = set(market_types)
        if "ssg" in market_types:
            mapping_market_types.add("ssg_std")

        for market_type in mapping_market_types:
            # 카테고리매핑 페이지 설정만 사용
            if mapping and mapping.target_mappings:
                target = mapping.target_mappings.get(market_type, "")
                if target:
                    result[market_type] = target
                    continue

            # DB 매핑 없으면 해당 마켓은 스킵 (사용자가 직접 매핑한 것만 전송)
            logger.info(f"[카테고리] {market_type} DB 매핑 없음 — 전송 대상에서 제외")

        # 경로 문자열 → 숫자 코드 변환
        # ssg: _sync_ssg_display가 cat2에 dispCtgId 코드맵을 저장하므로 변환 가능
        # ssg_std: _sync_ssg가 cat2에 stdCtgDclsId 코드맵을 저장하므로 변환 가능
        # (이전에는 cat2가 표준카테고리만 담아 ssg 변환이 불가했으나, sync_service 개선으로 해소됨)
        from backend.domain.samba.category.repository import SambaCategoryTreeRepository

        category_svc = SambaCategoryService(
            mapping_repo, SambaCategoryTreeRepository(self.session)
        )
        convert_markets = set(market_types) | (
            {"ssg_std"} if "ssg" in market_types else set()
        )
        for market_type in convert_markets:
            if market_type in result:
                cat_path = result[market_type]
                if cat_path and not cat_path.isdigit() and "|" not in cat_path:
                    code = await category_svc.resolve_category_code(
                        market_type, cat_path
                    )
                    if code:
                        logger.info(
                            "[카테고리 코드 변환] %s: '%s' → %s",
                            market_type,
                            cat_path,
                            code,
                        )
                        result[market_type] = code
                    else:
                        logger.warning(
                            "[카테고리 코드 변환] %s: '%s' 코드 없음 — 카테고리 동기화 후 재시도",
                            market_type,
                            cat_path,
                        )

        return result

    # ==================== 재전송 ====================

    async def retransmit(self, shipment_id: str) -> Optional[SambaShipment]:
        """실패한 계정에 대해 기존 shipment 레코드를 업데이트하며 재전송."""
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import dispatch_to_market

        shipment = await self.repo.get_async(shipment_id)
        if not shipment:
            return None

        old_result = shipment.transmit_result or {}
        old_errors = shipment.transmit_error or {}
        failed_accounts = [aid for aid, st in old_result.items() if st == "failed"]
        if not failed_accounts:
            return shipment

        # 상품 데이터 조회
        product_repo = SambaCollectedProductRepository(self.session)
        product_row = await product_repo.get_async(shipment.product_id)
        if not product_row:
            return shipment
        # OOM 방지: 전송에 불필요한 대용량 필드 제외
        product_dict = product_row.model_dump(exclude={"last_sent_data", "extra_data"})
        # 실측 사이즈표 — extra_data는 제외되므로 row에서 직접 주입 (#실측표)
        product_dict["actual_size"] = (product_row.extra_data or {}).get("actualSize")

        # 상세 HTML 재생성 — 정상 전송 경로(line 2083)와 동일. 이게 빠져 있으면
        # 재전송 때만 소싱처 원문 detail_html 이 그대로 마켓에 나간다
        # (지재권 위험 + 원문이 비면 상세 텅 빔 + 상단/하단 배너 누락).
        product_dict["detail_html"] = await self._build_detail_html(product_dict)

        # 재전송
        await self.repo.update_async(shipment_id, status="transmitting")
        new_result = dict(old_result)
        new_errors = dict(old_errors)

        # 실패 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_rt
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_rt

        _stmt_rt = _sel_rt(_SMA_rt).where(_SMA_rt.id.in_(failed_accounts))
        _res_rt = await self.session.execute(_stmt_rt)
        _rt_account_map = {a.id: a for a in _res_rt.scalars().all()}

        # 카테고리 매핑 재조회
        raw_category = product_row.category or ""

        # 검색필터명 조회 (플레이오토 임의분류용)
        if product_row.search_filter_id:
            from backend.domain.samba.collector.repository import (
                SambaSearchFilterRepository,
            )

            sf_repo = SambaSearchFilterRepository(self.session)
            sf = await sf_repo.get_async(product_row.search_filter_id)
            if sf and sf.name:
                product_dict["_search_filter_name"] = sf.name

        mapped_categories = await self._resolve_category_mappings(
            product_row.source_site or "",
            raw_category,
            failed_accounts,
        )

        for account_id in failed_accounts:
            try:
                account = _rt_account_map.get(account_id)
                if not account:
                    continue
                category_id = mapped_categories.get(account.market_type, "")
                # ESM Plus 크로스매핑: 지마켓↔옥션 자동 변환
                if not category_id and account.market_type in ("gmarket", "auction"):
                    other = "auction" if account.market_type == "gmarket" else "gmarket"
                    other_id = mapped_categories.get(other, "")
                    if other_id and str(other_id).isdigit():
                        from backend.domain.samba.proxy.esmplus import esm_map_category

                        category_id = esm_map_category(
                            other_id, other, account.market_type
                        )
                        if category_id:
                            logger.info(
                                f"[ESM 크로스매핑] {other}({other_id}) → {account.market_type}({category_id})"
                            )
                # 카페24/롯데홈쇼핑/GS샵은 카테고리 매핑 없이 플러그인 내부에서 자동 처리
                # 포이즌은 카탈로그(globalSkuId) 매칭이라 마켓 카테고리 자체가 없음
                if not category_id and account.market_type not in (
                    "playauto",
                    "cafe24",
                    "lottehome",
                    "gsshop",
                    "poison",
                ):
                    new_result[account_id] = "failed"
                    new_errors[account_id] = "카테고리 매핑 없음"
                    continue
                # 모든 DB 읽기 완료 — HTTP 전송 전 트랜잭션 종료 (idle in transaction 방지)
                # (2026-05-27) line 1794 와 동일 패턴 적용. dispatch_to_market 은 마켓
                # HTTP 호출 30~60s — 세션 보유 시 IIT 누적 → connection-closed.
                try:
                    await self.session.commit()
                except Exception:
                    # commit 실패 시 rollback으로 SessionTransaction PREPARED 고착 차단(이슈#276)
                    try:
                        await self.session.rollback()
                    except Exception:
                        pass
                # SSG 표준카테고리(stdCtgId) 주입 — 정상 send path 와 동일 패턴
                acct_product = dict(product_dict)
                if account.market_type == "ssg":
                    _std_cat = mapped_categories.get("ssg_std", "")
                    if _std_cat:
                        acct_product["_std_category_id"] = _std_cat
                # 저재고 오버셀 방지 캡 (#703) — 정상 send path(위쪽)와 동일 패턴.
                # 리셀 플랫폼(크림/포이즌)에만 적용 — _LOW_STOCK_SEND_CAP_MARKETS 참고.
                # options는 새 리스트로 교체(깊은 복사) — 원본 product_dict 오염 방지.
                if (
                    account.market_type in _LOW_STOCK_SEND_CAP_MARKETS
                    and acct_product.get("options")
                ):
                    _capped_opts_rt = []
                    for _opt_rt in acct_product["options"]:
                        _opt_rt_copy = (
                            dict(_opt_rt) if isinstance(_opt_rt, dict) else _opt_rt
                        )
                        if isinstance(_opt_rt_copy, dict):
                            try:
                                if (
                                    int(_opt_rt_copy.get("stock") or 0)
                                    <= _LOW_STOCK_SEND_CAP_TH
                                ):
                                    _opt_rt_copy["stock"] = 0
                            except (TypeError, ValueError):
                                pass
                        _capped_opts_rt.append(_opt_rt_copy)
                    acct_product["options"] = _capped_opts_rt
                result = await dispatch_to_market(
                    self.session,
                    account.market_type,
                    acct_product,
                    category_id,
                    account=account,
                )
                if result.get("success"):
                    new_result[account_id] = "success"
                    new_errors.pop(account_id, None)
                else:
                    new_result[account_id] = "failed"
                    new_errors[account_id] = result.get("message", "")
            except Exception as exc:
                new_result[account_id] = "failed"
                new_errors[account_id] = str(exc)

        values = list(new_result.values())
        all_success = len(values) > 0 and all(v == "success" for v in values)
        all_failed = len(values) > 0 and all(v == "failed" for v in values)
        final_status = (
            "completed" if all_success else ("failed" if all_failed else "partial")
        )

        updated = await self.repo.update_async(
            shipment_id,
            status=final_status,
            transmit_result=new_result,
            transmit_error=new_errors if new_errors else None,
            completed_at=datetime.now(UTC),
        )
        return updated or shipment

    # ==================== 마켓 상품 삭제 ====================

    async def delete_from_markets(
        self,
        product_ids: list[str],
        target_account_ids: list[str],
        current_idx: int | None = None,
        total_count: int | None = None,
        log_to_buffer: bool = False,
        disconnect_checker: Any | None = None,
        on_progress: Any | None = None,
    ) -> dict[str, Any]:
        """선택된 상품을 대상 마켓에서 삭제.

        log_to_buffer=True: 상품전송삭제 페이지 링 버퍼에 로그 기록 (폴링으로 실시간 표시).
        False(기본): 상품관리 페이지에서 호출 시 — 모달이 자체 로그를 표시하므로 버퍼 불필요.
        """
        from backend.domain.samba.collector.repository import (
            SambaCollectedProductRepository,
        )
        from backend.domain.samba.shipment.dispatcher import delete_from_market

        if log_to_buffer:
            from backend.domain.samba.job.worker import _add_shipment_log
            from datetime import (
                datetime as _dt_del,
                timezone as _tz_del,
                timedelta as _td_del,
            )

            def _del_log(msg: str) -> None:
                kst = (_dt_del.now(_tz_del.utc) + _td_del(hours=9)).strftime("%H:%M:%S")
                _add_shipment_log(f"[{kst}] {msg}")

        else:

            def _del_log(msg: str) -> None:  # type: ignore[misc]
                pass

        # 인덱스 prefix — 프론트에서 [i/N] 전달 시 표시
        idx_prefix = (
            f"[{current_idx:,}/{total_count:,}] "
            if current_idx is not None and total_count is not None
            else ""
        )

        product_repo = SambaCollectedProductRepository(self.session)

        # 대상 계정 배치 조회 (N+1 → 1회)
        from sqlmodel import select as _sel_del
        from backend.domain.samba.account.model import SambaMarketAccount as _SMA_del

        _stmt_del = _sel_del(_SMA_del).where(_SMA_del.id.in_(target_account_ids))
        _res_del = await self.session.execute(_stmt_del)
        _del_account_map = {a.id: a for a in _res_del.scalars().all()}

        results: list[dict[str, Any]] = []

        for product_id in product_ids:
            product_row = await product_repo.get_async(product_id)
            if not product_row:
                results.append(
                    {"product_id": product_id, "status": "failed", "error": "상품 없음"}
                )
                continue
            # 삭제잠금 가드 — 자동 경로(autotune/refresh)와 동일하게 수동 마켓삭제도 차단 (#301)
            if getattr(product_row, "lock_delete", False):
                results.append(
                    {"product_id": product_id, "status": "skipped", "error": "삭제잠금"}
                )
                continue

            # OOM 방지: 삭제에 불필요한 대용량 필드 제외
            product_dict = product_row.model_dump(
                exclude={"last_sent_data", "extra_data"}
            )
            market_product_nos = as_market_nos(product_row.market_product_nos)
            reg_accounts = product_row.registered_accounts or []
            delete_results: dict[str, str] = {}

            for account_id in target_account_ids:
                if disconnect_checker is not None and await disconnect_checker():
                    logger.info("[마켓삭제] 클라이언트 연결 종료 감지 - 계정 삭제 중단")
                    break
                # 이 상품에 등록된 계정만 삭제 대상
                if account_id not in reg_accounts:
                    acc = _del_account_map.get(account_id)
                    if not acc:
                        continue
                    # PlayAuto: API 삭제 불가 — DB 불일치 상태여도 성공 처리하여 프론트 배지 제거
                    if acc.market_type == "playauto":
                        delete_results[account_id] = "success"
                        continue
                    # non-PlayAuto: 상품번호가 있으면 registered_accounts 불일치 상태 → 삭제 시도
                    has_product_no = bool(
                        market_product_nos.get(f"{account_id}_origin")
                        or market_product_nos.get(account_id)
                    )
                    if not has_product_no:
                        # 상품번호도 없음 → 이미 삭제된 상태로 간주, 배지 정리
                        delete_results[account_id] = "success"
                        continue
                    # 상품번호 있음 → 아래 삭제 로직 fall-through

                account = _del_account_map.get(account_id)
                if not account:
                    delete_results[account_id] = "계정 없음"
                    continue

                # 상품번호를 product_dict에 주입 (디스패처가 사용)
                # 스마트스토어: 삭제 API는 originProductNo 사용 (2143473a 전송경로 패치와 대칭)
                if account.market_type == "smartstore":
                    product_no = market_product_nos.get(f"{account_id}_origin", "")
                    if not product_no:
                        raw = market_product_nos.get(account_id, "")
                        if isinstance(raw, dict):
                            product_no = (
                                raw.get("originProductNo")
                                or raw.get("smartstoreChannelProductNo")
                                or raw.get("groupProductNo")
                                or ""
                            )
                        else:
                            product_no = raw
                    product_no = str(product_no) if product_no else ""
                elif account.market_type in ("gmarket", "auction"):
                    # ESM 삭제 API는 마스터 goodsNo 필요 — _master 우선
                    product_no = market_product_nos.get(
                        f"{account_id}_master"
                    ) or market_product_nos.get(account_id, "")
                else:
                    product_no = market_product_nos.get(account_id, "")
                product_dict["market_product_no"] = {account.market_type: product_no}

                result = await delete_from_market(
                    self.session,
                    account.market_type,
                    product_dict,
                    account=account,
                    market_delete=True,
                )
                # 429 방지 — 삭제 요청 간 0.5초 딜레이
                await asyncio.sleep(0.5)

                # 로그용 상품/계정 레이블
                src_tag = (
                    f"[{product_row.source_site}] " if product_row.source_site else ""
                )
                prod_name = (product_row.name or product_id)[:30]
                prod_no = str(product_row.site_product_id or product_id or "")
                prod_label = (
                    f"{prod_name} (상품번호: {prod_no})" if prod_no else prod_name
                )
                acc_label = f"{account.market_name}({account.seller_id or '-'})"

                if result.get("success"):
                    if result.get("soldout_fallback"):
                        # 주문 진행중 → 품절 처리 fallback (등록 상태 유지)
                        delete_results[account_id] = "soldout_fallback"
                        _del_log(
                            f"{idx_prefix}{src_tag}{prod_label} → {acc_label}: 품절 처리 완료"
                        )
                        logger.info(
                            f"[마켓삭제] {account.market_type} 품절 fallback - 상품: {product_id}"
                        )
                    else:
                        delete_results[account_id] = "success"
                        _del_log(
                            f"{idx_prefix}{src_tag}{prod_label} → {acc_label}: 삭제 성공"
                        )
                        logger.info(
                            f"[마켓삭제] {account.market_type} 성공 - 상품: {product_id}"
                        )
                else:
                    delete_results[account_id] = result.get("message", "실패")
                    _del_log(
                        f"{idx_prefix}{src_tag}{prod_label} → {acc_label}: {delete_results[account_id]}"
                    )
                    logger.warning(
                        f"[마켓삭제] {account.market_type} 실패 - {result.get('message')}"
                    )

            # 성공한 계정만 등록 해제 (soldout_fallback은 등록 상태 유지)
            success_ids = [
                aid for aid, status in delete_results.items() if status == "success"
            ]
            if success_ids:
                new_reg = [a for a in reg_accounts if a not in success_ids]
                remove_keys = set(success_ids)
                for aid in success_ids:
                    remove_keys.add(f"{aid}_origin")
                    remove_keys.add(f"{aid}_master")
                    remove_keys.add(f"{aid}_site")
                new_nos = {
                    k: v for k, v in market_product_nos.items() if k not in remove_keys
                }
                update_data: dict[str, Any] = {
                    "registered_accounts": new_reg if new_reg else None,
                    "market_product_nos": new_nos if new_nos else None,
                }
                if not new_reg:
                    update_data["status"] = "collected"
                await product_repo.update_async(product_id, **update_data)

            results.append(
                {
                    "product_id": product_id,
                    "delete_results": delete_results,
                    "success_count": len(
                        [v for v in delete_results.values() if v == "success"]
                    ),
                }
            )
            if on_progress:
                await on_progress(len(results), len(product_ids))

        return {
            "processed": len(results),
            "results": results,
        }

    async def delete_all_by_account(
        self,
        account_id: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """특정 마켓 계정에 등록된 전체 상품을 마켓에서 삭제.

        dry_run=True이면 삭제 대상 상품 수만 반환.
        """
        from sqlalchemy import cast
        from sqlmodel import select

        from backend.domain.samba.account.model import SambaMarketAccount
        from backend.domain.samba.collector.model import SambaCollectedProduct

        # 1) 계정 존재 확인
        account = await self.session.get(SambaMarketAccount, account_id)
        if not account:
            raise ValueError(f"계정을 찾을 수 없습니다: {account_id}")

        # 2) 해당 계정에 등록된 상품 ID 조회
        from sqlalchemy import String as _String
        from sqlalchemy.dialects.postgresql import ARRAY as _PGARRAY

        # cast(f'["{id}"]', JSONB) 는 SQLAlchemy 이중 인코딩으로 @> 가 영원히 0건
        # 반환 — 계정 삭제/정리 시 등록상품을 하나도 못 찾아 조용히 아무 일도 안 함.
        # ARRAY(String)+`?|` 로 회피 (project_orm_cast_jsonb_double_encoding 재발, 2026-07-13).
        stmt = select(SambaCollectedProduct.id).where(
            SambaCollectedProduct.registered_accounts.op("?|")(
                cast([account_id], _PGARRAY(_String))
            )
        )
        result = await self.session.execute(stmt)
        product_ids = list(result.scalars().all())
        total_count = len(product_ids)

        # 3) dry_run이면 상품 수와 예상 시간만 반환
        if dry_run:
            return {
                "dry_run": True,
                "account_id": account_id,
                "account_label": account.account_label,
                "market_type": account.market_type,
                "total_products": total_count,
                "estimated_seconds": total_count * 0.5,
            }

        if total_count == 0:
            return {
                "account_id": account_id,
                "total_products": 0,
                "message": "삭제 대상 상품이 없습니다.",
            }

        # 4) 기존 delete_from_markets 재사용
        logger.info(
            f"[계정삭제] {account.account_label}({account.market_type}) "
            f"전체 {total_count}건 삭제 시작"
        )
        return await self.delete_from_markets(product_ids, [account_id])

    @staticmethod
    def get_status_label(status: str) -> str:
        return STATUS_LABELS.get(status, status)
