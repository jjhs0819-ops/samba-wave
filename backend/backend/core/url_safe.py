"""SSRF 방어 유틸 — URL host allowlist 검증."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlparse

# 기본 허용 scheme — file://, gopher://, dict:// 등 SSRF 벡터 차단용.
_DEFAULT_SCHEMES = frozenset({"http", "https"})


def validate_url_host(
    target: str,
    allowed_hosts: Iterable[str],
    *,
    schemes: Iterable[str] = _DEFAULT_SCHEMES,
) -> bool:
    """URL 의 host 가 allowlist 에 포함되며 허용 scheme 인지 검증.

    Args:
        target: 검증할 URL 문자열.
        allowed_hosts: 허용된 host 목록. 정확 일치하거나 서브도메인이어야 한다.
            (예: ``"musinsa.com"`` 은 ``musinsa.com`` / ``image.musinsa.com`` 매칭,
            ``evil-musinsa.com`` 차단.)
        schemes: 허용된 URL scheme. 기본값은 ``{"http", "https"}``.

    Returns:
        검증 성공 시 ``True``, 그 외 ``False``.

    Note:
        substring 검사 (``"musinsa.com" in url``) 는 ``https://attacker.com/musinsa.com``
        같은 우회 공격에 취약하다. ``urlparse`` + host endswith 비교가 안전하다.
    """
    if not target or not isinstance(target, str):
        return False

    allowed = {h.lower() for h in allowed_hosts}
    allowed_schemes = {s.lower() for s in schemes}

    try:
        parsed = urlparse(target)
    except (ValueError, TypeError):
        return False

    if parsed.scheme.lower() not in allowed_schemes:
        return False

    # userinfo (``user:pass@host``) 는 거부 — 정상 트래픽에는 없고, 로그/모니터링에
    # 가짜 자격증명을 흘려보내거나 일부 라이브러리에서 hostname 파싱 혼동을
    # 유발할 수 있다 (defense-in-depth, RFC 3986 의 deprecated 영역).
    if parsed.username is not None or parsed.password is not None:
        return False

    # netloc 에는 ``user:pass@host:port`` 가 포함될 수 있으므로 hostname 사용.
    host = (parsed.hostname or "").lower()
    if not host:
        return False

    return any(
        host == allowed_host or host.endswith("." + allowed_host)
        for allowed_host in allowed
    )


__all__ = ["validate_url_host"]
