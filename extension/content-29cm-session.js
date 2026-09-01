// 29CM 로그인 쿠키 백엔드 동기화 트리거.
// 29CM 원가(최대혜택가)는 상세 API 의 노출가를 쓰지만, 계정 기준 수집을 위해
// 로그인 쿠키를 백엔드에 넘긴다. 세션 쿠키는 httpOnly 라 content script 가 못 읽으므로
// background(chrome.cookies)가 읽어 전송한다 — 여기서는 트리거만 보낸다.
;(function () {
  try {
    // 로그인 상태에서만 의미가 있다. 마이페이지에 LOGOUT 이 보이면 로그인으로 본다.
    const text = document.body ? document.body.innerText : ''
    const loggedIn = text.includes('LOGOUT') || text.includes('로그아웃')
    chrome.runtime.sendMessage({ type: 'TWENTYNINECM_SYNC_COOKIE', loggedIn })
  } catch (e) {
    /* ignore */
  }
})()
