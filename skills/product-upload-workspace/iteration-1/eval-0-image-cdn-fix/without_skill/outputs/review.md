# 코드 리뷰: 스마트스토어 이미지 업로드 CDN 차단 감지

## 리뷰 대상 파일
- `backend/backend/domain/samba/proxy/smartstore.py` — `upload_image_from_url()` (225~270행)
- `backend/backend/domain/samba/shipment/dispatcher.py` — `_handle_smartstore()` (117~201행)
- `backend/backend/domain/samba/proxy/musinsa.py` — 이미지 URL 생성 로직 참조

---

## 1. 현재 구현 분석

### 1.1 `upload_image_from_url()` 함수 흐름

```
외부 이미지 URL 수신
  → Referer 설정 (도메인 기반)
  → httpx로 이미지 다운로드
  → 크기 검증 (1000B 미만이면 차단 판정)
  → 네이버 커머스 API로 업로드
  → 네이버 CDN URL 반환
```

### 1.2 Referer 설정 로직 (232~235행)

```python
parsed = urlparse(image_url)
referer = f"{parsed.scheme}://{parsed.netloc}/"
# 무신사 CDN은 musinsa.com Referer가 필요
if "msscdn.net" in (parsed.netloc or ""):
    referer = "https://www.musinsa.com/"
```

### 1.3 CDN 차단 감지 로직 (248~249행)

```python
if len(img_bytes) < 1000:
    raise SmartStoreApiError(f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성")
```

---

## 2. Referer 설정 평가

### 2.1 올바른 점
- **msscdn.net 도메인 감지가 정확함**: 무신사 이미지는 `image.msscdn.net` 도메인을 사용하며, 이 CDN은 핫링크 방지를 위해 Referer 검증을 수행한다. `musinsa.com`을 Referer로 설정하는 것은 올바른 접근이다.
- **일반적인 fallback 처리**: msscdn.net이 아닌 경우 이미지 원본 도메인을 Referer로 사용하는 것은 합리적인 기본값이다.

### 2.2 문제점 및 개선 필요 사항

#### [심각] Origin 헤더 누락
현재 `Referer`만 설정하고 `Origin` 헤더를 설정하지 않는다. 일부 CDN은 Referer와 Origin을 동시에 검증한다. 무신사 API 클라이언트(`musinsa.py` 88행)에서는 `Origin: https://www.musinsa.com`을 함께 설정하고 있지만, `upload_image_from_url()`에서는 누락되어 있다.

```python
# musinsa.py의 헤더 (올바른 설정)
"Referer": "https://www.musinsa.com/",
"Origin": "https://www.musinsa.com",

# smartstore.py의 이미지 다운로드 헤더 (Origin 누락)
"Referer": referer,
# Origin 없음 ← 문제
```

**권장 수정**: msscdn.net 감지 시 Origin 헤더도 함께 추가해야 한다.

#### [경고] Accept 헤더의 webp 우선 요청 문제
현재 Accept 헤더가 `image/webp,image/apng,image/*,*/*;q=0.8`로 webp를 우선 요청한다. 네이버 커머스 API가 webp 이미지를 정상 처리하지만, 일부 엣지 케이스에서 webp 포맷이 마켓 노출 시 호환성 문제를 일으킬 수 있다. 네이버 스마트스토어 자체는 webp를 지원하므로 현재로서는 큰 문제는 아니다.

#### [정보] 무신사 이미지 URL 패턴 확인
`musinsa.py`의 `_to_image_url()` 메서드(106~114행)에서 이미지 URL을 생성할 때:
- `http`로 시작하면 그대로 사용
- `//`로 시작하면 `https:` 접두사 추가
- 그 외에는 `https://image.msscdn.net` 접두사 추가

따라서 스마트스토어로 전달되는 이미지 URL은 항상 `image.msscdn.net` 도메인을 가지며, Referer 감지 로직의 `"msscdn.net" in (parsed.netloc or "")` 조건이 정확히 매칭된다.

---

## 3. 1000B 미만 감지 임계값 평가

### 3.1 현재 동작
이미지 다운로드 후 바이트 크기가 1000B(약 1KB) 미만이면 CDN 차단 이미지로 판단하고 예외를 발생시킨다.

### 3.2 적절성 분석

#### 장점
- **단순하고 효과적**: CDN 차단 시 반환되는 1x1 투명 GIF(43B), 에러 이미지(수백 B), 또는 빈 응답을 잡아낸다.
- **정상 이미지 오탐율 낮음**: 상품 이미지는 최소 수 KB 이상이므로 정상 이미지를 차단할 가능성이 매우 낮다.

#### 위험 요소

| 시나리오 | 실제 크기 | 감지 여부 | 비고 |
|---------|----------|----------|------|
| 1x1 투명 GIF | 43B | 감지됨 | CDN 차단 기본 응답 |
| "Forbidden" 텍스트 HTML | 100~500B | 감지됨 | 403 응답 body |
| CDN 경고 배너 이미지 | 1~5KB | **미감지** | 빨간 X 또는 "이미지를 사용할 수 없습니다" 이미지 |
| CDN 리다이렉트 이미지 (로고 등) | 3~10KB | **미감지** | msscdn.net이 핫링크 시 무신사 로고로 리다이렉트할 경우 |
| 매우 작은 정상 아이콘 | 500~900B | 오탐 가능 | 가능성 극히 낮음 (상품 이미지에서는 없음) |

#### [심각] Content-Type 미검증
HTTP 응답 상태 코드가 200이지만 Content-Type이 `text/html`이나 `application/json`인 경우가 있다. CDN이 차단하면서도 200 OK를 반환하고 HTML 에러 페이지를 보내는 패턴이다. 현재 코드는 Content-Type을 검증하지 않으므로 HTML 에러 페이지를 이미지로 업로드할 수 있다.

```python
content_type = img_resp.headers.get("content-type", "image/jpeg")
# content_type이 "text/html"인지 검증하지 않음 ← 문제
```

#### [경고] 1000B 임계값 자체는 보수적이지만 불충분
- CDN 차단 시 반환하는 대체 이미지(예: "핫링크 금지" 워터마크 이미지)는 보통 2~10KB 범위이므로 1000B 임계값으로는 감지 불가
- 그러나 임계값을 너무 높이면 정상적으로 작은 옵션 이미지를 오탐할 수 있으므로 단순 크기 기반 감지의 한계가 있다

---

## 4. dispatcher.py의 이미지 처리 흐름 분석

### 4.1 대표 이미지 처리 (156~164행)

```python
images_raw = product.get("images") or []
naver_images = []
for img_url in images_raw[:5]:
    try:
        naver_url = await client.upload_image_from_url(img_url)
        if naver_url:
            naver_images.append(naver_url)
    except Exception as e:
        logger.warning(f"[스마트스토어] 대표이미지 업로드 실패: {e}")
```

#### [심각] 이미지 전체 실패 시 상품 등록 진행
모든 이미지 업로드가 실패해도(`naver_images`가 빈 리스트) 상품 등록을 계속 진행한다. 이 경우 `transform_product()`에서 `representative`가 빈 딕셔너리 `{}`가 되어 이미지 없는 상품이 등록된다. 스마트스토어에서 이미지 없는 상품은 노출되지 않으므로 사실상 실패와 동일하지만 성공으로 보고된다.

### 4.2 상세 HTML 이미지 처리 (168~190행)

상세 HTML 내부의 이미지 URL을 정규식으로 추출하여 네이버에 업로드 후 URL을 치환하는 로직이 있다. 이 부분은 올바르게 구현되어 있으며:
- 이미 네이버 CDN인 URL은 스킵 (`naver.net`, `pstatic.net`)
- 개별 이미지 실패는 경고만 남기고 계속 진행
- URL 치환으로 원본 CDN 참조를 제거

#### [경고] `pstatic.net` 필터는 불완전
네이버 CDN 도메인은 `pstatic.net` 외에도 `shop-phinf.pstatic.net`, `shopping-phinf.pstatic.net` 등이 있고, `naver.net` 포함 체크가 이를 커버하고 있어 실질적 문제는 없다.

---

## 5. 종합 평가

### 잘 된 부분
1. **msscdn.net Referer 감지 및 설정** — 무신사 CDN 핫링크 방지를 정확히 우회
2. **상세 HTML 이미지 URL 치환** — CDN URL을 네이버 URL로 변환하여 핫링크 차단 방지
3. **User-Agent 설정** — 브라우저 에뮬레이션으로 봇 차단 우회
4. **follow_redirects=True** — CDN 리다이렉트 처리

### 개선 필요 사항 (우선순위순)

| 우선순위 | 문제 | 영향도 | 수정 난이도 |
|---------|------|--------|-----------|
| P0 | Origin 헤더 누락 (msscdn.net 요청 시) | CDN이 Referer+Origin 동시 검증 시 차단 | 낮음 |
| P0 | Content-Type 미검증 | HTML 에러 페이지를 이미지로 업로드 가능 | 낮음 |
| P1 | 이미지 전체 실패 시에도 상품 등록 진행 | 이미지 없는 상품 등록 (노출 안됨) | 낮음 |
| P1 | CDN 대체 이미지(2~10KB) 미감지 | 차단 이미지가 상품 이미지로 등록 | 중간 |
| P2 | 1000B 임계값만으로는 불충분 | 특정 CDN 차단 패턴 누락 가능 | 중간 |

---

## 6. 구체적 수정 제안

### 6.1 Origin 헤더 추가

```python
# 현재
headers = {
    "User-Agent": "Mozilla/5.0 ...",
    "Referer": referer,
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

# 수정안
origin = f"{parsed.scheme}://{parsed.netloc}"
if "msscdn.net" in (parsed.netloc or ""):
    origin = "https://www.musinsa.com"

headers = {
    "User-Agent": "Mozilla/5.0 ...",
    "Referer": referer,
    "Origin": origin,
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}
```

### 6.2 Content-Type 검증 추가

```python
content_type = img_resp.headers.get("content-type", "image/jpeg")
# CDN 차단 시 HTML/JSON 응답 감지
if not content_type.startswith("image/"):
    raise SmartStoreApiError(
        f"이미지가 아닌 응답 수신 (content-type: {content_type}) — CDN 차단 가능성"
    )
```

### 6.3 이미지 전체 실패 시 등록 중단

```python
# dispatcher.py _handle_smartstore() 내
if not naver_images and images_raw:
    return {
        "success": False,
        "error_type": "image_upload_failed",
        "message": f"이미지 업로드 전체 실패 ({len(images_raw)}장) — CDN 차단 확인 필요",
    }
```

### 6.4 향상된 CDN 차단 감지 (이미지 해시 기반)

1000B 임계값 외에 추가 검증:

```python
# 크기 검증 (기존)
if len(img_bytes) < 1000:
    raise SmartStoreApiError(...)

# 추가: Content-Type 검증
if not content_type.startswith("image/"):
    raise SmartStoreApiError(...)

# 추가: 알려진 차단 이미지 해시 비교 (선택적)
import hashlib
known_blocked_hashes = {
    "d41d8cd98f00b204e9800998ecf8427e",  # 빈 파일
    # 필요 시 무신사 CDN 차단 이미지 해시 추가
}
img_hash = hashlib.md5(img_bytes).hexdigest()
if img_hash in known_blocked_hashes:
    raise SmartStoreApiError("알려진 CDN 차단 이미지 감지")
```

---

## 7. 결론

현재 코드는 **기본적인 CDN 차단 대응이 되어 있지만 불완전**하다. Referer 설정은 올바르지만 Origin 헤더 누락, Content-Type 미검증, 이미지 전체 실패 시 등록 진행이라는 3가지 주요 문제가 있다. 특히 Content-Type 검증 누락은 CDN이 200 OK + HTML 에러 페이지를 반환하는 경우 HTML을 이미지로 업로드하는 심각한 문제를 유발할 수 있다.

**즉시 수정 권장**: Origin 헤더 추가 + Content-Type 검증 + 이미지 전체 실패 시 등록 중단
