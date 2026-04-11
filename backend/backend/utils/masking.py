"""민감 데이터 마스킹 유틸리티."""


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
    nested_secret_keys: tuple[str, ...] = ("secretKey", "appPassword"),
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
