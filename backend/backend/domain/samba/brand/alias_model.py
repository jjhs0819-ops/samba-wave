"""브랜드 표기변형(alias) → canonical 브랜드 매핑.

기존 brand/model.py 의 normalize_brand() 는 공백/대소문자/유통 접미사만
정규화하고 특수문자(아포스트로피 변형 등)는 그대로 둔다 — 이는 의도된
설계다(brand/model.py 의 docstring: "과하게 정규화하지 않는다. 부분일치는
엉뚱한 브랜드를 잡는다"). BrandGuardService 가 그 함수를 그대로 쓰고 있으므로
이번 Phase에서 그 함수를 바꾸면 기존 쿠팡 업로드 판정 동작이 바뀐다 — 하지
않는다.

대신 신규 Brand Risk System 전용으로 별도의(더 공격적인) 정규화 함수를 둔다.
예: ARC`TERYX(백틱) / ARC'TERYX(아포스트로피) / ARC’TERYX(컬리쿼트) /
ARC TERYX(공백) 를 전부 같은 alias_key 로 묶는다. 반대로 PUMA vs
PUMA BODYWEAR, SNOW PEAK vs SNOW PEAK APPAREL, NEW BALANCE vs
NEW BALANCE KIDS 처럼 실제 단어(BODYWEAR/APPAREL/KIDS)가 다른 경우는 문자
치환만으로는 절대 합쳐지지 않는다 — 이 함수는 특수문자만 지우지 실제 단어는
안 건드리기 때문에 두 요구사항이 동시에 만족된다.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String
from sqlmodel import Column, DateTime, Field, SQLModel, Text
from ulid import ULID

from backend.domain.samba.brand.model import normalize_brand

# 아포스트로피류 변형 문자 — 전부 빈 문자열로 치환한다(단어를 쪼개지 않고
# 그냥 삭제). 백틱(`)은 진짜 아포스트로피가 아니지만 ARC`TERYX 실사례(2026-08
# 데이터 감사에서 확인된 오타)때문에 포함한다.
_APOSTROPHE_CHARS = "'’‘`´ʻʼ"
_APOSTROPHE_TRANSLATE = str.maketrans("", "", _APOSTROPHE_CHARS)


def generate_brand_alias_id() -> str:
    return f"ba_{ULID()}"


def normalize_alias_key(name: str) -> str:
    """Brand Risk System 전용 정규화 — normalize_brand() 보다 한 단계 더 공격적.

    normalize_brand() 결과에 아포스트로피류 문자 제거를 추가로 적용한다.
    단어 자체(BODYWEAR/APPAREL/KIDS 등)는 건드리지 않으므로 상품군이 다른
    브랜드는 여전히 다른 키로 남는다.
    """
    base = normalize_brand(name)
    if not base:
        return ""
    return base.translate(_APOSTROPHE_TRANSLATE)


class SambaBrandAlias(SQLModel, table=True):
    """브랜드 표기변형 → canonical 브랜드 키 매핑 1건."""

    __tablename__ = "samba_brand_alias"

    id: str = Field(
        default_factory=generate_brand_alias_id,
        primary_key=True,
        max_length=30,
    )
    tenant_id: Optional[str] = Field(
        default=None, sa_column=Column(String, index=True, nullable=True)
    )

    # 이 alias 가 가리키는 "진짜" 브랜드의 키. normalize_alias_key(canonical
    # 브랜드명) 과 같은 값을 쓰는 것을 권장하지만 강제하지 않는다 — 운영자가
    # 임의의 대표 키를 골라도 조회 로직(risk_repository.resolve_canonical_key)
    # 은 그대로 동작한다.
    canonical_key: str = Field(sa_column=Column(Text, nullable=False, index=True))

    # 원본 표기 그대로 (예: "ARC`TERYX")
    alias_raw: str = Field(sa_column=Column(Text, nullable=False))

    # normalize_alias_key(alias_raw) — 조회는 항상 이 컬럼으로 한다
    alias_key: str = Field(sa_column=Column(Text, nullable=False, index=True))

    note: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
