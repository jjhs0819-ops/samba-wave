// SNKRDUNK 로그인 세션쿠키 백엔드 동기화 트리거.
// SNKRDUNK 는 MFA(SMS OTP)라 백엔드 id/pw 자동로그인 불가 → 로그인된 브라우저의
// session 쿠키를 백엔드로 전달해야 크림 해외매입 송장(사무국→구매자 발송)을 조회할 수 있다.
// session 쿠키는 httpOnly 라 content script 가 직접 못 읽음 → background(chrome.cookies)가
// 읽어 전송한다. 여기서는 트리거 메시지만 보낸다.
;(function () {
  try {
    chrome.runtime.sendMessage({ type: 'SNKRDUNK_SYNC_SESSION' })
  } catch (e) {
    /* ignore */
  }
})()
