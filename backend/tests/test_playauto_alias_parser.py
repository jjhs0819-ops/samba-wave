from backend.domain.samba.order.playauto_alias import parse_playauto_alias_entry


def test_parse_playauto_alias_entry_accepts_multiple_dash_variants() -> None:
    assert parse_playauto_alias_entry("1055695-고경") == ("1055695", "고경")
    assert parse_playauto_alias_entry("1055695 - 고경") == ("1055695", "고경")
    assert parse_playauto_alias_entry("1055695 – 고경") == ("1055695", "고경")
    assert parse_playauto_alias_entry("1055695 — 고경") == ("1055695", "고경")
    assert parse_playauto_alias_entry("037800lt-마늘") == ("037800LT", "마늘")
