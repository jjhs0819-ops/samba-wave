# 코드 리뷰: 스마트스토어 이미지 CDN 차단 감지 로직

## 리뷰 대상 파일

| 파일 | 역할 |
|------|------|
| `backend/backend/domain/samba/proxy/smartstore.py` | `upload_image_from_url()` — 외부 이미지 다운로드 + 네이버 업로드 |
| `backend/backend/domain/samba/shipment/dispatcher.py` | `_handle_smartstore()` — 상세 HTML 내 이미지 URL 치환 |
| `backend/backend/domain/samba/shipment/service.py` | `_build_detail_html()` — 상세페이지 HTML 생성 |
| `backend/backend/domain/samba/proxy/musinsa.py` | `_to_image_url()` — 무신사 이미지 URL 생성 |

---

## 1. 문제 현상

무신사에서 수집한 상품을 스마트스토어에 등록하면 이미지가 보이지 않는다.
무신사 CDN(`image.msscdn.net`)은 핫링크 방지 정책이 적용되어 있어, 올바른 Referer 없이 이미지를 요청하면 차단 이미지(1x1 투명 GIF 등)를 반환한다.

---

## 2. 현재 구현 분석

### 2.1 `upload_image_from_url()` (smartstore.py 225~270행)

```python
async def upload_image_from_url(self, image_url: str) -> str:
    # Referer 자동 설정
    parsed = urlparse(image_url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"
    # 무신사 CDN 특수 처리
    if "msscdn.net" in (parsed.netloc or ""):
        referer = "https://www.musinsa.com/"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        img_resp = await client.get(image_url, headers={
            "User-Agent": "Mozilla/5.0 ...",
            "Referer": referer,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        })
        if not img_resp.is_success:
            raise SmartStoreApiError(f"이미지 다운로드 실패: {img_resp.status_code}")
        img_bytes = img_resp.content
        # CDN 차단 감지
        if len(img_bytes) < 1000:
            raise SmartStoreApiError(
                f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성"
            )
```

### 2.2 `_handle_smartstore()` (dispatcher.py 117~201행)

상세 HTML 내 이미지 URL도 `upload_image_from_url()`로 업로드 후 치환한다:

```python
# 상세 HTML 내 이미지 정규식 추출
img_pattern = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
all_src_urls = img_pattern.findall(detail_html)
# 외부 CDN URL만 업로드 (네이버 URL이나 S3 URL은 제외)
for src_url in all_src_urls:
    if "naver.net" in src_url or "pstatic.net" in src_url:
        continue
    naver_url = await client.upload_image_from_url(src_url)
    url_map[src_url] = naver_url
# URL 치환
for old_url, new_url in url_map.items():
    detail_html = detail_html.replace(old_url, new_url)
```

---

## 3. Referer 설정 분석

### 3.1 현재 상태: **올바르게 구현됨**

| 검사 항목 | 결과 | 상세 |
|-----------|------|------|
| `msscdn.net` 도메인 감지 | **통과** | `if "msscdn.net" in (parsed.netloc or "")` — 서브도메인 포함 매칭 |
| Referer 값 | **통과** | `https://www.musinsa.com/` — 무신사 웹사이트 도메인 |
| 기타 도메인 폴백 | **통과** | `{scheme}://{netloc}/` — 이미지 원본 도메인 자동 설정 |
| User-Agent 설정 | **통과** | 크롬 브라우저 에뮬레이션 문자열 사용 |
| follow_redirects | **통과** | `follow_redirects=True` — 리다이렉트 자동 추적 |

### 3.2 잠재적 문제점

**문제 1: `msscdn.net` 이외의 무신사 이미지 도메인 미처리**

무신사 클라이언트(`musinsa.py`)의 `_to_image_url()` 메서드를 보면:

```python
@staticmethod
def _to_image_url(path: str) -> str:
    if path.startswith("http"):
        return path
    if path.startswith("//"):
        return f"https:{path}"
    return f"https://image.msscdn.net{path}"
```

현재는 `image.msscdn.net`만 사용하므로 `msscdn.net` 도메인 감지로 충분하다. 그러나 무신사가 `cdn.msscdn.net`, `static.msscdn.net` 등 다른 서브도메인을 사용하는 경우에도 대응이 가능하다(서브도메인 포함 매칭).

**평가: 현재 구현으로 충분하다. 위험도 낮음.**

**문제 2: `image.musinsa.com` 도메인 미처리**

무신사가 일부 이미지에 `image.musinsa.com` 도메인을 사용하는 경우가 있다. 현재 코드에서는 이 도메인을 감지하지 못하고 기본 Referer(`https://image.musinsa.com/`)를 설정한다. 이 Referer가 핫링크 방지를 통과하는지는 검증되지 않았다.

**평가: 잠재적 위험. 현재 수집 단계에서 `msscdn.net` 도메인만 사용하므로 당장은 문제 없음.**

---

## 4. CDN 차단 감지 (1000B 미만) 분석

### 4.1 현재 상태: **대체로 적절하나 엣지케이스 존재**

```python
if len(img_bytes) < 1000:
    raise SmartStoreApiError(
        f"이미지가 비정상적으로 작음({len(img_bytes)}B) — CDN 차단 가능성"
    )
```

| 검사 항목 | 결과 | 상세 |
|-----------|------|------|
| 1x1 투명 GIF 감지 | **통과** | 일반적으로 43~100B. 1000B 임계값으로 충분히 감지 |
| 1x1 투명 PNG 감지 | **통과** | 일반적으로 68~120B. 1000B 임계값으로 감지 |
| 차단 경고 HTML 감지 | **부분 통과** | HTML 응답이 1000B 미만이면 감지되지만, 1000B 이상의 HTML 에러 페이지는 놓침 |
| 정상 아이콘/썸네일 오탐 | **위험** | 매우 작은 아이콘(favicon 등)이 정상 이미지인데 차단으로 오인될 가능성 |
| Content-Type 미검증 | **위험** | `text/html` 응답(차단 페이지)이 1000B 이상이면 정상 이미지로 오인 |

### 4.2 개선 권장 사항

#### 권장 1: Content-Type 검증 추가 (우선순위: 높음)

CDN이 차단 시 HTML 에러 페이지를 반환하는 경우가 있다. 이때 크기만으로는 감지가 불가능하다.

```python
content_type = img_resp.headers.get("content-type", "")
# HTML 응답이면 차단 페이지일 가능성 높음
if "text/html" in content_type or "application/json" in content_type:
    raise SmartStoreApiError(
        f"이미지 응답이 이미지가 아닌 {content_type} — CDN 차단 가능성"
    )
```

**현재 코드에서는 Content-Type을 읽어서 확장자 결정에만 사용하고, 검증에는 활용하지 않는다.** 이미지가 아닌 응답(`text/html`, `application/json`)이 왔을 때 크기가 1000B 이상이면 정상으로 오인하고 네이버에 업로드를 시도하게 된다.

#### 권장 2: 이미지 매직 바이트 검증 (우선순위: 중간)

이미지 파일의 첫 몇 바이트(매직 넘버)를 검사하여 실제 이미지인지 확인:

```python
MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpeg',
    b'\x89PNG': 'png',
    b'GIF8': 'gif',
    b'RIFF': 'webp',  # RIFF....WEBP
}
is_image = any(img_bytes.startswith(m) for m in MAGIC_BYTES)
if not is_image:
    raise SmartStoreApiError("응답이 유효한 이미지 파일이 아님 — CDN 차단 가능성")
```

#### 권장 3: 1000B 임계값은 유지 (적절함)

- 일반적인 핫링크 차단 이미지(1x1 GIF/PNG)는 43~120B
- 실제 상품 이미지는 최소 수 KB 이상
- 1000B는 합리적인 경계값
- 다만 이 검사 **단독으로는 부족**하고, Content-Type 검증과 함께 사용해야 한다

---

## 5. 전체 파이프라인에서의 이미지 흐름 검증

### 5.1 이미지 업로드 파이프라인 (정상 동작 확인)

```
[1] service._build_detail_html()
    → 소싱처 CDN URL(msscdn.net) 포함된 HTML 생성

[2] dispatcher._handle_smartstore()
    → 대표이미지(images[:5]) 업로드: upload_image_from_url() 호출
    → 상세 HTML 내 이미지 추출 → upload_image_from_url() 호출
    → URL 치환: msscdn.net URL → pstatic.net URL

[3] transform_product()
    → 업로드된 네이버 URL로 변환된 product_copy 사용
```

**검증 결과: 파이프라인 구조는 올바르다.** 소싱처 CDN URL이 네이버 CDN URL로 정확히 치환되는 흐름이 구현되어 있다.

### 5.2 발견된 구조적 문제점

#### 문제 A: 이미지 업로드 실패 시 조용한 스킵 (심각도: 중간)

```python
# dispatcher.py 158~164행
for img_url in images_raw[:5]:
    try:
        naver_url = await client.upload_image_from_url(img_url)
        if naver_url:
            naver_images.append(naver_url)
    except Exception as e:
        logger.warning(f"[스마트스토어] 대표이미지 업로드 실패: {e}")
```

CDN 차단으로 `SmartStoreApiError`가 발생하면 `except Exception`으로 잡히고, 해당 이미지는 건너뛴다. **대표이미지(images[0])가 차단되어 건너뛰면 `naver_images`가 빈 배열이 되고**, `transform_product()`에서 `representativeImage.url`이 비어 있게 되어 **스마트스토어 API가 등록을 거부한다.**

이 경우 에러 메시지는 "이미지가 비정상적으로 작음" 경고 로그만 남고, 실제 등록 실패 원인이 "대표이미지 필수" 등으로 나타나 원인 추적이 어려워진다.

**개선 방안:** 대표이미지(첫 번째 이미지) 업로드 실패 시 전체 전송을 즉시 실패 처리하거나, 에러 메시지에 CDN 차단 원인을 명시해야 한다.

#### 문제 B: 상세 HTML 이미지 업로드 실패도 조용한 스킵 (심각도: 낮음)

```python
# dispatcher.py 181~186행
except Exception as e:
    logger.warning(f"[스마트스토어] 상세이미지 업로드 실패 ({src_url[:60]}): {e}")
```

상세 이미지 업로드 실패 시 원본 CDN URL이 HTML에 그대로 남는다. 이 경우 상품은 등록되지만, 상세페이지에서 해당 이미지가 깨져 보인다.

**개선 방안:** 실패한 이미지 URL을 제거하거나, "이미지를 불러올 수 없습니다" 플레이스홀더로 대체해야 한다.

#### 문제 C: 순차 업로드로 인한 성능 저하 (심각도: 낮음)

상세 이미지가 20~30장인 무신사 상품의 경우, 모든 이미지를 순차적으로 업로드하므로 전송 시간이 매우 길어진다. `asyncio.gather()`로 병렬화하면 성능을 크게 개선할 수 있다. (SKILL.md 알려진 제한사항 #3에 이미 기록됨)

---

## 6. 다른 소싱처 CDN 대응 현황

| 소싱처 CDN | Referer 처리 | 비고 |
|-----------|-------------|------|
| `msscdn.net` (무신사) | `musinsa.com` 명시 | **올바름** |
| ABCmart | 자동(원본 도메인) | 핫링크 방지 약함, 문제 없음 |
| Nike | 자동(원본 도메인) | CDN 정책 확인 필요 |
| KREAM | 자동(원본 도메인) | `kream.co.kr` CDN 정책 확인 필요 |
| 기타 11개 소싱처 | 자동(원본 도메인) | 기본 Referer로 충분할 가능성 높음 |

---

## 7. 종합 평가

### 현재 구현 점수: B+ (양호)

| 항목 | 점수 | 평가 |
|------|------|------|
| Referer 설정 | **A** | msscdn.net 감지 + musinsa.com Referer 설정 올바름 |
| CDN 차단 감지 (크기 기반) | **B** | 1000B 임계값 적절하나 단독으로는 불충분 |
| Content-Type 검증 | **D** | 미구현. HTML 차단 페이지 감지 불가 |
| 업로드 실패 처리 | **C** | 조용한 스킵으로 원인 추적 어려움 |
| 상세 HTML URL 치환 | **A** | 정규식 추출 + 네이버 URL 치환 정상 동작 |
| 이미 네이버 URL인 경우 스킵 | **A** | `naver.net`/`pstatic.net` 체크 올바름 |

### 핵심 개선 권장 사항 (우선순위 순)

1. **Content-Type 검증 추가** — `text/html` 또는 `application/json` 응답 감지
2. **대표이미지 업로드 실패 시 즉시 에러** — 조용한 스킵 대신 명확한 실패 처리
3. **이미지 매직 바이트 검증** — 실제 이미지 파일인지 확인
4. **실패 이미지 URL 처리** — 상세 HTML에서 제거 또는 플레이스홀더 대체
5. **병렬 업로드** — `asyncio.gather()` 적용으로 성능 개선

---

## 8. 결론

**현재 Referer 설정은 올바르게 구현되어 있다.** `msscdn.net` 도메인을 정확히 감지하고 `https://www.musinsa.com/` Referer를 설정하므로, 무신사 CDN의 핫링크 방지를 정상적으로 우회한다.

**1000B 미만 감지는 기본적인 보호로는 적절하지만, Content-Type 검증이 없어 HTML 에러 페이지(1000B 이상)를 놓칠 수 있다.** 이 경우 깨진 이미지 데이터가 네이버에 업로드되거나, 네이버 이미지 업로드 API가 거부하면서 "이미지 업로드 실패" 에러가 발생한다.

만약 현재 이미지가 안 보이는 현상이 실제로 발생하고 있다면, 가장 유력한 원인은:

1. **CDN 차단이 감지되어 대표이미지가 스킵됨** → `representativeImage.url`이 빈값 → 등록은 됐지만 이미지 없음
2. **상세 HTML 내 이미지 업로드 실패 후 원본 CDN URL이 잔존** → 스마트스토어에서 `msscdn.net` 이미지를 로드할 때 핫링크 차단됨
3. **Content-Type 검증 부재로 차단 페이지가 이미지로 업로드됨** → 깨진 이미지 표시

서버 로그에서 `"이미지가 비정상적으로 작음"` 또는 `"대표이미지 업로드 실패"` 경고 메시지를 확인하면 정확한 원인을 특정할 수 있다.
