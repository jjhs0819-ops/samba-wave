// 삼바 주문도우미 — 우편번호 검색 iframe 자동화 (모든 frame에 주입, 검색창일 때만 동작)
// 무신사 '주소 찾기'(Daum/Kakao 우편번호)가 열리면 고객 주소로 검색하고
// 최상단 결과를 자동 선택한다. job.addrSearching === true 일 때만.
(function () {
  const log = (...a) => console.log('%c[주문도우미·우편]', 'color:#d9480f;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function setNativeValue(el, val) {
    const proto = el instanceof window.HTMLTextAreaElement ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
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

  // 이 frame이 우편번호 검색 화면인지 빠르게 판별
  function isPostcodeFrame() {
    const href = location.href;
    if (/postcode|daum|kakao|zipcode|juso/i.test(href)) return true;
    const bt = (document.body && document.body.innerText) || '';
    if (/우편번호|도로명|지번|Powered by kakao|판교역로/.test(bt)) return true;
    const inp = document.querySelector('input[placeholder]');
    if (inp && /판교|도로|동|주소|검색|우편/.test(inp.placeholder || '')) return true;
    return false;
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
    query = query.replace(/\([^)]*\)/g, '').replace(/\s+/g, ' ').trim(); // 괄호 건물명 제거
    log('우편번호 검색 시작:', query, '@', location.href);

    // 1) 검색창
    let input = null;
    for (let i = 0; i < 80 && !input; i++) { input = findInput(); if (!input) await wait(150); }
    if (!input) { log('❌ 검색창 못 찾음'); return; }
    log('검색창 발견:', input.id || input.className || input.placeholder);

    // 2) 입력 + 검색
    input.focus();
    setNativeValue(input, query);
    await wait(200);
    fireEnter(input);
    if (input.form && input.form.requestSubmit) { try { input.form.requestSubmit(); } catch (e) { /* noop */ } }
    const sb = document.querySelector('button.btn_search, .btn_search, button[type=submit]');
    if (sb) { try { sb.click(); } catch (e) { /* noop */ } }

    // 3) 결과 대기 후 최상단 선택 (우편번호 5자리 + 도로명 포함 행 클릭)
    let row = null;
    for (let i = 0; i < 50 && !row; i++) {
      await wait(200);
      const cands = Array.from(document.querySelectorAll('div, li, dl, dd, a, button, span'))
        .filter((el) => {
          if (el.offsetParent === null) return false;
          const t = (el.innerText || '').trim();
          return t.length > 8 && t.length < 250 && /\d{5}/.test(t) && /(로|길)\s*\d/.test(t);
        })
        .sort((a, b) => (a.innerText || '').length - (b.innerText || '').length);
      if (cands.length) {
        log('결과 후보', cands.length, '개:', cands.slice(0, 3).map((e) => (e.innerText || '').replace(/\s+/g, ' ').slice(0, 50)));
        // 너무 작은 조각(우편번호만) 말고, 도로명까지 포함한 가장 작은 클릭대상
        row = cands.find((e) => /(로|길)\s*\d/.test(e.innerText) && /(동|구|시|군)/.test(e.innerText)) || cands[0];
      }
    }
    if (row) {
      log('✅ 최상단 결과 클릭:', (row.innerText || '').replace(/\s+/g, ' ').slice(0, 60));
      row.click();
      // 일부 구현은 내부 앵커 클릭 필요 → 자식도 한번 클릭 시도
      const inner = row.querySelector('a, [class*=road], [class*=addr]');
      if (inner && inner !== row) { try { inner.click(); } catch (e) { /* noop */ } }
    } else {
      log('❌ 결과 후보 없음. 검색이 실행됐는지 확인 필요. body 일부:',
        ((document.body && document.body.innerText) || '').slice(0, 300));
    }
  }

  run();
})();
