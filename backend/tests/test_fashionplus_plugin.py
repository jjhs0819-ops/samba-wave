"""패션플러스 마켓 플러그인 검증."""

import pytest

from backend.domain.samba.plugins.markets.fashionplus import (
    FashionPlusPlugin,
    extract_option_ids,
    is_self_sourced,
)


def test_레지스트리_식별자():
    plugin = FashionPlusPlugin()
    assert plugin.market_type == "fashionplus"
    assert plugin.policy_key == "패션플러스"


def test_패플_소싱분은_자기순환으로_차단():
    assert is_self_sourced({"source": "FASHIONPLUS"}) is True
    assert is_self_sourced({"source": "fashionplus"}) is True


def test_다른_소싱처는_통과():
    assert is_self_sourced({"source": "MUSINSA"}) is False
    assert is_self_sourced({}) is False


def test_등록응답에서_OptID_맵_추출():
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [
            {"OptID": 111, "Color": "BLACK", "Size": "270"},
            {"OptID": 222, "Color": "BLACK", "Size": "280"},
        ],
    }
    assert extract_option_ids(resp) == {"BLACK|270": 111, "BLACK|280": 222}


def test_OptID_없는_응답은_빈맵():
    assert extract_option_ids({"Status": "OK", "ItemID": 777}) == {}


@pytest.mark.asyncio
async def test_자기순환_상품은_전송하지_않는다():
    plugin = FashionPlusPlugin()
    result = await plugin.execute(
        session=None,
        product={"source": "FASHIONPLUS", "name": "x", "sale_price": 10000},
        creds={"custCode": "012555"},
        category_id="1010",
        account=None,
        existing_no="",
    )
    assert result["success"] is False
    assert "자기순환" in result["message"]


@pytest.mark.asyncio
async def test_삭제는_재고0_노출해제_삭제_3단으로_진행한다():
    """GoodsDelete 는 임시보관이라 재고0·노출해제를 먼저 해야 실제로 안 팔린다."""
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            return {"Status": "OK", "Message": ""}

    plugin = FashionPlusPlugin()
    result = await plugin.delete_with_client(FakeClient(), "777", options=[])
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is True


# ── 수정 라운드 1: 유령(삼바 삭제·마켓 생존) 방지 검증 ──


def test_OptID_숫자해석_불가는_건너뛰고_예외를_안_던진다():
    """GoodsAdd 원격 성공 후의 파싱 예외는 재시도→중복등록으로 이어지므로 삼킨다."""
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [
            {"OptID": "abc", "Color": "BLACK", "Size": "270"},
            {"OptID": 222, "Color": "BLACK", "Size": "280"},
        ],
    }
    assert extract_option_ids(resp) == {"BLACK|280": 222}


@pytest.mark.asyncio
async def test_옵션정보_없으면_1단_실패는_메모로_빠지고_2단_실패만_실패사유다():
    """옵션 정보가 없는 경로의 의도된 동작을 정확히 단언한다.

    1단(재고0)은 OptID 없는 fallback 행이라 거절돼도 실패로 합산하지 않고
    "옵션 정보 없음" 메모로만 남는다. 2단(노출해제) 실패는 유령이므로
    그대로 실패 사유가 되고, 3단은 계속 호출된다.
    """
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            if op in ("scm_option_upt", "goods_dsp"):
                return {"Status": "ERROR", "Message": "boom"}
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is False
    assert "2단" in result["message"]
    # 1단 거절은 실패 사유가 아니라 메모다
    assert "1단(재고0) 실패" not in result["message"]
    assert "옵션 정보 없음" in result["message"]


@pytest.mark.asyncio
async def test_옵션과_매핑이_정상인데_1단이_거절되면_실패로_집계된다():
    """옵션 정보 없음 면제와 달리, 매핑까지 멀쩡한 재고0 거절은 진짜 실패다.

    재고0 이 안 나간 옵션은 패플에서 계속 팔린다 — 성공으로 박제 금지.
    3단(임시보관)은 그래도 계속 호출돼야 한다.
    """
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            if op == "scm_option_upt":
                return {"Status": "Err-Dat-999", "Message": "거절"}
            return {"Status": "OK", "Message": ""}

    options = [
        {"color": "BLACK", "size": "270", "stock": 5},
        {"color": "BLACK", "size": "280", "stock": 5},
    ]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(),
        "777",
        options=options,
        option_ids={"BLACK|270": 111, "BLACK|280": 222},
    )
    assert called == ["scm_option_upt", "scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is False
    assert "1단(재고0) 실패" in result["message"]


@pytest.mark.asyncio
async def test_2단_예외에도_3단은_계속_진행하고_실패로_보고한다():
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            if op == "goods_dsp":
                raise RuntimeError("연결 끊김")
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is False
    assert "2단" in result["message"]


@pytest.mark.asyncio
async def test_부분_매핑이면_실패로_내리고_미전송_개수를_남긴다():
    """매핑 안 된 옵션은 재고0 이 안 나가 계속 팔린다 — 성공으로 박제 금지."""
    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    options = [
        {"color": "BLACK", "size": "270", "stock": 5, "opt_id": 111},
        {"color": "BLACK", "size": "280", "stock": 5},
        {"color": "BLACK", "size": "290", "stock": 5},
    ]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=options
    )
    assert result["success"] is False
    assert "옵션 2건 재고0 미전송" in result["message"]
    # 매핑된 옵션의 재고0 요청은 실제로 나가야 한다
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert len(stock_rows) == 1
    assert stock_rows[0]["OptID"] == 111
    assert stock_rows[0]["StockQty"] == 0


@pytest.mark.asyncio
async def test_삭제시_호출측_옵션_dict를_변형하지_않는다():
    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    options = [{"color": "BLACK", "size": "270", "stock": 5, "opt_id": 111}]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=options
    )
    assert result["success"] is True
    assert options[0]["stock"] == 5


@pytest.mark.asyncio
async def test_수정시_OptID_매핑_0건이면_실패로_보고한다():
    """options 는 있는데 매핑이 비면 재고가 전혀 안 갱신된다 — 성공 금지."""

    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    product = {
        "sale_price": 10000,
        "options": [{"color": "BLACK", "size": "270", "stock": 5}],
        # fp_option_ids 없음 → 전송 행 0건
    }
    result = await FashionPlusPlugin()._update(FakeClient(), product, "777")
    assert result["success"] is False
    assert "재고 미갱신" in result["message"]
    assert "가격은 갱신됨" in result["message"]


@pytest.mark.asyncio
async def test_수정시_옵션없는_상품은_가격만으로_성공한다():
    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin()._update(
        FakeClient(), {"sale_price": 10000}, "777"
    )
    assert result["success"] is True


# ── 최종 리뷰 F1: 자기순환 판정은 실제 모델 필드 source_site 기준 ──


def test_자기순환_판정은_source_site_필드를_본다():
    """수집 모델의 실제 필드는 source_site 다 (collector/model.py)."""
    assert is_self_sourced({"source_site": "FASHIONPLUS"}) is True
    assert is_self_sourced({"source_site": "fashionplus"}) is True
    assert is_self_sourced({"source_site": "MUSINSA"}) is False


def test_자기순환_판정_source_site가_source보다_우선():
    assert is_self_sourced({"source_site": "MUSINSA", "source": "FASHIONPLUS"}) is False
    # source_site 가 비어 있으면 source 폴백
    assert is_self_sourced({"source_site": "", "source": "FASHIONPLUS"}) is True


# ── 최종 리뷰 F3: 원사이즈(색상·사이즈 없음) 옵션도 OptID 매핑 ──


def test_등록응답_색상사이즈_없는_옵션은_이름으로_키를_만든다():
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [{"OptID": 111, "OptName": "FREE"}],
    }
    assert extract_option_ids(resp) == {"FREE": 111}


def test_등록응답_Name_필드도_이름_후보로_쓴다():
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [{"OptID": 111, "Name": "FREE"}],
    }
    assert extract_option_ids(resp) == {"FREE": 111}


def test_등록응답_OptID_0은_유효한_매핑():
    """payload 쪽(build_scm_option_upt)과 같은 is None 기준 — 0 을 버리면 안 된다."""
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [{"OptID": 0, "Color": "BLACK", "Size": "270"}],
    }
    assert extract_option_ids(resp) == {"BLACK|270": 0}


@pytest.mark.asyncio
async def test_원사이즈_옵션_왕복_매칭():
    """등록 응답(이름만 있는 옵션) → 재고 갱신에서 같은 키로 매칭돼야 한다.

    어긋나면 재고 갱신·삭제 1단이 영구 실패해 품절인데 계속 팔리는 유령이 된다.
    """
    resp = {
        "Status": "OK",
        "ItemID": 777,
        "Options": [{"OptID": 111, "OptName": "FREE"}],
    }
    option_ids = extract_option_ids(resp)

    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    product = {
        "sale_price": 10000,
        "options": [{"name": "FREE", "stock": 3}],  # 색상·사이즈 없음
        "fp_option_ids": option_ids,
    }
    result = await FashionPlusPlugin()._update(FakeClient(), product, "777")
    assert result["success"] is True
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert len(stock_rows) == 1
    assert stock_rows[0]["OptID"] == 111
    assert stock_rows[0]["StockQty"] == 3


# ── 최종 리뷰 F4: 표준 delete() 경로 + 옵션 ID 키 통일(fp_option_ids) ──


@pytest.mark.asyncio
async def test_옵션정보_없는_삭제는_1단_실패를_합산하지_않는다():
    """옵션을 아예 모르면 fallback 재고0 거절이 3단 성공을 가리면 안 된다.

    합산하면 항상 success=False → 삼바가 삭제완료로 못 박고 무한 재시도.
    """

    class FakeClient:
        async def call(self, op, payload):
            if op == "scm_option_upt":
                return {"Status": "Err-Dat-999", "Message": "OptID 없음"}
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert result["success"] is True
    assert "옵션 정보 없음" in result["message"]


@pytest.mark.asyncio
async def test_옵션정보_없는_삭제_성공시에도_생략_메모를_남긴다():
    class FakeClient:
        async def call(self, op, payload):
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert result["success"] is True
    assert "옵션 정보 없음" in result["message"]


@pytest.mark.asyncio
async def test_옵션정보_없어도_2단_실패는_그대로_실패다():
    """1단 면제는 옵션 정보 없음에 한정 — 노출해제 실패는 유령이므로 실패 유지."""

    class FakeClient:
        async def call(self, op, payload):
            if op == "goods_dsp":
                return {"Status": "ERROR", "Message": "boom"}
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=[]
    )
    assert result["success"] is False
    assert "2단" in result["message"]


@pytest.mark.asyncio
async def test_표준_delete_진입점은_3단_성공이면_성공으로_보고한다():
    called: list[str] = []

    class FakeClient:
        async def call(self, op, payload):
            called.append(op)
            return {"Status": "OK", "Message": ""}

    plugin = FashionPlusPlugin()
    plugin._build_client = lambda account: FakeClient()  # 네트워크 차단
    result = await plugin.delete(session=None, product_no="777", account=object())
    assert called == ["scm_option_upt", "goods_dsp", "goods_delete"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_삭제시_fp_option_ids_맵을_직접_받으면_재고0이_옵션별로_나간다():
    """정본 키 fp_option_ids 에 보관된 맵을 그대로 넘기는 경로."""
    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(),
        "777",
        options=[{"color": "BLACK", "size": "270", "stock": 5}],
        option_ids={"BLACK|270": 111},
    )
    assert result["success"] is True
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert len(stock_rows) == 1
    assert stock_rows[0]["OptID"] == 111
    assert stock_rows[0]["StockQty"] == 0


@pytest.mark.asyncio
async def test_삭제시_옵션row의_opt_id_0도_유효한_매핑():
    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    options = [{"color": "BLACK", "size": "270", "stock": 5, "opt_id": 0}]
    result = await FashionPlusPlugin().delete_with_client(
        FakeClient(), "777", options=options
    )
    assert result["success"] is True
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert stock_rows[0]["OptID"] == 0


@pytest.mark.asyncio
async def test_수정시_옵션ID_맵은_정본_키_fp_option_ids로_받는다():
    payloads: list[tuple[str, dict]] = []

    class FakeClient:
        async def call(self, op, payload):
            payloads.append((op, payload))
            return {"Status": "OK", "Message": ""}

    product = {
        "sale_price": 10000,
        "options": [{"color": "BLACK", "size": "270", "stock": 7}],
        "fp_option_ids": {"BLACK|270": 111},
    }
    result = await FashionPlusPlugin()._update(FakeClient(), product, "777")
    assert result["success"] is True
    stock_rows = [p for op, p in payloads if op == "scm_option_upt"]
    assert stock_rows[0]["OptID"] == 111
    assert stock_rows[0]["StockQty"] == 7


@pytest.mark.asyncio
async def test_등록_결과의_옵션ID_맵_키도_fp_option_ids다():
    """상위가 last_sent_data[계정]["fp_option_ids"] 에 그대로 보관하는 정본 키."""

    class FakeClient:
        async def call(self, op, payload):
            return {
                "Status": "OK",
                "ItemID": 777,
                "Options": [{"OptID": 111, "Color": "BLACK", "Size": "270"}],
            }

    result = await FashionPlusPlugin()._create(
        FakeClient(), _create_product(), "1010", "5477", ""
    )
    assert result["success"] is True
    assert result["fp_option_ids"] == {"BLACK|270": 111}


def _create_product() -> dict:
    return {
        "id": "p1",
        "site_product_id": "MU123",
        "name": "나이키 에어포스1",
        "sale_price": 89000,
        "images": ["https://mirror.example/1.jpg"],
        "options": [{"color": "BLACK", "size": "270", "stock": 5}],
    }


# ── 최종 리뷰 F5: 수수료율 미확정 게이트 (ENABLE_FASHIONPLUS) ──


@pytest.mark.asyncio
async def test_게이트_미설정이면_전송을_차단한다(monkeypatch):
    """수수료 맵 미등록 상태의 전송은 저가등록 사고(eBay·토스 전례)로 직결된다."""
    monkeypatch.delenv("ENABLE_FASHIONPLUS", raising=False)
    result = await FashionPlusPlugin().execute(
        session=None,
        product={"source_site": "MUSINSA", "name": "x", "sale_price": 10000},
        creds={},
        category_id="1010",
        account=None,
        existing_no="",
    )
    assert result["success"] is False
    assert "수수료율 미확정" in result["message"]
    assert "ENABLE_FASHIONPLUS=1" in result["message"]


@pytest.mark.asyncio
async def test_게이트_1이면_통과해_다음_단계로_진행한다(monkeypatch):
    monkeypatch.setenv("ENABLE_FASHIONPLUS", "1")
    result = await FashionPlusPlugin().execute(
        session=None,
        product={"source_site": "MUSINSA", "name": "x", "sale_price": 10000},
        creds={},
        category_id="1010",
        account=None,  # 게이트 통과 후 인증 검사에서 걸리는 것으로 통과를 증명
        existing_no="",
    )
    assert result["success"] is False
    assert "custCode" in result["message"]
    assert "수수료율" not in result["message"]
