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
    const t = (card.innerText || '').replace(/ /g, ' ');
    const m = (re) => { const x = t.match(re); return x ? x[1].trim() : ''; };

    const name = m(/수령인\s+([^\n]+?)\s+연락처/);
    const phone = m(/연락처\s+([0-9\-]+)/);
    const postal = m(/\[(\d{5})\]/);
    let addr = m(/주소\s+([\s\S]+?)(?:\s*\[\d{5}\]|고객메모|타마켓|쿠팡노출|$)/);
    addr = addr.replace(/\s+/g, ' ').trim(); // 줄바꿈(기본/상세 분리)을 공백으로
    let memo = m(/고객메모\s+([^\n]+)/);
    if (memo === '-') memo = '';
    const optionRaw = m(/\[옵션\]\s*([^\n]+)/);
    const qty = m(/수량\s*[:：]\s*(\d+)/) || '1';
    const extNo = m(/상품주문번호\s+([^\s|]+)/);
    const ordNo = m(/주문번호\s+([^\s|]+)/);

    // 사이즈 추출: 끝의 숫자(신발 250 등) 우선, 없으면 마지막 토큰(L 등)
    let size = optionRaw;
    const numEnd = optionRaw.match(/(\d{2,3})\s*$/);
    if (numEnd) size = numEnd[1];
    else { const toks = optionRaw.split(/\s+/).filter(Boolean); size = toks[toks.length - 1] || optionRaw; }

    return { name, phone, postal, addr, addr2: '', memo, size, optionRaw, qty: parseInt(qty) || 1, extNo, ordNo };
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
