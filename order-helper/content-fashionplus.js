// 삼바 주문도우미 — 패션플러스 자동화 (www.fashionplus.co.kr)
// 흐름: 삼바 원문링크 → 상품(/goods/detail/{no}) → 옵션선택 → 바로구매
//       → 주문서(/order/{세션ID}) → '배송지 변경' 모달(iframe) → '새 주소 입력' 탭
//       → 배송지 자동입력 → 등록 → 배송메모/필수동의. 결제(주문하기)는 사람이 직접.
//
// 프레임워크: jQuery 3.6.0 + data-* 커스텀 바인딩 (React/Vue 아님).
//   value 설정 후 input 이벤트 dispatch 로 내부 모델 동기화.
// 입력칸이 id/name 없이 maxlength 로만 구분됨 → maxlength 매핑으로 잡는다.
// 배송지 입력은 같은 도메인 iframe(/order/manage/delivery-address) 안에서 동작 →
//   top frame 에서 iframe.contentDocument 로 접근(동일 출처라 가능).
// 결제완료 페이지(writeback)는 완료 URL/셀렉터 확인 후 추가 예정.
(function () {
  const log = (...a) => console.log('%c[주문도우미·패션플러스]', 'color:#c2255c;font-weight:bold', ...a);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s, r) => (r || document).querySelector(s);
  const qa = (s, r) => Array.from((r || document).querySelectorAll(s));
  async function getJob() { const { job } = await chrome.storage.local.get('job'); return job || null; }
  async function setJob(p) { const j = (await getJob()) || {}; Object.assign(j, p); await chrome.storage.local.set({ job: j }); return j; }
  function sendMsg(type, extra) {
    return new Promise((res) => { try { chrome.runtime.sendMessage(Object.assign({ type }, extra), (r) => res(r || { ok: false })); } catch (e) { res({ ok: false, error: String(e) }); } });
  }
  async function waitFor(sel, t = 12000, root) {
    const end = Date.now() + t;
    while (Date.now() < end) {
      const e = q(sel, root);
      if (e && (root ? true : e.offsetParent !== null)) return e;
      await wait(120);
    }
    return q(sel, root);
  }
  function findByText(text, sel, root) {
    return qa(sel || 'a,button', root).find(
      (e) => (e.textContent || '').replace(/\s+/g, ' ').trim().includes(text) && (root ? true : e.offsetParent !== null)
    );
  }
  function banner(msg, color = '#c2255c') {
    let el = document.getElementById('__oh_banner');
    if (!el) {
      el = document.createElement('div'); el.id = '__oh_banner';
      el.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;font:600 14px/1.4 -apple-system,sans-serif;color:#fff;text-align:center;box-shadow:0 2px 8px rgba(0,0,0,.2)';
      document.documentElement.appendChild(el);
    }
    el.style.background = color; el.textContent = '🤖 주문도우미: ' + msg;
  }
  // value 주입 + input/change/blur dispatch. readonly 칸은 잠깐 해제 후 다시 잠금(값 유지).
  function setVal(el, v) {
    if (!el) return false;
    const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype;
    const ro = el.readOnly;
    if (ro) el.readOnly = false;
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, v == null ? '' : v);
    ['input', 'change', 'blur'].forEach((t) => el.dispatchEvent(new Event(t, { bubbles: true })));
    if (ro) el.readOnly = ro;
    return true;
  }

  // 받는사람 이름 정리: 라자다 주문 '(G2L) 4459753609' → 괄호 제거 후 '4459753609'.
  // 패션플러스 이름칸은 10자 제한이라 잘라서 반환.
  function cleanName(name) {
    return String(name || '').replace(/\([^)]*\)/g, '').trim().slice(0, 10);
  }

  // 주소 분리(무신사와 동일 로직): 도로명+건물번호 뒤(예: 'A동 GMARKET(...)')를 상세주소로.
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

  // ── 상품: 옵션 선택 + 바로구매 ──
  async function stepProduct(job) {
    if (job.phase && job.phase !== 'start') return;
    if (ranProduct) return; ranProduct = true;
    const MANUAL = '옵션을 직접 선택하고 [바로 구매]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.';
    const size = String(job.size || '').trim();
    await waitFor('li[data-index] button.btn_option', 10000);
    const opts = qa('li[data-index] button.btn_option').filter((b) => b.offsetParent !== null && !/sold|disabled|품절/i.test(b.className + ' ' + b.textContent));
    if (!opts.length) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
    // 단일옵션('단일상품')이면 자동선택, 여러 개면 사이즈 텍스트 매칭 시도
    let target = opts.length === 1 ? opts[0]
      : opts.find((b) => (b.textContent || '').toUpperCase().includes(size.toUpperCase()));
    if (!target) { banner(`🛈 옵션이 여러 개예요. ` + MANUAL, '#1971c2'); return; }
    banner('옵션 선택 중...');
    target.click();
    await wait(400);
    await setJob({ phase: 'order' });
    banner('바로 구매...');
    const buy = await waitFor('button[data-button="buy"]', 6000);
    if (!buy) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
    buy.click();
  }

  // 같은 출처 iframe 문서 확보 (배송지 입력창)
  async function waitForIframeDoc(srcPart, t = 12000) {
    const end = Date.now() + t;
    while (Date.now() < end) {
      const ifr = qa('iframe').find((f) => ((f.getAttribute('src') || f.src || '')).includes(srcPart));
      if (ifr) {
        try {
          const d = ifr.contentDocument || (ifr.contentWindow && ifr.contentWindow.document);
          if (d && d.querySelector('a.btn_tab, input.textfield')) return d;
        } catch (e) { /* 동일 출처라 보통 접근 가능 */ }
      }
      await wait(150);
    }
    return null;
  }

  // 배송메모: '직접 입력하기'(value=custom) 선택 → .syncer-ship-memo 동기화 입력칸 채움
  function setShipMemo(memo) {
    const sel = qa('select[data-select]').find((s) => qa('option', s).some((o) => o.value === 'custom'));
    if (!sel) { log('배송메모 select 없음'); return; }
    sel.value = 'custom';
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    const memoInput = q('.syncer-ship-memo');
    if (memoInput) setVal(memoInput, (String(memo || '').trim() || '-').slice(0, 20));
  }

  // 필수 동의: data-check 의 _group:'agree_check' 묶음. '전체 동의' 우선, 없으면 개별 체크.
  function checkRequiredAgree() {
    const inGroup = (cb) => /agree_check/.test(cb.getAttribute('data-check') || '');
    const all = qa('input[type="checkbox"][data-check]').find((cb) => inGroup(cb) && /check_all/.test(cb.getAttribute('data-check') || ''));
    if (all && !all.checked) { all.click(); all.dispatchEvent(new Event('change', { bubbles: true })); log('필수 전체동의 체크'); return; }
    let n = 0;
    qa('input[type="checkbox"][data-check]').forEach((cb) => {
      if (inGroup(cb) && !cb.checked) { cb.click(); cb.dispatchEvent(new Event('change', { bubbles: true })); n++; }
    });
    log('필수 동의 개별 체크', n);
  }

  // ── 주문서: '배송지 변경' → iframe '새 주소 입력' → 자동입력 → 등록 ──
  async function stepOrder(job) {
    if (job.addrDone) { banner('배송지 입력 완료 ✅ 배송메모/동의 확인 후 [주문하기]는 직접 진행하세요.', '#1971c2'); return; }
    if (job.addrPhase === 'running') return;
    await setJob({ addrPhase: 'running' });
    const c = Object.assign({}, job.customer || {});
    // 라자다 등 — 상세주소가 비어있고 기본주소에 'A동 GMARKET(...)'이 합쳐진 경우 분리
    if (!String(c.addr2 || '').trim()) {
      const sp = splitAddress(c.addr, '');
      if (sp.address2 && sp.address2.trim()) { c.addr = sp.address1; c.addr2 = sp.address2; }
    }

    // 1) '배송지 변경' → 모달(iframe) 오픈
    banner('배송지 변경 여는 중...');
    const changeBtn = findByText('배송지 변경', 'a,button') || q('a.btn-address');
    if (changeBtn) changeBtn.click();
    else { banner('"배송지 변경" 버튼 없음 — 직접 진행해주세요.', '#c92a2a'); await setJob({ addrPhase: null }); return; }

    // 2) iframe 문서 확보
    const doc = await waitForIframeDoc('delivery-address', 12000);
    if (!doc) { banner('배송지 입력창(iframe)을 못 찾음 — 직접 입력해주세요.', '#c92a2a'); await setJob({ addrPhase: null }); return; }

    // 3) '새 주소 입력' 탭
    const tab = findByText('새 주소', 'a.btn_tab, a', doc);
    if (tab) { tab.click(); await wait(500); }

    // 4) 입력칸(maxlength 매핑)
    await waitFor('input.textfield[maxlength="10"]', 8000, doc);
    const nameI = q('input.textfield[maxlength="10"]', doc);
    const phoneI = q('input.textfield[maxlength="14"]', doc);
    const detailI = q('input.textfield[maxlength="200"]', doc);
    const readonlys = qa('input.textfield[readonly]', doc);
    const postalI = readonlys[0]; // 우편번호
    const roadI = readonlys[1];   // 검색주소(도로명)

    banner('배송지 자동입력 중...');
    setVal(nameI, cleanName(c.name)); // 라자다 '(G2L) 4459753609' → '4459753609' (10자 제한)
    setVal(phoneI, String(c.phone || '010-8282-3536').replace(/[^0-9]/g, '')); // 숫자만 (연락처는 삼바측에서 고정)

    // 우편번호: readonly → 카카오 API 조회 후 직접 주입 (실패 시 안내)
    let zip = /^\d{5}$/.test(String(c.postal || '')) ? c.postal : null;
    if (!zip) {
      const r = await sendMsg('RESOLVE_ZIP', { address: c.addr });
      log('우편번호 조회', r);
      if (r && r.ok && r.zip) zip = r.zip;
    }
    if (zip) {
      setVal(postalI, zip);
      setVal(roadI, c.addr || ''); // 삼바 기본주소 그대로
    } else {
      banner('우편번호 자동조회 실패 — iframe의 [우편번호 찾기]로 직접 선택 후 등록해주세요.', '#c92a2a');
    }
    setVal(detailI, String(c.addr2 || '').slice(0, 200));

    // 5) 등록하기
    await wait(300);
    const reg = findByText('등록', 'button, a', doc);
    if (reg) { banner('새 배송지 등록 중...'); reg.click(); }
    await wait(900);

    // 6) 주문서 본문: 배송메모 직접입력 + 메모, 필수동의 체크
    setShipMemo(c.memo);
    checkRequiredAgree();

    await setJob({ addrDone: true, addrPhase: 'done' });
    banner('배송지 입력 완료 ✅ 배송메모/동의 확인 후 [주문하기]는 직접 진행하세요.', '#1971c2');
  }

  // ── 결제완료(/order/{id}/complete): 주문번호/결제금액 스크랩 → 삼바 기입 ──
  async function stepResult(job) {
    if (job.status === 'done') return; // 새로고침 중복 전송 방지
    await wait(800);
    const orderNo =
      (location.href.match(/\/order\/(\d+)\/complete/) || [])[1] ||
      (((findByText('주문번호', 'small, span, p, li') || {}).textContent || '').match(/(\d{6,})/) || [])[1] || '';
    // 최종 결제금액: '총 결제 예상금액' 행의 .text_price strong (예: 41,490)
    let amount = '';
    const totalP = qa('.text_total').find((p) => /결제/.test(p.textContent || ''));
    const strong = (totalP && (totalP.querySelector('.text_price strong') || totalP.querySelector('strong')))
      || q('.m_order-fin .text_total .text_price strong');
    if (strong) amount = ((strong.textContent || '').match(/([\d,]{3,})/) || [])[1]?.replace(/,/g, '') || '';
    const marketNo = job.extNo || job.ordNo || '';
    log('결제완료 감지', { sourcingNo: orderNo, amount, marketNo });
    if (!orderNo) { banner('주문번호를 못 읽음 — 삼바 기입 생략', '#c92a2a'); return; }
    banner(`주문완료! 주문번호 ${orderNo} / ${amount}원 — 삼바 기입 전송`, '#1971c2');
    chrome.runtime.sendMessage({ type: 'WRITEBACK', marketNo, sourcingNo: orderNo, amount, source: 'FASHIONPLUS' });
    await setJob({ status: 'done', result: { orderNo, amount } });
  }

  async function main() {
    let job = await getJob();
    const url = location.href;
    if (/\/goods\/detail\//.test(url)) {
      // 신선도: 방금 생성된 패션플러스 작업만 채택
      const fresh = (j) => j && j.phase === 'start' && j.status !== 'done' &&
        j.source === 'FASHIONPLUS' && j.ts && (Date.now() - j.ts) < 30000;
      for (let i = 0; i < 16; i++) { if (fresh(job)) break; await wait(300); job = await getJob(); }
      if (!fresh(job)) return;
    }
    if (!job) return;
    if (job.source !== 'FASHIONPLUS') return; // 패션플러스 작업만
    try {
      // 결제완료(/order/{id}/complete) 는 /order 보다 먼저 체크 (둘 다 매칭됨)
      if (/\/order\/\d+\/complete/.test(url)) return await stepResult(job);
      if (/\/goods\/detail\//.test(url)) return await stepProduct(job);
      if (/\/order\//.test(url)) return await stepOrder(job);
    } catch (e) { log('오류', e); banner('오류 발생 — 콘솔 확인', '#c92a2a'); }
  }

  main();
  try {
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area !== 'local' || !ch.job) return;
      const j = ch.job.newValue;
      if (j && j.phase === 'start' && j.source === 'FASHIONPLUS' &&
        j.ts && (Date.now() - j.ts) < 30000 && /\/goods\/detail\//.test(location.href) && !ranProduct) main();
    });
  } catch (e) { /* noop */ }
})();
