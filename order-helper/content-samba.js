// 삼바 주문도우미 — 삼바 주문 페이지 (ISOLATED world content script)
// 원문링크 클릭 → 주문 카드에서 고객정보 파싱 → source_url 캡처 → 자동주문 시작.
(function () {
  const log = (...a) => console.log('%c[주문도우미·삼바]', 'color:#1971c2;font-weight:bold', ...a);

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
    let addr = clean(addrTexts[0]);
    let addr2 = clean(addrTexts[1]);
    let postal = addrDiv ? ((addrDiv.textContent.match(/\[(\d{5})\]/) || [])[1] || '') : '';

    // 폴백: span 기반이 비면 카드 innerText 정규식으로 보강
    let nameF = name, phoneF = phone;
    if (!nameF || !addr) {
      const ct = (card.innerText || '').replace(/ /g, ' ');
      nameF = nameF || ((ct.match(/수령인\s+([^\n]+?)\s+연락처/) || [])[1] || '').trim();
      phoneF = phoneF || ((ct.match(/연락처\s+([0-9\-]+)/) || [])[1] || '').trim();
      postal = postal || ((ct.match(/\[(\d{5})\]/) || [])[1] || '');
      if (!addr) {
        let raw = ((ct.match(/주소\s+([\s\S]+?)(?:\s*\[\d{5}\]|고객메모|타마켓|쿠팡노출|$)/) || [])[1] || '')
          .replace(/\s+/g, ' ').trim();
        // 삼바 표시의 '/' 구분자로 기본/상세 분리 (정확 일치)
        if (raw.includes('/')) {
          const i = raw.indexOf('/');
          addr = raw.slice(0, i).trim();
          addr2 = raw.slice(i + 1).trim();
        } else {
          addr = raw;
        }
      }
    }

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

    // 소싱처 감지 (배지 텍스트) — 무신사 외 사이트는 이 확장이 자동화하지 않음
    const SITES = ['MUSINSA', 'LOTTEON', 'ABCMART', 'SSG', 'GSSHOP', 'GS', 'FASHIONPLUS', 'NIKE', 'OLIVEYOUNG', 'KREAM', 'ELANDMALL', 'GRANDSTAGE'];
    let source = '';
    Array.from(card.querySelectorAll('*')).some((el) => {
      if (el.children.length) return false;
      const u = (el.textContent || '').trim().toUpperCase().replace(/\s/g, '');
      if (SITES.indexOf(u) >= 0) { source = u; return true; }
      return false;
    });

    return { name: nameF, phone: phoneF, postal, addr, addr2, memo, size, optionRaw, qty: parseInt(qty) || 1, extNo, ordNo, source };
  }

  // 원문링크 클릭을 capture 단계에서 감지 (React onClick 보다 먼저 실행).
  // 작업(job)만 저장하고, 무신사 탭은 원래 원문링크(window.open) 동작 그대로 열림.
  // 무신사 탭이 뜨면 content-musinsa가 저장된 job을 읽어 자동 진행.
  document.addEventListener('click', (e) => {
    const btn = e.target.closest && e.target.closest('button');
    if (!btn) return;
    const txt = (btn.textContent || '').replace(/\s/g, '');
    if (txt.includes('링크')) log('버튼 클릭 감지:', JSON.stringify(txt));
    if (txt !== '원문링크') return; // 원주문링크=마켓 이동이라 제외

    const o = parseOrderCard(btn);
    log('파싱 결과 →', o);
    if (!o || !o.name || !o.addr) {
      log('주문 파싱 실패(원문링크는 정상 동작)');
      toast('주문 정보를 못 읽어 자동주문 미실행 (원문링크만 열림)', '#c92a2a');
      chrome.storage.local.remove('job'); // 이전 job 잔존으로 인한 오작동 방지
      return;
    }
    if (o.source && ['MUSINSA', 'ABCMART', 'GRANDSTAGE'].indexOf(o.source) < 0) {
      log('미지원 소싱처 →', o.source);
      toast(`${o.source} 주문은 자동주문 미지원. 원문링크만 열립니다.`, '#c92a2a');
      chrome.storage.local.remove('job');
      return;
    }
    // 연락처 규칙: ABC는 무조건 고정번호, 무신사는 0502 안심번호만 대체
    let phone = o.phone;
    const isAbc = o.source === 'ABCMART' || o.source === 'GRANDSTAGE';
    if (isAbc) {
      phone = '010-8282-3536';
      log('ABC 주문 → 연락처 010-8282-3536 고정');
    } else if (/^0502/.test((phone || '').replace(/[^0-9]/g, ''))) {
      phone = '010-8282-3536';
      log('안심번호(0502) 감지 → 010-8282-3536 으로 대체');
    }
    const job = {
      status: 'active', phase: 'start',
      ts: Date.now(),
      source: o.source || 'MUSINSA',
      size: o.size, quantity: o.qty,
      orderId: o.ordNo || o.extNo || '',
      extNo: o.extNo, ordNo: o.ordNo,
      customer: {
        name: o.name, phone, postal: o.postal,
        addr: o.addr, addr2: o.addr2, memo: o.memo,
      },
    };
    chrome.storage.local.set({ job }, () => log('자동주문 job 저장 →', job));
    toast(`자동주문 준비: ${o.name} / ${o.size}${o.postal ? ' / 우편 ' + o.postal : ''} — 무신사 탭에서 진행`, '#2b8a3e');
    // preventDefault 안 함 → React 원문링크 핸들러가 무신사 탭을 연다
  }, true);

  log('삼바 주문도우미 활성화 — 원문링크 클릭 시 자동주문');
})();
