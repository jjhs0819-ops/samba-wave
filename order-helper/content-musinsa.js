// 삼바 주문도우미 — 무신사 페이지 자동화 (ISOLATED world content script)
//
// chrome.storage.local 의 'job' 상태머신을 보고, 현재 URL에 맞는 단계를 수행한다.
(function () {
  const CFG = globalThis.OH_CONFIG;
  const SEL = CFG.sel;
  const log = (...a) => console.log('%c[주문도우미]', 'color:#2b8a3e;font-weight:bold', ...a);

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s) => document.querySelector(s);
  const qa = (s) => Array.from(document.querySelectorAll(s));

  async function waitFor(sel, t = 12000) {
    const end = Date.now() + t;
    while (Date.now() < end) {
      const e = q(sel);
      if (e && e.offsetParent !== null) return e;
      await wait(100);
    }
    return q(sel);
  }
  function findByText(text, tags = 'button,a,span,div') {
    return qa(tags).find((e) => e.textContent.trim() === text && e.offsetParent !== null);
  }
  async function waitForText(text, t = 12000) {
    const end = Date.now() + t;
    while (Date.now() < end) {
      const el = findByText(text);
      if (el) return el;
      await wait(100);
    }
    return null;
  }

  async function getJob() {
    const { job } = await chrome.storage.local.get('job');
    return job || null;
  }
  async function setJob(patch) {
    const j = (await getJob()) || {};
    Object.assign(j, patch);
    await chrome.storage.local.set({ job: j });
    return j;
  }

  function banner(msg, color = '#2b8a3e') {
    let el = document.getElementById('__oh_banner');
    if (!el) {
      el = document.createElement('div');
      el.id = '__oh_banner';
      el.style.cssText =
        'position:fixed;top:0;left:0;right:0;z-index:2147483647;padding:10px 16px;' +
        'font:600 14px/1.4 -apple-system,sans-serif;color:#fff;text-align:center;' +
        'box-shadow:0 2px 8px rgba(0,0,0,.2)';
      document.documentElement.appendChild(el);
    }
    el.style.background = color;
    el.textContent = '🤖 주문도우미: ' + msg;
  }

  // ─────────────────────────────────────────────────────────────
  //  주소 분리/정규화
  //  - 도로명(…로/길 + 건물번호) 또는 지번(…동/리 + 번지)을 찾아
  //    메인주소(address1)와 상세주소(address2)로 나눈다.
  //  - 합쳐진 한 칸 입력, 또는 건물번호가 상세주소 앞에 붙은 경우 모두 교정.
  // ─────────────────────────────────────────────────────────────
  function splitAddress(mainRaw, detailRaw) {
    const main = (mainRaw || '').trim();
    const detail = (detailRaw || '').trim();
    const full = (main + ' ' + detail).replace(/\s+/g, ' ').trim();
    if (!full) return { address1: main, address2: detail };

    const tokens = full.split(' ');

    // 1) 앵커 찾기: 도로명(로/길로 끝나는 토큰) 우선, 없으면 지번(읍/면/동/리)
    let anchor = -1;
    for (let i = 0; i < tokens.length; i++) {
      if (/[로길]\d*(번길)?$/.test(tokens[i])) anchor = i; // 예: 중앙로29길, 가람로, 중앙로29번길
    }
    let isRoad = anchor >= 0;
    if (anchor < 0) {
      for (let i = 0; i < tokens.length; i++) {
        // 행정구역 동/리/읍/면 (102동 같은 '숫자+동'은 제외)
        if (/^[가-힣]+(읍|면|동|리)$/.test(tokens[i]) && !/^\d/.test(tokens[i])) anchor = i;
      }
    }
    if (anchor < 0) return { address1: main, address2: detail }; // 판단 불가 → 원본 유지

    // 2) 앵커 뒤 첫 '건물번호(번지)' 토큰: 순수숫자 + 선택적 -숫자
    let bn = -1;
    for (let i = anchor + 1; i < tokens.length; i++) {
      if (/^\d+(-\d+)?(번지)?$/.test(tokens[i])) { bn = i; break; }
      // '113번' 같이 번 붙은 경우도 허용
      if (/^\d+(-\d+)?번$/.test(tokens[i])) { bn = i; break; }
    }
    if (bn < 0) return { address1: main, address2: detail };

    // 3) 건물번호 바로 뒤 괄호 건물명 (...)은 메인주소에 포함
    let end = bn;
    if (tokens[bn + 1] && tokens[bn + 1].startsWith('(')) {
      let j = bn + 1;
      while (j < tokens.length && !tokens[j].includes(')')) j++;
      if (j < tokens.length) end = j;
    }

    const address1 = tokens.slice(0, end + 1).join(' ');
    const address2 = tokens.slice(end + 1).join(' ');
    return { address1, address2: address2 || detail, _road: isRoad };
  }

  // ── 단계 1: 상품 — 옵션 선택 + 구매하기 ─────────────────────────
  async function stepProduct(job) {
    if (job.phase && job.phase !== 'start') return;
    banner(`옵션 '${job.size}' 선택 중...`);
    const trigger = await waitFor(SEL.optionTrigger);
    if (!trigger) { banner('옵션 버튼을 못 찾음', '#c92a2a'); return; }
    trigger.click();
    await waitFor(SEL.optionValue, 6000);
    const items = qa(SEL.optionValue);
    let target = items.find(
      (e) => (e.innerText || '').trim().split('\n')[0].trim().toUpperCase() ===
             String(job.size).toUpperCase()
    ) || items.find(
      (e) => (e.innerText || '').trim().toUpperCase().startsWith(String(job.size).toUpperCase())
    );
    if (!target) { banner(`사이즈 '${job.size}' 옵션 없음(품절?)`, '#c92a2a'); return; }
    target.click();
    await wait(250);
    await setJob({ phase: 'orderform' });
    banner('구매하기...');
    const buy = await waitFor(SEL.buyButton);
    if (!buy) { banner('구매하기 버튼 없음', '#c92a2a'); return; }
    buy.click();
  }

  // ── 단계 2: 주문서 — 배송지 변경 열기 ──────────────────────────
  async function stepOrderForm(job) {
    if (job.addressDone) {
      banner('배송지 입력 완료 ✅ 쿠폰·결제수단 선택 후 결제하세요. (결제 후 주문번호 자동기입)', '#1971c2');
      return;
    }
    if (job.addrPhase === 'running') return;
    const btn = await waitForText('배송지 변경');
    await setJob({ addrPhase: 'running', addrStep: 'list_initial' });
    banner('배송지 변경 여는 중...');
    if (btn) btn.click();
    else { banner('"배송지 변경" 버튼 없음', '#c92a2a'); await setJob({ addrPhase: null }); }
  }

  // ── 단계 3: 배송지 목록 팝업 ───────────────────────────────────
  async function stepAddrList(job) {
    if (job.addrPhase !== 'running') return;

    if (job.addrStep === 'saved') {
      const info = await (async () => {
        const end = Date.now() + 8000;
        while (Date.now() < end) {
          const el = qa(SEL.addrListItemInfo).find((e) => (e.innerText || '').includes(job.customer.name));
          if (el) return el;
          await wait(120);
        }
        return null;
      })();
      banner('고객 배송지 선택...');
      if (info) info.click();
      await wait(250);
      const changeBtn = q(SEL.addrListChangeButton);
      if (changeBtn) changeBtn.click();
      await setJob({ addressDone: true, addrPhase: 'done' });
      return;
    }

    // 최초: 비-기본(삭제 버튼 있는) 배송지의 '수정' 클릭
    await waitFor('.order-address-item', 8000);
    let editBtn = null;
    qa('.order-address-item').forEach((it) => {
      const btns = Array.from(it.querySelectorAll('button'));
      if (btns.some((b) => b.textContent.trim() === '삭제'))
        editBtn = btns.find((b) => b.textContent.trim() === '수정');
    });
    await setJob({ addrStep: 'editing' });
    if (editBtn) { banner('배송지 슬롯 수정 진입...'); editBtn.click(); }
    else { banner('배송지 추가하기...'); const a = q(SEL.addrAddLink); if (a) a.click(); }
  }

  // ── 단계 4: 배송지 입력 폼 — 주소 분리 후 background(MAIN)로 채움 ─
  async function stepAddrForm(job) {
    if (job.addrStep !== 'editing') return;
    banner('고객정보 자동입력 중...');

    // 주소 분리/정규화
    const c = Object.assign({}, job.customer);
    const sp = splitAddress(c.addr, c.addr2);
    c.addr = sp.address1;
    c.addr2 = sp.address2;
    const hasPostal = /^\d{5}$/.test(String(c.postal || ''));
    log('주소 분리:', { address1: c.addr, address2: c.addr2, 우편번호: c.postal, hasPostal });

    // 분리된 주소를 job에 반영 (우편번호 없으면 Daum 검색 스크립트가 이 주소로 검색)
    await setJob({ customer: c, addrSearching: !hasPostal });
    if (!hasPostal) banner('우편번호 없음 → 주소찾기 자동검색 중...', '#d9480f');

    let res;
    try {
      res = await chrome.runtime.sendMessage({ type: 'FILL_ADDRESS', customer: c, hasPostal });
    } catch (e) { res = { ok: false, error: String(e) }; }
    log('주소 자동입력 결과', res);
    if (res && res.ok) await setJob({ addrStep: 'saved', addrSearching: false });
    else banner('주소 자동입력 실패: ' + (res && res.error), '#c92a2a');
  }

  // ── 단계 5: 결제완료 — 주문번호/금액 스크랩 + 기입 ──────────────
  async function stepResult(job) {
    await wait(1000);
    const m = location.href.match(CFG.resultUrlRe);
    const orderNo = m ? m[1]
      : (document.body.innerText.match(/주문번호\s*[:：]?\s*([0-9\-]+)/) || [])[1] || '';
    const amtMatch = document.body.innerText.match(/총\s*결제\s*금액[\s\S]{0,30}?([\d,]{3,})\s*원/);
    const amount = amtMatch ? amtMatch[1].replace(/,/g, '') : '';
    log('결제완료 감지', { orderNo, amount, orderId: job.orderId });
    banner(`주문완료! 주문번호 ${orderNo} / ${amount}원 — 삼바 기입 전송`, '#1971c2');
    chrome.runtime.sendMessage({ type: 'WRITEBACK', orderId: job.orderId, orderNo, amount });
    await setJob({ status: 'done', result: { orderNo, amount } });
  }

  async function main() {
    const job = await getJob();
    if (!job) return;
    const url = location.href;
    try {
      if (CFG.resultUrlRe.test(url)) return await stepResult(job);
      if (job.status === 'done') return;
      if (/\/products\//.test(url)) return await stepProduct(job);
      if (/\/order\/order-form/.test(url)) return await stepOrderForm(job);
      if (/\/addresses\/order/.test(url)) return await stepAddrList(job);
      if (/\/addresses\/(update|add)/.test(url)) return await stepAddrForm(job);
    } catch (e) {
      log('단계 실행 오류', e);
      banner('오류 발생 — 콘솔 확인', '#c92a2a');
    }
  }

  main();
})();
