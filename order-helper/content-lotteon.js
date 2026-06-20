// 삼바 주문도우미 — 롯데온(www.lotteon.com) 자동화 (Vue SPA)
// 흐름: 삼바 원문링크 → 상품(/p/product/) [옵션은 사용자 직접선택] → 바로구매
//       → 주문서(/p/order/orderSheet) → '배송지 변경' → '기본배송지 아래 비기본 주소 수정'
//       → 받는분/연락처/주소검색(상세포함)/배송메시지/필수동의 → 저장 → 선택 → 확인 → 계속하기
//       → (사용자 결제) → 결제완료 주문상세(/p/order/claim/orderDetail) → 삼바 기입
// 네이티브 alert/confirm 은 background 가 MAIN world 에서 무력화(SUPPRESS_DIALOGS).
(function () {
  const log = (...a) => console.log('%c[주문도우미·롯데온]', 'color:#b51d2b;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s, r = document) => r.querySelector(s);
  const qa = (s, r = document) => Array.from(r.querySelectorAll(s));
  async function getJob() { const { job } = await chrome.storage.local.get('job'); return job || null; }
  async function setJob(p) { const j = (await getJob()) || {}; Object.assign(j, p); await chrome.storage.local.set({ job: j }); return j; }
  function sendMsg(type, extra) {
    return new Promise((res) => { try { chrome.runtime.sendMessage(Object.assign({ type }, extra), (r) => res(r || { ok: false })); } catch (e) { res({ ok: false, error: String(e) }); } });
  }
  function banner(msg, color = '#b51d2b') {
    let el = document.getElementById('__oh_banner');
    if (!el) { el = document.createElement('div'); el.id = '__oh_banner';
      el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;font:600 14px/1.4 -apple-system,sans-serif;color:#fff;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.2)';
      document.documentElement.appendChild(el); }
    el.style.background = color; el.textContent = '🤖 주문도우미: ' + msg;
  }
  function setVal(el, v) {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const ro = el.readOnly; if (ro) el.readOnly = false;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v == null ? '' : v);
    ['input', 'change', 'blur'].forEach((t) => el.dispatchEvent(new Event(t, { bubbles: true })));
    if (ro) el.readOnly = ro;
    return true;
  }
  function rclick(el) {
    if (!el) return false;
    for (const t of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
      try { el.dispatchEvent(new MouseEvent(t, { bubbles: true, cancelable: true, view: window })); } catch (e) { /* noop */ }
    }
    return true;
  }
  async function waitFor(sel, t = 10000, root = document) {
    const end = Date.now() + t;
    while (Date.now() < end) { const e = q(sel, root); if (e && e.offsetParent !== null) return e; await wait(150); }
    return null;
  }
  function byText(text, sel = 'button,a,span,div,li', root = document) {
    return qa(sel, root).find((e) => (e.textContent || '').trim() === text && e.offsetParent !== null);
  }
  async function waitText(text, t = 10000, sel, root) {
    const end = Date.now() + t;
    while (Date.now() < end) { const e = byText(text, sel, root); if (e) return e; await wait(150); }
    return null;
  }
  // 주소 분리(무신사/ABC/패션플러스와 동일)
  function splitAddress(mainRaw, detailRaw) {
    const main = (mainRaw || '').trim();
    const detail = (detailRaw || '').trim();
    const full = (main + ' ' + detail).replace(/\s+/g, ' ').trim();
    if (!full) return { address1: main, address2: detail };
    const tokens = full.split(' ');
    let anchor = -1;
    for (let i = 0; i < tokens.length; i++) if (/[로길]\d*(번길)?$/.test(tokens[i])) anchor = i;
    if (anchor < 0) for (let i = 0; i < tokens.length; i++) if (/^[가-힣]+(읍|면|동|리)$/.test(tokens[i]) && !/^\d/.test(tokens[i])) anchor = i;
    if (anchor < 0) return { address1: main, address2: detail };
    let bn = -1;
    for (let i = anchor + 1; i < tokens.length; i++) {
      if (/^\d+(-\d+)?(번지)?$/.test(tokens[i])) { bn = i; break; }
      if (/^\d+(-\d+)?번$/.test(tokens[i])) { bn = i; break; }
    }
    if (bn < 0) return { address1: main, address2: detail };
    let end = bn;
    if (tokens[bn + 1] && tokens[bn + 1].startsWith('(')) {
      let j = bn + 1;
      while (j < tokens.length && !tokens[j].includes(')')) j++;
      if (j < tokens.length) end = j;
    }
    return { address1: tokens.slice(0, end + 1).join(' '), address2: tokens.slice(end + 1).join(' ') || detail };
  }
  // 기본배송지 아래 '비기본' 주소(삭제 버튼 있는 행)의 '수정' 버튼
  function findEditButtonForNonDefault() {
    const dels = qa('button, a').filter((b) => (b.textContent || '').trim() === '삭제' && b.offsetParent !== null);
    for (const del of dels) {
      let box = del.parentElement;
      for (let i = 0; i < 6 && box; i++) {
        const edit = qa('button, a', box).find((b) => (b.textContent || '').trim() === '수정' && b.offsetParent !== null);
        if (edit) return edit;
        box = box.parentElement;
      }
    }
    return null;
  }

  // ── 주문서: 비기본 배송지 '수정' → 삼바 정보 입력 → 저장 → 선택 → 확인 → 계속하기 ──
  async function stepOrder(job) {
    if (job.addrDone) { banner('배송지 입력 완료 ✅ 결제는 직접 진행하세요.', '#1971c2'); return; }
    if (job.addrPhase === 'running') return;
    await setJob({ addrPhase: 'running' });
    await sendMsg('SUPPRESS_DIALOGS'); // 네이티브 alert/confirm 자동수락
    const c = Object.assign({}, job.customer || {});
    if (!String(c.addr2 || '').trim()) {
      const sp = splitAddress(c.addr, '');
      if (sp.address2 && sp.address2.trim()) { c.addr = sp.address1; c.addr2 = sp.address2; }
    }
    const fail = (m) => { banner('🛈 ' + m + ' — 배송지는 직접 입력 후 진행해주세요.', '#c92a2a'); setJob({ addrPhase: null }); };

    // 1) 배송지 변경 모달
    banner('배송지 변경 여는 중...');
    const changeBtn = (await waitFor('button.btnAddress', 8000)) || byText('변경', 'button');
    if (!changeBtn) return fail('배송지 변경 버튼 못 찾음');
    rclick(changeBtn);
    await waitText('배송지 선택', 6000) || await wait(500);

    // 2) 기본배송지 아래 비기본 주소 '수정'
    const editBtn = findEditButtonForNonDefault();
    if (!editBtn) return fail('수정할 비기본 배송지 없음(주소록에 기본 외 1개 필요)');
    banner('배송지 수정 진입...');
    rclick(editBtn);

    // 3) 수정 폼: 받는분 / 연락처(고정)
    const nameI = await waitFor('#productTaker', 8000);
    if (!nameI) return fail('배송지 수정 폼 못 찾음');
    const modal = nameI.closest('.v--modal-box') || document;
    await wait(300);
    setVal(nameI, c.name || '');
    setVal(q('#phoneNum', modal), '01082823536'); // 롯데온 연락처 고정

    // 4) 우편번호 찾기 → 주소검색
    banner('우편번호 검색 중...');
    const findBtn = q('.section.findAddress button', modal) || byText('우편번호 찾기', 'button', modal);
    if (!findBtn) return fail('우편번호 찾기 버튼 못 찾음');
    rclick(findBtn);

    let search = null;
    for (let i = 0; i < 40 && !search; i++) {
      await wait(150);
      search = qa('input[type="text"], input:not([type])').find((el) =>
        el.offsetParent !== null && /주소|검색|도로명|예\)/.test(el.placeholder || '') &&
        el.id !== 'productTaker' && el.id !== 'companyAddress');
    }
    if (!search) return fail('주소검색 입력창 못 찾음');
    setVal(search, String(c.addr || '').replace(/\([^)]*\)/g, '').trim());
    await wait(150);
    for (const t of ['keydown', 'keypress', 'keyup']) search.dispatchEvent(new KeyboardEvent(t, { bubbles: true, key: 'Enter', keyCode: 13, which: 13 }));
    const sBtn = byText('검색', 'button') || q('button.btnSearchInner'); if (sBtn) rclick(sBtn);

    // 5) 첫 결과 펼치고 → (결과 안) 상세주소 입력 → '사용'
    const item = await waitFor('.accordion__item', 8000);
    if (!item) return fail('주소 검색결과 없음');
    rclick(q('.accordion__trigger', item) || item);
    await wait(500);
    const detailIn = qa('input[type="text"], input:not([type])', item).find((el) => el.offsetParent !== null);
    if (detailIn) setVal(detailIn, String(c.addr2 || '').slice(0, 40));
    await wait(200);
    const useBtn = qa('button', item).find((b) => (b.textContent || '').trim() === '사용') || (await waitText('사용', 4000, 'button'));
    if (!useBtn) return fail('주소 "사용" 버튼 못 찾음');
    rclick(useBtn);
    await wait(900);

    // 6) (선택) 배송 메시지 = 고객메모
    if (c.memo) {
      const msgIn = qa('input[type="text"], textarea', modal).find((el) =>
        el.offsetParent !== null && el.id !== 'productTaker' &&
        (/배송 ?메시지|메시지|메모|직접 입력/.test(el.placeholder || '') || /연락주세요/.test(el.value || '')));
      if (msgIn) setVal(msgIn, String(c.memo).slice(0, 50));
    }

    // 7) (필수)개인정보 수집 및 이용 동의(수취인정보)
    let agree = q('#personalInfoAgreed1', modal);
    if (!agree) agree = qa('input[type="checkbox"]', modal).find((cb) => /수취인|개인정보 수집/.test((cb.closest('li,div,label') || {}).textContent || ''));
    if (agree && !agree.checked) rclick(agree);
    await wait(300);

    // 8) 저장 (네이티브 완료 alert 는 자동수락됨)
    const saveBtn = q('#fixingBtn button', modal) || byText('저장', 'button', modal);
    if (!saveBtn) return fail('저장 버튼 못 찾음');
    rclick(saveBtn);
    await wait(1500);

    // 9) 목록에서 방금 수정한 주소(이름 일치) 선택 + 확인 (변경 alert 자동수락)
    const nameHit = qa('label, span, div, li').find((e) => (e.textContent || '').includes(c.name) && e.offsetParent !== null);
    if (nameHit) { const radio = (nameHit.closest('li,div') || {}).querySelector && nameHit.closest('li,div').querySelector('input[type="radio"]'); rclick(radio || nameHit); }
    await wait(300);
    const confirmBtn = byText('확인', 'button');
    if (confirmBtn) rclick(confirmBtn);
    await wait(1200);

    // 10) 주문서 '계속하기'
    const nextBtn = byText('계속하기', 'button') || byText('계속하기', 'a');
    if (nextBtn) rclick(nextBtn);

    await setJob({ addrDone: true, addrPhase: 'done' });
    banner('배송지 입력 완료 ✅ 결제는 직접 진행하세요.', '#1971c2');
  }

  // ── 결제완료 주문상세(/p/order/claim/orderDetail): 주문번호/결제금액 → 삼바 기입 ──
  async function stepResult(job) {
    if (job.status === 'done') return;
    await wait(800);
    const orderNo =
      (q('#odNo') && q('#odNo').value) ||
      (location.href.match(/odNo=(\d+)/) || [])[1] ||
      ((q('.orderNumber') && q('.orderNumber').textContent) || '').replace(/[^0-9]/g, '') || '';
    // 총 결제금액 strong (예: 53,720)
    let amount = '';
    const strong = q('.amountInformation .column.equal strong') || q('.column.equal strong');
    if (strong) amount = ((strong.textContent || '').match(/([\d,]{3,})/) || [])[1]?.replace(/,/g, '') || '';
    const marketNo = job.extNo || job.ordNo || '';
    log('결제완료 감지', { sourcingNo: orderNo, amount, marketNo });
    if (!orderNo) { banner('주문번호를 못 읽음 — 삼바 기입 생략', '#c92a2a'); return; }
    banner(`주문완료! 주문번호 ${orderNo} / ${amount}원 — 삼바 기입 전송`, '#1971c2');
    chrome.runtime.sendMessage({ type: 'WRITEBACK', marketNo, sourcingNo: orderNo, amount, source: 'LOTTEON' });
    await setJob({ status: 'done', result: { orderNo, amount } });
  }

  async function main() {
    const job = await getJob();
    if (!job || job.source !== 'LOTTEON') return;
    const url = location.href;
    try {
      if (/\/orderDetail/.test(url)) return await stepResult(job);
      if (job.status === 'done') return;
      if (/\/p\/product\//.test(url)) {
        banner('🛈 옵션(색상/사이즈)을 직접 선택하고 [바로 구매하기]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.', '#1971c2');
        return;
      }
      if (/\/p\/order\//.test(url)) return await stepOrder(job);
    } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); }
  }

  main();
})();
