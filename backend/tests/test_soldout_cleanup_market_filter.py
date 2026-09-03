"""품절 잔존 마켓삭제 루프(`_soldout_cleanup_loop`)의 판매처 필터 테스트.

배경(2026-09-03): 쿠팡 계정이 정지·인증만료(401 Hmac key is expired)된 뒤에도
이 루프가 10분마다 삭제 API를 재시도했다. 삭제 실패 시 registered_accounts가
그대로 남으므로 같은 상품이 영구히 대기열(limit 100)을 점유했고, 당시 대기열
230건 중 123건이 '쿠팡 단독' 품절 상품이었다.

이 루프는 오토튠 판매처 필터(samba_settings.autotune_enabled_markets)를 읽지
않아 워룸에서 쿠팡을 해제해도 삭제 호출이 계속 나갔다. → 필터를 존중하게 하고,
per-account 스킵만으로는 대기열 점유가 안 풀리므로 SELECT WHERE 단계에서도
제외한다.

`allowed_acc_ids` 규약: None = 필터 미설정(전체 허용), set = 허용 계정 화이트리스트.
"""

from __future__ import annotations

import os

# BackendSettings(전역 import 시 인스턴스화) 최소 env
os.environ.setdefault("WRITE_DB_USER", "u")
os.environ.setdefault("WRITE_DB_PASSWORD", "p")
os.environ.setdefault("WRITE_DB_HOST", "localhost")
os.environ.setdefault("WRITE_DB_PORT", "5432")
os.environ.setdefault("WRITE_DB_NAME", "d")
os.environ.setdefault("READ_DB_USER", "u")
os.environ.setdefault("READ_DB_PASSWORD", "p")
os.environ.setdefault("READ_DB_HOST", "localhost")
os.environ.setdefault("READ_DB_PORT", "5432")
os.environ.setdefault("READ_DB_NAME", "d")
os.environ.setdefault("JWT_SECRET_KEY", "s")

from sqlalchemy.dialects import postgresql  # noqa: E402

from backend.lifecycle import (  # noqa: E402
    _soldout_market_where,
    _soldout_skip_account,
)


def _sql(cond) -> str:
    return str(cond.compile(dialect=postgresql.dialect()))


def _params(cond) -> list:
    return list(cond.compile(dialect=postgresql.dialect()).params.values())


class TestSoldoutMarketWhere:
    def test_필터_없으면_조건_없음(self):
        """None = 전체 허용 → 기존 동작(모든 마켓 품절삭제) 유지."""
        assert _soldout_market_where(None) == []

    def test_허용계정_0개면_대상_없음(self):
        """필터는 켜졌는데 해당 마켓 계정이 하나도 없으면 0건이어야 한다.

        여기서 조건을 비우면 필터가 통째로 무시돼 제외 마켓까지 삭제된다.
        """
        conds = _soldout_market_where(set())
        assert len(conds) == 1
        assert "false" in _sql(conds[0]).lower()

    def test_허용마켓_지정시_조건_1개(self):
        assert len(_soldout_market_where({"ma_2", "ma_1"})) == 1

    def test_jsonb_이중인코딩_함정_회피(self):
        """`@>` + cast(str, JSONB) 대신 `?|` 연산자를 써야 한다.

        2026-07-13 사고: cast('["ma_..."]', JSONB)는 SQLAlchemy가 파이썬 str을
        JSONB 바인드로 이중 인코딩해 containment가 영원히 0건이 됐다.
        """
        sql = _sql(_soldout_market_where({"ma_1"})[0])
        assert "?|" in sql
        assert "@>" not in sql

    def test_계정_순서_결정적(self):
        """set 순회 순서에 따라 쿼리 바인드가 흔들리지 않도록 정렬해 넣는다."""
        a = _params(_soldout_market_where({"ma_3", "ma_1", "ma_2"})[0])
        b = _params(_soldout_market_where({"ma_1", "ma_2", "ma_3"})[0])
        assert a == b == [["ma_1", "ma_2", "ma_3"]]


class TestSoldoutSkipAccount:
    def test_필터_없으면_스킵_안함(self):
        assert _soldout_skip_account("ma_1", None) is False

    def test_제외마켓_계정은_스킵(self):
        assert _soldout_skip_account("ma_coupang", {"ma_ssg"}) is True

    def test_허용마켓_계정은_삭제진행(self):
        assert _soldout_skip_account("ma_ssg", {"ma_ssg"}) is False

    def test_허용계정_0개면_전건_스킵(self):
        assert _soldout_skip_account("ma_ssg", set()) is True
