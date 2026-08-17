"""브랜드 판매 제한 — 소명 요청 / 지재권 / 절대금지 브랜드 관리.

쿠팡을 비롯한 마켓은 특정 브랜드를 "유통경로 소명" 없이 팔면 판매정지를 건다.
소명 대상은 마켓이 수시로 추가하므로 **한 번 만들고 끝나는 목록이 아니다** —
새로 확인될 때마다 이 테이블에 쌓고, 왜 그렇게 판단했는지(source)를 남긴다.

판정 근거는 두 갈래이며 둘 다 이 한 테이블에 모인다:
  1) 사람이 관리하는 목록 — 쇼팡 제공 엑셀, 마켓 공지, 본사 메일 등 (source='excel'/'manual')
  2) 쿠팡 브랜드 API 자동 판별 — brands/search 의 isUIDRequired (source='coupang_api')

관련: backend/scripts/import_brand_restrictions.py (엑셀 적재),
      backend/domain/samba/plugins/markets/coupang.py (업로드 가드)
"""

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Boolean, String
from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text
from ulid import ULID


def generate_brand_restriction_id() -> str:
    return f"br_{ULID()}"


# ── 판정값 ────────────────────────────────────────────────────────────
# 업로드 가드가 실제로 보는 것은 verdict 하나다. soomyeong/ipr 은 근거 기록용.
VERDICT_BLOCKED = "blocked"  # 판매 불가 — 소명 필요 / 지재권 / 절대금지
VERDICT_ALLOWED = "allowed"  # 자유 판매 확인됨
VERDICT_UNKNOWN = "unknown"  # 미확인 — 정책상 차단 취급(안전 우선)


class SambaBrandRestriction(SQLModel, table=True):
    """브랜드별 판매 제한 상태."""

    __tablename__ = "samba_brand_restriction"

    id: str = Field(
        default_factory=generate_brand_restriction_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 원본 표기 (사람이 읽는 용도). 엑셀/마켓 공지에 적힌 그대로.
    brand: str = Field(sa_column=Column(Text, nullable=False))

    # 매칭 키 — normalize_brand() 결과. 조회는 항상 이 컬럼으로 한다.
    # 부분일치는 엉뚱한 브랜드를 잡으므로(해칭룸→해피룸, 모이에토이파리스→아미파리스)
    # 정확일치 전용이다.
    brand_key: str = Field(sa_column=Column(Text, nullable=False, index=True))

    # blocked | allowed | unknown
    verdict: str = Field(sa_column=Column(Text, nullable=False, index=True))

    # ── 판정 근거 ──
    # 소명 | 비소명 | None(미기재)
    soomyeong: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # 지재권 | 절대금지 | None
    ipr: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
    # 이 브랜드를 금지어로 잡은 마켓들 (예: ["쿠팡", "스스"])
    markets: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    # 비고 — "본사 거래계약서 필요", "고발장접수", "마크비전" 등 대응 이력
    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # ── 쿠팡 API 자동 판별 캐시 ──
    # brands/search 응답의 isUIDRequired. True = 정품코드(소명) 필요.
    # None = 아직 조회 안 함. 조회에 비용이 들므로 캐시하고 재사용한다.
    coupang_uid_required: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    # 쿠팡 브랜드 라이브러리에 정확일치 항목이 있었는지.
    # False = 라이브러리에 없음 → 판단 불가 → unknown
    coupang_matched: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )
    coupang_checked_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # ── 신규 Brand Risk System 축 (Phase 1: 스키마만 추가, 판정 로직 미연결) ──
    # 전부 nullable. 값이 비어 있으면 "아직 이 축을 평가 안 함"이며 기존
    # verdict/soomyeong/ipr 판정과 BrandGuardService.check() 동작에는 영향이
    # 없다 — check()는 여전히 verdict만 읽는다(brand/service.py 미변경).
    #
    # ip_risk_level 과 coupang_pre_auth 는 서로 완전히 독립된 축이다.
    # 실측 근거(2026-08 데이터 감사): 브룩스는 coupang_api 판정상
    # coupang_uid_required=true(=사전소명 필요) 이면서 지재권 신고 이력은
    # 없는 상태 — 즉 ip_risk_level=NO_RISK_FOUND, coupang_pre_auth=REQUIRED
    # 조합이 실제로 존재한다. 단일 verdict 축으로는 이 조합을 표현 못 했다.

    # BLOCK_STRONG | BLOCK | CAUTION | NO_RISK_FOUND | REVIEW_REQUIRED | UNKNOWN
    # (brand/risk_constants.IP_RISK_LEVELS)
    ip_risk_level: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True, index=True)
    )

    # REQUIRED | NOT_REQUIRED | UNKNOWN (brand/risk_constants.COUPANG_PRE_AUTH_STATES)
    # 쿠팡이 유통경로 소명(재고증빙)을 요구하는지 여부 — ip_risk_level 과 무관.
    coupang_pre_auth: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # Marq Vision 관리목록 포함 여부. None=미확인, True/False=확인됨.
    # 기존 coupang_uid_required/coupang_matched 와 동일하게 nullable Boolean
    # 삼중상태(None=UNKNOWN) 컨벤션을 그대로 따른다.
    marq_vision: Optional[bool] = Field(
        default=None, sa_column=Column(Boolean, nullable=True)
    )

    # 마켓별 IP Risk 개별 판정 — {market_id: ip_risk_level}.
    # market_id 는 SambaForbiddenWord.market 과 동일 문자열 컨벤션
    # ('coupang'/'smartstore'/'elevenst'/'lotteon' 등, markets.ts 기준).
    # 예: {"coupang": "BLOCK", "lotteon": "BLOCK", "smartstore": "UNKNOWN"}
    # 마켓마다 다른 등급을 가지는 실제 사례(CASE_DB 다수)가 있어 단일
    # 스칼라 컬럼으로는 표현이 안 된다. 기존 markets(JSON 리스트, "이
    # 브랜드를 잡은 마켓 이름 나열용") 필드와는 목적이 다르므로 별도 컬럼.
    marketplace_risk: Optional[dict] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    # 이미지 위험 요약 — 자유텍스트. 구조화된 이미지 상태값
    # (ORIGINAL/CUTOUT/CROPPED/AI_TRANSFORMED/DIRECT_PHOTO/UNKNOWN)은 브랜드
    # 전체가 아니라 사건(case) 단위 속성이라 samba_brand_risk_case.image_state
    # 에 둔다. 한 브랜드 안에서도 사건마다 원본/누끼/AI변환이 섞이므로
    # 브랜드 레벨에서 단일 값으로 강제하면 정보가 손실된다.
    image_risk_note: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # A | B | C | D | UNKNOWN (brand/risk_constants.CONFIDENCE_LEVELS)
    # 근거 신뢰도 종합 요약. 개별 사건 신뢰도는 samba_brand_risk_case.confidence
    # 에 있고, 이 컬럼은 브랜드 단위로 사람이 매긴 요약값이다.
    confidence: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # evidence_count 컬럼은 의도적으로 만들지 않는다 — 사건 수는 항상
    # samba_brand_risk_case 를 실시간 COUNT 해서 구한다. 수동 정수 컬럼은
    # 반드시 실제 사건 수와 어긋나는 시점이 생긴다(soul.md 추측 금지 원칙).
    # risk_repository.SambaBrandRiskCaseRepository.count_by_normalized_brand() 참고.

    # excel | coupang_api | manual — 이 행이 어디서 왔는지
    source: str = Field(
        default="manual", sa_column=Column(Text, nullable=False, index=True)
    )
    # 자유 메모 (엑셀 원본 행 번호, 공지 URL 등 추적용)
    source_detail: Optional[Any] = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


def normalize_brand(name: str) -> str:
    """브랜드명 매칭 키 생성.

    정확일치 판정에 쓰므로 **과하게 정규화하지 않는다**. 공백/기호를 지나치게
    지우면 서로 다른 브랜드가 같은 키로 뭉쳐 오차단이 난다.
    적용 범위: 앞뒤 공백 → 제거, 내부 공백 → 제거, 대소문자 → 소문자,
    소싱처가 붙이는 유통 접미사("(백화점)", "[행사]" 등) → 제거.
    """
    import re

    if not name:
        return ""
    s = str(name).strip()
    # 소싱처가 붙이는 괄호 수식어 제거 — 브랜드 정체성과 무관
    s = re.sub(
        r"[\(\[【]\s*(백화점|행사|프리미엄|정품|공식|본사|직영)\s*[\)\]】]", "", s
    )
    s = re.sub(r"\s+", "", s)
    return s.lower()
