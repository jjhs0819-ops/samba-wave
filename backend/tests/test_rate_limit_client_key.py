"""rate_limit._client_key — X-Forwarded-For 마지막 IP 사용 (위조 방어)."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.rate_limit import _client_key


def _mock_request(headers: dict[str, str] | None = None, client_host: str | None = None):
    req = MagicMock()
    req.headers = {k.lower(): v for k, v in (headers or {}).items()}
    if client_host:
        req.client = MagicMock(host=client_host)
    else:
        req.client = None
    return req


class TestClientKey:
    def test_no_forwarded_falls_back_to_client_host(self):
        req = _mock_request(client_host="10.0.0.5")
        assert _client_key(req) == "10.0.0.5"

    def test_no_forwarded_no_client_returns_unknown(self):
        req = _mock_request()
        assert _client_key(req) == "unknown"

    def test_single_forwarded_ip_used(self):
        req = _mock_request(headers={"X-Forwarded-For": "1.2.3.4"})
        assert _client_key(req) == "1.2.3.4"

    def test_caddy_appended_ip_uses_last(self):
        # Caddy 가 자기 관찰 IP 를 끝에 append — 마지막 IP 가 신뢰값
        req = _mock_request(headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1"})
        assert _client_key(req) == "10.0.0.1"

    def test_spoofed_first_ip_ignored(self):
        # 클라이언트가 X-Forwarded-For 첫 부분 위조 → Caddy 가 자기 IP append
        # → 마지막 IP 만 사용하므로 위조값은 무시
        req = _mock_request(
            headers={"X-Forwarded-For": "127.0.0.1, evil-spoof, 10.0.0.1"}
        )
        assert _client_key(req) == "10.0.0.1"
        assert _client_key(req) != "127.0.0.1"

    def test_whitespace_around_ips_trimmed(self):
        req = _mock_request(headers={"X-Forwarded-For": "1.2.3.4 ,  10.0.0.1  "})
        assert _client_key(req) == "10.0.0.1"

    def test_empty_forwarded_falls_back(self):
        req = _mock_request(headers={"X-Forwarded-For": ""}, client_host="10.0.0.7")
        assert _client_key(req) == "10.0.0.7"
