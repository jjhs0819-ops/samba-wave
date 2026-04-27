"""민감 데이터 마스킹 유틸리티."""

import re
from typing import Any

# 모든 마켓/소싱 계정의 password 타입 필드명을 통합 (frontend settings/config.ts와 동기화)
# 응답 마스킹 + 업데이트 시 마스킹값 차단 양쪽에 일관되게 사용
ALL_NESTED_SECRET_KEYS: tuple[str, ...] = (
    "secretKey",
    "appPassword",
    "clientSecret",
    "apiSecret",
    "password",
    "accessToken",
    "partnerKey",
    "oauthToken",
    "appSecret",
    "userKey",
    "apiKeyDev",
    "apiKeyProd",
    "refreshToken",
)

# `mask_secret`이 만드는 출력은 정확히 "****" + (0~visible_chars)자
# false positive(우연히 사용자가 이 패턴으로 시작) 차단 위해 정규식으로 정확 매칭
_MASKED_PATTERN = re.compile(r"^\*{4}.{0,4}$")


def is_masked(value: Any) -> bool:
    """`mask_secret` 출력 형식인지 정확히 판별."""
    return isinstance(value, str) and bool(_MASKED_PATTERN.match(value))


def mask_secret(value: str | None, visible_chars: int = 4) -> str | None:
    """시크릿 값을 마스킹 처리. 끝 N자만 표시.

    예: "M2U0NWFhMmYtZGY0MS00Yjdk" → "****Yjdk"
    """
    if not value:
        return value
    if len(value) <= visible_chars:
        return "****"
    return "****" + value[-visible_chars:]


def mask_model_secrets(
    model_dict: dict,
    secret_fields: tuple[str, ...] = ("password", "api_secret"),
    nested_secret_keys: tuple[str, ...] = ALL_NESTED_SECRET_KEYS,
) -> dict:
    """모델 dict에서 민감 필드를 마스킹.

    - secret_fields: 최상위 필드 중 마스킹 대상
    - nested_secret_keys: additional_fields(JSON) 내부의 마스킹 대상 키
    """
    result = dict(model_dict)
    for field in secret_fields:
        if field in result and result[field]:
            result[field] = mask_secret(result[field])

    # additional_fields 내부 민감 키 마스킹
    af = result.get("additional_fields")
    if isinstance(af, dict):
        af = dict(af)
        for key in nested_secret_keys:
            if key in af and af[key]:
                af[key] = mask_secret(af[key])
        result["additional_fields"] = af

    return result


def drop_masked_secret_fields(
    incoming: dict,
    secret_keys: tuple[str, ...] = ALL_NESTED_SECRET_KEYS,
) -> dict:
    """incoming dict에서 마스킹된 secret 키를 제거(drop).

    저장 단계에서 사용 — 클라이언트가 GET 응답의 마스킹값을 그대로 PUT으로
    돌려보낼 경우 DB의 진짜 값을 마스킹값으로 덮어쓰는 사고를 차단.

    제거(drop)만 하고 머지/복원은 호출 측에서 기존 값과 합치도록 유지
    (cafe24 OAuth accessToken 등 다른 필드 보존 로직과 충돌하지 않게).
    """
    if not isinstance(incoming, dict):
        return incoming
    result = dict(incoming)
    for key in secret_keys:
        if key in result and is_masked(result[key]):
            result.pop(key, None)
    return result


def sanitize_top_level_secrets(
    data: dict,
    secret_fields: tuple[str, ...] = ("password", "api_secret"),
) -> dict:
    """최상위 secret 컬럼 중 마스킹값이면 키 자체를 제거.

    SambaMarketAccount.api_secret, SambaSourcingAccount.password 등이 대상.
    """
    if not isinstance(data, dict):
        return data
    result = dict(data)
    for field in secret_fields:
        if field in result and is_masked(result[field]):
            result.pop(field, None)
    return result
