# 크림매칭 시트 자동 동기화

구글 스프레드시트 **주문처리 → `크림매칭` 탭**을 채우는 스크립트 모음.

> **왜 이 문서가 있나 (2026-08-18)**
> 이 스크립트를 찾는 데 한참 걸렸다. `deploy/local/` 은 "배포용" 폴더로 보여서
> 아무도 여기를 안 뒤졌고, Apps Script 프로젝트 7개를 다 열어보고 디스크 전체를
> 시트 ID 로 grep 해도 안 나왔다. 결국 **P5 체크를 누르는 순간 새로 뜨는 프로세스를
> 잡아서** 찾았다. 같은 삽질을 반복하지 않도록 `tools/sheet_sync/` 로 옮기고 기록을 남긴다.

---

## 한눈에 보기

```
시트      주문처리 (1FM3smmTlsbxhN03CFCoK_Pp5byA9wTfpiQ66jOG0ohM)
탭        크림매칭 (gid 129447601)
방아쇠    P5 체크박스 — 체크하면 TRUE, 스크립트가 읽고 다시 FALSE 로 되돌림
실행      작업 스케줄러 `kream-ebay-watch` 가 1분마다 pythonw 로 watch_once 실행
인증      서비스 계정 키 C:/Users/canno/.claude/google-credentials.json
```

**Apps Script 가 아니다.** 시트에 묶인 Apps Script 프로젝트(`쿠팡_재고현황`)에는
크림 관련 코드가 전혀 없다. 실행 기록에도 안 남는다. 이 PC 의 파이썬이 P5 를
폴링하는 구조다.

## 파일

| 파일 | 역할 |
|------|------|
| `kream_ebay_watch_once.py` | P5 를 1회 확인 → 체크돼 있으면 sync 실행 (스케줄러가 부름) |
| `kream_ebay_watch_loop.py` | 2초 간격 상시 감시판 (수동 실행용) |
| `kream_ebay_sync.py` | 본체 — 크림 구매내역 읽어 시트 갱신 |
| `cdp_sheet_helpers.py` | 웨일 CDP(9223) 연결 헬퍼 |

> **`cdp_sheet_helpers.py` 는 `deploy/local/` 에도 같은 파일이 있다. 지우지 말 것.**
> 그 폴더의 스크립트 **90개**가 `from cdp_sheet_helpers import CDPConn` 로 같은 폴더에서
> 불러 쓴다(2026-08-18 에 이 파일만 옮겼다가 그쪽이 통째로 깨졌다). 양쪽은 같은 내용을
> 유지하고, 고칠 일이 있으면 두 곳 다 고친다.

`deploy/local/kream_ebay_watch_once.py` 는 **껍데기**다. 스케줄러가 그 경로를
가리키는데 스케줄러 수정에 관리자 권한이 필요해(0x80070005) 경로를 못 바꿨다.
그 파일은 이 폴더의 같은 이름 파일을 불러 실행할 뿐이니 로직을 거기 쓰지 말 것.

## 동작

1. 크림 구매내역(진행중 + 종료)을 **웨일 CDP 로** 읽는다 — 로그인 세션이 필요해서다.
   크림 공식 OpenAPI 의 `/orders` 는 **우리가 크림에 파는 판매 주문**(`A-LI…`)이라
   여기 쓸 수 없다. 시트의 `O-OR…` 은 크림에서 **사온** 주문이다.
2. 배송완료 신규건 → 이베이 표(A:I) 맨 아래에 도착순 추가. 할인율·원가 계산.
   이베이 주문은 DB `samba_order` 에서 가져온다(docker exec 로 조회).
3. 아직 배송완료 안 된 건 → K:N 구간을 통째로 새로 작성.

정렬은 `STATUS_ORDER` 를 따른다.

## 주의

- **콘솔 창**: `pythonw` 로 띄워도 내부 `subprocess.run(["docker", …])` 이 매번
  검은 창을 띄운다. `CREATE_NO_WINDOW` 를 반드시 붙일 것 (2026-08-18 적용).
- **pythonw + print()**: pythonw 는 `sys.stdout` 이 None 이라 `print()` 가
  AttributeError 로 죽는다. `watch_once.py` 상단처럼 로그 파일로 돌려놔야 한다.
- 로그: `deploy/local/kream_ebay_watch.log`

## 관련 작업 스케줄러

```
kream-ebay-watch   1분마다 · pythonw · deploy/local/kream_ebay_watch_once.py
```

창이 뜨는 다른 작업(`SambaDBBackup`, `SambaSnkrKreamBackup`)은 `-WindowStyle Hidden`
이 빠져 있다. 바꾸려면 **관리자 권한 PowerShell** 이 필요하다.
