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
    if (o.source && ['MUSINSA', 'ABCMART', 'GRANDSTAGE', 'LOTTEON'].indexOf(o.source) < 0) {
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

  // ── 결제완료 후 삼바 기입(writeback) ──
  // 무신사 결제완료 → background → 삼바 탭. 해당 주문 행에 소싱주문번호/실구매가/
  // 상태(배송대기중)/메모(장재훈) 입력. (삼바가 자체 인증으로 저장)
  const qa2 = (s, r = document) => Array.from((r || document).querySelectorAll(s));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  // 삼바 표(React 19 / Next 15)에 값 입력 + '저장'까지 트리거.
  //  - input/change → React onChange (텍스트칸: editingCosts/editingNotes 등 편집상태 갱신,
  //    드롭다운: onChange 에서 orderApi.update 로 즉시 저장)
  //  - (대기) 리렌더로 편집상태가 commit 되도록 → onBlur 저장 핸들러가 최신값을 읽음
  //  - focusout(+native blur) → React onBlur → orderApi.update 호출(서버 저장)
  //    ※ React 17+/19 는 onBlur 를 'blur' 가 아니라 'focusout' 으로 수신한다.
  //      과거엔 가짜 'blur' 만 쏴서, 화면엔 채워져도 서버 저장이 안 돼
  //      새로고침하면 소싱주문번호/실구매가/간단메모가 사라졌다.
  async function setReact(el, val) {
    if (!el) return;
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
    try { el.focus(); } catch (e) { /* noop */ }
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    if (el.tagName === 'SELECT') { await sleep(150); return; } // 드롭다운은 onChange 로 이미 저장
    await sleep(90);  // onChange 가 편집상태에 반영(리렌더)될 시간 → onBlur 가 최신값을 읽음
    el.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); // React onBlur 트리거
    try { el.blur(); } catch (e) { /* noop */ }
    await sleep(160); // orderApi.update(async) 저장 완료 대기
  }

  async function applyWriteback(wb) {
    if (!wb || !wb.marketNo) return;
    let tr = null;
    for (let i = 0; i < 20 && !tr; i++) {
      tr = qa2('tr').find((r) => (r.textContent || '').includes(wb.marketNo));
      if (!tr) await sleep(300);
    }
    if (!tr) { toast(`삼바에서 주문(${wb.marketNo}) 행을 못 찾음 — 화면에 그 주문이 보이게 해주세요`, '#c92a2a'); return; }
    toast('주문번호/금액/상태/메모 기입 중...', '#1971c2');
    const selects = qa2('select', tr);

    // 소싱주문번호 입력 활성화를 위해 주문계정(MUSINSA) 선택 (비활성 시)
    let srcInput = tr.querySelector('input[placeholder*="소싱주문번호"], input[placeholder*="주문계정 먼저"]');
    if (srcInput && srcInput.disabled) {
      const acct = selects.find((s) => qa2('option', s).some((o) => o.textContent.trim() === '주문계정'));
      if (acct) {
        // 소싱처 → 삼바 주문계정 optgroup 라벨 (ABCMART/GRANDSTAGE 는 'ABCmart' 로 정규화됨)
        const SITE_LABEL = { MUSINSA: 'MUSINSA', ABCMART: 'ABCmart', GRANDSTAGE: 'ABCmart' };
        const label = SITE_LABEL[String(wb.source || 'MUSINSA').toUpperCase()] || wb.source || 'MUSINSA';
        const opt = qa2(`optgroup[label="${label}"] option`, acct)[0]
          || qa2('option', acct).find((o) => o.value && o.value !== 'etc' && o.textContent.trim() !== '주문계정');
        if (opt) { await setReact(acct, opt.value); await sleep(500); } // 저장+리렌더로 입력칸 활성화 대기
      }
    }
    // 주문상태 → 배송대기중(wait_ship)
    const statusSel = qa2('select', tr).find((s) => qa2('option', s).some((o) => o.value === 'wait_ship'));
    if (statusSel) await setReact(statusSel, 'wait_ship');
    // 소싱주문번호 (재조회 — 위 저장으로 리렌더되었을 수 있음)
    srcInput = tr.querySelector('input[placeholder*="소싱주문번호"]');
    if (srcInput && !srcInput.disabled && wb.sourcingNo) await setReact(srcInput, String(wb.sourcingNo));
    // 실구매가
    const cost = tr.querySelector('input[placeholder*="실구매가"]');
    if (cost && wb.amount) await setReact(cost, String(wb.amount));
    // 간단메모 = 장재훈
    const notes = tr.querySelector('textarea[placeholder="간단메모"]');
    if (notes) await setReact(notes, '장재훈');

    toast(`✅ 기입 완료: 주문번호 ${wb.sourcingNo} / ${Number(wb.amount).toLocaleString()}원 / 배송대기중 / 메모 장재훈`, '#2b8a3e');
    chrome.storage.local.remove('pendingWriteback');
  }

  chrome.runtime.onMessage.addListener((msg, _s, resp) => {
    if (msg && msg.type === 'WRITEBACK_APPLY') { applyWriteback(msg).then(() => resp({ ok: true })); return true; }
  });
  // 삼바 탭이 결제 후 열렸거나 새로고침된 경우 대비 — 보류 중 writeback 처리
  chrome.storage.local.get('pendingWriteback', ({ pendingWriteback }) => {
    if (pendingWriteback && Date.now() - pendingWriteback.ts < 10 * 60000) applyWriteback(pendingWriteback);
  });
})();
