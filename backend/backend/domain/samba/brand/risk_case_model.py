"""브랜드 리스크 사건(case) DB — RISK_CASE_DATABASE.md 신규 사건 스키마 그대로.

samba_brand_restriction(브랜드별 최종 판정)과는 별개 테이블이다. 사건은
"왜 그렇게 판단했는지"의 근거 기록이고, 판정은 사건들을 종합한 결론이다 —
섞으면 나중에 "이 판정이 어느 사건 때문이었는지" 되짚을 수 없다.

append-only 로 운영한다. samba_brand_restriction 에 FK 를 걸지 않는다 —
MASTER.md 의 브랜드 대부분이 아직 samba_brand_restriction 에 없으므로(2026-08
데이터 감사 확인), FK 를 걸면 브랜드 판정 행이 없다는 이유로 사건 적재 자체가
막힌다. 연결은 normalized_brand 텍스트 매칭으로만 한다(느슨한 결합).
"""

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import String
from sqlmodel import Column, Date, DateTime, Field, SQLModel, Text
from ulid import ULID


def generate_risk_case_id() -> str:
    return f"rc_{ULID()}"


class SambaBrandRiskCase(SQLModel, table=True):
    """브랜드 리스크 개별 사건 — 신고/연락/판매중지/계정정지 등 실제 경험 1건."""

    __tablename__ = "samba_brand_risk_case"

    case_id: str = Field(
        default_factory=generate_risk_case_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 원본 표기 (사람이 읽는 용도)
    brand: str = Field(sa_column=Column(Text, nullable=False))

    # 매칭 키 — brand.model.normalize_brand() 결과. 조회는 이 컬럼으로 한다.
    # samba_brand_restriction.brand_key 와 같은 정규화 함수를 그대로 재사용
    # 한다(중복 구현 금지) — brand/model.py 의 normalize_brand 는 이 Phase에서
    # 수정하지 않으므로 기존 BrandGuardService 동작에 영향이 없다.
    normalized_brand: str = Field(sa_column=Column(Text, nullable=False, index=True))

    # 마켓 표기 원문 그대로 저장(예: "쿠팡", "롯데ON"). 표준화는 이후 과제.
    marketplace: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 신고 유형 (지재권/저작권/상표권/가품의심 등, 자유텍스트)
    report_type: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 권리자 또는 대행사 (예: "데상트코리아", "법무법인 산음", "Marq Vision")
    rights_holder_or_agent: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 접촉 경로 (메일/문자/전화/플랫폼 알림 등)
    contact_channel: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 제보자/경험자 (예: "강지안 공유", "판매자 직접")
    reporter: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # DIRECT | RELAY | RUMOR (brand/risk_constants.EXPERIENCE_TYPES)
    experience_type: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # ORIGINAL | CUTOUT | CROPPED | AI_TRANSFORMED | DIRECT_PHOTO | UNKNOWN
    # (brand/risk_constants.IMAGE_STATES) — 이 사건에서 실제 쓰인 이미지 상태.
    image_state: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 결과 (예: "판매중지", "계정정지→해제", "메일 수신만")
    result: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 계정 영향 (예: "계정정지 연결", "영향 없음")
    account_impact: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # A | B | C | D | UNKNOWN (brand/risk_constants.CONFIDENCE_LEVELS)
    confidence: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 출처 (예: "RISK_CASE_DATABASE.md", "카카오톡 공유", "직접 확인")
    source: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    # 원문 요약 — 사건 설명 그대로
    raw_summary: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # 사건 발생일. 문서상 "미상"인 사건이 많아 nullable — 모르면 비워둔다
    # (추측으로 채우지 않는다).
    incident_date: Optional[date] = Field(
        default=None, sa_column=Column(Date, nullable=True, index=True)
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
