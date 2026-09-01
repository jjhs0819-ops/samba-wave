"""패션플러스 판매마켓 인증키 생성.

패플이 제공한 레퍼런스 구현(API_key.php)을 그대로 이식했다.
서버에 발급을 요청하지 않고 CustCode 로부터 매 요청마다 로컬 생성한다.
"공개키가 시간(ymdH)마다 바뀐다" = 패플이 안내한 "1시간 유효"의 실체다.

레퍼런스 원본: ~/samba-personal-secrets/fashionplus/API_key.php
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# 패플 서버는 KST 기준으로 공개키를 만든다(레퍼런스가 Asia/Seoul 고정으로 시작).
# 우리 백엔드는 UTC 라, 이 변환을 빠뜨리면 9시간 어긋나 전 호출이 인증 실패한다.
KST = timezone(timedelta(hours=9))

_BLOCK_SIZE = 16


def _to_kst(now: datetime | None) -> datetime:
    """None 이면 현재시각, naive 면 KST 로 간주, aware 면 KST 로 변환."""
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def _pkcs7_pad(data: bytes, block_size: int = _BLOCK_SIZE) -> bytes:
    pad = block_size - (len(data) % block_size)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    return data[: -data[-1]]


def build_open_key(cust_code: str, now: datetime | None = None) -> str:
    """공개키 = md5(CustCode + KST 'ymdH'). 32자 hex 이므로 AES-256 키로 바로 쓴다."""
    if not cust_code:
        raise ValueError("CustCode 가 비어 있습니다")
    stamp = _to_kst(now).strftime("%y%m%d%H")
    return hashlib.md5(f"{cust_code}{stamp}".encode()).hexdigest()


def build_api_key(
    cust_code: str, now: datetime | None = None, iv: bytes | None = None
) -> str:
    """인증키 = base64(iv + AES-256-CBC(key=공개키, PKCS7)('공개키^YmdHis')).

    iv 는 테스트에서만 주입한다. 운영에서는 항상 난수를 쓴다.
    """
    kst_now = _to_kst(now)
    open_key = build_open_key(cust_code, kst_now)
    key_base = f"{open_key}^{kst_now.strftime('%Y%m%d%H%M%S')}"
    iv = iv or os.urandom(_BLOCK_SIZE)
    encryptor = Cipher(algorithms.AES(open_key.encode()), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(_pkcs7_pad(key_base.encode())) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext).decode()


def decode_api_key(
    cust_code: str, api_key: str, now: datetime | None = None
) -> str:
    """생성한 인증키를 되돌려 평문을 복원한다 (자체 검증·디버깅용)."""
    open_key = build_open_key(cust_code, now)
    raw = base64.b64decode(api_key)
    iv, ciphertext = raw[:_BLOCK_SIZE], raw[_BLOCK_SIZE:]
    decryptor = Cipher(algorithms.AES(open_key.encode()), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    return _pkcs7_unpad(plain).decode()
