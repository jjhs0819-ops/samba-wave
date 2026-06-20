// 삼바 주문도우미 — 백그라운드 (서비스 워커)
// 메시지 허브 + MAIN world 주소입력(CSP 우회) + 삼바 writeback 중계.
// ⚠️ executeScript(func)로 주입되는 함수는 '자기완결형'이어야 함 (외부 함수 참조 금지).

// 카카오 REST API 키 (팝업에서 저장한 키가 있으면 그게 우선). 우편번호 조회용.
const DEFAULT_KAKAO_KEY = '08bff9e4d109b15fe0d21d7f930bfa0d';

// 페이지(MAIN world) 네이티브 alert/confirm 자동수락 — 롯데온 배송지 저장/변경 시
// 뜨는 네이티브 팝업이 자동화 흐름을 막지 않도록 무력화. (자기완결형 함수)
function pageSuppressDialogs() {
  try {
    window.alert = function () {};
    window.confirm = function () { return true; };
    return { ok: true };
  } catch (e) { return { ok: false, error: String(e) }; }
}

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
          // 배송 요청사항(선택): 삼바 메모가 있으면 그대로, 비어 있으면 공백 1칸을
          // '직접입력'으로 넣어 무신사에 이전 요청사항이 자동으로 남는 것을 방지한다.
          {
            const memo = (c.memo && c.memo.trim()) ? c.memo : ' ';
            const pre = (vm.ui && vm.ui.additionalMessageType) || [];
            if (memo.trim() && pre.indexOf(memo) >= 0) vm.form.additionalMessage = memo;
            else { vm.form.additionalMessage = '직접입력'; vm.form.additionalMessageManual = memo; }
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
          // 배송 요청사항(선택): 삼바 메모가 있으면 그대로, 비어 있으면 공백 1칸을
          // '직접입력'으로 넣어 무신사에 이전 요청사항이 자동으로 남는 것을 방지한다.
          {
            const memo = (c.memo && c.memo.trim()) ? c.memo : ' ';
            const pre = (vm.ui && vm.ui.additionalMessageType) || [];
            if (memo.trim() && pre.indexOf(memo) >= 0) vm.form.additionalMessage = memo;
            else { vm.form.additionalMessage = '직접입력'; vm.form.additionalMessageManual = memo; }
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

  if (msg.type === 'SUPPRESS_DIALOGS') {
    if (!tabId) { sendResponse({ ok: false, error: 'no tab' }); return; }
    runInPage(tabId, pageSuppressDialogs, [], sendResponse);
    return true;
  }

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
      const key = kakaoKey || DEFAULT_KAKAO_KEY;
      if (!key) { sendResponse({ ok: false, error: 'no key' }); return; }
      try {
        const r = await fetch(
          'https://dapi.kakao.com/v2/local/search/address.json?query=' + encodeURIComponent(msg.address),
          { headers: { Authorization: 'KakaoAK ' + key } }
        );
        if (!r.ok) {
          const body = await r.text().catch(() => '');
          sendResponse({ ok: false, error: 'HTTP ' + r.status + ' ' + body.slice(0, 120) });
          return;
        }
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
    const wb = { marketNo: msg.marketNo, sourcingNo: msg.sourcingNo, amount: msg.amount, source: msg.source || 'MUSINSA', ts: Date.now() };
    console.log('[주문도우미] WRITEBACK', wb);
    // 삼바 탭이 나중에 열려도 처리되도록 저장 + 열려있는 삼바 탭들에 즉시 전달
    chrome.storage.local.set({ pendingWriteback: wb });
    chrome.tabs.query({ url: 'https://samba-wave-xi.vercel.app/*' }, (tabs) => {
      (tabs || []).forEach((t) => {
        try { chrome.tabs.sendMessage(t.id, Object.assign({ type: 'WRITEBACK_APPLY' }, wb), () => void chrome.runtime.lastError); } catch (e) { /* noop */ }
      });
    });
    sendResponse({ ok: true });
    return true;
  }
});
