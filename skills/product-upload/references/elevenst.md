# 11번가 OpenAPI 상세 참조

소스 파일: `backend/backend/domain/samba/proxy/elevenst.py`

---

## 인증 방식

- **방식:** 32자리 Open API Key (헤더 전달)
- **헤더:** `openapikey: {apiKey}`
- **Content-Type:** `text/xml; charset=UTF-8`
- **Accept:** `application/xml`

```python
headers = {
  "openapikey": self.api_key,
  "Content-Type": "text/xml; charset=UTF-8",
  "Accept": "application/xml",
}
```

**설정 조회:** `samba_settings` 테이블 `store_11st` 키 → `apiKey` 값

---

## API 엔드포인트

| 동작 | 메서드 | 경로 |
|------|--------|------|
| 상품 등록 | `POST` | `/rest/prodservices/product` |
| 상품 조회 | `GET` | `/rest/prodservices/product/{productCode}` |
| 상품 수정 | `PUT` | `/rest/prodservices/product/{productCode}` |

**BASE_URL:** `https://api.11st.co.kr/rest/prodservices`
**타임아웃:** 30초

---

## transform_product() 출력 XML 구조

`ElevenstClient.transform_product(product, category_code)` 의 반환값:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Product>
  <sellerPrdCd></sellerPrdCd>
  <prdNm>{name, XML 이스케이프}</prdNm>
  <prdStatCd>01</prdStatCd>
  <dispCtgrNo>{category_code}</dispCtgrNo>
  <brand>{brand, XML 이스케이프}</brand>
  <selPrc>{int(sale_price)}</selPrc>
  <selMthdCd>01</selMthdCd>
  <aplBgnDy>{등록일 yyyyMMdd}</aplBgnDy>
  <aplEndDy>{등록일+1년 yyyyMMdd}</aplEndDy>
  <prdWeight>0</prdWeight>
  <dlvCnFee>0</dlvCnFee>
  <dlvGrntYn>Y</dlvGrntYn>
  <dlvCstInstBasiCd>DV_FREE</dlvCstInstBasiCd>
  <rtngdDlvCst>5000</rtngdDlvCst>
  <exchDlvCst>5000</exchDlvCst>
  <dlvBsPlc>경상북도 경주시 송효동 302-4</dlvBsPlc>
  <rtngBsPlc>경상북도 경주시 송효2길 40-13</rtngBsPlc>
  <orgnNm>{origin || "기타", XML 이스케이프}</orgnNm>
  <taxTypCd>01</taxTypCd>
  <minorSelCnYn>N</minorSelCnYn>
  <htmlDetail><![CDATA[{detail_html || "<p>{name}</p>"}]]></htmlDetail>
  <imageUrl>{images[0], XML 이스케이프}</imageUrl>
  <addImageUrl1>{images[1], XML 이스케이프}</addImageUrl1>
  <addImageUrl2>{images[2], XML 이스케이프}</addImageUrl2>
  <addImageUrl3>{images[3], XML 이스케이프}</addImageUrl3>
  <sellerOptions>
    <sellerOption>
      <optionName>옵션</optionName>
      <optionValue>{option.name || option.size || "기본", XML 이스케이프}</optionValue>
      <stockQty>{option.stock || 999}</stockQty>
      <sellerOptionPrice>0</sellerOptionPrice>
    </sellerOption>
  </sellerOptions>
  <asDetail>상세페이지 참조</asDetail>
  <rtngExchDetail>상세페이지 참조</rtngExchDetail>
</Product>
```

---

## 필드 매핑 테이블

| CollectedProduct | 11번가 XML 태그 | 변환 로직 | 폴백 |
|---|---|---|---|
| `name` | `<prdNm>` | XML 이스케이프 | (필수) |
| `sale_price` | `<selPrc>` | `int()` | (필수) |
| `images[0]` | `<imageUrl>` | XML 이스케이프 | (필수) |
| `images[1:4]` | `<addImageUrl1~3>` | XML 이스케이프 | (선택) |
| `detail_html` | `<htmlDetail>` | `<![CDATA[...]]>` 래핑 | `<p>{name}</p>` |
| `brand` | `<brand>` | XML 이스케이프 | `""` |
| `origin` | `<orgnNm>` | XML 이스케이프 | `"기타"` |
| `options[].name/size` | `<optionValue>` | XML 이스케이프 | `"기본"` |
| `options[].stock` | `<stockQty>` | 그대로 | `999` |
| `category_code` | `<dispCtgrNo>` | 그대로 | (필수) |

### 고정값

| XML 태그 | 값 | 설명 |
|---|---|---|
| `<prdStatCd>` | `01` | 판매중 |
| `<selMthdCd>` | `01` | 직접판매 |
| `<dlvCstInstBasiCd>` | `DV_FREE` | 무료배송 |
| `<rtngdDlvCst>` | `5000` | 반품 배송비 |
| `<exchDlvCst>` | `5000` | 교환 배송비 |
| `<dlvBsPlc>` | `경상북도 경주시 송효동 302-4` | 출고지 |
| `<rtngBsPlc>` | `경상북도 경주시 송효2길 40-13` | 반품지 |
| `<taxTypCd>` | `01` | 과세 |
| `<minorSelCnYn>` | `N` | 미성년자 구매 불가 |

---

## 제한사항

| 항목 | 제한 |
|------|------|
| 상품명 길이 | 100자 |
| 대표 이미지 | 1장 (외부 URL 직접 사용) |
| 추가 이미지 | 최대 3장 (`images[1:4]`) |
| 이미지 형식 | JPG/PNG |
| 상세설명 | HTML (`<![CDATA[]]>` 래핑) |
| 옵션 | `<sellerOption>` 배열 |
| 배송비 | 무료 고정 (`DV_FREE`) |
| 반품/교환비 | 각 5,000원 |
| 유효기간 | 등록일 ~ 등록일+1년 (자동 계산) |
| 데이터 포맷 | XML |

---

## XML 이스케이프

`_escape_xml()` 함수 (elevenst.py 라인 188~196):

```python
def _escape_xml(text: str) -> str:
  return (
    text.replace("&", "&amp;")
    .replace("<", "&lt;")
    .replace(">", "&gt;")
    .replace('"', "&quot;")
    .replace("'", "&apos;")
  )
```

**주의:** 상품명, 브랜드, 옵션값 등 모든 텍스트 필드에 적용 필수.
옵션값에 `&`나 `<`가 포함되면 XML 파싱 에러 발생.

---

## 응답 파싱

XML 응답을 dict로 변환:
- `resultCode` == `200` 또는 `0` → 성공
- 그 외 → `ElevenstApiError` 발생

```python
result_code = data.get("resultCode", "") or data.get("ResultCode", "")
if result_code and str(result_code) != "200" and str(result_code) != "0":
  msg = data.get("resultMessage", "") or data.get("message", "")
  raise ElevenstApiError(f"API 에러 ({result_code}): {msg}")
```

---

## 디스패처 연동

`dispatcher.py:_handle_11st()` (라인 236~261):

1. `samba_settings` 테이블에서 `store_11st` 키 조회
2. `apiKey` 추출
3. 카테고리 코드 숫자 검증 (`category_id.isdigit()`)
4. `ElevenstClient.transform_product()` → XML 생성
5. `client.register_product(xml_data)` 호출

**이미지 업로드:** 별도 업로드 없음. 외부 URL 직접 사용.
**삭제/판매중지:** 미구현 (MARKET_DELETE_HANDLERS에 없음)
