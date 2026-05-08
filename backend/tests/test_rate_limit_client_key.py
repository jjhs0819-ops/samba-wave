"""rate_limit._client_key — X-Forwarded-For 마지막 IP 사용 (위조 방어)."""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.core.rate_limit import _client_key


def _mock_request(
    headers: dict[str, str] | None = None, client_host: str | None = None
):
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

    def test_trailing_comma_with_empty_last_falls_back(self):
        # 헤더 끝에 trailing comma 가 있어 마지막이 빈 문자열 → fallback 으로 client.host
        req = _mock_request(
            headers={"X-Forwarded-For": "1.2.3.4, "},
            client_host="10.0.0.8",
        )
        assert _client_key(req) == "10.0.0.8"

    def test_only_comma_falls_back(self):
        req = _mock_request(headers={"X-Forwarded-For": ","}, client_host="10.0.0.9")
        assert _client_key(req) == "10.0.0.9"

    def test_ipv6_brackets_stripped(self):
        # IPv6 bracket 정규화 — "[::1]" 과 "::1" 같은 IP 로 일관 처리
        req = _mock_request(headers={"X-Forwarded-For": "1.2.3.4, [::1]"})
        assert _client_key(req) == "::1"

    def test_client_host_without_attr_falls_back_to_unknown(self):
        # request.client 객체에 .host 속성 누락 (테스트 mock 등) → AttributeError 회피
        req = MagicMock()
        req.headers = {}
        # spec=[] 객체는 어떤 속성에도 AttributeError 를 일으키지 않으나 .host 는 None
        client = MagicMock(spec=[])
        req.client = client
        assert _client_key(req) == "unknown"

    def test_null_byte_trailing_rejected_falls_back(self):
        # NULL byte 가 IP 끝에 붙어도 strip 으로 제거 안 됨 → printable 검증으로 fallback
        # 동일 IP 가 다른 rate-limit 키로 갈라지는 우회를 차단
        req = _mock_request(
            headers={"X-Forwarded-For": "1.2.3.4, 10.0.0.1\x00"},
            client_host="127.0.0.1",
        )
        assert _client_key(req) == "127.0.0.1"

    def test_control_char_leading_rejected_falls_back(self):
        # IP 앞 \x01 — 제어문자는 strip 으로 제거 안 됨
        req = _mock_request(
            headers={"X-Forwarded-For": "1.2.3.4, \x0110.0.0.1"},
            client_host="127.0.0.1",
        )
        assert _client_key(req) == "127.0.0.1"

    def test_control_char_only_xff_falls_back_to_unknown(self):
        # 제어문자만 있어 fallback 도 없는 경우 → "unknown"
        req = _mock_request(headers={"X-Forwarded-For": "\x00\x01\x02"})
        assert _client_key(req) == "unknown"

    def test_control_char_in_client_host_falls_back_to_unknown(self):
        # client.host 에도 제어문자 검증 적용 — defense-in-depth
        req = _mock_request(client_host="10.0.0.1\x00")
        assert _client_key(req) == "unknown"

    def test_normal_ipv4_passes_printable_check(self):
        # 정상 IPv4 는 모두 printable — 회귀 방지
        req = _mock_request(headers={"X-Forwarded-For": "203.0.113.42"})
        assert _client_key(req) == "203.0.113.42"

    def test_normal_ipv6_passes_printable_check(self):
        # IPv6 (콜론·hex) 도 printable — false rejection 없음
        req = _mock_request(headers={"X-Forwarded-For": "[2001:db8::1]"})
        assert _client_key(req) == "2001:db8::1"
