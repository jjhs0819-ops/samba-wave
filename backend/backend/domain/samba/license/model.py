from datetime import datetime
from typing import Optional

from ulid import ULID
from sqlmodel import Field, SQLModel


def _new_lk_id() -> str:
    return f"lk_{ULID()}"


def generate_license_key() -> str:
    import secrets
    import string

    chars = string.ascii_uppercase.replace("O", "").replace(
        "I", ""
    ) + string.digits.replace("0", "").replace("1", "")
    segments = ["".join(secrets.choice(chars) for _ in range(4)) for _ in range(4)]
    return f"SW-{'-'.join(segments)}"


class SambaLicense(SQLModel, table=True):
    __tablename__ = "samba_license"

    id: str = Field(default_factory=_new_lk_id, primary_key=True)
    license_key: str = Field(unique=True, index=True)
    buyer_name: str
    buyer_email: str
    is_active: bool = Field(default=True)
    expires_at: Optional[datetime] = Field(default=None)
    notes: Optional[str] = Field(default=None)
    last_verified_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
