"""hermes_client 단위 테스트 — 네트워크/DB 불필요한 순수 로직만 검증."""

from backend.domain.samba.ai import hermes_client


def test_base_url_override_strips_trailing_slash():
    # override 가 주어지면 settings 를 건드리지 않고 그대로(끝 슬래시만 제거) 사용.
    assert hermes_client._base_url("http://host:11434/") == "http://host:11434"
    assert hermes_client._base_url("http://host:11434") == "http://host:11434"


def test_default_model_override():
    assert hermes_client._default_model("hermes3:3b") == "hermes3:3b"


def test_extract_json_reexported():
    # gemma_client 의 JSON 추출 로직을 그대로 재노출하는지 확인.
    assert hermes_client.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert hermes_client.extract_json('prefix {"b": 2} suffix') == {"b": 2}
