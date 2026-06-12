// 삼바 주문도우미 — 우편번호 검색 iframe 자동화 (모든 frame 주입, 검색창일 때만 동작)
// 무신사 '주소 찾기'(Daum/Kakao)가 열리면: 고객 주소 입력 → 검색 → 최상단 결과 선택.
// job.addrSearching === true 일 때만.
(function () {
  const log = (...a) => console.log('%c[주문도우미·우편]', 'color:#d9480f;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function setNativeValue(el, val) {
    const proto = window.HTMLInputElement.prototype;
    try { Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val); }
    catch (e) { el.value = val; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function fireEnter(el) {
    for (const type of ['keydown', 'keypress', 'keyup']) {
      el.dispatchEvent(new KeyboardEvent(type, { bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
    }
  }
  // 실제 사용자 클릭처럼 — pointer/mouse 전체 시퀀스
  function deepClick(el) {
    const seq = ['pointerover', 'pointerenter', 'mouseover', 'mousemove', 'pointerdown', 'mousedown', 'focus', 'pointerup', 'mouseup', 'click'];
    for (const type of seq) {
      try {
        const Ctor = type.startsWith('pointer') ? (window.PointerEvent || MouseEvent) : (type === 'focus' ? FocusEvent : MouseEvent);
        el.dispatchEvent(new Ctor(type, { bubbles: true, cancelable: true, view: window }));
      } catch (e) { try { el.dispatchEvent(new MouseEvent('click', { bubbles: true })); } catch (e2) { /* noop */ } }
    }
  }

  function isPostcodeFrame() {
    if (/postcode|daum|kakao|zipcode|juso/i.test(location.href)) return true;
    const bt = (document.body && document.body.innerText) || '';
    if (/우편번호|도로명|지번|Powered by kakao|판교역로/.test(bt)) return true;
    const inp = document.querySelector('input[placeholder]');
    return !!(inp && /판교|도로|동|주소|검색|우편/.test(inp.placeholder || ''));
  }
  function findInput() {
    const inputs = Array.from(document.querySelectorAll('input')).filter((i) => i.offsetParent !== null);
    return inputs.find((i) => /판교|도로|동|주소|검색|우편/.test(i.placeholder || ''))
      || inputs.find((i) => i.type === 'text' || i.type === 'search' || !i.type)
      || inputs[0] || null;
  }

  async function run() {
    let job;
    try { ({ job } = await chrome.storage.local.get('job')); } catch (e) { return; }
    if (!job || job.status === 'done' || !job.addrSearching) return;
    if (!isPostcodeFrame()) return;

    let query = (job.customer && job.customer.addr) || '';
    if (!query) return;
    query = query.replace(/\([^)]*\)/g, '').replace(/\s+/g, ' ').trim();
    const roadToken = (query.split(/\s+/).find((t) => /[로길]/.test(t))) || query.split(/\s+/).slice(-2)[0] || '';
    log('우편번호 검색 시작:', query, '| roadToken:', roadToken, '@', location.href);

    // 1) 검색창 입력 + 검색
    let input = null;
    for (let i = 0; i < 80 && !input; i++) { input = findInput(); if (!input) await wait(150); }
    if (!input) { log('❌ 검색창 못 찾음'); return; }
    log('검색창 발견:', input.id || input.className || input.placeholder);
    input.focus();
    setNativeValue(input, query);
    await wait(200);
    fireEnter(input);
    if (input.form && input.form.requestSubmit) { try { input.form.requestSubmit(); } catch (e) { /* noop */ } }
    const sb = document.querySelector('button.btn_search, .btn_search, button[type=submit]');
    if (sb) { try { sb.click(); } catch (e) { /* noop */ } }

    // 2) 결과행 찾기: roadToken 포함 + 같은 조상에 5자리 우편번호
    let row = null;
    for (let i = 0; i < 60 && !row; i++) {
      await wait(200);
      const els = Array.from(document.querySelectorAll('*')).filter((el) => el.offsetParent !== null);
      const roadEls = els
        .filter((el) => {
          const t = (el.textContent || '').replace(/\s+/g, ' ');
          return roadToken && t.includes(roadToken) && t.length < 160;
        })
        .sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (roadEls.length) {
        const target = roadEls[0];
        // 우편번호(5자리)를 포함하는 가장 가까운 조상 = 결과행
        let anc = target, found = null;
        for (let k = 0; k < 7 && anc; k++) { if (/\d{5}/.test(anc.textContent || '')) found = anc; anc = anc.parentElement; }
        row = found || target;
        log('결과행 발견:', (row.innerText || '').replace(/\s+/g, ' ').slice(0, 70));
      }
    }

    // 3) 선택(클릭)
    if (row) {
      // 도로명 텍스트 조각 우선 클릭 후 행 클릭 (핸들러 위치 불문 커버)
      const roadChild = Array.from(row.querySelectorAll('*'))
        .find((e) => (e.textContent || '').includes(roadToken) && e.children.length <= 1) || row;
      deepClick(roadChild);
      await wait(120);
      deepClick(row);
      log('✅ 최상단 결과 선택 클릭 완료');
    } else {
      log('❌ 결과행 못 찾음 (roadToken=', roadToken, '). body 일부:',
        ((document.body && document.body.innerText) || '').replace(/\s+/g, ' ').slice(0, 300));
    }
  }

  run();
})();
