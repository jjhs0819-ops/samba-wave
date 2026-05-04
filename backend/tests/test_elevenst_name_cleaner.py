from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.samba.proxy.elevenst import (
    _clean_product_name,
    _limit_repeated_name_words,
)


def test_limit_repeated_name_words_blocks_third_exact_repeat():
    name = "나이키 양말 트레이닝 양말 쿠션 양말"

    cleaned = _limit_repeated_name_words(name)

    assert cleaned == "나이키 양말 트레이닝 양말 쿠션"


def test_limit_repeated_name_words_blocks_third_repeat_from_compound_words():
    name = "나이키 데님팬츠 루즈 데님 스케이트 팬츠 팬츠"

    cleaned = _limit_repeated_name_words(name)

    assert cleaned == "나이키 데님팬츠 루즈 데님 스케이트 팬츠"


def test_clean_product_name_removes_banned_patterns_and_limits_repeats():
    name = "무료배송 나이키 양말 트레이닝 양말 쿠션 양말"

    cleaned = _clean_product_name(name)

    assert cleaned == "나이키 양말 트레이닝 양말 쿠션"
