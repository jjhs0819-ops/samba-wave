# 취소승인 기능 확장 - 쿠팡/11번가 지원 추가

## 개요

현재 `approve-cancel` 엔드포인트는 스마트스토어만 지원합니다. 쿠팡과 11번가에도 취소승인을 수행할 수 있도록 프록시 메서드 추가 및 라우터 분기 로직을 확장합니다.

## 변경 대상 파일

| 파일 | 변경 내용 |
|------|----------|
| `backend/backend/domain/samba/proxy/coupang.py` | `approve_cancel` 메서드 추가 |
| `backend/backend/domain/samba/proxy/elevenst.py` | `approve_cancel` 메서드 추가 |
| `backend/backend/api/v1/routers/samba/order.py` | `approve_cancel` 엔드포인트에 쿠팡/11번가 분기 추가 |

---

## 1. 쿠팡 프록시 - `approve_cancel` 메서드 추가

**파일:** `backend/backend/domain/samba/proxy/coupang.py`

**쿠팡 Wing API 취소승인 엔드포인트:**
- `PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approve`
- 쿠팡은 취소/반품을 `returnRequests`로 통합 관리하며, 취소승인 시 `approve` 엔드포인트 사용

**추가 위치:** `get_product` 메서드 아래, `transform_product` 메서드 위

```python
  # ------------------------------------------------------------------
  # 주문 취소승인
  # ------------------------------------------------------------------

  async def approve_cancel(
    self,
    receipt_id: str,
    cancel_count: int = 1,
  ) -> dict[str, Any]:
    """취소요청 승인.

    Coupang Wing API:
    PUT /v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approve

    Args:
      receipt_id: 취소/반품 접수번호 (receiptId). 주문 동기화 시 order_number에 저장된 값.
      cancel_count: 취소 수량 (기본 1)
    """
    path = (
      f"/v2/providers/openapi/apis/api/v4/vendors/"
      f"{self.vendor_id}/returnRequests/{receipt_id}/approve"
    )
    result = await self._call_api("PUT", path)
    logger.info(f"[쿠팡] 취소승인 완료: receiptId={receipt_id}")
    return result
```

---

## 2. 11번가 프록시 - `approve_cancel` 메서드 추가

**파일:** `backend/backend/domain/samba/proxy/elevenst.py`

**11번가 셀러 API 취소승인 엔드포인트:**
- `PUT /rest/prodservices/claims/{claimNo}/accept` (취소요청 승인)
- 11번가는 XML 기반 API이며, 클레임 번호(`claimNo`)로 취소승인 처리

**추가 위치:** `get_product` 메서드 아래, `transform_product` 메서드 위

```python
  # ------------------------------------------------------------------
  # 주문 취소승인
  # ------------------------------------------------------------------

  async def approve_cancel(self, claim_no: str) -> dict[str, Any]:
    """취소요청 승인.

    11번가 셀러 API:
    PUT /rest/prodservices/claims/{claimNo}/accept

    Args:
      claim_no: 클레임 번호. 주문 동기화 시 order_number에 저장된 값.
    """
    result = await self._call_api("PUT", f"/claims/{claim_no}/accept")
    logger.info(f"[11번가] 취소승인 완료: claimNo={claim_no}")
    return result
```

---

## 3. 라우터 - `approve_cancel` 엔드포인트 확장

**파일:** `backend/backend/api/v1/routers/samba/order.py`

기존 `approve_cancel` 함수를 아래 코드로 **전체 교체**합니다.

**기존 코드 (교체 대상):** 111행 ~ 164행

```python
@router.post("/{order_id}/approve-cancel")
async def approve_cancel(
    order_id: str,
    session: AsyncSession = Depends(get_write_session_dependency),
):
    """취소요청 주문에 대해 마켓 취소승인 실행."""
    from backend.domain.samba.account.repository import SambaMarketAccountRepository
    from backend.domain.samba.forbidden.repository import SambaSettingsRepository

    svc = _write_service(session)
    order = await svc.get_order(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="주문을 찾을 수 없습니다")

    if not order.order_number:
        raise HTTPException(status_code=400, detail="상품주문번호가 없습니다")

    # 마켓 계정 조회
    if not order.channel_id:
        raise HTTPException(status_code=400, detail="마켓 계정 정보가 없습니다")

    account_repo = SambaMarketAccountRepository(session)
    account = await account_repo.get_async(order.channel_id)
    if not account:
        raise HTTPException(status_code=400, detail="마켓 계정을 찾을 수 없습니다")

    # ── 스마트스토어 ──
    if account.market_type == "smartstore":
        from backend.domain.samba.proxy.smartstore import SmartStoreClient
        extras = account.additional_fields or {}
        client_id = extras.get("clientId", "") or account.api_key or ""
        client_secret = extras.get("clientSecret", "") or account.api_secret or ""
        if not client_id or not client_secret:
            settings_repo = SambaSettingsRepository(session)
            row = await settings_repo.find_by_async(key="store_smartstore")
            if row and isinstance(row.value, dict):
                client_id = client_id or row.value.get("clientId", "")
                client_secret = client_secret or row.value.get("clientSecret", "")
        if not client_id or not client_secret:
            raise HTTPException(status_code=400, detail="스마트스토어 인증정보 없음")

        client = SmartStoreClient(client_id, client_secret)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    # ── 쿠팡 ──
    elif account.market_type == "coupang":
        from backend.domain.samba.proxy.coupang import CoupangClient
        extras = account.additional_fields or {}
        access_key = extras.get("accessKey", "") or account.api_key or ""
        secret_key = extras.get("secretKey", "") or account.api_secret or ""
        vendor_id = extras.get("vendorId", "") or extras.get("vendorCode", "") or ""
        if not access_key or not secret_key or not vendor_id:
            raise HTTPException(status_code=400, detail="쿠팡 인증정보 없음 (accessKey, secretKey, vendorId 필요)")

        client = CoupangClient(access_key, secret_key, vendor_id)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    # ── 11번가 ──
    elif account.market_type == "11st":
        from backend.domain.samba.proxy.elevenst import ElevenstClient
        api_key = account.api_key or ""
        if not api_key:
            extras = account.additional_fields or {}
            api_key = extras.get("apiKey", "")
        if not api_key:
            raise HTTPException(status_code=400, detail="11번가 인증정보 없음 (apiKey 필요)")

        client = ElevenstClient(api_key)
        try:
            await client.approve_cancel(order.order_number)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"취소승인 실패: {e}")

    else:
        raise HTTPException(status_code=400, detail=f"{account.market_type} 취소승인 미지원")

    # DB 상태 업데이트 (공통)
    await svc.update_order(order_id, {
        "shipping_status": "취소완료",
    })
    logger.info(f"[취소승인] {order.order_number} ({account.market_type}) 취소승인 완료")
    return {"ok": True, "message": f"취소승인 완료 ({account.market_type})"}
```

---

## 마켓별 취소승인 API 정리

| 마켓 | API 엔드포인트 | HTTP 메서드 | 인증 방식 | 식별자 |
|------|---------------|------------|----------|--------|
| 스마트스토어 | `/v1/pay-order/seller/product-orders/{productOrderId}/claim/cancel/approve` | POST | OAuth2 Bearer | productOrderId |
| 쿠팡 | `/v2/providers/openapi/apis/api/v4/vendors/{vendorId}/returnRequests/{receiptId}/approve` | PUT | HMAC-SHA256 | receiptId (취소접수번호) |
| 11번가 | `/rest/prodservices/claims/{claimNo}/accept` | PUT | openapikey 헤더 | claimNo (클레임번호) |

## 변경 영향도

- **프론트엔드:** 변경 불필요. 기존 `approve-cancel` 엔드포인트를 동일하게 호출하면 백엔드가 마켓 타입에 따라 자동 분기합니다.
- **DB:** 변경 불필요. 기존 `order_number` 필드에 각 마켓의 주문/클레임 식별자가 저장되어 있으므로 그대로 활용합니다.
- **재시작 필요:** 백엔드 서버만 재시작하면 됩니다.
