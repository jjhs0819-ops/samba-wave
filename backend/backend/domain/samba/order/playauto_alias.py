import re
from typing import Any


def normalize_playauto_alias_code(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if re.fullmatch(r"\d+\.0+", upper):
        return re.sub(r"\.0+$", "", upper)
    return upper


def parse_playauto_alias_entry(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    match = re.match(r"^(.*?)\s*[-\u2010-\u2015\u2212]\s*(.+)$", raw)
    if not match:
        return normalize_playauto_alias_code(raw), ""
    code = normalize_playauto_alias_code(match.group(1))
    nick = str(match.group(2) or "").strip()
    return code, nick
