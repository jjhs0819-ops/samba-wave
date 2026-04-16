from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.notice_utils import build_smartstore_notice


def test_build_smartstore_notice_truncates_oversized_string_fields() -> None:
    notice = build_smartstore_notice(
        {
            "category1": "신발",
            "name": "테스트 신발",
            "care_instructions": "a" * 1605,
            "quality_guarantee": "b" * 1602,
            "material": "합성가죽",
            "brand": "테스트브랜드",
        }
    )

    shoes_notice = notice["shoes"]

    assert notice["productInfoProvidedNoticeType"] == "SHOES"
    assert len(shoes_notice["caution"]) == 1500
    assert len(shoes_notice["warrantyPolicy"]) == 1500
    assert shoes_notice["caution"] == "a" * 1500
    assert shoes_notice["warrantyPolicy"] == "b" * 1500
