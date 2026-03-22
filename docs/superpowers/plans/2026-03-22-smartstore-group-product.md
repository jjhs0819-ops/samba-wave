# 스마트스토어 그룹상품 완전자동화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 수집된 상품 중 같은 모델의 다른 색상 변형을 자동 감지하여 스마트스토어 그룹상품 API로 묶어 등록

**Architecture:** D방식 그룹핑(similarNo → styleCode → 상품명 패턴)으로 수집 시 group_key 생성. 전송 시 그룹 미리보기 모달 → 확인 후 그룹상품 API 호출. 비동기 폴링으로 결과 확인. 기존 단일상품은 삭제 후 그룹 재등록.

**Tech Stack:** Python/FastAPI, SQLAlchemy, Alembic, Next.js/React/TypeScript

**Spec:** `docs/superpowers/specs/2026-03-22-smartstore-group-product-design.md`

---

## Task 1: DB 모델 + 마이그레이션

**Files:**
- Modify: `backend/backend/domain/samba/collector/model.py:209` (care_instructions 뒤)
- Create: `backend/alembic/versions/xxxx_add_group_product_fields.py`

- [ ] **Step 1: SambaCollectedProduct에 3개 필드 추가**

`backend/backend/domain/samba/collector/model.py` 라인 209 (`care_instructions`) 뒤에 추가:

```python
# 그룹상품 관련
group_key: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True, index=True))
similar_no: Optional[str] = Field(default=None, sa_column=Column(String(50), nullable=True))
group_product_no: Optional[int] = Field(default=None, sa_column=Column(BigInteger, nullable=True))
```

`BigInteger` import 추가: `from sqlalchemy import BigInteger` (기존 import 확인 후)

- [ ] **Step 2: Alembic 마이그레이션 생성**

```bash
cd backend && alembic revision --autogenerate -m "add_group_product_fields"
```

- [ ] **Step 3: 마이그레이션 실행**

```bash
cd backend && .venv/Scripts/python.exe -m alembic upgrade head
```

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/domain/samba/collector/model.py backend/alembic/versions/*group_product*
git commit -m "feat: 그룹상품 DB 모델 필드 추가 (group_key, similar_no, group_product_no)"
```

---

## Task 2: 그룹핑 유틸 함수

**Files:**
- Create: `backend/backend/domain/samba/collector/grouping.py`

- [ ] **Step 1: grouping.py 생성**

```python
"""상품 그룹핑 유틸. D방식: similarNo → styleCode 모델코드 → 상품명 패턴."""
import re
from typing import Optional


def parse_color_from_name(name: str) -> str:
    """상품명에서 색상 추출.
    패턴: '모델명 - 색상 / 스타일코드' → '색상' 반환.
    """
    if " - " not in name:
        return ""
    after_dash = name.split(" - ", 1)[1]
    if " / " in after_dash:
        return after_dash.split(" / ", 1)[0].strip()
    return after_dash.strip()


def extract_model_code(style_code: str) -> Optional[str]:
    """스타일코드에서 모델코드 추출.
    'CW2288-111' → 'CW2288', 'DD8959-001' → 'DD8959'.
    """
    if not style_code or "-" not in style_code:
        return None
    model_code = style_code.rsplit("-", 1)[0].strip()
    return model_code if model_code else None


def extract_model_name(name: str) -> Optional[str]:
    """상품명에서 모델명 추출.
    '에어 포스 1 07 M - 화이트 / CW2288-111' → '에어 포스 1 07 M'.
    """
    if " - " not in name:
        return None
    model_name = name.split(" - ", 1)[0].strip()
    return model_name if model_name else None


def generate_group_key(
    brand: str,
    similar_no: str | None,
    style_code: str | None,
    name: str | None,
) -> Optional[str]:
    """D방식 그룹핑 키 생성.

    우선순위:
    1. similarNo가 0이 아닌 경우 → 'similar_{similarNo}'
    2. style_code에서 모델코드 추출 → 'style_{brand}_{modelCode}'
    3. 상품명에서 ' - ' 앞 모델명 → 'name_{brand}_{modelName}'
    """
    brand_key = (brand or "").lower().replace(" ", "_")

    # 1순위: similarNo
    if similar_no and similar_no != "0":
        return f"similar_{similar_no}"

    # 2순위: style_code 모델코드
    model_code = extract_model_code(style_code or "")
    if model_code and brand_key:
        return f"style_{brand_key}_{model_code}"

    # 3순위: 상품명 패턴
    model_name = extract_model_name(name or "")
    if model_name and brand_key:
        return f"name_{brand_key}_{model_name}"

    return None


def group_products_by_key(products: list[dict]) -> dict[str, list[dict]]:
    """상품 리스트를 group_key별로 그룹핑.
    group_key가 없거나 1건뿐인 경우 singles로 분류.
    반환: { "groups": { key: [products] }, "singles": [products] }
    """
    from collections import defaultdict
    key_map: dict[str, list[dict]] = defaultdict(list)
    no_key: list[dict] = []

    for p in products:
        gk = p.get("group_key")
        if gk:
            key_map[gk].append(p)
        else:
            no_key.append(p)

    groups = {}
    singles = list(no_key)
    for key, items in key_map.items():
        if len(items) >= 2:
            groups[key] = items
        else:
            singles.extend(items)

    return {"groups": groups, "singles": singles}
```

- [ ] **Step 2: 커밋**

```bash
git add backend/backend/domain/samba/collector/grouping.py
git commit -m "feat: 그룹상품 그룹핑 유틸 함수 (group_key 생성, 색상 파싱)"
```

---

## Task 3: 수집 시 group_key 자동 생성

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/collector.py:660-685` (MUSINSA product_data)

- [ ] **Step 1: MUSINSA 수집에 similarNo, group_key, color 추가**

`collector.py` 라인 660-685의 MUSINSA `product_data` 딕셔너리 구성 부분에서:

1. 상세 API 응답(`detail`)에서 `similarNo` 추출:
```python
similar_no = str(detail.get("similarNo", "0"))
```

2. `product_data` 딕셔너리에 필드 추가:
```python
from backend.domain.samba.collector.grouping import generate_group_key, parse_color_from_name

# product_data 안에 추가
"similar_no": similar_no,
"color": parse_color_from_name(detail.get("name", "")),
"group_key": generate_group_key(
    brand=detail.get("brand", ""),
    similar_no=similar_no,
    style_code=detail.get("styleNo", ""),
    name=detail.get("name", ""),
),
```

- [ ] **Step 2: KREAM/기타 소싱처 product_data에도 group_key 추가**

KREAM (라인 827-845, 1200-1220, 1288-1308) 및 기타 (라인 1474-1484):
```python
"similar_no": None,  # KREAM/기타는 similarNo 없음
"color": parse_color_from_name(p_name),
"group_key": generate_group_key(
    brand=brand,
    similar_no=None,
    style_code=style_code,
    name=p_name,
),
```

- [ ] **Step 3: 기존 상품 갱신 시 group_key 재생성**

`collector.py`의 refresh_products 엔드포인트 (라인 1802+)에서, 갱신된 상품에 `group_key`가 없으면 생성:

```python
if not product.group_key:
    from backend.domain.samba.collector.grouping import generate_group_key, parse_color_from_name
    product.group_key = generate_group_key(
        brand=product.brand or "",
        similar_no=product.similar_no,
        style_code=product.style_code or "",
        name=product.name or "",
    )
    if not product.color:
        product.color = parse_color_from_name(product.name or "")
```

- [ ] **Step 4: 백엔드 서버 재시작 후 수집 테스트**

무신사에서 나이키 운동화 수집 → DB에서 `group_key`, `similar_no`, `color` 값 확인.
**재시작 필요: 백엔드**

- [ ] **Step 5: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/collector.py
git commit -m "feat: 수집 시 group_key/similar_no/color 자동 생성"
```

---

## Task 4: SmartStoreClient 그룹상품 API 메서드

**Files:**
- Modify: `backend/backend/domain/samba/proxy/smartstore.py` (SmartStoreClient 클래스 끝부분)

**참고:** SmartStoreClient는 `_call_api(method, path, body, params)` 헬퍼를 사용함. 직접 httpx 호출하지 않고 이 메서드를 사용.

- [ ] **Step 1: 판매옵션 가이드 조회 메서드 추가**

```python
async def get_purchase_option_guides(self, category_id: str) -> list:
    """카테고리별 표준 판매옵션 가이드 조회.
    그룹상품 등록 시 guideId를 결정하기 위해 사용.
    빈 리스트 반환 시 해당 카테고리는 그룹상품 미지원.
    """
    data = await self._call_api(
        "GET", "/v2/standard-purchase-option-guides",
        params={"categoryId": category_id},
    )
    return data.get("contents", [])
```

- [ ] **Step 2: 그룹상품 등록 메서드 추가**

```python
async def register_group_product(self, payload: dict) -> dict:
    """그룹상품 등록 (비동기). 결과는 poll_group_status로 확인."""
    return await self._call_api("POST", "/v2/standard-group-products", body=payload)
```

- [ ] **Step 3: 그룹상품 상태 폴링 메서드 추가**

```python
async def poll_group_status(self, max_wait: int = 300) -> dict:
    """그룹상품 등록/수정 결과 폴링. 최대 max_wait초 대기."""
    import asyncio as _asyncio
    start = time.time()
    while time.time() - start < max_wait:
        result = await self._call_api("GET", "/v2/standard-group-products/status")
        state = result.get("progress", {}).get("state", "")
        if state == "COMPLETED":
            return result
        elif state in ("ERROR", "FAILED"):
            error_msg = result.get("errorMessage", "알 수 없는 오류")
            raise SmartStoreApiError(f"그룹상품 등록 실패: {state} - {error_msg}")
        await _asyncio.sleep(3)
    raise TimeoutError("그룹상품 등록 타임아웃 (5분 초과)")
```

- [ ] **Step 4: 그룹상품 수정/삭제 메서드 추가**

```python
async def update_group_product(self, group_no: int, payload: dict) -> dict:
    """그룹상품 수정."""
    return await self._call_api("PUT", f"/v2/standard-group-products/{group_no}", body=payload)

async def delete_group_product(self, group_no: int) -> dict:
    """그룹상품 삭제."""
    return await self._call_api("DELETE", f"/v2/standard-group-products/{group_no}")
```

- [ ] **Step 5: transform_group_product 변환 메서드 추가**

```python
@staticmethod
def transform_group_product(
    products: list[dict],
    category_id: str,
    guide_id: int,
    account_settings: dict,
) -> dict:
    """수집 상품 리스트 → 그룹상품 API 페이로드 변환.

    Args:
        products: 같은 group_key를 가진 상품 리스트
        category_id: 스마트스토어 리프 카테고리 ID
        guide_id: 판매옵션 가이드 ID
        account_settings: 계정 설정 (A/S, 배송, 할인 등)
    """
    first = products[0]
    brand = first.get("brand", "")

    # 그룹 상품명: 모델명 (색상 제거)
    name = first.get("name", "")
    if " - " in name:
        group_name = name.split(" - ", 1)[0].strip()
    else:
        group_name = name

    # A/S 정보
    as_phone = account_settings.get("asPhone", "상세페이지 참조")
    as_message = account_settings.get("asMessage", "상세페이지 참조")

    # 고시정보 (첫 상품 기준)
    notice = SmartStoreClient._build_product_notice(first)

    # 공통 상세 HTML
    common_detail = first.get("detail_html", "")

    # 개별 상품(specificProducts) 구성
    specific_products = []
    for p in products:
        color = p.get("color", "") or "기본"
        sale_price = p.get("_final_sale_price") or p.get("sale_price") or p.get("original_price", 0)
        stock = account_settings.get("stockQuantity") or 999

        # 옵션에서 재고 계산
        options = p.get("options") or []
        if options:
            total_stock = sum(
                o.get("stock", 0)
                for o in options
                if not o.get("isSoldOut", False)
            )
            if total_stock > 0:
                stock = min(stock, total_stock)

        sp = {
            "standardPurchaseOptions": [
                {"valueName": color}
            ],
            "salePrice": int(sale_price),
            "stockQuantity": stock,
            "images": {
                "representativeImage": {"url": (p.get("images") or [""])[0]},
                "optionalImages": [
                    {"url": url} for url in (p.get("images") or [])[1:5]
                ],
            },
            "deliveryInfo": SmartStoreClient._build_delivery_info(account_settings),
            "originAreaInfo": {"originAreaCode": "03", "content": p.get("origin") or "상세설명참조"},
            "smartstoreChannelProduct": {
                "naverShoppingRegistration": account_settings.get("naverShopping", True),
                "channelProductDisplayStatusType": "ON",
            },
            "sellerCodeInfo": {"sellerManagementCode": p.get("style_code", "")},
        }

        # 기존 상품번호가 있으면 포함 (수정용)
        existing_no = p.get("_origin_product_no")
        if existing_no:
            sp["originProductNo"] = int(existing_no)

        # 할인 정책
        discount_rate = account_settings.get("discountRate")
        if discount_rate and float(discount_rate) > 0:
            sp["immediateDiscountPolicy"] = {
                "discountMethod": {
                    "value": int(float(discount_rate)),
                    "unitType": "PERCENT",
                }
            }

        specific_products.append(sp)

    payload = {
        "groupProduct": {
            "leafCategoryId": category_id,
            "name": group_name,
            "guideId": guide_id,
            "brandName": brand,
            "minorPurchasable": True,
            "saleType": "NEW",
            "productInfoProvidedNotice": notice,
            "afterServiceInfo": {
                "afterServiceTelephoneNumber": as_phone,
                "afterServiceGuideContent": as_message,
            },
            "commonDetailContent": common_detail,
            "specificProducts": specific_products,
            "smartstoreGroupChannel": {},
        }
    }

    # 브랜드 ID
    brand_id = first.get("_brand_id")
    if brand_id:
        payload["groupProduct"]["brandId"] = int(brand_id)

    # SEO 태그
    tags = first.get("tags") or []
    seller_tags = [{"text": t} for t in tags[:10] if t and not t.startswith("__")]
    if seller_tags:
        payload["groupProduct"]["seoInfo"] = {"sellerTags": seller_tags}

    return payload
```

- [ ] **Step 6: 커밋**

```bash
git add backend/backend/domain/samba/proxy/smartstore.py
git commit -m "feat: SmartStoreClient 그룹상품 API 메서드 추가"
```

---

## Task 5: 그룹 미리보기 + 전송 백엔드 API

**Files:**
- Modify: `backend/backend/api/v1/routers/samba/shipment.py`
- Modify: `backend/backend/domain/samba/shipment/service.py`

- [ ] **Step 1: shipment.py에 그룹 미리보기 엔드포인트 추가**

`backend/backend/api/v1/routers/samba/shipment.py` 끝에 추가:

```python
class GroupPreviewRequest(BaseModel):
    product_ids: list[str]
    account_id: str

class GroupPreviewProduct(BaseModel):
    id: str
    name: str
    color: str | None
    sale_price: float | None
    thumbnail: str | None
    existing_product_no: str | None

class GroupPreviewGroup(BaseModel):
    group_key: str
    group_name: str
    products: list[GroupPreviewProduct]

class GroupPreviewResponse(BaseModel):
    groups: list[GroupPreviewGroup]
    singles: list[GroupPreviewProduct]
    delete_count: int
    group_count: int
    single_count: int

@router.post("/group-preview")
async def group_preview(
    body: GroupPreviewRequest,
    session: AsyncSession = Depends(get_read_session_dependency),
):
    """전송 대상 상품에서 그룹핑 가능한 상품을 감지하여 미리보기 반환."""
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    from backend.domain.samba.collector.grouping import group_products_by_key

    repo = SambaCollectedProductRepository(session)
    products = []
    for pid in body.product_ids:
        p = await repo.get_async(pid)
        if p:
            products.append(p.model_dump())

    # search_filter_id별로 분리 후 그룹핑 (다른 검색그룹끼리는 묶지 않음)
    from collections import defaultdict
    by_filter: dict[str, list[dict]] = defaultdict(list)
    for p in products:
        sf_id = p.get("search_filter_id") or "_none"
        by_filter[sf_id].append(p)

    all_groups = {}
    all_singles = []
    for sf_id, sf_products in by_filter.items():
        r = group_products_by_key(sf_products)
        all_groups.update(r["groups"])
        all_singles.extend(r["singles"])

    result = {"groups": all_groups, "singles": all_singles}

    # 그룹별 미리보기 구성
    groups = []
    delete_count = 0
    for key, items in result["groups"].items():
        # 그룹명: 첫 상품명에서 색상 제거
        first_name = items[0].get("name", "")
        group_name = first_name.split(" - ", 1)[0].strip() if " - " in first_name else first_name

        group_products = []
        for item in items:
            market_nos = item.get("market_product_nos") or {}
            existing_no = market_nos.get(body.account_id)
            if existing_no:
                delete_count += 1
            images = item.get("images") or []
            group_products.append(GroupPreviewProduct(
                id=item["id"],
                name=item.get("name", ""),
                color=item.get("color"),
                sale_price=item.get("sale_price"),
                thumbnail=images[0] if images else None,
                existing_product_no=existing_no,
            ))
        groups.append(GroupPreviewGroup(
            group_key=key,
            group_name=group_name,
            products=group_products,
        ))

    singles = []
    for item in result["singles"]:
        images = item.get("images") or []
        market_nos = item.get("market_product_nos") or {}
        singles.append(GroupPreviewProduct(
            id=item["id"],
            name=item.get("name", ""),
            color=item.get("color"),
            sale_price=item.get("sale_price"),
            thumbnail=images[0] if images else None,
            existing_product_no=market_nos.get(body.account_id),
        ))

    return GroupPreviewResponse(
        groups=groups,
        singles=singles,
        delete_count=delete_count,
        group_count=len(groups),
        single_count=len(singles),
    )
```

- [ ] **Step 2: shipment.py에 그룹 전송 엔드포인트 추가**

```python
class GroupSendItem(BaseModel):
    group_key: str
    product_ids: list[str]

class GroupSendRequest(BaseModel):
    groups: list[GroupSendItem]
    singles: list[str]  # 단일 전송 상품 ID
    account_id: str

@router.post("/group-send")
async def group_send(
    body: GroupSendRequest,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """그룹상품 + 단일상품 전송."""
    from backend.domain.samba.shipment.service import SambaShipmentService
    svc = SambaShipmentService(session)

    results = []

    # 1. 그룹상품 전송
    for group in body.groups:
        try:
            result = await svc.transmit_group(
                product_ids=group.product_ids,
                account_id=body.account_id,
            )
            results.append({"group_key": group.group_key, "status": "success", **result})
        except Exception as e:
            results.append({"group_key": group.group_key, "status": "error", "error": str(e)})

    # 2. 단일상품 전송 (기존 방식)
    single_results = []
    if body.singles:
        single_result = await svc.start_update(
            product_ids=body.singles,
            update_items=["price", "stock", "image", "description"],
            target_account_ids=[body.account_id],
        )
        single_results = single_result

    return {
        "group_results": results,
        "single_results": single_results,
    }
```

- [ ] **Step 3: service.py에 transmit_group 메서드 추가**

`backend/backend/domain/samba/shipment/service.py`의 `SambaShipmentService` 클래스에 추가:

**참고:** `SambaShipmentService` 생성자는 `(repo: SambaShipmentRepository, session: AsyncSession)`.
라우터에서 `_get_service(session)` → `SambaShipmentService(SambaShipmentRepository(session), session)` 패턴으로 생성.
`_transmit_product`는 기존 service.py 라인 110에 이미 존재. 카테고리 매핑은 `_transmit_product` 내부 로직(라인 154-189)을 참고하여 유사하게 구현.
가격 계산은 `_transmit_product` 내부 로직(라인 313-341)을 참고.

```python
# 모듈 레벨 동시성 제어 락 (account_id별)
import asyncio as _asyncio
_group_locks: dict[str, _asyncio.Lock] = {}

def _get_group_lock(account_id: str) -> _asyncio.Lock:
    if account_id not in _group_locks:
        _group_locks[account_id] = _asyncio.Lock()
    return _group_locks[account_id]
```

`SambaShipmentService` 클래스에 추가:

```python
async def transmit_group(self, product_ids: list[str], account_id: str) -> dict:
    """그룹상품을 스마트스토어에 등록.

    1. 상품 조회 및 카테고리/가격 준비
    2. guideId 조회 (미지원 시 단일상품 폴백)
    3. 기존 단일상품 삭제
    4. 그룹상품 등록 (비동기)
    5. 폴링으로 결과 확인
    6. groupProductNo + productNos 저장
    """
    from backend.domain.samba.collector.repository import SambaCollectedProductRepository
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.proxy.smartstore import SmartStoreClient

    product_repo = SambaCollectedProductRepository(self.session)
    account_repo = SambaMarketAccountRepository(self.session)

    # 상품 조회
    products = []
    for pid in product_ids:
        p = await product_repo.get_async(pid)
        if p:
            products.append(p)
    if len(products) < 2:
        raise ValueError("그룹상품은 2개 이상의 상품이 필요합니다")

    # 계정 조회
    account = await account_repo.get_async(account_id)
    if not account:
        raise ValueError(f"계정을 찾을 수 없습니다: {account_id}")

    additional = account.additional_fields or {}
    client_id = additional.get("clientId") or account.api_key
    client_secret = additional.get("clientSecret") or account.api_secret
    client = SmartStoreClient(client_id, client_secret)

    # 카테고리 매핑 조회 (첫 상품 기준, _transmit_product 라인 154-189 참고)
    first = products[0]
    from backend.domain.samba.category.repository import SambaCategoryMappingRepository
    cat_repo = SambaCategoryMappingRepository(self.session)
    source_cat = first.category or ""
    mappings = await cat_repo.filter_by_async(source_category=source_cat, limit=1)
    category_id = mappings[0].target_category_code if mappings else None
    if not category_id:
        raise ValueError("카테고리 매핑을 찾을 수 없습니다")

    # account_id별 동시성 락
    lock = _get_group_lock(account_id)
    async with lock:
        # guideId 조회
        guides = await client.get_purchase_option_guides(category_id)
        if not guides:
            # 카테고리 미지원 → 단일상품 폴백
            logger.info(f"카테고리 {category_id} 그룹상품 미지원, 단일상품으로 전송")
            fallback_results = []
            for p in products:
                shipment = await self._transmit_product(
                    p.id, [account_id], ["price", "stock", "image", "description"]
                )
                fallback_results.append(shipment)
            return {
                "group_product_no": None,
                "product_count": len(products),
                "deleted_count": 0,
                "fallback": True,
            }
        guide_id = guides[0].get("guideId")

        # 기존 단일상품 삭제
        deleted_nos = []
        for p in products:
            market_nos = p.market_product_nos or {}
            existing_no = market_nos.get(account_id)
            if existing_no:
                try:
                    origin_no = existing_no
                    if isinstance(existing_no, dict):
                        origin_no = existing_no.get("originProductNo", existing_no)
                    await client.delete_product(str(origin_no))
                    deleted_nos.append(origin_no)
                except Exception:
                    pass  # 삭제 실패 시 스킵

        # 상품 데이터 준비 (가격 계산, 이미지 업로드)
        # 가격 계산은 _transmit_product 라인 313-341 참고
        product_dicts = []
        for p in products:
            pd = p.model_dump()
            # 정책 기반 가격 계산 (기존 _transmit_product 로직 참고)
            policy_id = p.applied_policy_id
            if policy_id:
                from backend.domain.samba.policy.repository import SambaPolicyRepository
                pol_repo = SambaPolicyRepository(self.session)
                policy = await pol_repo.get_async(policy_id)
                if policy:
                    cost = p.sale_price or p.original_price or 0
                    margin = policy.margin_rate or 0
                    shipping = policy.shipping_cost or 0
                    extra = policy.extra_charge or 0
                    final = cost * (1 + margin / 100) + shipping + extra
                    fee_rate = policy.fee_rate or 0
                    if fee_rate > 0:
                        final = final / (1 - fee_rate / 100)
                    pd["_final_sale_price"] = int(round(final, -1))
            if "_final_sale_price" not in pd:
                pd["_final_sale_price"] = p.sale_price or p.original_price or 0

            # 이미지 업로드
            uploaded_images = []
            for img_url in (pd.get("images") or [])[:5]:
                try:
                    naver_url = await client.upload_image_from_url(img_url)
                    uploaded_images.append(naver_url)
                except Exception:
                    uploaded_images.append(img_url)
            pd["images"] = uploaded_images
            product_dicts.append(pd)

        # 페이로드 변환
        payload = SmartStoreClient.transform_group_product(
            products=product_dicts,
            category_id=category_id,
            guide_id=guide_id,
            account_settings=additional,
        )

        # 그룹상품 등록
        await client.register_group_product(payload)

        # 폴링
        try:
            poll_result = await client.poll_group_status(max_wait=300)
        except Exception as e:
            # 그룹 등록 실패 → 삭제된 상품 롤백 (단일상품 재등록)
            logger.error(f"그룹등록 실패, 단일상품으로 롤백: {e}")
            for p in products:
                try:
                    await self._transmit_product(
                        p.id, [account_id], ["price", "stock", "image", "description"]
                    )
                except Exception:
                    pass
            raise e

        # 결과 저장
        group_product_no = poll_result.get("groupProductNo")
        product_nos = poll_result.get("productNos", [])

        for i, p in enumerate(products):
            updates = {"group_product_no": group_product_no}
            if i < len(product_nos):
                pno = product_nos[i]
                market_nos = dict(p.market_product_nos or {})
                market_nos[account_id] = {
                    "originProductNo": pno.get("originProductNo"),
                    "smartstoreChannelProductNo": pno.get("smartstoreChannelProductNo"),
                    "groupProductNo": group_product_no,
                }
                updates["market_product_nos"] = market_nos
                registered = list(p.registered_accounts or [])
                if account_id not in registered:
                    registered.append(account_id)
                updates["registered_accounts"] = registered
            await product_repo.update_async(p.id, **updates)

        return {
            "group_product_no": group_product_no,
            "product_count": len(products),
            "deleted_count": len(deleted_nos),
        }
```

- [ ] **Step 4: 커밋**

```bash
git add backend/backend/api/v1/routers/samba/shipment.py backend/backend/domain/samba/shipment/service.py
git commit -m "feat: 그룹상품 미리보기/전송 백엔드 API"
```

---

## Task 6: 프론트엔드 API + 그룹 미리보기 모달

**Files:**
- Modify: `frontend/src/lib/samba/api.ts`
- Modify: `frontend/src/app/samba/collector/page.tsx`

- [ ] **Step 1: api.ts에 타입 + API 함수 추가**

`frontend/src/lib/samba/api.ts`의 `shipmentApi` 앞에 타입 추가:

```typescript
export interface GroupPreviewProduct {
  id: string
  name: string
  color: string | null
  sale_price: number | null
  thumbnail: string | null
  existing_product_no: string | null
}

export interface GroupPreviewGroup {
  group_key: string
  group_name: string
  products: GroupPreviewProduct[]
}

export interface GroupPreviewResponse {
  groups: GroupPreviewGroup[]
  singles: GroupPreviewProduct[]
  delete_count: number
  group_count: number
  single_count: number
}

export interface GroupSendResponse {
  group_results: { group_key: string; status: string; error?: string; group_product_no?: number }[]
  single_results: Record<string, unknown>
}
```

`shipmentApi` 객체 안에 추가:

```typescript
groupPreview: (productIds: string[], accountId: string) =>
  request<GroupPreviewResponse>(`${SAMBA_PREFIX}/shipments/group-preview`, {
    method: 'POST',
    body: JSON.stringify({ product_ids: productIds, account_id: accountId }),
  }),

groupSend: (groups: { group_key: string; product_ids: string[] }[], singles: string[], accountId: string) =>
  request<GroupSendResponse>(`${SAMBA_PREFIX}/shipments/group-send`, {
    method: 'POST',
    body: JSON.stringify({ groups, singles, account_id: accountId }),
  }),
```

- [ ] **Step 2: collector/page.tsx에 그룹 미리보기 모달 상태 추가**

상단 state 영역에 추가:

```typescript
// 그룹상품 전송
const [showGroupModal, setShowGroupModal] = useState(false)
const [groupPreview, setGroupPreview] = useState<GroupPreviewResponse | null>(null)
const [groupSending, setGroupSending] = useState(false)
const [groupTargetAccount, setGroupTargetAccount] = useState('')
```

import에 추가:
```typescript
import { shipmentApi, type GroupPreviewResponse } from '@/lib/samba/api'
```

- [ ] **Step 3: 그룹 전송 버튼 + 핸들러 추가**

기존 전송 버튼 영역(라인 740 부근)에 그룹전송 버튼 추가:

```typescript
<button
  onClick={async () => {
    if (selectedIds.size === 0) { showAlert('검색그룹을 선택해주세요'); return }
    // 선택된 그룹의 모든 상품 ID 수집을 위해 accounts 필요
    const smartstoreAccounts = accounts.filter(a => a.market_type === 'smartstore')
    if (smartstoreAccounts.length === 0) { showAlert('스마트스토어 계정이 없습니다'); return }
    const accountId = smartstoreAccounts[0].id
    setGroupTargetAccount(accountId)
    // 선택된 그룹의 상품 조회
    try {
      const allProductIds: string[] = []
      for (const filterId of selectedIds) {
        const res = await collectorApi.listProducts(filterId, 0, 10000)
        allProductIds.push(...res.items.map((p: Record<string, string>) => p.id))
      }
      const preview = await shipmentApi.groupPreview(allProductIds, accountId)
      setGroupPreview(preview)
      setShowGroupModal(true)
    } catch (e) {
      showAlert('그룹 미리보기 실패', 'error')
    }
  }}
  disabled={groupSending || selectedIds.size === 0}
  style={{
    background: 'rgba(81,207,102,0.1)',
    border: '1px solid rgba(81,207,102,0.35)',
    color: '#51CF66', padding: '0.3rem 0.75rem', borderRadius: '6px',
    fontSize: '0.8rem', cursor: selectedIds.size === 0 ? 'not-allowed' : 'pointer',
    opacity: selectedIds.size === 0 ? 0.5 : 1,
  }}
>
  {groupSending ? '전송중...' : '그룹상품 전송'}
</button>
```

- [ ] **Step 4: 그룹 미리보기 모달 UI 추가**

페이지 하단 모달 영역에 추가:

```tsx
{showGroupModal && groupPreview && (
  <div style={{
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    background: 'rgba(0,0,0,0.7)', zIndex: 9999,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    <div style={{
      background: '#1a1a1a', borderRadius: '12px', padding: '1.5rem',
      maxWidth: '700px', width: '90%', maxHeight: '80vh', overflow: 'auto',
      border: '1px solid #333',
    }}>
      <h3 style={{ color: '#51CF66', marginBottom: '1rem', fontSize: '1.1rem' }}>
        그룹상품 전송 미리보기
      </h3>

      {groupPreview.groups.map(g => (
        <div key={g.group_key} style={{
          background: 'rgba(81,207,102,0.05)', border: '1px solid rgba(81,207,102,0.2)',
          borderRadius: '8px', padding: '0.75rem', marginBottom: '0.75rem',
        }}>
          <div style={{ color: '#51CF66', fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem' }}>
            [그룹] {g.group_name} ({g.products.length}건)
          </div>
          {g.products.map(p => (
            <div key={p.id} style={{
              display: 'flex', alignItems: 'center', gap: '0.5rem',
              padding: '0.25rem 0', fontSize: '0.8rem', color: '#ccc',
            }}>
              {p.thumbnail && (
                <img src={p.thumbnail} alt="" style={{ width: 32, height: 32, borderRadius: 4, objectFit: 'cover' }} />
              )}
              <span style={{ flex: 1 }}>{p.color || '기본'}</span>
              <span>{p.sale_price?.toLocaleString()}원</span>
              {p.existing_product_no && (
                <span style={{ color: '#FF6B6B', fontSize: '0.7rem' }}>기존삭제</span>
              )}
            </div>
          ))}
        </div>
      ))}

      {groupPreview.singles.length > 0 && (
        <div style={{
          background: 'rgba(255,140,0,0.05)', border: '1px solid rgba(255,140,0,0.2)',
          borderRadius: '8px', padding: '0.75rem', marginBottom: '0.75rem',
        }}>
          <div style={{ color: '#FF8C00', fontWeight: 600, marginBottom: '0.5rem', fontSize: '0.9rem' }}>
            [단일] {groupPreview.singles.length}건
          </div>
          {groupPreview.singles.map(p => (
            <div key={p.id} style={{ fontSize: '0.8rem', color: '#ccc', padding: '0.15rem 0' }}>
              {p.name} - {p.sale_price?.toLocaleString()}원
            </div>
          ))}
        </div>
      )}

      {groupPreview.delete_count > 0 && (
        <div style={{ color: '#FF6B6B', fontSize: '0.8rem', marginBottom: '1rem' }}>
          기존 단일등록 {groupPreview.delete_count}건 삭제 후 그룹상품으로 재등록됩니다
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
        <button
          onClick={() => setShowGroupModal(false)}
          style={{
            background: 'rgba(255,255,255,0.05)', border: '1px solid #444',
            color: '#888', padding: '0.4rem 1rem', borderRadius: '6px', cursor: 'pointer',
          }}
        >
          취소
        </button>
        <button
          onClick={async () => {
            setGroupSending(true)
            try {
              const groups = groupPreview.groups.map(g => ({
                group_key: g.group_key,
                product_ids: g.products.map(p => p.id),
              }))
              const singles = groupPreview.singles.map(p => p.id)
              const res = await shipmentApi.groupSend(groups, singles, groupTargetAccount)
              const successCount = res.group_results.filter(r => r.status === 'success').length
              const failCount = res.group_results.filter(r => r.status === 'error').length
              showAlert(`그룹상품 ${successCount}건 성공, ${failCount}건 실패`, successCount > 0 ? 'success' : 'error')
              setShowGroupModal(false)
              load()
            } catch (e) {
              showAlert('그룹 전송 실패', 'error')
            }
            setGroupSending(false)
          }}
          disabled={groupSending}
          style={{
            background: groupSending ? 'rgba(81,207,102,0.1)' : 'rgba(81,207,102,0.2)',
            border: '1px solid rgba(81,207,102,0.5)',
            color: '#51CF66', padding: '0.4rem 1rem', borderRadius: '6px',
            cursor: groupSending ? 'not-allowed' : 'pointer',
          }}
        >
          {groupSending ? '전송중...' : `전송 (그룹 ${groupPreview.group_count}건 + 단일 ${groupPreview.single_count}건)`}
        </button>
      </div>
    </div>
  </div>
)}
```

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/lib/samba/api.ts frontend/src/app/samba/collector/page.tsx
git commit -m "feat: 그룹상품 전송 미리보기 모달 UI"
```

---

## Task 7: 상품관리 페이지 그룹 배지

**Files:**
- Modify: `frontend/src/app/samba/products/page.tsx`

- [ ] **Step 1: 상품 목록에 그룹 배지 표시**

상품 카드 렌더링 영역에서 `group_key`가 있는 상품에 배지 추가:

```tsx
{product.group_key && (
  <span style={{
    background: 'rgba(81,207,102,0.15)',
    color: '#51CF66',
    padding: '0.1rem 0.4rem',
    borderRadius: '4px',
    fontSize: '0.65rem',
    marginLeft: '0.25rem',
  }}>
    그룹
  </span>
)}
{product.group_product_no && (
  <span style={{
    background: 'rgba(76,154,255,0.15)',
    color: '#4C9AFF',
    padding: '0.1rem 0.4rem',
    borderRadius: '4px',
    fontSize: '0.65rem',
    marginLeft: '0.25rem',
  }}>
    그룹등록완료
  </span>
)}
```

- [ ] **Step 2: 커밋**

```bash
git add frontend/src/app/samba/products/page.tsx
git commit -m "feat: 상품관리 그룹 배지 표시"
```

---

## Task 8: 통합 테스트 및 마무리

- [ ] **Step 1: 백엔드 서버 재시작**

```bash
cd backend && .venv/Scripts/python.exe run.py
```
**재시작 필요: 백엔드**

- [ ] **Step 2: 프론트엔드 재시작**

```bash
cd frontend && pnpm dev
```
**재시작 필요: 프론트엔드**

- [ ] **Step 3: E2E 테스트**

1. 무신사에서 나이키 운동화 검색 → 수집
2. 수집된 상품에 `group_key`, `color` 값이 있는지 확인
3. 검색그룹 선택 → "그룹상품 전송" 버튼 클릭
4. 미리보기 모달에서 그룹핑 결과 확인
5. 전송 → 스마트스토어 셀러센터에서 그룹상품 확인

- [ ] **Step 4: 최종 커밋**

```bash
git add -A
git commit -m "feat: 스마트스토어 그룹상품 완전자동화 통합 완료"
```
