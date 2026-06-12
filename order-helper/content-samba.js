// 삼바 주문도우미 — 삼바 주문 페이지 (ISOLATED world content script)
// 원문링크 클릭 → 주문 카드에서 고객정보 파싱 → source_url 캡처 → 자동주문 시작.
(function () {
  const log = (...a) => console.log('%c[주문도우미·삼바]', 'color:#1971c2;font-weight:bold', ...a);
  let pending = null;

  function toast(msg, color = '#1971c2') {
    let el = document.getElementById('__oh_toast');
    if (!el) {
      el = document.createElement('div');
      el.id = '__oh_toast';
      el.style.cssText =
        'position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:12px 16px;' +
        'font:600 13px/1.4 -apple-system,sans-serif;color:#fff;border-radius:8px;max-width:340px;' +
        'box-shadow:0 4px 16px rgba(0,0,0,.3)';
      document.body.appendChild(el);
    }
    el.style.background = color;
    el.textContent = '🤖 ' + msg;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.style.display = 'none'; }, 6000);
    el.style.display = 'block';
  }

  // 원문링크가 속한 주문 카드를 찾아 고객정보 파싱
  function parseOrderCard(btn) {
    let card = btn;
    for (let i = 0; i < 14 && card; i++) {
      const tx = card.textContent || '';
      if (tx.includes('수령인') && tx.includes('연락처') && tx.includes('원문링크')) break;
      card = card.parentElement;
    }
    if (!card) return null;
    // 라벨(수령인/연락처/주소...) span을 찾아 그 그룹 div 반환
    const groupDiv = (label) => {
      const spans = Array.from(card.querySelectorAll('div > span'));
      const lab = spans.find(
        (s) => s.textContent.trim() === label &&
               s.parentElement && s.parentElement.querySelector('[role="button"]')
      );
      return lab ? lab.parentElement : null;
    };
    const copyTexts = (div) =>
      div ? Array.from(div.querySelectorAll('[role="button"]')).map((s) => s.textContent.trim()) : [];
    const clean = (s) => (s && s !== '-' ? s : '');

    // 핵심: 삼바가 이미 나눠둔 기본주소/상세주소 span을 그대로 읽음 (100% 동일, '/' 무시)
    const name = clean(copyTexts(groupDiv('수령인'))[0]);
    const phone = clean(copyTexts(groupDiv('연락처'))[0]);
    const addrDiv = groupDiv('주소');
    const addrTexts = copyTexts(addrDiv);
    const addr = clean(addrTexts[0]);
    const addr2 = clean(addrTexts[1]);
    const postal = addrDiv ? ((addrDiv.textContent.match(/\[(\d{5})\]/) || [])[1] || '') : '';

    // 고객메모
    let memo = '';
    const memoLab = Array.from(card.querySelectorAll('span')).find((s) => s.textContent.trim() === '고객메모');
    if (memoLab && memoLab.parentElement) {
      memo = (memoLab.parentElement.innerText || '').replace('고객메모', '').trim();
      if (memo === '-') memo = '';
    }

    // 옵션/수량/주문번호 (제품 영역)
    const t = card.innerText || '';
    const optionRaw = ((t.match(/\[옵션\]\s*([^\n]+)/) || [])[1] || '').trim();
    const qty = (t.match(/수량\s*[:：]\s*(\d+)/) || [])[1] || '1';
    const extNo = (t.match(/상품주문번호\s+([^\s|]+)/) || [])[1] || '';
    const ordNo = (t.match(/주문번호\s+([^\s|]+)/) || [])[1] || '';

    // 사이즈: 끝의 숫자(신발 250 등) 우선, 없으면 마지막 토큰(L/S 등)
    let size = optionRaw;
    const numEnd = optionRaw.match(/(\d{2,3})\s*$/);
    if (numEnd) size = numEnd[1];
    else { const toks = optionRaw.split(/\s+/).filter(Boolean); size = toks[toks.length - 1] || optionRaw; }

    return { name, phone, postal, addr, addr2, memo, size, optionRaw, qty: parseInt(qty) || 1, extNo, ordNo };
  }

  // 원문링크 클릭을 capture 단계에서 감지 (React onClick 보다 먼저 실행)
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('button');
    if (!btn) return;
    const txt = (btn.textContent || '').replace(/\s/g, '');
    // 디버그: '링크' 들어간 버튼 클릭은 모두 로그 (진단용)
    if (txt.includes('링크')) log('버튼 클릭 감지:', JSON.stringify(txt));
    // '원문링크' 정확히 (원주문링크=마켓 이동이라 제외)
    if (txt === '원문링크') {
      const o = parseOrderCard(btn);
      if (!o || !o.name || !o.addr) {
        log('주문 파싱 실패(원문링크는 정상 동작) →', o);
        toast('주문 정보를 못 읽어 자동주문 미실행 (원문링크만 열림)', '#c92a2a');
        pending = null;
        return; // 무장 안 함 → window.open 정상 동작
      }
      pending = o;
      window.dispatchEvent(new CustomEvent('OH_ARM')); // MAIN world 무장
      log('원문링크 트리거 무장 →', o);
    }
  }, true);

  // MAIN world에서 source_url 캡처되면 자동주문 시작
  window.addEventListener('OH_TRIGGER', (e) => {
    const url = e.detail && e.detail.url;
    if (!pending || !url) return;
    const p = pending; pending = null;
    const job = {
      status: 'active', phase: 'start',
      size: p.size, quantity: p.qty,
      orderId: p.ordNo || p.extNo || '',
      extNo: p.extNo, ordNo: p.ordNo,
      customer: {
        name: p.name, phone: p.phone, postal: p.postal,
        addr: p.addr, addr2: p.addr2, memo: p.memo,
      },
    };
    log('자동주문 시작 →', { url, job });
    toast(`자동주문 시작: ${p.name} / ${p.size} / 우편 ${p.postal}`, '#2b8a3e');
    chrome.runtime.sendMessage({ type: 'START_JOB', job, productUrl: url }, (res) => log('START_JOB', res));
  });

  log('삼바 주문도우미 활성화 — 원문링크 클릭 시 자동주문');
})();
