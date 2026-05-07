"""CORS origin regex 분기 단위 테스트 — chrome 확장앱 명시 allowlist."""

from __future__ import annotations

import re

import pytest

from backend.core.config import BackendSettings


def _build(env: dict[str, str]) -> BackendSettings:
    """필수 env 만 채워 BackendSettings 인스턴스 빌드."""
    base = {
        "WRITE_DB_USER": "u",
        "WRITE_DB_PASSWORD": "p",
        "WRITE_DB_HOST": "localhost",
        "WRITE_DB_PORT": "5432",
        "WRITE_DB_NAME": "d",
        "READ_DB_USER": "u",
        "READ_DB_PASSWORD": "p",
        "READ_DB_HOST": "localhost",
        "READ_DB_PORT": "5432",
        "READ_DB_NAME": "d",
        "JWT_SECRET_KEY": "s",
    }
    base.update(env)
    return BackendSettings(**{k.lower(): v for k, v in base.items()})


def _match(regex: str, origin: str) -> bool:
    return re.fullmatch(regex, origin) is not None


class TestNoChromeIdsEnv:
    """env 비어있을 때 — fallback 으로 모든 32자 [a-z] 확장 허용."""

    def test_fallback_any_32_lowercase_id(self):
        s = _build({})
        regex = s.cors_origin_regex
        assert _match(regex, "chrome-extension://" + "a" * 32)
        assert _match(regex, "chrome-extension://" + "b" * 32)

    def test_fallback_rejects_31_chars(self):
        s = _build({})
        assert not _match(s.cors_origin_regex, "chrome-extension://" + "a" * 31)

    def test_fallback_rejects_uppercase(self):
        s = _build({})
        assert not _match(s.cors_origin_regex, "chrome-extension://" + "A" * 32)

    def test_fallback_rejects_digits(self):
        s = _build({})
        assert not _match(s.cors_origin_regex, "chrome-extension://" + "1" * 32)


class TestSingleChromeIdEnv:
    """env 에 단일 ID 만 주입 — 정확히 그 ID 만 허용."""

    def test_exact_id_allowed(self):
        ext_id = "a" * 32
        s = _build({"CHROME_EXTENSION_IDS": ext_id})
        regex = s.cors_origin_regex
        assert _match(regex, f"chrome-extension://{ext_id}")

    def test_other_id_rejected(self):
        ext_id = "a" * 32
        s = _build({"CHROME_EXTENSION_IDS": ext_id})
        # 다른 32자 ID 는 차단
        assert not _match(s.cors_origin_regex, "chrome-extension://" + "b" * 32)


class TestMultipleChromeIdsEnv:
    """env 에 여러 ID 콤마 구분 — 명시된 ID 만 허용."""

    def test_all_listed_ids_allowed(self):
        a = "a" * 32
        b = "b" * 32
        s = _build({"CHROME_EXTENSION_IDS": f"{a},{b}"})
        regex = s.cors_origin_regex
        assert _match(regex, f"chrome-extension://{a}")
        assert _match(regex, f"chrome-extension://{b}")

    def test_unlisted_id_rejected(self):
        a = "a" * 32
        b = "b" * 32
        s = _build({"CHROME_EXTENSION_IDS": f"{a},{b}"})
        assert not _match(s.cors_origin_regex, "chrome-extension://" + "c" * 32)

    def test_whitespace_around_commas_tolerated(self):
        a = "a" * 32
        b = "b" * 32
        s = _build({"CHROME_EXTENSION_IDS": f"  {a} ,  {b} "})
        regex = s.cors_origin_regex
        assert _match(regex, f"chrome-extension://{a}")
        assert _match(regex, f"chrome-extension://{b}")


class TestInvalidChromeIdsEnv:
    """잘못된 형식만 들어있으면 어떤 확장 origin 도 허용하지 않음."""

    def test_invalid_only_ids_blocks_all_extensions(self):
        s = _build({"CHROME_EXTENSION_IDS": "INVALID,too_short"})
        regex = s.cors_origin_regex
        assert not _match(regex, "chrome-extension://" + "a" * 32)

    def test_mixed_valid_and_invalid_keeps_only_valid(self):
        a = "a" * 32
        s = _build({"CHROME_EXTENSION_IDS": f"INVALID,{a},123"})
        regex = s.cors_origin_regex
        # valid 한 a 는 통과
        assert _match(regex, f"chrome-extension://{a}")
        # 기타 32자 ID 는 차단 (allowlist 좁혀짐)
        assert not _match(regex, "chrome-extension://" + "b" * 32)


class TestNonExtensionOrigins:
    """확장 외 origin 분기는 영향 없음."""

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://samba-wave-frontend.vercel.app",
            "https://samba-wave-staging.vercel.app",
        ],
    )
    def test_known_origins_allowed(self, origin):
        s = _build({})
        assert _match(s.cors_origin_regex, origin)

    @pytest.mark.parametrize(
        "origin",
        [
            "https://attacker.com",
            "https://evil-samba-wave.vercel.app.attacker.com",
            "https://samba-wave-fake.com",
        ],
    )
    def test_unknown_origins_rejected(self, origin):
        s = _build({})
        assert not _match(s.cors_origin_regex, origin)
