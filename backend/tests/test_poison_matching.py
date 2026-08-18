"""POIZON 품번·사이즈 매칭 테스트 (2026-08-18).

전수 스캔에서 드러난 두 가지 손실 원인을 고친다.

① 품번 오염 — 소싱처가 공식 품번 뒤에 내부코드를 붙여 저장한다
   (KR7598_S_K, KE0662_K). 포이즌은 정확 일치만 지원해서 아디다스 오리지널
   2,564건이 통째로 미매칭이었다. 접미사를 뗀 후보로 재조회하면 살아난다.

② 사이즈 체계 혼선 — 브랜드마다 주는 사이즈 후보가 다르다.
   뉴발란스는 KR(225), 나이키 신발은 CHN(225)만, 나이키 의류는 JP M 만 준다.
   기존에는 먼저 들어온 표기가 이겨서 어느 체계로 매칭됐는지 통제가 안 됐다.
   KR > CHN > EU > 범용 > US/UK > JP 순으로 우선순위를 고정한다.
"""

from __future__ import annotations

from backend.domain.samba.proxy.poison import article_number_candidates
from backend.domain.samba.plugins.markets.poison import build_size_index


# ── ① 품번 정제 ────────────────────────────────────────────────
def test_접미사가_붙은_품번은_정제본을_후보로_낸다():
    assert article_number_candidates("KR7598_S_K") == ["KR7598_S_K", "KR7598"]
    assert article_number_candidates("KE0662_K") == ["KE0662_K", "KE0662"]
    assert article_number_candidates("JZ0507_S_JS") == ["JZ0507_S_JS", "JZ0507"]


def test_접미사가_없으면_원본만():
    assert article_number_candidates("IQ7388-300") == ["IQ7388-300"]
    assert article_number_candidates("L47573200") == ["L47573200"]


def test_정제하면_너무_짧아지는_품번은_후보에서_뺀다():
    # 3043A_077_100 → 3043A 는 품번으로 볼 수 없다
    assert article_number_candidates("3043A_077_100") == ["3043A_077_100"]


def test_공백과_대소문자를_정리한다():
    assert article_number_candidates("  kr7598_s_k ")[0] == "KR7598_S_K"


def test_빈값은_빈목록():
    assert article_number_candidates("") == []
    assert article_number_candidates(None) == []


# ── ② 사이즈 우선순위 ──────────────────────────────────────────
def _sku(gid, size_value, cands):
    return {"globalSkuId": gid, "sizeValue": size_value, "sizeCandidates": cands}


def test_KR표기가_있으면_KR이_이긴다():
    # 뉴발란스 형태 — sizeValue 는 발볼(보통 D), 실제 사이즈는 KR 후보에 있다
    skus = [
        _sku(1, "보통 (D)", {"KR": "225", "EU": "37", "JP": "22.5"}),
        _sku(2, "보통 (D)", {"KR": "230", "EU": "37.5", "JP": "23"}),
    ]
    idx = build_size_index(skus)
    sku, src = idx["225"]
    assert sku["globalSkuId"] == 1
    assert src == "KR"


def test_KR이_없으면_CHN_밀리미터로_매칭():
    # 나이키 신발 형태 — KR 없이 CHN 이 mm 를 준다
    skus = [_sku(10, "36", {"EU": "36", "US": "5.5", "CHN": "225"})]
    idx = build_size_index(skus)
    sku, src = idx["225"]
    assert sku["globalSkuId"] == 10
    assert src == "CHN"


def test_KR과_CHN이_같은_값이면_KR이_이긴다():
    a = _sku(1, "37", {"KR": "230"})
    b = _sku(2, "37.5", {"CHN": "230"})
    idx = build_size_index([b, a])  # CHN 을 먼저 넣어도
    sku, src = idx["230"]
    assert sku["globalSkuId"] == 1
    assert src == "KR"


def test_JP표기는_가장_나중에_쓴다():
    # 나이키 의류 형태 — JP 밖에 없으면 그거라도 쓰되 출처를 남긴다
    skus = [_sku(20, "JP M", {"SIZE": "JP M", "CHN": "170/88A"})]
    idx = build_size_index(skus)
    sku, src = idx["M"]
    assert sku["globalSkuId"] == 20
    assert src in ("SIZE", "sizeValue")


def test_범용사이즈는_그대로_매칭():
    skus = [_sku(30, "M", {"SIZE": "M"})]
    idx = build_size_index(skus)
    sku, src = idx["M"]
    assert sku["globalSkuId"] == 30


def test_sizeValue는_후보가_없을_때만_쓴다():
    skus = [_sku(40, "41", {"KR": "260"})]
    idx = build_size_index(skus)
    assert idx["260"][0]["globalSkuId"] == 40  # KR 로 매칭
    assert "41" in idx  # sizeValue 도 별칭으로는 남는다
