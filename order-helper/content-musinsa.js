// 삼바 주문도우미 — 무신사 페이지 자동화 (ISOLATED world content script)
//
// chrome.storage.local 의 'job' 상태머신을 보고, 현재 URL에 맞는 단계를 수행한다.
// job = {
//   status: 'active'|'done',
//   phase: 'start'|'orderform',
//   size, quantity, orderId,
//   customer: { name, phone, postal, addr, addr2, memo },
//   addrPhase, addrStep, addressDone,
//   result: { orderNo, amount }
// }
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
      if (e) return e;
      await wait(200);
    }
    return null;
  }
  function clickByText(text, tags = 'button,a,span,div') {
    const el = qa(tags).find(
      (e) => e.textContent.trim() === text && e.offsetParent !== null
    );
    if (el) { el.click(); return true; }
    return false;
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
  async function clearJob() { await chrome.storage.local.remove('job'); }

  // 화면 상단 배너로 사용자에게 진행상황 안내
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

  // ── 단계 1: 상품 페이지 — 옵션 선택 + 구매하기 ──────────────────
  async function stepProduct(job) {
    if (job.phase && job.phase !== 'start') return; // 이미 진행됨
    banner(`옵션 '${job.size}' 선택 중...`);
    const trigger = await waitFor(SEL.optionTrigger);
    if (!trigger) { banner('옵션 버튼을 못 찾음', '#c92a2a'); return; }
    trigger.click();
    await wait(1200);
    const items = qa(SEL.optionValue);
    let target = items.find(
      (e) => (e.innerText || '').trim().split('\n')[0].trim().toUpperCase() ===
             String(job.size).toUpperCase()
    );
    if (!target) target = items.find(
      (e) => (e.innerText || '').trim().toUpperCase().startsWith(String(job.size).toUpperCase())
    );
    if (!target) { banner(`사이즈 '${job.size}' 옵션 없음(품절?)`, '#c92a2a'); return; }
    target.click();
    await wait(1000);
    await setJob({ phase: 'orderform' });
    banner('구매하기 클릭...');
    const buy = await waitFor(SEL.buyButton);
    if (!buy) { banner('구매하기 버튼 없음', '#c92a2a'); return; }
    buy.click();
    // → /order/order-form 으로 이동 (다음 페이지 로드 시 stepOrderForm)
  }

  // ── 단계 2: 주문서 — 배송지 변경 팝업 오픈 ──────────────────────
  async function stepOrderForm(job) {
    if (job.addressDone) {
      banner('배송지 입력 완료 ✅ 쿠폰·결제수단 선택 후 결제하세요. (결제 후 자동으로 주문번호 기입됩니다)', '#1971c2');
      return;
    }
    if (job.addrPhase === 'running') return; // 팝업 진행 중
    await wait(1500);
    banner('배송지 변경 여는 중...');
    await setJob({ addrPhase: 'running', addrStep: 'list_initial' });
    if (!clickByText('배송지 변경')) {
      banner('"배송지 변경" 버튼을 못 찾음', '#c92a2a');
      await setJob({ addrPhase: null });
    }
    // → 새 팝업창(addresses/order)에서 stepAddrList
  }

  // ── 단계 3: 배송지 목록 팝업 ────────────────────────────────────
  async function stepAddrList(job) {
    if (job.addrPhase !== 'running') return;
    await wait(1500);

    if (job.addrStep === 'saved') {
      // 저장 완료 후 복귀: 고객 주소 선택 + 변경하기
      banner('고객 배송지 선택...');
      const info = qa(SEL.addrListItemInfo).find(
        (e) => (e.innerText || '').includes(job.customer.name)
      );
      if (info) info.click();
      await wait(600);
      const changeBtn = q(SEL.addrListChangeButton);
      if (changeBtn) changeBtn.click();
      await setJob({ addressDone: true, addrPhase: 'done' });
      // 팝업이 닫히고 order-form 갱신됨
      return;
    }

    // 최초: 비-기본(삭제 버튼 있는) 배송지의 '수정' 클릭
    let editBtn = null;
    qa('.order-address-item').forEach((it) => {
      const btns = Array.from(it.querySelectorAll('button'));
      const hasDelete = btns.some((b) => b.textContent.trim() === '삭제');
      if (hasDelete) editBtn = btns.find((b) => b.textContent.trim() === '수정');
    });
    await setJob({ addrStep: 'editing' });
    if (editBtn) {
      banner('비기본 배송지 슬롯 수정 진입...');
      editBtn.click();
    } else {
      banner('배송지 추가하기...');
      const add = q(SEL.addrAddLink);
      if (add) add.click();
    }
    // → addresses/update 또는 add 로 이동 → stepAddrForm
  }

  // ── 단계 4: 배송지 입력 폼 (Vue) — MAIN world 주입으로 채움 ──────
  async function stepAddrForm(job) {
    if (job.addrStep !== 'editing') return;
    await wait(1800); // Vue mount 대기
    banner('고객정보 자동입력 중...');
    injectVueFill(job.customer);
    await setJob({ addrStep: 'saved' });
    // injectVueFill 내부에서 formSubmit → addresses/order 로 복귀 → stepAddrList(saved)
  }

  // 페이지(MAIN) 컨텍스트에서 무신사 Vue 인스턴스를 직접 조작해 폼을 채우고 저장
  function injectVueFill(c) {
    const code =
      '(()=>{try{' +
      'var c=' + JSON.stringify(c) + ';' +
      'var root=document.querySelector("#commonLayoutContents");' +
      'var vm=root&&root.__vue__;' +
      'if(!vm||!vm.form){console.warn("[주문도우미] Vue 폼 없음");return;}' +
      'vm.form.name=c.name; vm.form.mobile=c.phone;' +
      'if(typeof vm.findAddressComplete==="function"){vm.findAddressComplete({zipcode:c.postal,address1:c.addr});}' +
      'else{vm.form.zipcode=c.postal; vm.form.address1=c.addr;}' +
      'vm.form.address2=c.addr2;' +
      'if(c.memo){var pre=(vm.ui&&vm.ui.additionalMessageType)||[];' +
      ' if(pre.indexOf(c.memo)>=0){vm.form.additionalMessage=c.memo;}' +
      ' else{vm.form.additionalMessage="직접입력"; vm.form.additionalMessageManual=c.memo;}}' +
      'setTimeout(function(){try{vm.formSubmit();}catch(e){console.warn(e);}},700);' +
      '}catch(e){console.warn("[주문도우미] 주입 오류",e);}})();';
    const s = document.createElement('script');
    s.textContent = code;
    document.documentElement.appendChild(s);
    s.remove();
  }

  // ── 단계 5: 결제완료 결과 페이지 — 주문번호/금액 스크랩 + 기입 ────
  async function stepResult(job) {
    await wait(1500);
    const m = location.href.match(CFG.resultUrlRe);
    const orderNo = m ? m[1] : (document.body.innerText.match(/주문번호\s*[:：]?\s*([0-9\-]+)/) || [])[1] || '';
    const amtMatch = document.body.innerText.match(/총\s*결제\s*금액[\s\S]{0,30}?([\d,]{3,})\s*원/);
    const amount = amtMatch ? amtMatch[1].replace(/,/g, '') : '';
    log('결제완료 감지', { orderNo, amount, orderId: job.orderId });
    banner(`주문완료! 주문번호 ${orderNo} / ${amount}원 — 삼바 기입 전송`, '#1971c2');
    chrome.runtime.sendMessage({
      type: 'WRITEBACK',
      orderId: job.orderId,
      orderNo,
      amount,
    });
    await setJob({ status: 'done', result: { orderNo, amount } });
  }

  // ── 라우터 ──────────────────────────────────────────────────────
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
