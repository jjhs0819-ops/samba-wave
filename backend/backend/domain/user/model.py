"""
User domain SQLModel models.

Table Structure:
- User: Core user authentication and basic info (soft delete)
- UserProfile: Extended profile details (1:1)
- UserLifestyle: Lifestyle preferences (1:1)
- UserPreference: Matching preferences (1:1)
- UserDocument: Identity documents (1:N, soft delete)
- UserPhoto: Profile photos (1:N, soft delete)
- UserSubscription: Membership info (1:1)
- UserAccessAudit: Access audit log

NOTE: No FK constraints - referential integrity managed at application level.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Column, DateTime, Field, JSON, SQLModel, Text
from sqlalchemy import Boolean

from ulid import ULID

from backend.domain.user.enums import (
    AuthTypeEnum,
    CarOwnershipEnum,
    DinkPreferenceEnum,
    DivorceStatusEnum,
    DocumentTypeEnum,
    DocumentVerificationStatusEnum,
    EducationEnum,
    GenderEnum,
    LongDistanceEnum,
    PhotoTypeEnum,
    ReligionEnum,
    SalaryRangeEnum,
    SmokingEnum,
    TattooEnum,
    UserStatusEnum,
)


def generate_user_id() -> str:
    """Generate user ID with prefix."""
    return f"usr_{ULID()}"


def generate_doc_id() -> str:
    """Generate document ID with prefix."""
    return f"doc_{ULID()}"


def generate_photo_id() -> str:
    """Generate photo ID with prefix."""
    return f"pho_{ULID()}"


def generate_sub_id() -> str:
    """Generate subscription ID with prefix."""
    return f"sub_{ULID()}"


def generate_audit_id() -> str:
    """Generate audit ID with prefix."""
    return f"aud_{ULID()}"


class User(SQLModel, table=True):
    """
    Core user table with authentication and basic identification.

    - Supports soft delete via deleted_at
    - Stores firebase_id for migration reference
    - Phone is unique identifier (normalized without hyphens)
    """
    __tablename__ = "user"

    id: str = Field(
        default_factory=generate_user_id,
        primary_key=True,
        max_length=30,
    )

    # Firebase migration reference
    firebase_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True, index=True),
    )

    # Authentication
    auth_type: AuthTypeEnum = Field(
        default=AuthTypeEnum.PHONE,
        sa_column=Column(Text, nullable=False),
    )
    auth_provider_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Email for account linking (Firebase social auth)
    email: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True, index=True),
    )

    # Basic identification
    # NOTE: phone, name, gender are nullable for social login users (Kakao, etc.)
    # Social login users can complete their profile later
    phone: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True, unique=True, index=True),
    )
    name: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    gender: Optional[GenderEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    birth_year: Optional[int] = Field(
        default=None,
        nullable=True,
    )

    # Status
    status: UserStatusEnum = Field(
        default=UserStatusEnum.DRAFT,
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Admin flag
    is_admin: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default="false", index=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )


class UserProfile(SQLModel, table=True):
    """
    Extended user profile information (1:1 with User).

    Contains job, education, location, and self-description fields.
    """
    __tablename__ = "user_profile"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Education
    education: Optional[EducationEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    university: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Job
    job: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    job_detail: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    salary_range: Optional[SalaryRangeEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Location
    district: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Physical
    height: Optional[int] = Field(
        default=None,
        nullable=True,
    )

    # Self description
    mbti: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    about_me: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    profile_appeal: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    likes_dislikes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    sufficient_condition: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    necessary_condition: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class UserLifestyle(SQLModel, table=True):
    """
    User lifestyle preferences and status (1:1 with User).

    Contains smoking, religion, tattoo, relationship history, etc.
    """
    __tablename__ = "user_lifestyle"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Lifestyle attributes
    smoking: Optional[SmokingEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    religion: Optional[ReligionEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    tattoo: Optional[TattooEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    car_ownership: Optional[CarOwnershipEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    dink_preference: Optional[DinkPreferenceEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    divorce_status: Optional[DivorceStatusEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    long_distance: Optional[LongDistanceEnum] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Relationship history
    relationship_count: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    last_relationship: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    marriage_timing: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class UserPreference(SQLModel, table=True):
    """
    User matching preferences (1:1 with User).

    Contains preferred partner characteristics.
    """
    __tablename__ = "user_preference"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Height preferences
    preferred_height_min: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    preferred_height_max: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    preferred_height_label: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Age preferences
    preferred_age_youngest: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    preferred_age_oldest: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    preferred_age_label: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Other preferences (stored as JSON arrays)
    preferred_heights: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    preferred_ages: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    preferred_lifestyle: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    preferred_appearance: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    values: Optional[List[str]] = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    values_custom: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class UserDocument(SQLModel, table=True):
    """
    User identity documents (1:N with User, soft delete).

    Stores ID cards and employment proof with S3 keys (not URLs).
    """
    __tablename__ = "user_document"

    id: str = Field(
        default_factory=generate_doc_id,
        primary_key=True,
        max_length=30,
    )
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Document type
    document_type: DocumentTypeEnum = Field(
        sa_column=Column(Text, nullable=False),
    )

    # S3 storage (NEVER store URLs, only keys)
    s3_key: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    original_filename: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    file_size: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    content_type: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Firebase migration reference
    firebase_storage_path: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Verification
    verification_status: DocumentVerificationStatusEnum = Field(
        default=DocumentVerificationStatusEnum.PENDING,
        sa_column=Column(Text, nullable=False),
    )
    verified_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )
    verified_by: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )


class UserPhoto(SQLModel, table=True):
    """
    User profile photos (1:N with User, soft delete).

    Stores photos with S3 keys (not URLs).
    """
    __tablename__ = "user_photo"

    id: str = Field(
        default_factory=generate_photo_id,
        primary_key=True,
        max_length=30,
    )
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )

    # Photo type
    photo_type: PhotoTypeEnum = Field(
        sa_column=Column(Text, nullable=False),
    )

    # S3 storage (NEVER store URLs, only keys)
    s3_key: str = Field(
        sa_column=Column(Text, nullable=False),
    )
    thumbnail_s3_key: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    original_filename: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    file_size: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    content_type: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Firebase migration reference
    firebase_storage_path: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Display order
    display_order: int = Field(default=0, nullable=False)

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    deleted_at: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )


class UserSubscription(SQLModel, table=True):
    """
    User membership/subscription information (1:1 with User).
    """
    __tablename__ = "user_subscription"

    id: str = Field(
        default_factory=generate_sub_id,
        primary_key=True,
        max_length=30,
    )
    user_id: str = Field(
        sa_column=Column(Text, nullable=False, unique=True, index=True),
    )

    # Membership type
    membership_type: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Deposit status
    deposit_status: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Payment info
    payment_amount: Optional[int] = Field(
        default=None,
        nullable=True,
    )
    payment_date: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )

    # Referral
    referral_source: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Consultation
    phone_consult_status: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    meeting_schedule: Optional[datetime] = Field(
        sa_column=Column(DateTime(timezone=True), nullable=True),
        default=None,
    )

    # Match rating
    match_rating_average: Optional[float] = Field(
        default=None,
        nullable=True,
    )

    # Notes
    notes: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )


class UserAccessAudit(SQLModel, table=True):
    """
    Audit log for sensitive data access (view photos, documents).

    Records who accessed what user data and when.
    """
    __tablename__ = "user_access_audit"

    id: str = Field(
        default_factory=generate_audit_id,
        primary_key=True,
        max_length=30,
    )

    # Who accessed
    accessor_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    accessor_type: str = Field(
        sa_column=Column(Text, nullable=False),
    )  # "admin", "user", "system"

    # What was accessed
    target_user_id: str = Field(
        sa_column=Column(Text, nullable=False, index=True),
    )
    resource_type: str = Field(
        sa_column=Column(Text, nullable=False),
    )  # "photo", "document", "profile"
    resource_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Access details
    action: str = Field(
        sa_column=Column(Text, nullable=False),
    )  # "view", "download", "update", "delete"
    ip_address: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    user_agent: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )

    # Timestamp
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(tz=timezone.utc),
    )
