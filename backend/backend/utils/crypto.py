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
    """암호화된 토큰 → 원본 문자열 복호화.

    Fernet 토큰 형태(`gAAAAA`로 시작)인데 복호화에 실패하면 빈 문자열을 반환한다.
    이전 키로 암호화된 토큰을 평문 폴백으로 그대로 반환하면 무신사/롯데ON 등에
    암호화 문자열이 그대로 Cookie 헤더로 전송돼 비로그인 응답이 내려오는 사고가
    반복됨(2026-05-10 진단). 평문 폴백은 마이그레이션 초기에만 필요했으므로
    이제는 명시적 실패로 전환해 호출부가 재로그인 유도하도록 한다.
    """
    if not token:
        return ""
    is_fernet_like = token.startswith("gAAAA")
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as e:
        if is_fernet_like:
            logger.error(
                "복호화 실패: Fernet 토큰이지만 현재 키로 풀 수 없음 — "
                "다른 jwt_secret_key 시점에 저장된 값일 가능성. "
                "확장앱에서 해당 사이트 재로그인 후 쿠키를 다시 저장하세요. err=%s",
                e,
            )
            return ""
        # 평문(비-Fernet) 데이터 호환: 과거 평문 저장값은 그대로 반환
        logger.warning("복호화 실패 (평문 폴백, 비-Fernet 형태): %s", e)
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
