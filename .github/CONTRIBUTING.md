# 삼바웨이브 팀원 작업 가이드

## 브랜치 규칙

- **main 직접 push 금지** — 반드시 PR을 통해서만 머지
- 브랜치 이름: `feature/담당처-plugin` 또는 `feature/담당처-sourcing`
- 본인 담당 플러그인 파일만 수정

## 작업 순서

```bash
# 1. main 최신화
git checkout main
git pull origin main

# 2. 작업 브랜치 생성
git checkout -b feature/XXX-plugin

# 3. 본인 플러그인 파일만 수정
#    - plugins/markets/XXX.py
#    - plugins/sourcing/XXX.py
#    - proxy/XXX.py

# 4. 커밋 & 푸시
git add 수정파일
git commit -m "커밋 메시지 (한국어)"
git push origin feature/XXX-plugin

# 5. GitHub에서 PR 생성 → 팀장 리뷰 요청
# 6. CI 통과 + 팀장 승인 후 머지
```

## 수정 가능 파일

| 담당 | 수정 가능 파일 |
|------|--------------|
| SSG (김호수) | `plugins/sourcing/ssg.py`, `proxy/ssg_sourcing.py` |
| 쿠팡 (장재훈) | `plugins/markets/coupang.py`, `proxy/coupang.py` |
| GS샵 (장재훈) | `plugins/sourcing/gsshop.py`, `proxy/gsshop_sourcing.py` |
| ABCmart (김창현) | `plugins/sourcing/abcmart.py`, `proxy/abcmart.py` |
| 나이키 (조명재) | `plugins/sourcing/nike.py`, `proxy/nike.py` |
| 롯데ON (김준길) | `plugins/markets/lotteon.py`, `proxy/lotteon.py` |
| Qoo10 (정의선) | `plugins/markets/qoo10.py` |

## 절대 수정 금지 파일

- `plugins/__init__.py`
- `plugins/market_base.py`
- `plugins/sourcing_base.py`
- `collector/` 폴더 전체
- `.github/workflows/deploy-cloudrun.yml`
- `frontend/src/app/samba/**/page.tsx` (공유 UI)

위 파일 수정이 필요하면 → **수정하지 말고 팀장에게 요청**

## 커밋 규칙

- 커밋 메시지는 **한국어**
- Python 파일 수정 시 커밋 전 반드시 실행:
  ```bash
  cd backend
  ruff format .
  ruff check --fix .
  ```

## 브랜치 최신화 (오래된 브랜치)

작업 기간이 길어졌다면 main을 먼저 합치고 작업:

```bash
git checkout feature/XXX-plugin
git merge origin/main
# 충돌 발생 시 → 본인 플러그인 파일만 본인 코드로, 나머지는 main 코드 유지
```
