// 삼바 주문도우미 — 다음(Daum/Kakao) 우편번호 검색 iframe 자동화
// 무신사 '주소 찾기'가 열리면 이 iframe(postcode.map.daum.net 등) 안에서
// 고객 주소로 검색하고 최상단 결과를 자동 선택한다.
// (job.addrSearching === true 일 때만 동작)
(function () {
  const log = (...a) => console.log('%c[주문도우미·우편]', 'color:#d9480f;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function setNativeValue(el, val) {
    try {
      const d = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      d.set.call(el, val);
    } catch (e) { el.value = val; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }

  async function run() {
    let job;
    try { ({ job } = await chrome.storage.local.get('job')); } catch (e) { return; }
    if (!job || job.status === 'done' || !job.addrSearching) return;
    let query = (job.customer && job.customer.addr) || '';
    if (!query) return;
    // 괄호 건물명 제거 → 검색 정확도 향상 (예: "독산로 87 (유명빌딩)" → "독산로 87")
    query = query.replace(/\([^)]*\)/g, '').replace(/\s+/g, ' ').trim();
    log('우편번호 검색 시작:', query, '@', location.href);

    // 1) 검색창 찾기
    let input = null;
    for (let i = 0; i < 60 && !input; i++) {
      input = document.querySelector('input#region_name')
        || document.querySelector('input[type=text]')
        || document.querySelector('input:not([type=hidden]):not([type=button])');
      if (!input) await wait(150);
    }
    if (!input) {
      log('❌ 검색창 못 찾음. body 일부:', (document.body && document.body.innerHTML.slice(0, 600)) || '');
      return;
    }
    log('검색창 발견:', input.id || input.className || input.placeholder);

    input.focus();
    setNativeValue(input, query);
    await wait(150);
    for (const type of ['keydown', 'keypress', 'keyup']) {
      input.dispatchEvent(new KeyboardEvent(type, { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
    }
    // 검색 버튼이 따로 있으면 클릭 시도
    const searchBtn = document.querySelector('button[type=submit], .btn_search, button.search, [class*=search] button');
    if (searchBtn) { try { searchBtn.click(); } catch (e) { /* noop */ } }

    await wait(1600);

    // 2) 최상단 결과 클릭 (여러 후보 셀렉터 + 휴리스틱)
    const sels = [
      '#list .roadAddrPart1', '#list dt', '#list li', '.post_resultList li',
      '[class*=result] li', '[class*=result] dl', 'ul li', 'dl',
    ];
    let row = null;
    for (const s of sels) {
      const el = document.querySelector(s);
      if (el && el.offsetParent !== null && /[0-9]/.test(el.textContent)) { row = el; break; }
    }
    if (!row) {
      // 휴리스틱: 도로명/지번 + 숫자 텍스트를 가진 보이는 클릭요소 중 첫 번째
      const cands = Array.from(document.querySelectorAll('li, dl, dt, div, a'))
        .filter((el) => {
          const t = (el.textContent || '').trim();
          return el.offsetParent !== null && t.length > 6 && t.length < 120 &&
            /[0-9]/.test(t) && /(로|길|동|리)/.test(t);
        });
      log('결과 후보 수:', cands.length, cands.slice(0, 4).map((e) => e.textContent.trim().slice(0, 45)));
      row = cands[0] || null;
    }
    if (row) {
      log('✅ 최상단 결과 클릭:', (row.textContent || '').trim().slice(0, 50));
      row.click();
    } else {
      log('❌ 결과 후보 없음. body 일부:', (document.body && document.body.innerHTML.slice(0, 1000)) || '');
    }
  }

  run();
})();
