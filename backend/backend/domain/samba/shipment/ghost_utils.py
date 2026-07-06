"""스마트스토어 유령(역고아) 판정 순수 로직.

cleanup-orphans 엔드포인트(shipment.py)에서 분리 — 네트워크/DB 없이
판정 규칙만 담아 유닛테스트 가능하게 한다.

용어:
- 역고아(stale): DB엔 계정 매핑이 있는데 Naver에 해당 상품이 없는 것 → 매핑 해제 대상
- 재연결(relink): DB 매핑의 originNo는 Naver에 없지만, 같은 품번
  (sellerManagementCode=style_code)의 상품이 Naver에 살아있는 것.
  기존엔 "재등록 보호"로 무조건 스킵해 유령표시가 영구 방치됐다 →
  살아있는 상품의 새 originNo/channelNo로 매핑을 갱신한다.

재연결 안전 가드 (실마켓 매핑을 바꾸는 작업이므로 보수적으로):
- 같은 품번의 죽은 매핑이 2개 이상이면 어느 쪽이 진짜인지 알 수 없음 → 보류(ambiguous)
- 재연결 대상 Naver 상품을 다른 DB 상품이 이미 매핑 중이면(주인 있음) →
  이 매핑은 남은 찌꺼기 → 역고아로 처리 (이중 매핑 = #534 identity 충돌 방지)
"""

from typing import Any


def judge_smartstore_stale(
    db_origin_map: dict[str, dict[str, Any]],
    naver_nos: set[str],
    naver_mgmt_map: dict[str, dict[str, str]],
    pages_incomplete: bool,
    claimed_nos: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """DB→Naver 역고아/재연결 판정.

    Args:
      db_origin_map: DB 매핑 originNo → 상품 info(db_id/style_code/...)
      naver_nos: Naver에 실존하는 originProductNo/channelProductNo 전체 집합
      naver_mgmt_map: sellerManagementCode → {"origin_no": ..., "channel_no": ...}
      pages_incomplete: Naver 페이징 수집에 누락 페이지가 있으면 True.
        못 본 페이지의 상품은 "Naver에 없음"으로 오판되므로
        역고아/재연결 판정을 전부 보류한다(정상 매핑 해제 사고 방지).
      claimed_nos: 이 계정으로 DB에 매핑된 모든 상품번호 집합(전체 카탈로그 기준,
        origin/channel 포함). 재연결 대상이 이미 다른 상품의 매핑이면 재연결 금지.

    Returns:
      (stale_db, relinks, ambiguous).
      relinks 항목엔 new_origin_no/new_channel_no 포함.
      ambiguous = 같은 품번의 죽은 매핑이 복수라 재연결을 보류한 항목(무조치, 보고용).
    """
    if pages_incomplete:
        return [], [], []

    claimed = claimed_nos or set()

    # 죽은 매핑들의 품번 중복 카운트 — 같은 품번 2개 이상이면 재연결 모호
    dead_style_counts: dict[str, int] = {}
    for origin_no, info in db_origin_map.items():
        if origin_no in naver_nos:
            continue
        style = str(info.get("style_code", "") or "")
        if style:
            dead_style_counts[style] = dead_style_counts.get(style, 0) + 1

    stale_db: list[dict[str, Any]] = []
    relinks: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    for origin_no, info in db_origin_map.items():
        if origin_no in naver_nos:
            continue
        style = str(info.get("style_code", "") or "")
        live = naver_mgmt_map.get(style) if style else None
        live_origin = str(live.get("origin_no", "") or "") if live else ""
        if live_origin:
            live_channel = str(live.get("channel_no", "") or "")
            # 살아있는 상품을 다른 DB 상품이 이미 매핑 중(주인 있음) →
            # 이 죽은 매핑은 찌꺼기 = 역고아. (자기 자신의 매핑번호는 죽은
            # 번호이므로 live 번호와 겹칠 수 없음 → claimed 판정에 안전)
            if live_origin in claimed or (live_channel and live_channel in claimed):
                stale_db.append(info)
                continue
            # 같은 품번의 죽은 매핑이 복수 → 어느 상품을 연결할지 모호 → 보류
            if dead_style_counts.get(style, 0) > 1:
                ambiguous.append(info)
                continue
            relinks.append(
                {
                    **info,
                    "new_origin_no": live_origin,
                    "new_channel_no": live_channel,
                }
            )
            continue
        stale_db.append(info)
    return stale_db, relinks, ambiguous
