from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.shipment.service import SambaShipmentService


def test_apply_option_name_rules_updates_option_name_fields() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    name_rule = SimpleNamespace(
        option_rules=[
            {"from": "오프화이트", "to": "OFF-WHITE"},
            {"from": "블랙", "to": "BLACK"},
        ]
    )
    options = [
        {"name": "오프화이트 블랙 / 260", "stock": 3},
        {"option_name": "오프화이트 블랙 / 270", "stock": 5},
        "오프화이트 블랙 / 280",
    ]

    result = service._apply_option_name_rules(options, name_rule)

    assert result == [
        {"name": "OFF-WHITE BLACK / 260", "stock": 3},
        {"option_name": "OFF-WHITE BLACK / 270", "stock": 5},
        "OFF-WHITE BLACK / 280",
    ]


def test_apply_option_name_rules_keeps_options_without_rules() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    name_rule = SimpleNamespace(option_rules=[])
    options = [{"name": "기존 옵션", "stock": 1}]

    result = service._apply_option_name_rules(options, name_rule)

    assert result == options


def test_extract_market_product_no_recovers_nested_lotteon_payload() -> None:
    service = SambaShipmentService(repo=None, session=None)  # type: ignore[arg-type]
    payload = {
        "success": True,
        "data": {
            "success": True,
            "data": {
                "returnCode": "0000",
                "data": [
                    {
                        "resultCode": "0000",
                        "spdNo": "LO1234567890",
                    }
                ],
            },
        },
    }

    result = service._extract_market_product_no(payload)

    assert result == "LO1234567890"
