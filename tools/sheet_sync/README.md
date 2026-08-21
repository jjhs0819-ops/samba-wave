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
방아쇠    P열 체크박스 — 체크하면 TRUE, 스크립트가 읽고 다시 FALSE 로 되돌림
          **위치를 고정하지 않는다.** P1:P20 에서 체크된 칸을 찾는다(아래 참조)
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


## 체크박스 위치를 고정하지 마라 [2026-08-20]

"P5 를 눌러도 반응이 없다" 는 신고가 반복된다. 두 번 다 같은 원인이었다.

- 2026-08-14: 탭이 옮겨져 실행 실패
- 2026-08-20: **체크박스가 P6 로 내려가 있었다.** 스크립트는 빈 P5 만 읽어
  영영 트리거되지 않았고, 사용자가 눌러둔 TRUE 가 P6 에 그대로 남아 있었다.

시트는 사람이 행을 넣고 빼므로 셀 주소가 움직인다. 그래서 `watch_once` 는
`P1:P20` 을 읽어 **체크된 첫 칸**을 찾아 쓴다. 새 스크립트를 만들 때도 주소를
박지 말 것.

진단 순서:
1. `Get-ScheduledTaskInfo -TaskName kream-ebay-watch` — LastTaskResult 0 이면 스케줄러는 정상
2. `kream_ebay_watch.log` 마지막 시각 — P5 가 FALSE 면 아무것도 안 찍히는 게 정상이라
   "로그가 멈췄다" 만으로는 고장이 아니다
3. **시트에서 P열 값을 직접 읽어본다** — 여기서 위치 어긋남이 드러난다

## P5 를 눌러도 반응이 없다 — 원인 3가지 [2026-08-21 갱신]

증상은 같아도 원인이 매번 달랐다. **아래 순서로 확인**하면 빠르다.

1. **체크박스 위치가 밀렸다** (2026-08-14, 2026-08-20)
   → 지금은 `P1:P20` 에서 체크된 칸을 자동으로 찾으므로 재발하지 않는다.

2. **웨일 창이 최소화·비활성** (2026-08-21) ← 가장 최근 원인
   창이 활성 상태가 아니면 웨일이 **입력 이벤트에 응답을 안 준다.**
   `Input.dispatchMouseEvent`(휠)가 무응답 → CDP 타임아웃 → 스크립트 사망.
   같은 탭에서 `Runtime.evaluate` 는 0.2초로 멀쩡하다(그래서 "탭은 정상"으로 보인다).
   → `window.scrollTo` 로 교체해 해결. **앞으로 입력 이벤트를 쓰지 마라.**

3. **크림 buying 탭이 먹통**
   `pending` / `finished` 탭 두 개가 다 있어야 한다. 하나가 죽었으면 닫고 새로 연다:
   ```python
   urllib.request.Request("http://127.0.0.1:9223/json/new?" + url, method="PUT")  # GET 은 405
   ```

**진단 명령** (순서대로):
```bash
# ① 스케줄러 — LastTaskResult 0 이면 정상
powershell -Command "Get-ScheduledTaskInfo -TaskName kream-ebay-watch"
# ② 로그 마지막 예외
tail -30 tools/sheet_sync/kream_ebay_watch.log
# ③ 시트 P열 실제 값
# ④ CDP 탭 목록 — my/buying 이 pending·finished 둘 다 있는지
curl -s http://127.0.0.1:9223/json
```

실행 중 예외가 나면 체크를 True 로 되돌리므로(2026-08-21), 실패해도 다음 폴링에서
자동 재시도된다. "체크만 풀리고 아무 일도 안 일어남" 은 이제 안 생긴다.
