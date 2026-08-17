"""정책에 마켓 설정이 없는 계정으로의 전송 차단 가드.

2026-08-15 사고: 포이즌 전용 정책(market_policies 에 "포이즌" 키만 존재)이 적용된
푸마 185건이 11번가로 전송됐다. 계정이 "다르게" 지정된 경우는 막으면서 "아예 없는"
경우는 그대로 통과시키던 분기 때문이다. 통과하면 calc_market_price 가 빈 dict 를
받아 feeRate·마켓 배송비를 건너뛰고 원가+공통마진만 반영된 저가로 등록된다.
"""

from types import SimpleNamespace

from backend.domain.samba.shipment.service import (
    calc_market_price,
    filter_accounts_by_policy,
)

_POISON_ONLY = {"포이즌": {"accountId": "acc_poison", "feeRate": 10}}
_FULL = {
    "11번가": {"accountId": "acc_11st", "feeRate": 31, "shippingCost": 3000},
    "포이즌": {"accountId": "acc_poison", "feeRate": 10},
}


def _accounts(**kv):
    return {aid: SimpleNamespace(market_type=mt) for aid, mt in kv.items()}


def test_정책에_없는_마켓은_차단된다():
    allowed, blocked = filter_accounts_by_policy(
        ["acc_11st"], _accounts(acc_11st="11st"), _POISON_ONLY
    )
    assert allowed == []
    assert blocked == {"acc_11st": "11번가"}


def test_정책에_있는_마켓은_통과한다():
    allowed, blocked = filter_accounts_by_policy(
        ["acc_poison"], _accounts(acc_poison="poison"), _POISON_ONLY
    )
    assert allowed == ["acc_poison"]
    assert blocked == {}


def test_일부만_차단되고_나머지는_전송된다():
    allowed, blocked = filter_accounts_by_policy(
        ["acc_poison", "acc_11st"],
        _accounts(acc_poison="poison", acc_11st="11st"),
        _POISON_ONLY,
    )
    assert allowed == ["acc_poison"]
    assert blocked == {"acc_11st": "11번가"}


def test_market_policies가_통째로_비면_전건_차단():
    """예전 게이트(`if policy_market_data:`)는 이 경우 필터 자체를 건너뛰어
    모든 마켓을 수수료 미반영으로 통과시켰다."""
    allowed, blocked = filter_accounts_by_policy(
        ["acc_11st", "acc_poison"],
        _accounts(acc_11st="11st", acc_poison="poison"),
        {},
    )
    assert allowed == []
    assert blocked == {"acc_11st": "11번가", "acc_poison": "포이즌"}


def test_정책키_매핑없는_마켓은_그대로_허용():
    """어느 맵에도 없는 market_type 은 정책으로 판단할 근거가 없어 허용한다."""
    allowed, blocked = filter_accounts_by_policy(
        ["acc_x"], _accounts(acc_x="정체불명마켓"), _POISON_ONLY
    )
    assert allowed == ["acc_x"]
    assert blocked == {}


def test_플러그인_전용_마켓도_가드에_걸린다():
    """poison/toss 는 service.py 하드코딩 맵에 없고 플러그인 레지스트리에만 있다.
    하드코딩 맵만 보면 정책에 포이즌 설정이 없어도 무조건 통과해 버린다."""
    allowed, blocked = filter_accounts_by_policy(
        ["acc_toss"], _accounts(acc_toss="toss"), _POISON_ONLY
    )
    assert allowed == []
    assert blocked == {"acc_toss": "토스"}


def test_계정이_다르게_지정되면_기존대로_차단():
    """기존 accountIds 필터 동작은 그대로여야 한다."""
    allowed, blocked = filter_accounts_by_policy(
        ["acc_other"], _accounts(acc_other="11st"), _FULL
    )
    assert allowed == []
    assert blocked == {}  # 미설정이 아니라 계정 불일치 차단


def test_조회안되는_계정은_조용히_제외():
    allowed, blocked = filter_accounts_by_policy(["missing"], {}, _FULL)
    assert allowed == []
    assert blocked == {}


def test_차단하지_않으면_저가로_등록된다는_근거():
    """가드의 존재 이유 — 마켓 설정이 없으면 수수료 그로스업이 통째로 빠진다."""
    pricing = {"marginRate": 10, "feeRate": 0, "shippingCost": 0}
    price_with = calc_market_price(100_000, pricing, "11st", _FULL)
    price_without = calc_market_price(100_000, pricing, "11st", _POISON_ONLY)
    assert price_without < price_with
