"""
User domain enums with Korean text mappings for Firebase data migration.

Each enum includes:
- Code values for database storage
- Korean to code mapping for migration
- Display labels for API responses
"""
from enum import Enum
from typing import Optional


class AuthTypeEnum(str, Enum):
    """Authentication provider type."""
    NAVER = "naver"
    KAKAO = "kakao"
    GMAIL = "gmail"
    PHONE = "phone"  # Default for migrated users
    APPLE = "apple"


class GenderEnum(str, Enum):
    """User gender."""
    MALE = "male"
    FEMALE = "female"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["GenderEnum"]:
        mapping = {
            "남": cls.MALE,
            "남성": cls.MALE,
            "남자": cls.MALE,
            "여": cls.FEMALE,
            "여성": cls.FEMALE,
            "여자": cls.FEMALE,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.MALE: "남성",
            self.FEMALE: "여성",
        }
        return mapping.get(self, "")


class SmokingEnum(str, Enum):
    """Smoking status."""
    NON_SMOKER = "non_smoker"
    SMOKER = "smoker"
    OCCASIONALLY = "occasionally"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["SmokingEnum"]:
        mapping = {
            "비흡연": cls.NON_SMOKER,
            "흡연": cls.SMOKER,
            "가끔 흡연": cls.OCCASIONALLY,
            "가끔": cls.OCCASIONALLY,
            "사회적 흡연": cls.OCCASIONALLY,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.NON_SMOKER: "비흡연",
            self.SMOKER: "흡연",
            self.OCCASIONALLY: "가끔 흡연",
        }
        return mapping.get(self, "")


class ReligionEnum(str, Enum):
    """Religious affiliation."""
    NONE = "none"
    CHRISTIAN = "christian"
    BUDDHIST = "buddhist"
    CATHOLIC = "catholic"
    OTHER = "other"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["ReligionEnum"]:
        mapping = {
            "무교": cls.NONE,
            "없음": cls.NONE,
            "기독교": cls.CHRISTIAN,
            "개신교": cls.CHRISTIAN,
            "불교": cls.BUDDHIST,
            "천주교": cls.CATHOLIC,
            "가톨릭": cls.CATHOLIC,
            "기타": cls.OTHER,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.NONE: "무교",
            self.CHRISTIAN: "기독교",
            self.BUDDHIST: "불교",
            self.CATHOLIC: "천주교",
            self.OTHER: "기타",
        }
        return mapping.get(self, "")


class LongDistanceEnum(str, Enum):
    """Long distance relationship preference."""
    IMPOSSIBLE = "impossible"
    DEPENDS = "depends"
    POSSIBLE = "possible"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["LongDistanceEnum"]:
        mapping = {
            "불가능": cls.IMPOSSIBLE,
            "상황에 따라": cls.DEPENDS,
            "가능": cls.POSSIBLE,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.IMPOSSIBLE: "불가능",
            self.DEPENDS: "상황에 따라",
            self.POSSIBLE: "가능",
        }
        return mapping.get(self, "")


class TattooEnum(str, Enum):
    """Tattoo status."""
    NONE = "none"
    SMALL = "small"
    VISIBLE = "visible"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["TattooEnum"]:
        mapping = {
            "문신 없음": cls.NONE,
            "없음": cls.NONE,
            "작은 문신 있음": cls.SMALL,
            "작은 문신": cls.SMALL,
            "문신 있음": cls.SMALL,  # 일반적인 문신 있음은 SMALL로 처리
            "눈에 띄는 문신": cls.VISIBLE,
            "눈에 띄는 문신 있음": cls.VISIBLE,
            "비공개": None,  # 비공개는 null 처리
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.NONE: "문신 없음",
            self.SMALL: "작은 문신 있음",
            self.VISIBLE: "눈에 띄는 문신",
        }
        return mapping.get(self, "")


class DivorceStatusEnum(str, Enum):
    """Divorce/marriage status."""
    NEVER_MARRIED = "never_married"
    DIVORCED = "divorced"
    DIVORCED_WITH_KIDS = "divorced_with_kids"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["DivorceStatusEnum"]:
        mapping = {
            "돌싱이 아닙니다": cls.NEVER_MARRIED,
            "돌싱 아님": cls.NEVER_MARRIED,
            "돌싱입니다": cls.DIVORCED,
            "돌싱": cls.DIVORCED,
            "돌싱입니다(자녀x)": cls.DIVORCED,
            "돌싱입니다(자녀o)": cls.DIVORCED_WITH_KIDS,
            "자녀있는 돌싱": cls.DIVORCED_WITH_KIDS,
            "자녀 있는 돌싱": cls.DIVORCED_WITH_KIDS,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.NEVER_MARRIED: "돌싱이 아닙니다",
            self.DIVORCED: "돌싱입니다",
            self.DIVORCED_WITH_KIDS: "자녀있는 돌싱",
        }
        return mapping.get(self, "")


class EducationEnum(str, Enum):
    """Education level."""
    HIGH_SCHOOL = "high_school"
    ASSOCIATE_ENROLLED = "associate_enrolled"
    ASSOCIATE_GRADUATED = "associate_graduated"
    BACHELOR_ENROLLED = "bachelor_enrolled"
    BACHELOR_GRADUATED = "bachelor_graduated"
    MASTER_ENROLLED = "master_enrolled"
    MASTER_GRADUATED = "master_graduated"
    DOCTORATE_ENROLLED = "doctorate_enrolled"
    DOCTORATE_GRADUATED = "doctorate_graduated"
    FOREIGN = "foreign"
    OTHER = "other"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["EducationEnum"]:
        mapping = {
            "고졸": cls.HIGH_SCHOOL,
            "고등학교 졸업": cls.HIGH_SCHOOL,
            "고등학교 졸업(검정고시 포함)": cls.HIGH_SCHOOL,
            "전문대 재학": cls.ASSOCIATE_ENROLLED,
            "전문대 졸업": cls.ASSOCIATE_GRADUATED,
            "전문학사 졸업": cls.ASSOCIATE_GRADUATED,
            "학사 재학": cls.BACHELOR_ENROLLED,
            "대학 재학": cls.BACHELOR_ENROLLED,
            "대학교 재학(4년)": cls.BACHELOR_ENROLLED,
            "학사 졸업": cls.BACHELOR_GRADUATED,
            "대학 졸업": cls.BACHELOR_GRADUATED,
            "대졸": cls.BACHELOR_GRADUATED,
            "석사 재학": cls.MASTER_ENROLLED,
            "석사 과정 재학": cls.MASTER_ENROLLED,
            "박사 과정 재학": cls.DOCTORATE_ENROLLED,
            "석사 졸업": cls.MASTER_GRADUATED,
            "석사": cls.MASTER_GRADUATED,
            "박사 재학": cls.DOCTORATE_ENROLLED,
            "박사 졸업": cls.DOCTORATE_GRADUATED,
            "박사": cls.DOCTORATE_GRADUATED,
            "해외 대학 재학/졸업": cls.FOREIGN,
            "기타": cls.OTHER,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.HIGH_SCHOOL: "고졸",
            self.ASSOCIATE_ENROLLED: "전문대 재학",
            self.ASSOCIATE_GRADUATED: "전문대 졸업",
            self.BACHELOR_ENROLLED: "학사 재학",
            self.BACHELOR_GRADUATED: "학사 졸업",
            self.MASTER_ENROLLED: "석사 재학",
            self.MASTER_GRADUATED: "석사 졸업",
            self.DOCTORATE_ENROLLED: "박사 재학",
            self.DOCTORATE_GRADUATED: "박사 졸업",
        }
        return mapping.get(self, "")


class CarOwnershipEnum(str, Enum):
    """Car ownership status."""
    YES = "yes"
    NO = "no"
    PLANNING = "planning"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["CarOwnershipEnum"]:
        mapping = {
            "있음": cls.YES,
            "있어요": cls.YES,
            "없음": cls.NO,
            "없어요": cls.NO,
            "구입 계획 있음": cls.PLANNING,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.YES: "있음",
            self.NO: "없음",
            self.PLANNING: "구입 계획 있음",
        }
        return mapping.get(self, "")


class DinkPreferenceEnum(str, Enum):
    """DINK (Double Income No Kids) preference."""
    YES = "yes"
    NO = "no"
    UNDECIDED = "undecided"

    @classmethod
    def from_korean(cls, korean: str) -> Optional["DinkPreferenceEnum"]:
        mapping = {
            "딩크를 원합니다": cls.YES,
            "딩크 원함": cls.YES,
            "딩크를 원하지 않습니다": cls.NO,
            "딩크 원하지 않음": cls.NO,
            "아직 잘 모르겠어요": cls.UNDECIDED,
            "딩크를 고려 중입니다": cls.UNDECIDED,
            "미정": cls.UNDECIDED,
        }
        return mapping.get(korean)

    def to_korean(self) -> str:
        mapping = {
            self.YES: "딩크를 원합니다",
            self.NO: "딩크를 원하지 않습니다",
            self.UNDECIDED: "아직 잘 모르겠어요",
        }
        return mapping.get(self, "")


class UserStatusEnum(str, Enum):
    """User account status."""
    DRAFT = "draft"  # Initial registration incomplete
    PENDING_REVIEW = "pending_review"  # Submitted for admin review
    ACTIVE = "active"  # Approved and active
    SUSPENDED = "suspended"  # Temporarily suspended
    WITHDRAWN = "withdrawn"  # User voluntarily left

    @classmethod
    def from_firebase_status(cls, status: str) -> Optional["UserStatusEnum"]:
        """Map Firebase status values to enum."""
        mapping = {
            "new": cls.DRAFT,
            "draft": cls.DRAFT,
            "pending": cls.PENDING_REVIEW,
            "pending_review": cls.PENDING_REVIEW,
            "active": cls.ACTIVE,
            "approved": cls.ACTIVE,
            "suspended": cls.SUSPENDED,
            "withdrawn": cls.WITHDRAWN,
        }
        return mapping.get(status.lower() if status else "")


class DocumentTypeEnum(str, Enum):
    """User document type."""
    ID_CARD = "id_card"
    EMPLOYMENT_PROOF = "employment_proof"

    @classmethod
    def from_firebase_category(cls, category: str) -> Optional["DocumentTypeEnum"]:
        mapping = {
            "idCard": cls.ID_CARD,
            "id_card": cls.ID_CARD,
            "employmentProof": cls.EMPLOYMENT_PROOF,
            "employment_proof": cls.EMPLOYMENT_PROOF,
        }
        return mapping.get(category)


class PhotoTypeEnum(str, Enum):
    """User photo type."""
    FACE = "face"
    FULL = "full"

    @classmethod
    def from_firebase_role(cls, role: str) -> Optional["PhotoTypeEnum"]:
        mapping = {
            "face": cls.FACE,
            "full": cls.FULL,
        }
        return mapping.get(role.lower() if role else "")


class DocumentVerificationStatusEnum(str, Enum):
    """Document verification status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SalaryRangeEnum(str, Enum):
    """Salary range tier."""
    TIER_1 = "1"  # Lowest tier
    TIER_2 = "2"
    TIER_3 = "3"
    TIER_4 = "4"
    TIER_5 = "5"  # Highest tier

    @classmethod
    def from_value(cls, value: str) -> Optional["SalaryRangeEnum"]:
        mapping = {
            "1": cls.TIER_1,
            "2": cls.TIER_2,
            "3": cls.TIER_3,
            "4": cls.TIER_4,
            "5": cls.TIER_5,
        }
        return mapping.get(str(value))


class MatchCategoryEnum(str, Enum):
    """Match category type."""
    INTRO = "intro"
    EXTRA = "extra"

    @classmethod
    def from_value(cls, value: str) -> Optional["MatchCategoryEnum"]:
        mapping = {
            "intro": cls.INTRO,
            "extra": cls.EXTRA,
        }
        return mapping.get(value.lower() if value else "")
