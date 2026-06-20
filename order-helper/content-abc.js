// 삼바 주문도우미 — ABC마트/그랜드스테이지 자동화 (a-rt.com)
// 흐름: 삼바 원문링크 → ABC 상품(/product/new?prdtNo=) → 사이즈선택 → 바로구매
//      → 주문서(/order) → 배송지 자동입력. 결제(#btnPayment)는 사람이 직접.
(function () {
  const log = (...a) => console.log('%c[주문도우미·ABC]', 'color:#e8590c;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));
  async function getJob() { const { job } = await chrome.storage.local.get('job'); return job || null; }
  async function setJob(p) { const j = (await getJob()) || {}; Object.assign(j, p); await chrome.storage.local.set({ job: j }); return j; }
  function sendMsg(type, extra) {
    return new Promise((res) => { try { chrome.runtime.sendMessage(Object.assign({ type }, extra), (r) => res(r || { ok: false })); } catch (e) { res({ ok: false, error: String(e) }); } });
  }
  async function waitFor(sel, t = 12000) {
    const end = Date.now() + t;
    while (Date.now() < end) { const e = q(sel); if (e && e.offsetParent !== null) return e; await wait(120); }
    return q(sel);
  }
  function banner(msg, color = '#e8590c') {
    let el = document.getElementById('__oh_banner');
    if (!el) {
      el = document.createElement('div'); el.id = '__oh_banner';
      el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;font:600 14px/1.4 -apple-system,sans-serif;color:#fff;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.2)';
      document.documentElement.appendChild(el);
    }
    el.style.background = color; el.textContent = '🤖 주문도우미: ' + msg;
  }
  function setVal(el, v) {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v == null ? '' : v);
    ['input', 'change', 'blur'].forEach((t) => el.dispatchEvent(new Event(t, { bubbles: true })));
    return true;
  }
  function setRO(el, v) { if (!el) return false; const w = el.readOnly; el.readOnly = false; setVal(el, v); el.readOnly = w; return true; }

  // 주소 분리(무신사/패션플러스와 동일): 도로명+건물번호 뒤(예: 'A동 GMARKET(...)')를 상세주소로.
  function splitAddress(mainRaw, detailRaw) {
    const main = (mainRaw || '').trim();
    const detail = (detailRaw || '').trim();
    const full = (main + ' ' + detail).replace(/\s+/g, ' ').trim();
    if (!full) return { address1: main, address2: detail };
    const tokens = full.split(' ');
    let anchor = -1;
    for (let i = 0; i < tokens.length; i++) {
      if (/[로길]\d*(번길)?$/.test(tokens[i])) anchor = i;
    }
    if (anchor < 0) {
      for (let i = 0; i < tokens.length; i++) {
        if (/^[가-힣]+(읍|면|동|리)$/.test(tokens[i]) && !/^\d/.test(tokens[i])) anchor = i;
      }
    }
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

  let ranProduct = false;

  // ── 상품: 사이즈 선택 + 바로구매 ──
  async function stepProduct(job) {
    if (job.phase && job.phase !== 'start') return;
    if (ranProduct) return; ranProduct = true;
    const MANUAL = '옵션을 직접 선택하고 [바로구매]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.';
    const size = String(job.size || '').trim();
    await waitFor('button.btn-prod-size', 10000);
    let btn = qa(`li[data-product-option-no="${size}"] button.btn-prod-size`)
      .find((b) => b.offsetParent !== null && !b.classList.contains('sold-out'));
    if (!btn) btn = qa('button.btn-prod-size')
      .find((b) => b.offsetParent !== null && !b.classList.contains('sold-out') && (b.textContent || '').trim() === size);
    if (!btn) { banner('🛈 사이즈 자동선택 실패(' + size + '). ' + MANUAL, '#1971c2'); return; }
    banner(`옵션 '${size}' 선택 중...`);
    btn.click();
    await wait(400);
    await setJob({ phase: 'order' });
    banner('바로구매...');
    const buy = qa('button[data-product-button="buy-now"]').find((b) => b.offsetParent !== null) || q('button[data-product-button="buy-now"]');
    if (!buy) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
    buy.click();
  }

  // ── 주문서: 배송지 자동입력 (결제는 사람이) ──
  async function stepOrder(job) {
    if (job.addrDone) { banner('배송지 입력 완료 ✅ 결제(결제하기)는 직접 진행하세요.', '#1971c2'); return; }
    const c = Object.assign({}, job.customer || {});
    // 라자다 등 — 상세주소가 비어있고 기본주소에 'A동 GMARKET(...)'이 합쳐진 경우 분리
    if (!String(c.addr2 || '').trim()) {
      const sp = splitAddress(c.addr, '');
      if (sp.address2 && sp.address2.trim()) { c.addr = sp.address1; c.addr2 = sp.address2; }
    }
    banner('배송지 자동입력 중...');
    // 신규입력 모드
    const radio = await waitFor('#newDlvy', 10000);
    if (radio && !radio.checked) { radio.click(); radio.dispatchEvent(new Event('change', { bubbles: true })); }
    await wait(300);
    setVal(q('#rcvrName'), c.name || '');
    setVal(q('#rcvrHdphn'), String(c.phone || '010-8282-3536').replace(/[^0-9]/g, ''));

    // 우편번호: 5자리 있으면 사용, 없으면 카카오 API 조회 → readonly 직접 주입
    let zip = /^\d{5}$/.test(String(c.postal || '')) ? c.postal : null;
    if (!zip) {
      const r = await sendMsg('RESOLVE_ZIP', { address: c.addr });
      log('우편번호 조회', r);
      if (r && r.ok && r.zip) zip = r.zip;
    }
    if (zip) {
      setRO(q('#rcvrPostCode'), zip);
      setRO(q('#rcvrPostAddr'), c.addr || ''); // 삼바 기본주소 그대로
    } else {
      banner('우편번호 자동조회 실패 — [우편번호 찾기]로 직접 선택 후 결제하세요.', '#c92a2a');
    }
    setVal(q('#rcvrDtlAddr'), String(c.addr2 || '').slice(0, 40));

    // 배송메모: 항상 '직접입력' 선택 → 메모(없으면 '-') 입력 → 수정 가능하게(readonly 해제)
    const sel = q('#dlvyMemo');
    if (sel) {
      sel.value = 'write';
      sel.dispatchEvent(new Event('change', { bubbles: true }));
      const memoInput = q('#dlvyMemoText');
      if (memoInput) {
        memoInput.readOnly = false; // 영구 해제 — 사용자가 수정 가능
        setVal(memoInput, (String(c.memo || '').trim() || '-').slice(0, 40));
      }
    }

    // [필수] 주문 내역에 대한 동의 자동 체크
    checkRequiredAgree();

    await setJob({ addrDone: true });
    banner('배송지 입력 완료 ✅ 결제(결제하기)는 직접 진행하세요.', '#1971c2');
  }

  // 필수 동의 체크박스 자동 체크 (주문 내역 동의 등)
  function checkRequiredAgree() {
    let n = 0;
    qa('input[type="checkbox"]').forEach((cb) => {
      const scope = cb.closest('li, label') || cb.parentElement;
      const t = (scope && scope.textContent || '').replace(/\s+/g, ' ');
      if (/\[필수\]|주문 내역에 대한 동의|구매에 동의|전자상거래법/.test(t)) {
        if (!cb.checked) { cb.click(); cb.dispatchEvent(new Event('change', { bubbles: true })); }
        n++;
      }
    });
    const hid = q('#termAgreeYn1'); if (hid) hid.value = 'Y';
    log('필수 동의 체크', n, '개');
  }

  // ── 결제완료: 주문번호/결제금액 스크랩 → 삼바 기입(writeback) ──
  //  완료페이지: /order/complete?orderNo=...
  //  주문번호 #orderNo (또는 URL orderNo=), 결제금액 #totalPaymentAmt
  async function stepResult(job) {
    if (job.status === 'done') return; // 새로고침 시 중복 전송 방지
    await wait(800);
    const orderNo =
      ((q('#orderNo') && q('#orderNo').textContent) || '').trim() ||
      (location.href.match(/orderNo=([0-9]+)/) || [])[1] || '';
    const amtEl = q('#totalPaymentAmt');
    const amount = amtEl
      ? ((amtEl.textContent || '').match(/([\d,]{3,})/) || [])[1]?.replace(/,/g, '') || ''
      : '';
    const marketNo = job.extNo || job.ordNo || '';
    log('결제완료 감지', { sourcingNo: orderNo, amount, marketNo, source: job.source });
    if (!orderNo) { banner('주문번호를 못 읽음 — 삼바 기입 생략', '#c92a2a'); return; }
    banner(`주문완료! 주문번호 ${orderNo} / ${amount}원 — 삼바 기입 전송`, '#1971c2');
    chrome.runtime.sendMessage({ type: 'WRITEBACK', marketNo, sourcingNo: orderNo, amount, source: job.source });
    await setJob({ status: 'done', result: { orderNo, amount } });
  }

  async function main() {
    let job = await getJob();
    const url = location.href;
    if (/\/product\//.test(url)) {
      // 신선도: 방금 생성된 ABC 작업만 채택
      const fresh = (j) => j && j.phase === 'start' && j.status !== 'done' &&
        (j.source === 'ABCMART' || j.source === 'GRANDSTAGE') && j.ts && (Date.now() - j.ts) < 30000;
      for (let i = 0; i < 16; i++) { if (fresh(job)) break; await wait(300); job = await getJob(); }
      if (!fresh(job)) return;
    }
    if (!job) return;
    if (job.source !== 'ABCMART' && job.source !== 'GRANDSTAGE') return; // ABC 작업만
    try {
      // 결제완료(/order/complete) 는 /order 보다 먼저 체크 (둘 다 매칭되므로)
      if (/\/order\/complete/.test(url)) return await stepResult(job);
      if (/\/product\//.test(url)) return await stepProduct(job);
      if (/\/order(\b|\/|\?|$)/.test(url)) return await stepOrder(job);
    } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); }
  }

  main();
  try {
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.job) return;
      const j = ch.job.newValue;
      if (j && j.phase === 'start' && (j.source === 'ABCMART' || j.source === 'GRANDSTAGE') &&
        j.ts && (Date.now() - j.ts) < 30000 && /\/product\//.test(location.href) && !ranProduct) main();
    });
  } catch (e) { /* noop */ }
})();
