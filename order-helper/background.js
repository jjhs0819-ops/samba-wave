// 삼바 주문도우미 — 백그라운드 (서비스 워커)
// 메시지 허브 + MAIN world 주소입력(CSP 우회) + 삼바 writeback 중계.

// 페이지(MAIN) 컨텍스트에서 실행될 함수 — 무신사 Vue 인스턴스로 주소폼을 채우고 저장.
// executeScript(world:'MAIN')로 주입되므로 페이지 CSP의 영향을 받지 않는다.
function pageFillAddress(c) {
  return new Promise((resolve) => {
    let tries = 0;
    const iv = setInterval(() => {
      tries++;
      const root = document.querySelector('#commonLayoutContents');
      const vm = root && root.__vue__;
      // fetchAddress() 가 끝나 form.id 가 채워진 뒤(서버데이터 로드 후)에 덮어쓴다
      if (vm && vm.form && (vm.form.id || tries > 15)) {
        clearInterval(iv);
        try {
          vm.form.name = c.name;
          vm.form.mobile = c.phone;
          if (typeof vm.findAddressComplete === 'function') {
            vm.findAddressComplete({ zipcode: c.postal, address1: c.addr });
          } else {
            vm.form.zipcode = c.postal;
            vm.form.address1 = c.addr;
          }
          vm.form.address2 = c.addr2;
          if (c.memo) {
            const pre = (vm.ui && vm.ui.additionalMessageType) || [];
            if (pre.indexOf(c.memo) >= 0) {
              vm.form.additionalMessage = c.memo;
            } else {
              vm.form.additionalMessage = '직접입력';
              vm.form.additionalMessageManual = c.memo;
            }
          }
          const filled = {
            name: vm.form.name, mobile: vm.form.mobile,
            zipcode: vm.form.zipcode, address1: vm.form.address1, address2: vm.form.address2,
          };
          setTimeout(() => {
            try { vm.formSubmit(); } catch (e) { /* noop */ }
            resolve({ ok: true, filled });
          }, 800);
        } catch (e) {
          resolve({ ok: false, error: String(e) });
        }
      } else if (tries > 40) {
        clearInterval(iv);
        resolve({ ok: false, error: 'NO_VUE' });
      }
    }, 200);
  });
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'START_JOB') {
    chrome.storage.local.set({ job: msg.job }, () => {
      chrome.tabs.create({ url: msg.productUrl });
      sendResponse({ ok: true });
    });
    return true;
  }

  if (msg.type === 'FILL_ADDRESS') {
    const tabId = sender.tab && sender.tab.id;
    if (!tabId) { sendResponse({ ok: false, error: 'no tab' }); return; }
    chrome.scripting
      .executeScript({
        target: { tabId, allFrames: false },
        world: 'MAIN',
        func: pageFillAddress,
        args: [msg.customer],
      })
      .then((arr) => {
        const r = (arr && arr[0] && arr[0].result) || { ok: false, error: 'no result' };
        console.log('[주문도우미] FILL_ADDRESS 결과', r);
        sendResponse(r);
      })
      .catch((e) => sendResponse({ ok: false, error: String(e) }));
    return true; // async
  }

  if (msg.type === 'WRITEBACK') {
    console.log('[주문도우미] WRITEBACK (삼바 기입 예정)', msg);
    // TODO: 삼바 탭으로 메시지 보내 PUT /api/v1/samba/orders/{orderId} 호출
    sendResponse({ ok: true });
    return true;
  }
});
