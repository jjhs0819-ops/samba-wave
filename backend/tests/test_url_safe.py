"""SSRF allowlist 검증 (validate_url_host) 단위 테스트."""

from __future__ import annotations

import pytest

from backend.core.url_safe import validate_url_host

_MUSINSA = frozenset({"musinsa.com", "musinsa.onelink.me"})


class TestValidateUrlHost:
    # ── 정상 ──

    def test_exact_host_match(self):
        assert validate_url_host("https://musinsa.com/path", _MUSINSA)

    def test_subdomain_match(self):
        assert validate_url_host("https://image.musinsa.com/img.jpg", _MUSINSA)
        assert validate_url_host("https://www.musinsa.com/", _MUSINSA)

    def test_deep_subdomain_match(self):
        assert validate_url_host("https://a.b.musinsa.com/p", _MUSINSA)

    def test_http_scheme_allowed(self):
        assert validate_url_host("http://musinsa.com/", _MUSINSA)

    # ── SSRF 우회 시도 차단 ──

    def test_userinfo_with_allowed_host_rejected(self):
        # ``http://attacker:pass@musinsa.com`` — hostname 은 musinsa.com 이지만
        # userinfo 가 있는 URL 은 정상 트래픽에 없으므로 거부 (defense-in-depth)
        assert not validate_url_host("https://attacker:pass@musinsa.com/", _MUSINSA)

    def test_userinfo_only_username_rejected(self):
        assert not validate_url_host("https://user@musinsa.com/", _MUSINSA)

    def test_userinfo_with_disallowed_host_rejected(self):
        # 일반 host allowlist 거부와 무관 — userinfo 있어도 거부
        assert not validate_url_host("https://u:p@attacker.com/", _MUSINSA)

    def test_attacker_domain_with_allowed_in_path(self):
        # `https://attacker.com/musinsa.com` → substring 검사로는 통과하지만
        # 정확/서브도메인 매칭으로는 차단되어야 함.
        assert not validate_url_host("https://attacker.com/musinsa.com", _MUSINSA)

    def test_attacker_domain_ending_with_allowed(self):
        # `https://evil-musinsa.com` — `endswith("." + allowed)` 가 아니므로 차단.
        assert not validate_url_host("https://evil-musinsa.com/", _MUSINSA)

    def test_attacker_domain_with_allowed_as_path_prefix(self):
        # netloc 이 attacker, path 에 musinsa.com 이 들어간 케이스.
        assert not validate_url_host("https://attacker.com/musinsa.com/x", _MUSINSA)

    def test_userinfo_injection_uses_hostname_not_netloc(self):
        # `https://musinsa.com@attacker.com/` — netloc 은
        # `musinsa.com@attacker.com`, 실제 host 는 `attacker.com`.
        # urlparse.hostname 사용으로 우회 차단.
        assert not validate_url_host("https://musinsa.com@attacker.com/", _MUSINSA)

    def test_uppercase_host_normalized(self):
        assert validate_url_host("https://MUSINSA.com/", _MUSINSA)
        assert validate_url_host("https://Image.Musinsa.Com/", _MUSINSA)

    # ── scheme ──

    def test_file_scheme_rejected(self):
        # SSRF 의 전형 — `file:///etc/passwd` 차단.
        assert not validate_url_host("file:///etc/passwd", _MUSINSA)

    def test_gopher_scheme_rejected(self):
        assert not validate_url_host("gopher://musinsa.com/", _MUSINSA)

    def test_no_scheme_rejected(self):
        # ``musinsa.com/path`` — scheme 없음, urlparse 가 path 로 파싱.
        assert not validate_url_host("musinsa.com/path", _MUSINSA)

    def test_custom_schemes(self):
        # 호출부가 schemes 를 명시할 수 있어야 함.
        assert validate_url_host("ftp://musinsa.com/", _MUSINSA, schemes={"ftp"})
        assert not validate_url_host("https://musinsa.com/", _MUSINSA, schemes={"ftp"})

    # ── edge ──

    def test_empty_url(self):
        assert not validate_url_host("", _MUSINSA)

    def test_none_like(self):
        assert not validate_url_host(None, _MUSINSA)  # type: ignore[arg-type]

    def test_non_string_rejected(self):
        assert not validate_url_host(12345, _MUSINSA)  # type: ignore[arg-type]

    def test_empty_allowlist_blocks_all(self):
        assert not validate_url_host("https://musinsa.com/", frozenset())


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://musinsa.com/", True),
        ("https://image.musinsa.com/p.jpg", True),
        ("https://www.musinsa.com/onelink", True),
        ("https://musinsa.onelink.me/abc", True),
        ("https://attacker.com/?x=musinsa.com", False),
        ("https://attacker-musinsa.com/", False),
        ("file://musinsa.com/", False),
        ("javascript:alert(1)", False),
    ],
)
def test_parametrized(url: str, expected: bool):
    assert validate_url_host(url, _MUSINSA) is expected
