# 롯데ON Open API — 상품 등록 참조

## 기본 정보

- **인증**: Bearer {apiKey}
- **기본 URL**: `https://openapi.lotteon.com`
- **카테고리/브랜드 URL**: `https://onpick-api.lotteon.com`
- **필수 헤더**: Accept-Language: ko, X-Timezone: GMT+09:00

## API 경로 매핑

| 기능 | 경로 | 메서드 |
|------|------|--------|
| 인증 (거래처 조회) | `/v1/openapi/common/v1/identity` | GET |
| 상품 등록 | `/v1/openapi/product/v1/product/registration/request` | POST |
| 상품 수정 | `/v1/openapi/product/v1/product/modification/request` | POST |
| 상품 조회 | `/v1/openapi/product/v1/product/detail` | POST (body: trGrpCd, trNo, spdNo) |
| 재고 변경 | `/v1/openapi/product/v1/item/stock/change` | POST |
| 가격 변경 | `/v1/openapi/product/v1/item/price/change` | POST |
| 판매상태 변경 | `/v1/openapi/product/v1/product/status/change` | POST |
| 표준카테고리 | `onpick-api.lotteon.com/cheetah/econCheetah.ecn?job=cheetahStandardCategory` | GET |
| 브랜드 검색 | `onpick-api.lotteon.com/cheetah/econCheetah.ecn?job=cheetahBrnd` | GET |

## 거래처 인증 흐름

1. `GET /v1/openapi/common/v1/identity` 호출
2. 응답에서 `trGrpCd`, `trNo` 추출
3. 이후 모든 상품 API에 이 값 사용

## 필수 필드 (상품 등록)

- `trGrpCd`, `trNo` — 거래처 코드 (identity API에서 자동 획득)
- `scatNo` — 표준카테고리번호
- `spdNm` — 상품명 (최대 150자)
- `slStrtDttm`, `slEndDttm` — 판매 시작/종료 일시
- `owhpNo` — 출고지번호 (거래처 API 사전 등록)
- `dvCstPolNo` — 배송비정책번호
- `rtrpNo` — 회수지번호
- `prstPckPsbYn`, `prstMsgPsbYn` — 선물포장/메시지 여부

## 이미지 필드명

- `pdFileLst[].origImgFileNm` — 상품 파일
- `itmImgLst[].origImgFileNm` — 단품 이미지

## 카테고리 구조

- **표준카테고리** (`scatNo`): `BC43030200` 형태 — cheetah API의 `std_cat_id`
- **전시카테고리** (`dcatLst[].lfDcatNo`): `FC18100502` 형태 — cheetah API 응답의 `disp_list[].disp_cat_id`
- `scatNo`에는 표준카테고리, `dcatLst`에는 전시카테고리를 넣어야 함
- 하위 카테고리 조회: `filter_2`로 부모 ID 지정 (filter_1은 단건 조회)

## 에러 대응

- 401: API Key 무효 또는 만료
- 403: IP 미등록 (롯데ON 파트너센터에서 IP 등록 필요)
- 404: API 경로 오류 (이 문서의 경로 확인)
- 429: 호출 한도 초과

## 주의사항

- `get_product()`는 **POST** 방식 (body에 spdNo 전달)
- 카테고리/브랜드는 **별도 도메인** (`onpick-api.lotteon.com`)
- `brdNo`는 브랜드번호(숫자), 텍스트명이 아님 → 브랜드 API로 사전 검색 필요
