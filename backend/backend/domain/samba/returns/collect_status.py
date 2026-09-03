"""반품 회수상태 자동판정 (T4-v2 — 2026-09-03, 실측 경로 확정판).

사장님 수작업 흐름(원주문 송장 → 택배사 사이트 검색 → 반송장 확인 →
반송장 역조회 → 집하여부 → 반품탭 상태 반영)을 그대로 자동화한다.
반송장은 삼바 DB에 없으므로 **원송장에서 끌어온다** (2026-09-03 실측 확정):
  - CJ대한통운: trace.cjlogistics.com REST → data.rtnWblno (빈 문자열=미발행)
  - 한진택배:   hanjin.com WaybillResult.do HTML → [반품운송장번호 : <a>NNN</a>]
  - 롯데·로젠·딜리박스·우체국: 원송장에 반송장이 안 붙음(실측) → 미지원 처리

반송장 확보 우선순위:
  1) samba_order.return_collect_tracking (이미 채워진 값 — LOTTEON 회수조회 등)
  2) fetch_return_waybill(원송장) — CJ/한진 원송장 조회로 반송장 획득.
     얻으면 samba_order.return_collect_* 에 저장(재조회 절감).
  3) 마켓 반품 클레임 원본에서 회수송장 추출 (_extract_collect_tracking, 보조)
     — 실제 응답 필드명이 아직 미확인이라 후보키 목록으로 방어적 탐색.
       못 찾으면 raw 의 "키 목록만" logger.info 로 남겨 운영 1회 실행으로
       실측 필드명을 확보할 수 있게 한다 (값/개인정보는 절대 로그 금지).

집하 판정 — 반송장을 deliverytracker v1 로 역조회 (CJ/한진 모두 조회됨 실측):
  | 상황                                          | samba_return.status |
  |-----------------------------------------------|---------------------|
  | 원송장 없음 / 미지원 택배사 / 반송장 미발행   | not_collected       |
  | 반송장 있음 + 이벤트 있음 + 최종 배송완료 아님| collecting          |
  | 반송장 있음 + 최종 배송완료                   | collected           |

안전규칙:
  - 되돌리기 금지 — collected→collecting/not_collected, collecting→not_collected
    방향의 하향 전이는 하지 않는다 (진행 방향으로만 올린다).
  - completion_detail 이 확정값(취소/반품/교환/거부)인 행은 건드리지 않는다.
  - 판정 근거는 samba_return.timeline 에 {date, status, message} 로 append.
    송장번호는 뒤 4자리만 남기고 마스킹.
  - 외부 API 예외는 해당 건만 error 집계하고 배치 전체는 계속 진행.
    동시성 Semaphore(2), 건당 타임아웃 10초(403/429 는 백오프 재시도).
"""

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── 상수 ──────────────────────────────────────────────────────────────

# 회수상태 어휘 및 진행 순위 (되돌리기 금지 판정용)
STATUS_NOT_COLLECTED = "not_collected"  # 미수거
STATUS_COLLECTING = "collecting"  # 수거중
STATUS_COLLECTED = "collected"  # 수거완료

_COLLECT_STATUS_RANK: dict[str, int] = {
    STATUS_NOT_COLLECTED: 0,
    STATUS_COLLECTING: 1,
    STATUS_COLLECTED: 2,
}

_STATUS_LABEL: dict[str, str] = {
    STATUS_NOT_COLLECTED: "미수거",
    STATUS_COLLECTING: "수거중",
    STATUS_COLLECTED: "수거완료",
}

# completion_detail 확정값 — 이 값이 박힌 행은 자동판정이 건드리지 않는다
# (order.py::_RETURN_FINAL_DETAILS 와 동일 어휘. order.py 는 수정 금지 파일이라
#  import 하지 않고 여기 복제 — 어휘 변경 시 양쪽 동기화 필요)
_FINAL_COMPLETION_DETAILS = ("취소", "반품", "교환", "거부")

# 마켓 클레임 raw 에서 회수송장/회수택배사를 찾을 후보키.
# ⚠️ 실제 필드명 미확인 상태의 방어적 목록 — 대소문자/스네이크/카멜 무시 비교용으로
# 소문자 + 구분자 제거 형태로 보관한다. 앞쪽일수록 우선순위 높음
# (반품 전용 키 > 범용 송장 키 순).
_COLLECT_TRACKING_KEY_CANDIDATES: tuple[str, ...] = (
    "rtngddlvno",  # rtngdDlvNo
    "clctdlvno",  # clctDlvNo
    "returninvoiceno",  # returnInvoiceNo
    "returndlvno",  # returnDlvNo
    "rtninvoiceno",  # rtnInvoiceNo
    "collectinvoiceno",  # collectInvoiceNo
    "rtngdwybl",  # rtngdWybl
    "wyblno",  # wyblNo
    "invoiceno",  # invoiceNo
    "dlvno",  # dlvNo
    "deliveryno",  # deliveryNo
)

_COLLECT_COURIER_KEY_CANDIDATES: tuple[str, ...] = (
    "rtngddlvconm",  # rtngdDlvCoNm
    "clctdlvconm",  # clctDlvCoNm
    "returndlvco",  # returnDlvCo
    "rtndlvconm",  # rtnDlvCoNm
    "rtngddlvco",  # rtngdDlvCo
    "clctdlvco",  # clctDlvCo
    "deliverycompany",  # deliveryCompany
    "dlvconm",  # dlvCoNm
    "wyblconm",  # wyblCoNm
    "wyblco",  # wyblCo
)

# 택배사명 표기 흔들림 보정 — SHIPPING_COMPANY_TO_CARRIER_ID(order.py) 의
# 정식 키로 정규화한다. 매핑 자체는 order.py 것을 재사용(수정 금지 파일이라 지연 import).
_COURIER_ALIASES: dict[str, str] = {
    "CJ": "CJ대한통운",
    "CJ택배": "CJ대한통운",
    "CJGLS": "CJ대한통운",
    "대한통운": "CJ대한통운",
    "한진": "한진택배",
    "롯데": "롯데택배",
    "로젠": "로젠택배",
    "우체국": "우체국택배",
    "경동": "경동택배",
    "대신": "대신택배",
}

# 배치 실행 파라미터
# [2026-09-04] 5 → 2. 운영 첫 실행에서 배송조회가 403(호출제한)으로 3건 실패했다.
# 대상이 수십 건 규모라 동시성을 낮춰도 전체 소요는 거의 그대로다.
_CONCURRENCY = 2  # 동시 배송조회 수
_PER_ITEM_TIMEOUT = 10.0  # 건당 타임아웃(초)

# ── 반송장 자동획득 (원송장 → 반송장, 2026-09-03 실측 확정) ──────────

# 원송장 조회로 반송장을 끌어올 수 있는 택배사 (정규화된 정식명 기준).
# 롯데·로젠·딜리박스·우체국은 원송장에 반송장이 노출되지 않음(실측) → 미지원.
RETURN_WAYBILL_SUPPORTED: frozenset[str] = frozenset({"CJ대한통운", "한진택배"})

# CJ대한통운 — POST form(wblNo) + Referer 헤더만으로 조회됨 (쿠키/CSRF 불필요 실측)
_CJ_TRACE_URL = "https://trace.cjlogistics.com/next/rest/selectTrackingWaybil.do"
_CJ_TRACE_REFERER = "https://trace.cjlogistics.com/next/tracking.html"

# 한진택배 — GET + User-Agent 필요. HTML 안 [반품운송장번호 : <a>NNN</a>] 파싱
_HANJIN_TRACE_URL = "https://www.hanjin.com/kor/CMS/DeliveryMgr/WaybillResult.do"
_HANJIN_USER_AGENT = "Mozilla/5.0"
# 기본 패턴 — 실측 마크업:
#   [<strong>반품운송장번호</strong> : <a href="...wblnum=573871357113...">573871357113</a>]
_HANJIN_RETURN_RE = re.compile(
    r"반품운송장번호</strong>\s*:\s*<a[^>]*>\s*(\d{8,})\s*</a>"
)
# 폴백 패턴 — 앵커 마크업이 바뀌어도 링크 파라미터(wblnum=반송장)로 회수 시도
_HANJIN_RETURN_FALLBACK_RE = re.compile(r"wblnum=(\d{8,})")


async def fetch_return_waybill(courier: str, tracking: str) -> Optional[str]:
    """원송장 → 반송장 자동획득 (CJ대한통운/한진택배만, 실측 확정 경로).

    - 미지원 택배사·빈 송장은 HTTP 호출 없이 즉시 None.
    - 반송장 미발행(CJ rtnWblno 빈값 / 한진 패턴 미검출)도 None.
    - 네트워크/파싱 실패는 None + warning (예외 전파 금지).
      ⚠️ 응답 본문(HTML/JSON)은 로그에 절대 찍지 않는다 — 실패 사실만.
    """
    normalized = _normalize_courier(courier)
    if normalized not in RETURN_WAYBILL_SUPPORTED:
        return None
    invoice = re.sub(r"[^0-9A-Za-z]", "", tracking or "")
    if not invoice:
        return None

    import httpx

    try:
        async with httpx.AsyncClient(timeout=_PER_ITEM_TIMEOUT) as hc:
            if normalized == "CJ대한통운":
                resp = await hc.post(
                    _CJ_TRACE_URL,
                    data={"wblNo": invoice},
                    headers={"Referer": _CJ_TRACE_REFERER},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "[반송장조회] CJ 비정상 응답 status=%s tracking=%s",
                        resp.status_code,
                        _mask_tracking(invoice),
                    )
                    return None
                payload = resp.json()
                data = payload.get("data") if isinstance(payload, dict) else None
                if not isinstance(data, dict):
                    # 응답 형태 변경 — 본문은 찍지 않고 실패 사실만 남긴다
                    logger.warning(
                        "[반송장조회] CJ 응답 형태 변경으로 파싱 실패 tracking=%s",
                        _mask_tracking(invoice),
                    )
                    return None
                rtn = str(data.get("rtnWblno") or "").strip()
                return rtn or None  # 빈 문자열 = 반송장 미발행

            # 한진택배
            resp = await hc.get(
                _HANJIN_TRACE_URL,
                params={"mCode": "MN038", "schLang": "KR", "wblnumText2": invoice},
                headers={"User-Agent": _HANJIN_USER_AGENT},
            )
            if resp.status_code != 200:
                logger.warning(
                    "[반송장조회] 한진 비정상 응답 status=%s tracking=%s",
                    resp.status_code,
                    _mask_tracking(invoice),
                )
                return None
            html = resp.text or ""
            m = _HANJIN_RETURN_RE.search(html)
            if m:
                return m.group(1)
            # 폴백 — 마크업 변경 대비. 원송장 자기자신은 제외
            for fm in _HANJIN_RETURN_FALLBACK_RE.finditer(html):
                if fm.group(1) != invoice:
                    return fm.group(1)
            return None  # 반송장 미발행 (또는 페이지에 미노출)
    except Exception as e:  # noqa: BLE001 — 외부 조회 실패는 None 으로 흡수
        # ⚠️ 응답 본문 로그 금지 — 예외 타입/요약만
        logger.warning(
            "[반송장조회] %s 조회 실패 tracking=%s: %s: %s",
            normalized,
            _mask_tracking(invoice),
            type(e).__name__,
            str(e)[:120],
        )
        return None


# ── 순수 헬퍼 (테스트 대상) ────────────────────────────────────────────


def _normalize_key(key: str) -> str:
    """키 비교용 정규화 — 소문자화 + '_'/'-' 제거 (스네이크/카멜/케밥 무시)."""
    return re.sub(r"[_\-\s]", "", str(key)).lower()


def _clean_tracking_value(value: Any) -> Optional[str]:
    """송장번호 후보값 검증 — 숫자 포함 6자 이상 영숫자만 인정."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    cleaned = re.sub(r"[^0-9A-Za-z]", "", text)
    if len(cleaned) < 6 or not any(ch.isdigit() for ch in cleaned):
        return None
    return text


def _clean_courier_value(value: Any) -> Optional[str]:
    """택배사명 후보값 검증 — 1~30자 문자열만 인정."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    if not text or len(text) > 30:
        return None
    return text


def _walk_key_paths(raw: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """raw dict 의 키 경로 목록만 수집 (값은 절대 담지 않는다 — 로그용)."""
    paths: list[str] = []
    if depth > 2:
        return paths
    if isinstance(raw, dict):
        for k, v in raw.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            paths.append(path)
            paths.extend(_walk_key_paths(v, path, depth + 1))
    elif isinstance(raw, list):
        for item in raw[:3]:  # 리스트는 앞 3개만 대표로
            paths.extend(_walk_key_paths(item, f"{prefix}[]", depth + 1))
    return paths


def _extract_collect_tracking(raw: dict) -> tuple[Optional[str], Optional[str]]:
    """마켓 반품 클레임 raw dict 에서 (회수송장, 회수택배사) 를 추출.

    - 후보키 목록(_COLLECT_TRACKING_KEY_CANDIDATES 등)을 대소문자·스네이크/카멜
      무시하고 훑는다. 중첩 dict/list 는 2단계까지 재귀 탐색.
    - 같은 후보키가 여러 곳에 있으면 (후보 우선순위, 얕은 깊이) 순으로 채택.
    - 송장을 못 찾으면 raw 의 키 목록만 logger.info 로 남긴다
      (실측 필드명 확보용 — 값/개인정보는 로그 금지).
    """
    if not isinstance(raw, dict):
        return None, None

    # (우선순위, 깊이, 값) 매치 수집
    tracking_hits: list[tuple[int, int, str]] = []
    courier_hits: list[tuple[int, int, str]] = []

    def _scan(node: Any, depth: int) -> None:
        if depth > 2:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                nk = _normalize_key(k)
                if nk in _COLLECT_TRACKING_KEY_CANDIDATES:
                    cleaned = _clean_tracking_value(v)
                    if cleaned:
                        tracking_hits.append(
                            (_COLLECT_TRACKING_KEY_CANDIDATES.index(nk), depth, cleaned)
                        )
                if nk in _COLLECT_COURIER_KEY_CANDIDATES:
                    cleaned = _clean_courier_value(v)
                    if cleaned:
                        courier_hits.append(
                            (_COLLECT_COURIER_KEY_CANDIDATES.index(nk), depth, cleaned)
                        )
                if isinstance(v, (dict, list)):
                    _scan(v, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _scan(item, depth + 1)

    _scan(raw, 0)

    tracking = min(tracking_hits)[2] if tracking_hits else None
    courier = min(courier_hits)[2] if courier_hits else None

    if tracking is None:
        # ⚠️ 값은 찍지 않는다 — 키 목록만 남겨 실측 필드명 확보 지원
        logger.info(
            "[회수판정] 클레임 raw 에서 회수송장 후보키 미발견 — 키 목록: %s",
            sorted(set(_walk_key_paths(raw))),
        )
    return tracking, courier


def _mask_tracking(tracking: str) -> str:
    """송장 마스킹 — 뒤 4자리만 남기고 가린다 (로그/타임라인용)."""
    text = str(tracking or "")
    if len(text) <= 4:
        return text
    return "*" * (len(text) - 4) + text[-4:]


def judge_collect_status(track: Optional[dict]) -> tuple[str, str]:
    """배송조회 결과 → (회수상태, 최종상태 텍스트) 판정. 순수 함수.

    track 형식 (deliverytracker v1 원본 축약):
      {"state": {"id", "text"}, "progresses": [{"status": {"id","text"}, ...}]}
    track 이 None 이면 404/조회불가로 본다.
    """
    if not track:
        return STATUS_NOT_COLLECTED, "조회결과 없음"

    events = track.get("progresses") or []
    state = track.get("state") or {}
    state_id = str(state.get("id") or "").lower()
    state_text = str(state.get("text") or "")

    if not events:
        return STATUS_NOT_COLLECTED, state_text or "이벤트 없음"

    # 최종 배송완료 판정 — state.id 우선, 텍스트/마지막 이벤트 보조
    last_event = events[-1] if isinstance(events[-1], dict) else {}
    last_status = last_event.get("status") or {}
    last_status_id = str(last_status.get("id") or "").lower()
    delivered = (
        state_id == "delivered"
        or last_status_id == "delivered"
        or "배송완료" in state_text
    )
    final_text = (
        state_text or str(last_status.get("text") or "") or "진행중"
    )
    if delivered:
        return STATUS_COLLECTED, final_text
    return STATUS_COLLECTING, final_text


def _may_transition(current: Optional[str], new: str) -> bool:
    """되돌리기 금지 규칙 — 진행 방향 전이만 허용.

    - current 가 회수상태 어휘가 아니면(예: requested) 최초 판정으로 허용.
    - current == new 는 변경 없음이므로 False.
    - 회수상태끼리는 순위(new > current)일 때만 허용.
    """
    new_rank = _COLLECT_STATUS_RANK.get(new)
    if new_rank is None:
        return False
    cur_rank = _COLLECT_STATUS_RANK.get(current or "")
    if cur_rank is None:
        return True  # 최초 판정
    return new_rank > cur_rank


def _is_final_detail(completion_detail: Optional[str]) -> bool:
    """completion_detail 확정값(취소/반품/교환/거부) 여부 — 확정 행은 스킵."""
    return (completion_detail or "").strip() in _FINAL_COMPLETION_DETAILS


def _normalize_courier(name: Optional[str]) -> Optional[str]:
    """택배사명 정규화 — 별칭을 정식 키로 치환."""
    text = (name or "").strip()
    if not text:
        return None
    return _COURIER_ALIASES.get(text, text)


def _carrier_id_for(courier: Optional[str]) -> Optional[str]:
    """택배사 한국어명 → deliverytracker carrier_id.

    매핑은 order.py 의 SHIPPING_COMPANY_TO_CARRIER_ID 를 재사용한다
    (order.py 는 수정 금지 파일 + 대형 라우터 모듈이라 순환 import 방지 지연 import).
    """
    normalized = _normalize_courier(courier)
    if not normalized:
        return None
    from backend.api.v1.routers.samba.order import SHIPPING_COMPANY_TO_CARRIER_ID

    return SHIPPING_COMPANY_TO_CARRIER_ID.get(normalized)


# ── 외부 조회 ─────────────────────────────────────────────────────────


async def _fetch_track(carrier_id: str, invoice: str) -> Optional[dict]:
    """deliverytracker v1 조회 — 404 는 None, 그 외 오류는 예외.

    order.py::get_tracking 과 동일 API 를 쓰되 order.py 수정 금지라 자체 구현.
    """
    import httpx

    invoice_clean = re.sub(r"[^0-9A-Za-z]", "", invoice or "")
    if not invoice_clean:
        return None

    url = f"https://apis.tracker.delivery/carriers/{carrier_id}/tracks/{invoice_clean}"
    # [2026-09-04] 429/403 재시도 — 운영 첫 실행에서 반송장 7건 중 3건이 403 으로 튕겼다.
    # deliverytracker v1 은 짧은 시간에 몰아치면 호출을 막는다(반송장 자체는 이미 확보한
    # 상태였으므로 조회만 실패). 지수 백오프로 2회까지 다시 시도한다.
    delays = (1.5, 4.0)
    last_status = 0
    async with httpx.AsyncClient(timeout=_PER_ITEM_TIMEOUT) as hc:
        for attempt in range(len(delays) + 1):
            resp = await hc.get(url)
            if resp.status_code == 404:
                return None
            if resp.status_code < 400:
                return resp.json()
            last_status = resp.status_code
            if resp.status_code not in (403, 429, 503) or attempt == len(delays):
                break
            await asyncio.sleep(delays[attempt])
    raise RuntimeError(f"배송조회 비정상 응답 status={last_status}")


async def _load_market_claim_items(
    session: Any, order: Any, cache: dict[str, list[dict]]
) -> list[dict]:
    """주문의 마켓 계정으로 반품 클레임 raw 목록을 조회 (계정 단위 캐시).

    현재는 SSG(listExchangeTarget)만 지원 — 설계상 회수 택배사/송장 필드가
    있을 가능성이 가장 높은 곳. 그 외 마켓은 빈 목록 (추후 확장).
    실패는 조용히 빈 목록 처리 (배치 계속 진행).
    """
    channel_id = getattr(order, "channel_id", None)
    if not channel_id:
        return []
    if channel_id in cache:
        return cache[channel_id]

    items: list[dict] = []
    try:
        from backend.domain.samba.account.repository import (
            SambaMarketAccountRepository,
        )

        account = await SambaMarketAccountRepository(session).get_async(channel_id)
        if account and account.market_type == "ssg":
            extras = account.additional_fields or {}
            api_key = (
                (extras.get("apiKey") if isinstance(extras, dict) else "")
                or account.api_key
                or ""
            )
            if api_key:
                from backend.domain.samba.proxy.ssg import SSGClient

                client = SSGClient(api_key)
                try:
                    items = await client.get_return_requests(days=7)
                finally:
                    try:
                        await client.close()
                    except Exception:  # noqa: BLE001 — 종료 실패는 무시
                        pass
    except Exception as e:  # noqa: BLE001 — 클레임 조회 실패는 배치 중단 사유 아님
        logger.warning("[회수판정] 마켓 클레임 조회 실패 channel=%s: %s", channel_id, e)
        items = []

    cache[channel_id] = items
    return items


def _match_claim_item(items: list[dict], order: Any) -> Optional[dict]:
    """클레임 목록에서 이 주문의 raw 항목 찾기 — 주문번호 일치 기준."""
    candidates = {
        str(getattr(order, "order_number", "") or ""),
        str(getattr(order, "claim_order_number", "") or ""),
    }
    candidates.discard("")
    if not candidates:
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in ("orordNo", "ordNo", "orderNo", "orderId"):
            if str(item.get(key) or "") in candidates:
                return item
    return None


async def _resolve_collect_tracking(
    session: Any, order: Any, claim_cache: dict[str, list[dict]]
) -> dict[str, Any]:
    """반송장 확보 — {"tracking","courier","source","waybill_found","unsupported"}.

    우선순위 (T4-v2 확정):
      1) order.return_collect_tracking (이미 채워진 값 — 재조회 안 함)
      2) fetch_return_waybill — CJ/한진 원송장 조회로 반송장 획득.
         얻으면 order.return_collect_* 에 저장(재조회 절감. commit 은 배치 말미).
      3) 마켓 반품 클레임 raw 에서 추출 (보조)

    tracking 이 None 이면 source 로 사유를 구분:
      "미지원택배사" / "반송장미발행" / "원송장없음"
    """
    # 1) 이미 채워진 회수송장
    stored = getattr(order, "return_collect_tracking", None)
    if stored and str(stored).strip():
        courier = getattr(order, "return_collect_courier", None) or getattr(
            order, "shipping_company", None
        )
        return {
            "tracking": str(stored).strip(),
            "courier": courier,
            "source": "회수송장(저장값)",
            "waybill_found": False,
            "unsupported": False,
        }

    orig_tracking = str(getattr(order, "tracking_number", None) or "").strip()
    orig_courier = _normalize_courier(getattr(order, "shipping_company", None))
    supported = orig_courier in RETURN_WAYBILL_SUPPORTED
    unsupported = bool(orig_tracking) and not supported  # 원송장은 있는데 미지원

    # 2) 원송장 → 반송장 자동획득 (CJ/한진)
    if orig_tracking and supported and orig_courier:
        waybill = await fetch_return_waybill(orig_courier, orig_tracking)
        if waybill:
            # 획득한 반송장은 주문에 저장해 다음 배치의 재조회를 아낀다
            order.return_collect_courier = orig_courier  # 반송장도 동일 택배사(실측)
            order.return_collect_tracking = waybill
            order.return_collect_at = datetime.now(UTC)
            session.add(order)
            return {
                "tracking": waybill,
                "courier": orig_courier,
                "source": "반송장(원송장조회)",
                "waybill_found": True,
                "unsupported": False,
            }

    # 3) 마켓 반품 클레임 원본에서 추출 (보조)
    items = await _load_market_claim_items(session, order, claim_cache)
    raw = _match_claim_item(items, order)
    if raw is not None:
        tracking, courier = _extract_collect_tracking(raw)
        if tracking:
            return {
                "tracking": tracking,
                "courier": courier or getattr(order, "shipping_company", None),
                "source": "회수송장(마켓클레임)",
                "waybill_found": False,
                "unsupported": False,
            }

    # 확보 실패 — 사유별 라벨 (판정표: 전부 not_collected)
    if unsupported:
        source = "미지원택배사"
    elif orig_tracking:
        source = "반송장미발행"
    else:
        source = "원송장없음"
    return {
        "tracking": None,
        "courier": None,
        "source": source,
        "waybill_found": False,
        "unsupported": unsupported,
    }


# ── 배치 본체 ─────────────────────────────────────────────────────────


def _within_cooldown(
    auto_checked_at: Optional[datetime], cutoff: datetime
) -> bool:
    """auto_checked_at 이 쿨다운 컷오프 이후(=최근)인지 판정 (T8 쿨다운).

    naive datetime(레거시/SQLite)은 UTC 로 간주해 비교한다.
    """
    if auto_checked_at is None:
        return False
    checked = auto_checked_at
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=UTC)
    return checked >= cutoff


async def refresh_collect_status(
    session: Any,
    tenant_id: Optional[str] = None,
    return_ids: Optional[list[str]] = None,
    cooldown_minutes: int = 60,
) -> dict:
    """반품/교환 행의 회수상태(not_collected/collecting/collected)를 일괄 자동판정.

    대상 기본값: type in ('return','exchange') AND completion_detail 진행중(또는 NULL).
    return_ids 지정 시 해당 행만 (확정행 스킵 규칙은 동일 적용).
    마감행(closed_at IS NOT NULL — T7)은 어느 경로든 조회 대상에서 제외.

    쿨다운(T8): auto_checked_at 이 cooldown_minutes 이내인 행은 택배사 호출을
    아끼기 위해 스킵한다 (cooldown_minutes=0 이면 쿨다운 없음). 조회한 행은
    상태 변경 여부와 무관하게 auto_checked_at=now 를 기록한다.

    체크날짜 자동기입(T8): 이번 배치가 status 를 '실제로 바꾼' 행만
    check_date 를 오늘(KST 자정)로 세팅한다. 상태가 안 바뀐 행(반송장 여전히
    미발행 / 미지원 택배사 등)은 check_date 를 건드리지 않는다 → 과거 날짜로
    남아 사장님 눈에 띈다 (이게 이 기능의 핵심 목적).

    반환: {"ok": True, "checked": n, "updated": n, "skipped": n,
           "cooldown_skipped": n, "no_tracking": n, "waybill_found": n,
           "unsupported_courier": n, "errors": [...]}
      - cooldown_skipped: 쿨다운(1시간 이내 재조회)으로 스킵한 건수
      - waybill_found: 이번 배치에서 원송장 조회로 반송장을 새로 얻은 건수
      - unsupported_courier: 반송장 조회 미지원 택배사(롯데·로젠 등)라 미확보 건수
    """
    from datetime import timedelta

    from sqlalchemy import or_
    from sqlmodel import select

    from backend.domain.samba.order.model import SambaOrder
    from backend.domain.samba.returns.model import SambaReturn
    from backend.utils import now_kst

    # ── 대상 조회 ──
    stmt = select(SambaReturn).where(SambaReturn.type.in_(("return", "exchange")))
    # 마감행 제외 (T7) — 마감된 건은 자동조회가 다시 건드리지 않는다
    stmt = stmt.where(SambaReturn.closed_at.is_(None))
    if return_ids:
        stmt = stmt.where(SambaReturn.id.in_(return_ids))
    else:
        stmt = stmt.where(
            or_(
                SambaReturn.completion_detail.is_(None),
                SambaReturn.completion_detail == "",
                SambaReturn.completion_detail == "진행중",
            )
        )
    if tenant_id:
        # 테넌트 격리 — NULL 은 레거시 데이터로 허용 (repository.list_filtered 와 동일)
        stmt = stmt.where(
            or_(SambaReturn.tenant_id == tenant_id, SambaReturn.tenant_id.is_(None))
        )
    result = await session.execute(stmt)
    targets: list[Any] = list(result.scalars().all())

    # 연결 주문 일괄 로드
    order_map: dict[str, Any] = {}
    order_ids = {r.order_id for r in targets if r.order_id}
    if order_ids:
        o_result = await session.execute(
            select(SambaOrder).where(SambaOrder.id.in_(order_ids))
        )
        order_map = {o.id: o for o in o_result.scalars().all()}

    checked = 0
    updated = 0
    skipped = 0
    cooldown_skipped = 0  # 쿨다운(최근 조회)으로 스킵한 건수 (T8)
    no_tracking = 0
    waybill_found = 0  # 이번에 원송장 조회로 반송장을 새로 얻은 건수
    unsupported_courier = 0  # 반송장 조회 미지원 택배사 건수
    order_saved = False  # 반송장 저장으로 주문행 변경 여부 (commit 판단용)
    errors: list[dict] = []

    claim_cache: dict[str, list[dict]] = {}

    now_utc = datetime.now(UTC)
    # 쿨다운 컷오프 — auto_checked_at 이 이 시각 이후면 스킵 (0이면 쿨다운 없음)
    cooldown_cutoff: Optional[datetime] = (
        now_utc - timedelta(minutes=cooldown_minutes) if cooldown_minutes > 0 else None
    )

    # 확정행/이미 수거완료/마감행/쿨다운 행은 조회 자체를 생략
    probe_targets: list[Any] = []
    for ret in targets:
        checked += 1
        if getattr(ret, "closed_at", None) is not None:
            # 마감행 (T7) — SQL 에서 이미 제외되지만 방어적으로 한 번 더 스킵
            skipped += 1
            continue
        if _is_final_detail(ret.completion_detail):
            skipped += 1
            continue
        if ret.status == STATUS_COLLECTED:
            skipped += 1
            continue
        if cooldown_cutoff is not None and _within_cooldown(
            getattr(ret, "auto_checked_at", None), cooldown_cutoff
        ):
            # 쿨다운 (T8) — 최근 1시간 내 이미 조회한 행은 택배사 호출 절감
            cooldown_skipped += 1
            continue
        # 조회 대상 확정 — 상태 변경 여부와 무관하게 '마지막으로 본 시각' 기록
        # (다음 배치의 쿨다운 기준. commit 은 배치 말미에 일괄)
        ret.auto_checked_at = now_utc
        session.add(ret)
        probe_targets.append(ret)

    # ── 1단계: 반송장 확보 (순차 — AsyncSession 은 동시 사용 금지.
    #    클레임 조회는 계정 단위 캐시라 반복 호출 부하 없음) ──
    resolved: list[dict] = []
    for ret in probe_targets:
        order = order_map.get(ret.order_id)
        if order is None:
            resolved.append({"ret": ret, "outcome": "error", "error": "연결 주문 없음"})
            continue
        try:
            found = await _resolve_collect_tracking(session, order, claim_cache)
        except Exception as e:  # noqa: BLE001 — 개별 실패는 배치를 죽이지 않는다
            resolved.append(
                {"ret": ret, "outcome": "error", "error": str(e)[:200]}
            )
            continue
        if found["waybill_found"]:
            waybill_found += 1
            order_saved = True
        tracking = found["tracking"]
        if not tracking:
            if found["unsupported"]:
                unsupported_courier += 1
            resolved.append(
                {"ret": ret, "outcome": "no_tracking", "source": found["source"]}
            )
            continue
        courier = found["courier"]
        carrier_id = _carrier_id_for(courier)
        if not carrier_id:
            resolved.append(
                {
                    "ret": ret,
                    "outcome": "error",
                    "error": f"배송조회 미지원 택배사: {courier or '미상'}",
                }
            )
            continue
        resolved.append(
            {
                "ret": ret,
                "outcome": "pending_track",
                "tracking": tracking,
                "courier": _normalize_courier(courier),
                "carrier_id": carrier_id,
                "source": found["source"],
            }
        )

    # ── 2단계: 배송조회 (외부 HTTP 만 동시 — Semaphore 5, 건당 10초) ──
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def _probe(item: dict) -> dict:
        """배송조회 + 판정만 수행. DB 는 건드리지 않는다."""
        try:
            async with sem:
                track = await asyncio.wait_for(
                    _fetch_track(item["carrier_id"], item["tracking"]),
                    timeout=_PER_ITEM_TIMEOUT,
                )
            status, final_text = judge_collect_status(track)
            return {**item, "outcome": "judged", "status": status, "final_text": final_text}
        except (TimeoutError, asyncio.TimeoutError):
            return {**item, "outcome": "error", "error": "배송조회 타임아웃"}
        except Exception as e:  # noqa: BLE001 — 개별 실패는 배치를 죽이지 않는다
            return {**item, "outcome": "error", "error": str(e)[:200]}

    probe_results: list[dict] = []
    pending = [item for item in resolved if item["outcome"] == "pending_track"]
    probe_results.extend(item for item in resolved if item["outcome"] != "pending_track")
    if pending:
        probe_results.extend(await asyncio.gather(*(_probe(i) for i in pending)))

    # ── 3단계: 판정 반영 (순차 DB 쓰기) ──
    now = datetime.now(UTC)
    for pr in probe_results:
        ret = pr["ret"]
        outcome = pr["outcome"]

        if outcome == "error":
            errors.append({"return_id": ret.id, "error": pr["error"]})
            continue

        if outcome == "no_tracking":
            no_tracking += 1
            new_status = STATUS_NOT_COLLECTED
            # 사유(미지원택배사/반송장미발행/원송장없음)를 타임라인에 남긴다
            message = f"회수 자동판정 — {pr.get('source') or '반송장미확인'} → 미수거"
        else:
            new_status = pr["status"]
            message = (
                f"회수 자동판정 — {pr['courier'] or '택배사미상'} "
                f"{_mask_tracking(pr['tracking'])} ({pr['source']}) "
                f"/ 최종 '{pr['final_text']}' → {_STATUS_LABEL[new_status]}"
            )

        # 되돌리기 금지 — 진행 방향 전이만 반영
        if not _may_transition(ret.status, new_status):
            skipped += 1
            continue

        ret.status = new_status
        # [T8] 체크날짜 자동기입 — 상태를 '실제로 바꾼' 행만 오늘(KST 자정)로.
        # 상태가 안 바뀐 행은 위 _may_transition 가드에서 걸러져 여기 안 온다 →
        # check_date 가 과거 날짜로 남아 '아직 봐야 하는 건'으로 눈에 띈다.
        ret.check_date = now_kst().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        ret.timeline = [
            *(ret.timeline or []),
            {"date": now.isoformat(), "status": new_status, "message": message},
        ]
        ret.updated_at = now
        session.add(ret)
        updated += 1

    if updated or order_saved or probe_targets:
        # 반송장을 새로 얻어 주문행에 저장한 경우와, 상태 변경이 없어도
        # auto_checked_at(조회 시각) 을 기록한 경우 모두 반영해야 한다
        await session.commit()

    summary = {
        "ok": True,
        "checked": checked,
        "updated": updated,
        "skipped": skipped,
        "cooldown_skipped": cooldown_skipped,
        "no_tracking": no_tracking,
        "waybill_found": waybill_found,
        "unsupported_courier": unsupported_courier,
        "errors": errors,
    }
    logger.info("[회수판정] 배치 완료: %s", {**summary, "errors": len(errors)})
    return summary
