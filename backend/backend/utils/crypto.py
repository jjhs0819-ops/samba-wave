"""쿠키/민감정보 암호화 유틸 — Fernet (AES-128-CBC + HMAC-SHA256)."""

import base64
import hashlib
import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# JWT 시크릿에서 Fernet 키를 파생 (별도 환경변수 불필요)
_fernet: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    """Fernet 인스턴스 싱글턴 — jwt_secret_key 기반 키 파생."""
    global _fernet
    if _fernet is None:
        from backend.core.config import settings

        # jwt_secret_key → SHA-256 → base64 URL-safe 32바이트 = Fernet 키
        raw = hashlib.sha256(settings.jwt_secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(raw)
        _fernet = Fernet(key)
    return _fernet


def encrypt_value(plaintext: str) -> str:
    """문자열 암호화 → base64 토큰 반환."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(token: str) -> str:
    """암호화된 토큰 → 원본 문자열 복호화."""
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        logger.warning("복호화 실패 (평문 폴백): %s", e)
        # 암호화 전 평문 데이터 호환 — 마이그레이션 기간 동안 평문 반환
        return token


# 암호화 대상 설정 키 목록
ENCRYPTED_KEYS = frozenset(
    {
        "musinsa_cookie",
        "musinsa_cookies",
        "kream_cookie",
        "lotteon_cookie",
    }
)


def is_encrypted_key(key: str) -> bool:
    """해당 설정 키가 암호화 대상인지 확인."""
    return key in ENCRYPTED_KEYS
