// 삼바 주문도우미 — 백그라운드 (서비스 워커)
// 메시지 허브 + MAIN world 주소입력(CSP 우회) + 삼바 writeback 중계.
// ⚠️ executeScript(func)로 주입되는 함수는 '자기완결형'이어야 함 (외부 함수 참조 금지).

// 우편번호 없는 경우: 이름/연락처/상세/메모 채우고 주소찾기(Daum) 오픈
function pageOpenSearch(c) {
  return new Promise((resolve) => {
    let tries = 0;
    const iv = setInterval(() => {
      tries++;
      const root = document.querySelector('#commonLayoutContents');
      const vm = root && root.__vue__;
      if (vm && vm.form && (vm.form.id || tries > 15)) {
        clearInterval(iv);
        try {
          vm.form.name = c.name;
          vm.form.mobile = c.phone;
          vm.form.address2 = c.addr2;
          if (c.memo) {
            const pre = (vm.ui && vm.ui.additionalMessageType) || [];
            if (pre.indexOf(c.memo) >= 0) vm.form.additionalMessage = c.memo;
            else { vm.form.additionalMessage = '직접입력'; vm.form.additionalMessageManual = c.memo; }
          }
          vm.form.zipcode = '';
          vm.form.address1 = '';
          if (vm.searchAddressOpen) vm.searchAddressOpen();
          resolve({ ok: true });
        } catch (e) { resolve({ ok: false, error: String(e) }); }
      } else if (tries > 50) { clearInterval(iv); resolve({ ok: false, error: 'NO_VUE' }); }
    }, 120);
  });
}

// 우편번호 확보 후: 전체 폼 채우고 저장 (address1/2는 삼바 정확값 강제)
function pageFillZip(c, zip) {
  return new Promise((resolve) => {
    let tries = 0;
    const iv = setInterval(() => {
      tries++;
      const root = document.querySelector('#commonLayoutContents');
      const vm = root && root.__vue__;
      if (vm && vm.form && (vm.form.id || tries > 15)) {
        clearInterval(iv);
        try {
          if (vm.searchAddressClose) { try { vm.searchAddressClose(); } catch (e) { /* noop */ } }
          vm.form.name = c.name;
          vm.form.mobile = c.phone;
          vm.form.address2 = c.addr2;
          if (c.memo) {
            const pre = (vm.ui && vm.ui.additionalMessageType) || [];
            if (pre.indexOf(c.memo) >= 0) vm.form.additionalMessage = c.memo;
            else { vm.form.additionalMessage = '직접입력'; vm.form.additionalMessageManual = c.memo; }
          }
          if (typeof vm.findAddressComplete === 'function') {
            vm.findAddressComplete({ zipcode: String(zip), address1: c.addr });
          } else {
            vm.form.zipcode = String(zip);
          }
          vm.form.address1 = c.addr;   // 삼바 정확값 강제
          vm.form.address2 = c.addr2;
          const filled = { zipcode: vm.form.zipcode, address1: vm.form.address1, address2: vm.form.address2 };
          // 결과 먼저 반환 후(IPC 보장) 약간의 지연 뒤 저장(=페이지 이동)
          resolve({ ok: true, filled });
          setTimeout(() => { try { vm.formSubmit(); } catch (e) { /* noop */ } }, 350);
        } catch (e) { resolve({ ok: false, error: String(e) }); }
      } else if (tries > 50) { clearInterval(iv); resolve({ ok: false, error: 'NO_VUE' }); }
    }, 120);
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

  if (msg.type === 'RESOLVE_ZIP') {
    chrome.storage.local.get('kakaoKey', async ({ kakaoKey }) => {
      if (!kakaoKey) { sendResponse({ ok: false, error: 'no key' }); return; }
      try {
        const r = await fetch(
          'https://dapi.kakao.com/v2/local/search/address.json?query=' + encodeURIComponent(msg.address),
          { headers: { Authorization: 'KakaoAK ' + kakaoKey } }
        );
        const d = await r.json();
        const docs = d.documents || [];
        const doc = docs.find((x) => x.road_address && x.road_address.zone_no) || docs[0];
        const zip = doc && doc.road_address && doc.road_address.zone_no
          ? doc.road_address.zone_no
          : (doc && doc.address && doc.address.zip_code) || '';
        const road = doc && doc.road_address ? doc.road_address.address_name : '';
        if (zip) sendResponse({ ok: true, zip, road });
        else sendResponse({ ok: false, error: 'no result' });
      } catch (e) { sendResponse({ ok: false, error: String(e) }); }
    });
    return true;
  }

  if (msg.type === 'WRITEBACK') {
    console.log('[주문도우미] WRITEBACK (삼바 기입 예정)', msg);
    sendResponse({ ok: true });
    return true;
  }
});
