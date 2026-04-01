---
name: ESM Plus (ESM Trading API) 조사 결과
description: ESM Plus(G마켓/옥션) Seller API v2 인증방식, 엔드포인트, 상품등록 필수 파라미터, Rate Limit, 권한신청 절차
type: project
---

## 공식 API 문서 위치
- 메인: https://etapi.gmarket.com/
- 인증가이드: https://etapi.gmarket.com/pages/API-가이드
- 기술문의: etapihelp@gmail.com / et_api@ebay.co.kr

## 인증 방식: JWT (HMAC-SHA256)

### JWT Header
```json
{
  "alg": "HS256",
  "typ": "JWT",
  "kid": "ESM+ 마스터ID"  // hostingId에 해당
}
```

### JWT Payload
```json
{
  "iss": "www.esmplus.com",   // 또는 클라이언트 도메인
  "sub": "sell",
  "aud": "sa.esmplus.com",
  "ssi": "A:옥션판매자ID,G:지마켓판매자ID"  // 단독 지정도 가능
}
```

### Signature 생성
```
HMAC-SHA256(base64UrlEncode(header) + "." + base64UrlEncode(payload), secretKey)
```

### HTTP 헤더 전송
```
Authorization: Bearer {JWT토큰}
```

**Why:** hostingId = kid 필드(ESM+ 마스터ID), secretKey = HMAC-SHA256 서명 키
**How to apply:** JWT 생성 시 kid에 hlccorp, secretKey M2U0NWFhMmYtZGY0MS00Yjdk 사용

---

## 지마켓/옥션 구분 파라미터

| 값 | 마켓 |
|----|------|
| siteType: 1, siteId: "1" | 옥션(IAC) |
| siteType: 2, siteId: "2" | 지마켓(GMKT) |
| ssi 필드: "A:ID" | 옥션 단독 |
| ssi 필드: "G:ID" | 지마켓 단독 |
| ssi 필드: "A:ID,G:ID" | 양사 동시 |

---

## 핵심 엔드포인트 (baseUrl: https://sa2.esmplus.com)

### 상품 CRUD
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /item/v1/goods | 상품 등록 |
| PUT | /item/v1/goods/{goodsNo} | 상품 수정 (전체 필드 재전송 필요) |
| GET | /item/v1/goods/{goodsNo} | 상품 조회 |
| DELETE | /item/v1/goods/{goodsNo} | 상품 삭제 (판매중지 상태 선행 필수) |
| POST | /item/v1/goods/convert-legacy-goods | 구버전 상품 전환 |

### 가격/재고/판매상태
| 메서드 | 경로 | 설명 |
|--------|------|------|
| PUT | /item/v1/goods/{goodsNo}/sell-status | 가격/재고/판매상태 수정 |
| GET | /item/v1/goods/{goodsNo}/sell-status | 판매상태 조회 |

sell-status 필드:
- isSell.gmkt / isSell.iac: true(판매)/false(판매중지)
- Price.gmkt / Price.iac: 가격 (10원~10억)
- Stock.gmkt / Stock.iac: 재고 (1~99999)
- SellingPeriod: -1, 0, 15, 30, 60, 90, 365

### 이미지
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /item/v1/goods/{goodsNo}/images | 이미지 수정 |

이미지 방식: URL 방식 (http/https URL 직접 전달, multipart 업로드 아님)
- BasicImage.URL: 대표이미지 (필수, 최소 600x600, 권장 1000x1000)
- AdditionalImage1~14: 추가이미지 최대 14장 (순차 입력 필수)

### 카테고리
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /item/v1/categories/site-cats | 전체 대분류 조회 |
| GET | /item/v1/categories/site-cats/{siteCatCode} | 하위 카테고리 조회 |

- isLeaf: true인 카테고리만 상품등록 가능
- 옥션은 isLeaf=true 카테고리만 등록 허용

### 목록 조회
| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | /item/v1/goods/search | 상품 목록 조회 (최대 30회/분) |
| GET | /item/v1/goods/{goodsNo}/status | 상품번호 상태 조회 |
| GET | /item/v1/site-goods/{siteGoodsNo}/goods-no | 사이트 상품번호 → 마스터번호 변환 |

### 기타 참조 데이터
| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /item/v1/origin/codes | 원산지 코드 목록 |
| GET | /item/v1/official-notice/groups | 고시 정보 그룹 조회 |
| GET | /item/v1/official-notice/groups/{officialNoticeNo}/codes | 고시 정보 항목 조회 |

---

## 상품 등록 필수 필드 구조

```json
{
  "itemBasicInfo": {
    "goodsName": {
      "kor": "상품명 (최대 100 bytes)"
    },
    "category": {
      "site": [
        {
          "siteType": 1,         // 1=옥션, 2=지마켓
          "catCode": "leaf카테고리코드"
        }
      ]
    }
  },
  "itemAddtionalInfo": {
    "price": {
      "Gmkt": 10000,           // 지마켓 가격
      "Iac": 10000             // 옥션 가격
    },
    "stock": {
      "Gmkt": 100,
      "Iac": 100
    },
    "shipping": {
      "type": 1,               // 1=택배, 2=직접
      "companyNo": 123,        // 택배사 코드
      "policy": {
        "placeNo": 456         // 배송지 번호
      }
    },
    "officialNoticeNo": 789,   // 고시 정보 번호
    "descriptions": {
      "kor": {
        "html": "<상품 상세 HTML>"
      }
    }
  }
}
```

---

## 상품 등록/수정 응답 형식

```json
// 성공
{
  "goodsNo": 12345,             // 마스터 상품번호
  "siteDetail": {
    "gmkt": {"SiteGoodsNo": "G상품번호", "SiteGoodsComment": ""},
    "iac": {"SiteGoodsNo": "A상품번호", "SiteGoodsComment": ""}
  },
  "resultCode": 0,
  "message": null
}

// 실패
{
  "resultCode": 1000,
  "message": "오류 메시지"
}
```

---

## Rate Limit

| API | 제한 |
|-----|------|
| 상품 목록 조회 | 30회/분 |
| 주문 조회 | 1회/5초 (판매자ID 기준) |
| 상품 등록 | 100건/분 (일반 셀러) |

- 등록 후 약 2~3분 경과 후 수정 API 호출 가능
- Rate Limit 초과 시 resultCode: 3000 반환

---

## 삭제 관련 중요 규칙

**삭제 전 판매중지 필수**: isSell.gmkt/iac = false 먼저 호출 → 이후 DELETE 가능
판매중지 상태 1개월 유지 시 자동 삭제됨

---

## 권한 신청 절차

### 셀러 측 설정 (판매자가 직접 수행)
1. ESM PLUS 로그인
2. [ESM+ 계정(ID) 관리] → [ESM API 관리]
3. [호스팅 또는 Selling Tool 사용] → "사용함" 설정
4. 서비스제공사 선택 (상품/주문 각각 최대 5개)
5. [API 사용신청] 클릭

### 셀링툴(삼바웨이브) 측 설정
- ESM+ 메뉴 직접 오픈되지 않는 경우: et_api@ebay.co.kr로 마스터ID + SecretKey 발급 요청
- hostingId = ESM+ 마스터ID (셀링툴 업체의 마스터ID)
- 판매자별로 ssi에 옥션ID/지마켓ID를 넣어 토큰 생성

**Why:** ESM+ Trading API는 셀링툴사(삼바웨이브)가 마스터ID+SecretKey를 보유하고, 판매자가 ESM+에서 해당 셀링툴에 권한을 부여하는 구조
**How to apply:** 삼바웨이브의 hostingId(hlccorp)는 kid에, 판매자의 옥션/지마켓ID는 ssi에 매 요청마다 동적으로 설정
