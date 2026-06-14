// 삼바 주문도우미 — 롯데온(www.lotteon.com) 자동화 (Vue SPA)
// 옵션(색상/사이즈)은 사용자가 직접 선택(커스텀 드롭다운). 주문서 배송지만 자동입력.
// 결제("계속하기")는 사람이 직접.
(function () {
  const log = (...a) => console.log('%c[주문도우미·롯데온]', 'color:#b51d2b;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s, r = document) => r.querySelector(s);
  const qa = (s, r = document) => Array.from(r.querySelectorAll(s));
  async function getJob() { const { job } = await chrome.storage.local.get('job'); return job || null; }
  async function setJob(p) { const j = (await getJob()) || {}; Object.assign(j, p); await chrome.storage.local.set({ job: j }); return j; }
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

  // ── 주문서 배송지 자동입력 ──
  async function stepOrder(job) {
    if (job.addrDone) { banner('배송지 입력 완료 ✅ "계속하기"(결제)는 직접 진행하세요.', '#1971c2'); return; }
    await setJob({ addrDone: true }); // 루프 방지: 진입 즉시 1회만
    const c = job.customer || {};
    const fail = (m) => banner('🛈 ' + m + ' — 배송지는 직접 입력 후 진행해주세요.', '#c92a2a');

    banner('배송지 변경 여는 중...');
    const changeBtn = (await waitFor('button.btnAddress', 8000)) || byText('변경');
    if (!changeBtn) return fail('배송지 변경 버튼 못 찾음');
    rclick(changeBtn);

    const addNew = await waitText('새 배송지 추가', 8000);
    if (!addNew) return fail('"새 배송지 추가" 못 찾음');
    rclick(addNew);

    const nameI = await waitFor('#productTaker', 8000);
    if (!nameI) return fail('배송지 등록 폼 못 찾음');
    const modal = nameI.closest('.v--modal-box') || document;
    await wait(300);
    setVal(nameI, c.name || '');
    setVal(q('#phoneNum', modal), String(c.phone || '').replace(/[^0-9]/g, ''));

    // 우편번호 찾기 → 주소검색 모달
    banner('우편번호 검색 중...');
    const findBtn = q('.section.findAddress button', modal) || q('#companyAddress', modal)?.parentElement?.querySelector('button');
    if (!findBtn) return fail('우편번호 찾기 버튼 못 찾음');
    rclick(findBtn);

    // 주소검색 입력창(플레이스홀더/모달 내 텍스트 input)
    let search = null;
    for (let i = 0; i < 40 && !search; i++) {
      await wait(150);
      search = qa('input[type="text"], input:not([type])').find((el) =>
        el.offsetParent !== null && /올림픽로|주소|검색|예\)/.test(el.placeholder || '') &&
        el.id !== 'productTaker' && el.id !== 'companyAddress');
    }
    if (!search) return fail('주소검색 입력창 못 찾음');
    setVal(search, String(c.addr || '').replace(/\([^)]*\)/g, '').trim());
    await wait(150);
    for (const t of ['keydown', 'keypress', 'keyup']) search.dispatchEvent(new KeyboardEvent(t, { bubbles: true, key: 'Enter', keyCode: 13, which: 13 }));
    const sBtn = byText('검색') || q('button.btnSearchInner'); if (sBtn) rclick(sBtn);

    // 첫 결과 펼치고 '사용'
    const item = await waitFor('.accordion__item', 8000);
    if (!item) return fail('주소 검색결과 없음');
    rclick(q('.accordion__trigger', item) || item);
    await wait(500);
    const useBtn = qa('button', item).find((b) => (b.textContent || '').trim() === '사용') || (await waitText('사용', 4000, 'button'));
    if (!useBtn) return fail('주소 "사용" 버튼 못 찾음');
    rclick(useBtn);
    await wait(800);

    // 상세주소: findAddress 섹션의 마지막 입력칸
    const fa = q('.section.findAddress', modal) || modal;
    const addrIns = qa('input[type="text"], input:not([type])', fa).filter((el) => el.id !== 'companyAddress');
    if (addrIns.length) setVal(addrIns[addrIns.length - 1], String(c.addr2 || '').slice(0, 40));

    // 배송 메시지(폼 내, 선택) — 있으면 직접입력 칸에
    if (c.memo) {
      const memoIn = qa('input[type="text"]', modal).find((el) => /직접 입력/.test(el.placeholder || ''));
      if (memoIn) setVal(memoIn, String(c.memo).slice(0, 25));
    }

    // 필수 동의 체크(저장 버튼 활성화 위해 필요)
    const agree = q('#personalInfoAgreed1', modal); if (agree && !agree.checked) rclick(agree);
    await wait(300);

    // 저장
    const saveBtn = q('#fixingBtn button', modal) || byText('저장', 'button', modal);
    if (!saveBtn) return fail('저장 버튼 못 찾음');
    rclick(saveBtn);
    await wait(1200);

    // 주소록에서 방금 추가한 배송지 선택 + 확인
    const nameHit = qa('label, span, div, li').find((e) => (e.textContent || '').includes(c.name) && e.offsetParent !== null);
    if (nameHit) { const radio = nameHit.closest('li,div')?.querySelector('input[type="radio"]'); rclick(radio || nameHit); }
    await wait(300);
    const confirm = byText('확인', 'button');
    if (confirm) rclick(confirm);

    banner('배송지 입력 완료 ✅ "계속하기"(결제)는 직접 진행하세요.', '#1971c2');
  }

  async function main() {
    const job = await getJob();
    if (!job || job.status === 'done' || job.source !== 'LOTTEON') return;
    const url = location.href;
    try {
      if (/\/p\/product\//.test(url)) {
        banner('🛈 옵션(색상/사이즈)을 직접 선택하고 [바로 구매하기]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.', '#1971c2');
        return;
      }
      if (/\/p\/order\//.test(url)) return await stepOrder(job);
    } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); }
  }

  main();
})();
