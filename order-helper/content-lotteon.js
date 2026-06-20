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

  // 배송지 선택 목록에서 이름이 일치하는 항목의 radio 선택 (기본배송지=장재훈 제외, 비기본만 radio)
  function selectAddressRadioByName(name) {
    const radios = qa('input[type="radio"]').filter((r) => r.offsetParent !== null);
    for (const r of radios) {
      let box = r.parentElement;
      for (let d = 0; d < 6 && box; d++) {
        if ((box.textContent || '').includes(name)) { rclick(r); return true; }
        box = box.parentElement;
      }
    }
    return false;
  }

  // 주문서 '배송요청사항'(.deliveryRequest)에 고객메모를 직접입력으로 채운다.
  async function fillDeliveryRequest(memo) {
    if (!memo) return;
    const reqBox = q('.deliveryRequest') || q('[class*="deliveryRequest"]') || document;
    let reqInput = qa('input[type="text"], textarea', reqBox).find((el) => el.offsetParent !== null && el.id !== 'productTaker');
    if (!reqInput) {
      const reqChange = q('button[data-cmpnt-name="ord_delrequest_change"]', reqBox) ||
        qa('button', reqBox).find((b) => /변경/.test(b.textContent || '') && b.offsetParent !== null);
      if (reqChange) { rclick(reqChange); await wait(700); }
      const direct = qa('label, span, div, button, li', reqBox).find((e) => /직접\s*입력/.test(e.textContent || '') && e.offsetParent !== null);
      if (direct) { rclick(direct); await wait(400); }
      reqInput = qa('input[type="text"], textarea', reqBox).find((el) => el.offsetParent !== null && el.id !== 'productTaker');
    }
    if (reqInput) setVal(reqInput, String(memo).slice(0, 50));
    else banner('🛈 배송요청사항 자동입력 실패 — 직접 입력해주세요.', '#d9480f');
  }

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

    // 주소검색 팝업의 검색 입력창. placeholder '예)올림픽로 300' 으로 식별.
    // ⚠ 헤더 전역검색도 .searchArea 클래스를 쓰므로 그걸로 잡으면 안 됨 →
    //    placeholder '올림픽로' 또는 팝업 전용 컨테이너(.zipCodeWrap/.searchAreaWrap)로만 식별.
    let search = null;
    for (let i = 0; i < 50 && !search; i++) {
      await wait(150);
      search = qa('input').find((el) => el.offsetParent !== null && /올림픽로/.test(el.placeholder || '')) ||
        q('.zipCodeWrap input[type="search"]') || q('.searchAreaWrap input[type="search"]');
    }
    if (!search) return fail('주소검색 입력창 못 찾음');
    await wait(450); // 팝업 Vue v-model 바인딩 안정화 대기 (이른 입력 시 리셋됨)
    const query = String(c.addr || '').replace(/\([^)]*\)/g, '').trim();
    // 검색창 전용 입력: blur 없이 focus→value→input (blur 가 입력을 무효화하던 문제 회피)
    const typeSearch = (v) => {
      try { search.focus(); } catch (e) { /* noop */ }
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(search, v);
      search.dispatchEvent(new Event('input', { bubbles: true }));
      search.dispatchEvent(new Event('keyup', { bubbles: true }));
    };
    typeSearch(query);
    await wait(200);
    if ((search.value || '') !== query) { typeSearch(query); await wait(200); } // 1회 재시도
    // 검색 실행: 돋보기 버튼(.btnSearchInner) 우선, 삭제버튼(.btnSearchDel)은 제외
    for (const t of ['keydown', 'keypress', 'keyup']) search.dispatchEvent(new KeyboardEvent(t, { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
    const box = search.closest('.searchAreaWrap, .zipCodeWrap, .searchArea') || search.parentElement || document;
    const sBtn = q('.btnSearchInner', box) ||
      qa('button', box).find((b) => b.offsetParent !== null && !/btnSearchDel/.test(b.className));
    if (sBtn) rclick(sBtn);

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
    // ⚠ #fixingBtn 안에는 약관 '보기' 버튼도 있으므로 .buttonGroup 의 저장 버튼을 정확히 지정
    const fixing = document.querySelector('#fixingBtn');
    const saveBtn = (fixing && (fixing.querySelector('.buttonGroup button') ||
      qa('button', fixing).find((b) => /저장/.test(b.textContent || '') && b.offsetParent !== null)))
      || qa('button').find((b) => /저장/.test(b.textContent || '') && b.offsetParent !== null);
    if (!saveBtn) return fail('저장 버튼 못 찾음');
    rclick(saveBtn);
    await wait(1500);

    // 9) 저장 후 — 배송지 변경(목록)을 다시 열어 방금 수정한 주소(이름 일치) radio 선택 + 확인
    //    (저장만으론 주문에 적용 안 됨. 목록에서 선택+확인 해야 기본배송지 대신 적용됨)
    await wait(1000);
    if (!byText('배송지 선택')) {
      const reopen = (await waitFor('button.btnAddress', 5000)) || byText('변경', 'button');
      if (reopen) rclick(reopen);
      await waitText('배송지 선택', 5000);
    }
    let picked = false;
    for (let i = 0; i < 15 && !picked; i++) { picked = selectAddressRadioByName(c.name || ''); if (!picked) await wait(250); }
    if (!picked) banner('🛈 수정한 주소 자동선택 실패 — 목록에서 직접 선택 후 확인해주세요.', '#d9480f');
    await wait(400);
    const confirmBtn = byText('확인', 'button');
    if (confirmBtn) rclick(confirmBtn);
    await wait(1300);

    // 9-1) 배송요청사항(주문서)에 고객메모 직접입력
    await fillDeliveryRequest(c.memo);
    await wait(300);

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

  // ── 상품 페이지: 옵션(사이즈) 선택 + 바로 구매하기 ──
  let ranProduct = false;
  async function stepProduct(job) {
    if (ranProduct) return; ranProduct = true;
    const MANUAL = '옵션(색상/사이즈)을 직접 선택하고 [바로 구매하기]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.';
    const size = String(job.size || '').trim();
    // 옵션 그룹(.optionWrap) — 1개면 자동선택, 색상+사이즈처럼 2개 이상이면 수동
    await waitFor('.optionWrap', 8000);
    const groups = qa('.optionWrap').filter((g) => g.offsetParent !== null);
    if (groups.length === 0) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
    if (groups.length >= 2) { banner('🛈 옵션이 여러 개예요(색상·사이즈 등). ' + MANUAL, '#1971c2'); return; }

    const group = groups[0];
    banner(`옵션 '${size}' 선택 중...`);
    // 1) 드롭다운 열기
    rclick(q('.selectResult', group) || group);
    // 2) 목록 대기
    await waitFor('ul.selectLists', 4000, group);
    await wait(300);
    const listRoot = q('ul.selectLists', group) || group;
    const items = qa('li', listRoot).filter((li) => li.offsetParent !== null);
    // 3) 사이즈 매칭: li 의 첫 숫자 토큰 === size (품절 제외), 폴백으로 포함 매칭
    let target = items.find((li) => {
      const t = (li.textContent || '').replace(/\s+/g, ' ').trim();
      if (/품절|sold|일시품절/i.test(t)) return false;
      return ((t.match(/\d+/) || [])[0] || '') === size;
    }) || items.find((li) => !/품절|sold|일시품절/i.test(li.textContent || '') && (li.textContent || '').includes(size));
    if (!target) { banner(`🛈 사이즈 '${size}' 자동선택 실패. ` + MANUAL, '#d9480f'); return; }
    rclick(q('.labelTextWrap', target) || target);
    await wait(500);
    // 4) 바로 구매하기
    const buy = byText('바로 구매하기', 'button, a') || qa('button, a').find((b) => /바로\s*구매/.test(b.textContent || '') && b.offsetParent !== null);
    if (!buy) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
    banner('바로 구매하기...');
    rclick(buy);
  }

  async function main() {
    let job = await getJob();
    const url = location.href;
    // 상품 페이지: 방금 생성된 롯데온 작업 채택(작업이 늦게 들어와도 대기)
    if (/\/p\/product\//.test(url)) {
      const fresh = (j) => j && j.source === 'LOTTEON' && j.status !== 'done' && j.ts && (Date.now() - j.ts) < 60000;
      for (let i = 0; i < 16 && !fresh(job); i++) { await wait(300); job = await getJob(); }
      if (!fresh(job)) return;
      try { return await stepProduct(job); } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); return; }
    }
    if (!job || job.source !== 'LOTTEON') return;
    try {
      if (/\/orderDetail/.test(url)) return await stepResult(job);
      if (job.status === 'done') return;
      if (/\/p\/order\//.test(url)) return await stepOrder(job);
    } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); }
  }

  main();
  // 작업이 늦게 저장되는 경우 대비 — 상품 페이지에서 job 변경 감지 시 재시도
  try {
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.job) return;
      const j = ch.job.newValue;
      if (j && j.source === 'LOTTEON' && j.status !== 'done' && j.ts && (Date.now() - j.ts) < 60000 &&
        /\/p\/product\//.test(location.href) && !ranProduct) main();
    });
  } catch (e) { /* noop */ }
})();
