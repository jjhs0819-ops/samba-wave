"""Legacy(SambaForbiddenWord) vs 신규 Brand Risk System 충돌 감지 — READ ONLY.

이 모듈은 어떤 전송/등록 경로에도 연결돼 있지 않다(Phase 1 범위 밖).
samba_forbidden_word 를 수정/삭제하지 않는다 — 조회만 한다.

배경(2026-08 데이터 감사 실측): SambaForbiddenWord 에 ARC`TERYX 가 전체마켓
(market=NULL) 활성 금지어로 등록돼 있었다. 그런데 BRAND_RISK_MASTER.md 에서
아크테릭스는 지재권 위험 목록에 없고 "쿠팡 사전소명 후보"로만 언급된다 —
사전소명 필요와 지재권 위험을 혼동해 전체마켓을 차단한 것으로 의심되는
사례다. 등록 경위는 UNKNOWN_REASON(등록주체/source 컬럼이 애초에 없어 추적
불가)으로 결론났다.

이 함수는 그런 패턴을 "레거시가 전체마켓 차단 중인데, 신규 축은 지재권
위험이 아니라 사전소명 문제라고 말하고 있다"는 조건으로 탐지한다. 지금은
신규 축 데이터가 비어 있으므로(Phase 2 전) 항상 None 을 반환하는 게 정상이다
— Phase 2 에서 MASTER 데이터가 적재되면 실제로 걸리는 사례가 나온다.
"""

from dataclasses import dataclass
from typing import Optional

from sqlmodel import select

from backend.domain.samba.brand.model import SambaBrandRestriction, normalize_brand
from backend.domain.samba.brand.risk_constants import (
    COUPANG_PRE_AUTH_REQUIRED,
    IP_RISK_NO_RISK_FOUND,
)
from backend.domain.samba.forbidden.model import SambaForbiddenWord


@dataclass
class LegacyConflict:
    brand: str
    normalized_brand: str
    forbidden_word: str
    forbidden_word_market: Optional[str]  # None = 전체마켓(공통)
    ip_risk_level: Optional[str]
    coupang_pre_auth: Optional[str]
    reason: str


async def check_legacy_conflict(
    session, brand: str, tenant_id: Optional[str] = None
) -> Optional[LegacyConflict]:
    """레거시 전체마켓 금지어와 신규 IP위험 축이 어긋나는지 점검.

    충돌로 판단하는 조건(둘 다 명시적으로 성립해야 함 — UNKNOWN/None 은
    "아직 모름"이지 "안전하다고 확인됨"이 아니므로 충돌로 치지 않는다):
      1) samba_forbidden_word 에 이 브랜드와 정확 일치하는 전체마켓
         (market IS NULL) 활성 금지어가 있고
      2) samba_brand_restriction.ip_risk_level == NO_RISK_FOUND (명시적으로
         "지재권 위험 없음"으로 확인됨) 이면서
      3) samba_brand_restriction.coupang_pre_auth == REQUIRED (사전소명은
         필요하다고 확인됨)

    즉 "지재권 위험은 낮은데 전체마켓을 막아 놓은" 패턴만 잡는다. 데이터가
    아직 없으면(Phase 2 전) 조건 2/3 이 성립할 수 없으므로 항상 None.
    """
    key = normalize_brand(brand)
    if not key:
        return None

    fw_stmt = select(SambaForbiddenWord).where(
        SambaForbiddenWord.type == "forbidden",
        SambaForbiddenWord.is_active == True,  # noqa: E712
        SambaForbiddenWord.market.is_(None),
    )
    fw_rows = (await session.execute(fw_stmt)).scalars().all()
    fw_match = next((r for r in fw_rows if normalize_brand(r.word) == key), None)
    if fw_match is None:
        return None  # 레거시에 전체마켓 차단이 없으면 비교 대상 자체가 없음

    br_stmt = select(SambaBrandRestriction).where(
        SambaBrandRestriction.brand_key == key
    )
    if tenant_id is not None:
        br_stmt = br_stmt.where(
            (SambaBrandRestriction.tenant_id == tenant_id)
            | (SambaBrandRestriction.tenant_id.is_(None))
        )
    else:
        br_stmt = br_stmt.where(SambaBrandRestriction.tenant_id.is_(None))
    br = (await session.execute(br_stmt)).scalars().first()

    ip_risk = br.ip_risk_level if br else None
    pre_auth = br.coupang_pre_auth if br else None

    if ip_risk != IP_RISK_NO_RISK_FOUND or pre_auth != COUPANG_PRE_AUTH_REQUIRED:
        return None

    return LegacyConflict(
        brand=fw_match.word,
        normalized_brand=key,
        forbidden_word=fw_match.word,
        forbidden_word_market=fw_match.market,
        ip_risk_level=ip_risk,
        coupang_pre_auth=pre_auth,
        reason=(
            "레거시 forbidden_word가 전체마켓 완전차단 중인데 신규 IP위험 축은 "
            "지재권 위험 없음(NO_RISK_FOUND)이고 사전소명(REQUIRED)만 확인됨 — "
            "ARC`TERYX 실사례와 동일 패턴"
        ),
    )
