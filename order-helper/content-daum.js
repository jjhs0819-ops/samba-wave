// 삼바 주문도우미 — 우편번호 검색 iframe (모든 frame 주입, 검색창일 때만 동작)
// 무신사 '주소 찾기'(Daum/Kakao)에서: 고객 주소 입력 → 검색 → 결과 우편번호를 '읽기'만 함.
// ⚠️ 결과를 클릭하지 않음(차단 위험 회피). 매칭되는 결과의 우편번호를 storage에 저장하면
//    무신사 쪽(content-musinsa)이 그 우편번호로 직접 폼을 채워 저장한다.
// job.addrSearching === true 일 때만, 프레임당 1회만 동작 (안전).
(function () {
  const log = (...a) => console.log('%c[주문도우미·우편]', 'color:#d9480f;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function setNativeValue(el, val) {
    try { Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, val); }
    catch (e) { el.value = val; }
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  function fireEnter(el) {
    for (const type of ['keydown', 'keypress', 'keyup']) {
      el.dispatchEvent(new KeyboardEvent(type, { bubbles: true, cancelable: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
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
  async function mark(patch) {
    try {
      const { job } = await chrome.storage.local.get('job');
      await chrome.storage.local.set({ job: Object.assign({}, job, patch) });
    } catch (e) { /* noop */ }
  }

  async function run() {
    let job;
    try { ({ job } = await chrome.storage.local.get('job')); } catch (e) { return; }
    if (!job || job.status === 'done' || !job.addrSearching) return;
    if (!isPostcodeFrame()) return;
    if (window.__ohDaumDone) return; // 안전: 프레임당 1회만
    window.__ohDaumDone = true;

    let query = (job.customer && job.customer.addr) || '';
    if (!query) return;
    query = query.replace(/\([^)]*\)/g, '').replace(/\s+/g, ' ').trim();
    const parts = query.split(/\s+/);
    const roadToken = parts.find((t) => /[로길]/.test(t)) || parts.slice(-2)[0] || '';
    const bnoMatch = roadToken && query.match(new RegExp(esc(roadToken) + '\\s*(\\d+(?:-\\d+)?)'));
    const bno = bnoMatch ? bnoMatch[1] : '';
    log('검색 시작:', query, '| 도로명:', roadToken, '| 건물번호:', bno, '@', location.href);

    // 1) 입력 + 검색 (한 번만). 검색창 없으면 이 frame은 대상이 아님 → 조용히 종료
    //    (무신사 zipCode 래퍼 frame엔 입력창이 없음. 실제 Daum frame만 처리)
    let input = null;
    for (let i = 0; i < 40 && !input; i++) { input = findInput(); if (!input) await wait(150); }
    if (!input) { log('이 frame엔 검색창 없음 — 대상 아님(종료)'); return; }
    log('검색창 발견:', input.id || input.className || input.placeholder);
    input.focus();
    setNativeValue(input, query);
    await wait(200);
    fireEnter(input);
    if (input.form && input.form.requestSubmit) { try { input.form.requestSubmit(); } catch (e) { /* noop */ } }
    const sb = document.querySelector('button.btn_search, .btn_search, button[type=submit]');
    if (sb) { try { sb.click(); } catch (e) { /* noop */ } }

    // 2) 결과에서 '매칭되는' 우편번호 읽기 (클릭 안 함, 텍스트만). 결과 뜨면 즉시 멈춤.
    //    ※ offsetParent 가시성 필터 제거: Daum 결과가 position:fixed 등이라 걸러지던 문제 해결.
    let zip = null;
    const roadRe = bno ? new RegExp(esc(roadToken) + '\\s*' + esc(bno) + '(?!\\d)') : null;
    for (let i = 0; i < 60 && !zip; i++) {
      await wait(250);
      if (i === 10) { try { fireEnter(input); } catch (e) { /* noop */ } } // 결과 없으면 1회만 재검색
      const blocks = Array.from(document.querySelectorAll('*'))
        .filter((el) => {
          const t = (el.textContent || '').replace(/\s+/g, ' ');
          if (t.length > 300 || !/\d{5}/.test(t)) return false;
          if (roadToken && !t.includes(roadToken)) return false;
          if (roadRe && !roadRe.test(t)) return false;   // 입력 주소와 정확히 매칭
          return true;
        })
        .sort((a, b) => (a.textContent || '').length - (b.textContent || '').length);
      if (blocks.length) {
        const m = (blocks[0].textContent || '').match(/\b(\d{5})\b/) || (blocks[0].textContent || '').match(/(\d{5})/);
        if (m) {
          zip = m[1];
          log('✅ 매칭 결과 우편번호:', zip, '|', (blocks[0].innerText || '').replace(/\s+/g, ' ').slice(0, 70));
        }
      }
    }

    if (zip) {
      await mark({ resolvedZip: zip });
      log('우편번호 전달 완료 →', zip);
    } else {
      log('이 frame에서 매칭 결과 못 읽음 — 종료(다른 frame/타임아웃에 맡김)');
    }
  }

  run();
})();
