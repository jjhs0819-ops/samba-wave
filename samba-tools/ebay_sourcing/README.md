# 번장 → eBay 소싱/등록 툴 (안정 위치)

> 이전엔 이 스크립트들이 세션 임시폴더(temp scratchpad)에 있어 매번 사라지고 재작성했음.
> 여기로 옮겨 영구 보관. 규칙·상세는 메모리 `project_ebay_pokemon_sourcing.md` 참조.

## 계정/대상
- **K-TCG Vault = 캐논리츠 = seller byunggi** (`ma_01KXQCB67RZBBE99H8TM2J4K8J`) — 광고/marketing 재동의 완료
- TCG Authenticore = 마늘 (`ma_01KWVPQYKN...`) — marketing 미승인(광고 skip)

## 절대 규칙 [중요]
1. **insertion fee**: 새 리스팅마다 과금. **이미 있는 상품은 revise**(resource.py). 진짜 신규만 register.py.
2. **최초 등록**: eBay 리서치 SOLD 탭 베스트셀러 **Sell Similar 값 복제**(title/category/aspects) → 상위노출. 쌩등록 금지.
3. **번장 후보**: `saleStatus == SELLING`만. SOLD_OUT/RESERVED(예약중)/삭제 제외. 구매글(삽니다/매입)·일괄/LOT·일판 제외.
4. **사진**: 대표 = tcg_vault 하단 가로 포스트잇(Gemini). 나머지 = 번장 추가이미지. **생성 후 반드시 육안검증**(상품 사라짐/포스트잇만/가림).
5. 품절≠삭제. 다른셀러로 재소싱(번장 재고 대개 1개).

## 실행 환경 (분담)
- **호스트**(웨일 CDP 9223): `search.py`, `sweep.py`, `match_substitute.py`
  - `backend/.venv/Scripts/python.exe samba-tools/ebay_sourcing/sweep.py`
  - `... search.py "메가 이상해꽃 SAR"`
  - **[2026-08-06] 호스트→DB(127.0.0.1:5432) 직접연결 TLS 깨짐**(asyncpg `ConnectionDoesNotExistError`, 원인 미규명). DB 필요한 호스트 스크립트는 컨테이너에서 dump→`docker cp`로 빼서 읽는 우회 필수. Whale(CDP)만 호스트 직접 가능.
- **컨테이너**(backend 모듈: DB/eBay/Gemini): `postit.py`, `resource.py`, `register.py`, `apply_substitute.py`, `suspend_batch.py`, `price_sync.py`, `set_stock.py`
  - `docker cp samba-tools/ebay_sourcing/<f>.py local-samba-api-1:/tmp/<f>.py`
  - `docker exec local-samba-api-1 /app/backend/.venv/bin/python3 /tmp/<f>.py ...`

## 표준 흐름
### 품절 대체 — 단건 (기존 리스팅 revise, 수수료0)
1. `sweep.py` → 품절 상품 목록
2. `search.py "<카드명>"` → SELLING 다른셀러 pid 선정
3. `postit.py "<새pid 이미지URL>" /tmp/postit.jpg` → docker cp 빼서 **육안검증**
4. `resource.py <product_id> <새pid> <새원가>` → 기존 리스팅 revise (★새리스팅 아님 확인)

### 품절 대체 — 배치 (사이클, "사이클 돌려")
1. `sweep.py` → problems.json(품절 목록)
2. `match_substitute.py`(구 `_cyc_match.py`) → problems.json 읽어 후보 자동탐색 → candidates.json
   - **[중요·2026-08-06 사고]** 콤마 포함/"교환·제시·네고·판교" 키워드 제목은 가격 신뢰불가로 자동제외(`feedback_ebay_bunjang_negotiable_price_trap` 메모리). 카드번호 없는 후보는 사람이 원본·신규 사진 페어 대조 필수(`feedback_ebay_promo_variant_name_blind`)
3. 몽타주 만들어 **육안검증**(사람 승인 후 진행)
4. `apply_substitute.py` → candidates.json 일괄 revise(수수료0)
5. 매칭실패/비카드는 `suspend_batch.py`로 판매중지(삭제 아님)

### 신규 등록 (진짜 없을 때만)
1. eBay 리서치 Sell Similar 값 확보(title/category/aspects)
2. `postit.py` → 육안검증
3. `register.py <bpid> "<한글명>" "<영문명>" <category> <원가> [--locked <usd>] [--stock <n>]`
   - dedup 체크 내장(이미 있으면 중단→resource.py)

## 파일 역할
| 파일 | 역할 | 실행 |
|---|---|---|
| common.py | 상수·웨일fetch·DB DSN | (import) |
| sweep.py | 45개 소스 품절/가격 스캔 | 호스트 |
| search.py | 같은카드 SELLING 다른셀러 검색(단건) | 호스트 |
| match_substitute.py | 품절목록 일괄 대체후보 자동탐색(배치) | 호스트 |
| postit.py | tcg_vault 포스트잇 Gemini 합성 | 컨테이너 |
| resource.py | 품절→다른셀러 revise(단건, 수수료0) | 컨테이너 |
| apply_substitute.py | candidates.json 일괄 revise(배치, 수수료0) | 컨테이너 |
| suspend_batch.py | 매칭실패/비카드 일괄 판매중지 | 컨테이너 |
| register.py | 신규 등록(dedup·고정가) | 컨테이너 |
| price_sync.py | price_updates.json 원가 일괄 갱신 | 컨테이너 |
| set_stock.py | SKU별 판매가능수량 강제조정 | 컨테이너 |

## 관련 코드(backend, 영구)
- 검색엔진: `plugins/sourcing/bunjang.py`
- eBay: `plugins/markets/ebay.py` + `proxy/ebay.py`(EbayClient) + `shipment/service.py`(calc_market_price)
- 이미지: `image/service.py`(_transform_image_gemini, gemini 키=samba_settings '{tenant}:gemini')
