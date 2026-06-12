// 삼바 주문도우미 — 백그라운드 (서비스 워커)
// 메시지 허브 + MAIN world 주소입력(CSP 우회) + 삼바 writeback 중계.

// 공통: 무신사 배송지 폼 Vue 인스턴스 얻기까지 폴링
function _withVue(fn, resolve) {
  let tries = 0;
  const iv = setInterval(() => {
    tries++;
    const root = document.querySelector('#commonLayoutContents');
    const vm = root && root.__vue__;
    if (vm && vm.form && (vm.form.id || tries > 15)) {
      clearInterval(iv);
      try { fn(vm); } catch (e) { resolve({ ok: false, error: String(e) }); }
    } else if (tries > 50) {
      clearInterval(iv);
      resolve({ ok: false, error: 'NO_VUE' });
    }
  }, 120);
}

function _applyCommon(vm, c) {
  vm.form.name = c.name;
  vm.form.mobile = c.phone;
  vm.form.address2 = c.addr2;
  if (c.memo) {
    const pre = (vm.ui && vm.ui.additionalMessageType) || [];
    if (pre.indexOf(c.memo) >= 0) vm.form.additionalMessage = c.memo;
    else { vm.form.additionalMessage = '직접입력'; vm.form.additionalMessageManual = c.memo; }
  }
}

// 우편번호 없는 경우: 이름/연락처/상세/메모 채우고 주소찾기(Daum) 오픈
function pageOpenSearch(c) {
  return new Promise((resolve) => {
    _withVue((vm) => {
      _applyCommon(vm, c);
      vm.form.zipcode = '';
      vm.form.address1 = '';
      if (vm.searchAddressOpen) vm.searchAddressOpen();
      resolve({ ok: true });
    }, resolve);
  });
}

// 우편번호 확보 후: 전체 폼 채우고 저장 (address1/2는 삼바 정확값으로 강제)
function pageFillZip(c, zip) {
  return new Promise((resolve) => {
    _withVue((vm) => {
      if (vm.searchAddressClose) { try { vm.searchAddressClose(); } catch (e) { /* noop */ } }
      _applyCommon(vm, c);
      if (typeof vm.findAddressComplete === 'function') {
        vm.findAddressComplete({ zipcode: String(zip), address1: c.addr });
      } else {
        vm.form.zipcode = String(zip);
      }
      vm.form.address1 = c.addr;   // 삼바 정확값 강제
      vm.form.address2 = c.addr2;
      const filled = { zipcode: vm.form.zipcode, address1: vm.form.address1, address2: vm.form.address2 };
      setTimeout(() => {
        try { vm.formSubmit(); } catch (e) { /* noop */ }
        resolve({ ok: true, filled });
      }, 400);
    }, resolve);
  });
}

function runInPage(tabId, func, args, sendResponse) {
  chrome.scripting
    .executeScript({ target: { tabId, allFrames: false }, world: 'MAIN', func, args })
    .then((arr) => {
      const r = (arr && arr[0] && arr[0].result) || { ok: false, error: 'no result' };
      console.log('[주문도우미]', func.name, r);
      sendResponse(r);
    })
    .catch((e) => sendResponse({ ok: false, error: String(e) }));
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'START_JOB') {
    chrome.storage.local.set({ job: msg.job }, () => {
      chrome.tabs.create({ url: msg.productUrl });
      sendResponse({ ok: true });
    });
    return true;
  }

  const tabId = sender.tab && sender.tab.id;

  if (msg.type === 'OPEN_SEARCH') {
    if (!tabId) { sendResponse({ ok: false, error: 'no tab' }); return; }
    runInPage(tabId, pageOpenSearch, [msg.customer], sendResponse);
    return true;
  }

  if (msg.type === 'FILL_ZIP') {
    if (!tabId) { sendResponse({ ok: false, error: 'no tab' }); return; }
    runInPage(tabId, pageFillZip, [msg.customer, msg.zip], sendResponse);
    return true;
  }

  if (msg.type === 'WRITEBACK') {
    console.log('[주문도우미] WRITEBACK (삼바 기입 예정)', msg);
    // TODO: 삼바 탭으로 메시지 보내 PUT /api/v1/samba/orders/{orderId} 호출
    sendResponse({ ok: true });
    return true;
  }
});
