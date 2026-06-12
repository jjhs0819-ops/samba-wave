// 삼바 주문도우미 — 백그라운드 (서비스 워커)
// 메시지 허브 + 삼바 writeback 중계.

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'START_JOB') {
    // 팝업/삼바에서 주문 작업 시작 요청
    chrome.storage.local.set({ job: msg.job }, () => {
      chrome.tabs.create({ url: msg.productUrl });
      sendResponse({ ok: true });
    });
    return true; // async
  }

  if (msg.type === 'WRITEBACK') {
    // 결제완료 → 삼바에 주문번호/금액 기입
    // 1단계(현재): 로그만. 삼바 연동은 다음 단계에서 추가.
    console.log('[주문도우미] WRITEBACK (삼바 기입 예정)', msg);
    // TODO: 삼바 탭으로 메시지 보내 PUT /api/v1/samba/orders/{orderId} 호출
    sendResponse({ ok: true });
    return true;
  }
});
