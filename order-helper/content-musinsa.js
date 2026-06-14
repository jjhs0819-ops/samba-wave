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
  function sendMsg(type, extra) {
    return new Promise((resolve) => {
      try { chrome.runtime.sendMessage(Object.assign({ type }, extra), (r) => resolve(r || { ok: false, error: 'no response' })); }
      catch (e) { resolve({ ok: false, error: String(e) }); }
    });
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

  let ranProduct = false; // 옵션선택 중복 실행 방지(경합/onChanged 이중 트리거 대비)

  // ── 단계 1: 상품 — 옵션 선택 + 구매하기 ─────────────────────────
  //  · 옵션 드롭다운이 1개(사이즈만)면 자동 선택 + 구매하기
  //  · 옵션이 여러 개(색상+사이즈 등)이거나 사이즈를 못 찾으면 자동선택하지 않고
  //    사용자가 직접 고르게 안내. (job은 살려둠 → 주문서 가면 배송지 자동입력)
  async function stepProduct(job) {
    if (job.phase && job.phase !== 'start') return;
    if (ranProduct) return;
    ranProduct = true;

    const MANUAL = '옵션을 직접 선택하고 [구매하기]를 누르세요. 주문서에서 배송지는 자동 입력됩니다.';
    const trigger = await waitFor(SEL.optionTrigger);
    if (!trigger) {
      banner('🛈 ' + MANUAL, '#1971c2');
      return; // 옵션 UI 못 찾음 → 수동. job 유지(주문서에서 주소 자동입력)
    }

    // 옵션 드롭다운 개수 확인 (색상+사이즈처럼 2개 이상이면 수동)
    const triggers = qa(SEL.optionTrigger);
    if (triggers.length >= 2) {
      banner('🛈 옵션이 여러 개예요(예: 색상·사이즈). ' + MANUAL, '#1971c2');
      return; // 자동선택 안 함, job 유지
    }

    banner(`옵션 '${job.size}' 선택 중...`);
    trigger.click();
    await waitFor(SEL.optionValue, 6000);
    const items = qa(SEL.optionValue);
    let target = items.find(
      (e) => (e.innerText || '').trim().split('\n')[0].trim().toUpperCase() ===
             String(job.size).toUpperCase()
    ) || items.find(
      (e) => (e.innerText || '').trim().toUpperCase().startsWith(String(job.size).toUpperCase())
    );
    if (!target) {
      // 사이즈 자동매칭 실패 → 중단하지 말고 수동 안내 (주문서 가면 주소 자동입력)
      banner(`🛈 사이즈 '${job.size}' 자동선택 실패. ` + MANUAL, '#d9480f');
      return;
    }
    target.click();
    await wait(250);
    await setJob({ phase: 'orderform' });
    banner('구매하기...');
    const buy = await waitFor(SEL.buyButton);
    if (!buy) { banner('🛈 ' + MANUAL, '#1971c2'); return; }
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

  // ── 단계 4: 배송지 입력 폼 — 삼바 정확값 입력 (+우편번호 없으면 주소찾기로 조회) ─
  async function stepAddrForm(job) {
    if (job.addrStep !== 'editing') return;
    // 루프 방지: 진입 즉시 'saved'로 전환 → 저장 후 목록에서 '수정' 재진입 차단
    const count = (job.addrFormCount || 0) + 1;
    await setJob({ addrStep: 'saved', addrFormCount: count });
    if (count > 3) {
      banner('주소 자동입력 반복 감지 — 중단. 직접 진행해주세요.', '#c92a2a');
      return; // 안전장치: 반복 시 더 이상 자동입력 안 함
    }
    banner('고객정보 자동입력 중...');

    const c = Object.assign({}, job.customer); // 삼바 정확값(기본/상세주소) 그대로
    const hasPostal = /^\d{5}$/.test(String(c.postal || ''));
    log('주소 입력:', { address1: c.addr, address2: c.addr2, 우편번호: c.postal, hasPostal });

    let zip = c.postal;
    if (!hasPostal) {
      // 카카오 우편번호 API로 1회 조회 (재시도/DOM긁기 없음)
      banner('우편번호 자동조회 중...', '#d9480f');
      const r = await sendMsg('RESOLVE_ZIP', { address: c.addr });
      log('우편번호 조회 결과', r);
      if (r && r.ok && r.zip) {
        zip = r.zip;
      } else {
        // 키 없음/실패 → 주소찾기 창만 열어주고 사용자가 직접 선택+저장 (재시도 안 함)
        const err = (r && r.error) || '알 수 없음';
        const why = err === 'no key' ? '카카오 API 키 미설정' : ('자동조회 실패: ' + err);
        banner(`우편번호 ${why} → 주소찾기에서 직접 선택 후 저장해주세요.`, '#c92a2a');
        await sendMsg('OPEN_SEARCH', { customer: c });
        return;
      }
    }

    const res = await sendMsg('FILL_ZIP', { customer: c, zip });
    log('주소 저장 결과', res);
    if (!(res && res.ok)) banner('주소 자동입력 실패: ' + (res && res.error), '#c92a2a');
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
    let job = await getJob();
    // 상품 페이지: '방금(이 탭 열림 직전) 생성된' 작업만 채택 (이전 주문의 잔존 작업 무시)
    if (/\/products\//.test(location.href)) {
      const fresh = (j) => j && j.phase === 'start' && j.status !== 'done' && !j.aborted &&
                           j.ts && (Date.now() - j.ts) < 30000;
      for (let i = 0; i < 16; i++) {
        if (fresh(job)) break;
        await wait(300);
        job = await getJob();
      }
      if (!fresh(job)) { log('이 탭에 해당하는 최신 작업 없음 — 대기/무시'); return; }
    }
    if (!job) return;
    if (job.source && job.source !== 'MUSINSA') return; // ABC 등 타 소싱 작업은 무시
    if (job.aborted) return; // 옵션없음 등으로 중단된 작업 — 아무것도 안 함
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

  // 경합 보강: 상품 페이지 로드 후 job(phase=start)이 늦게 들어와도 즉시 반응
  try {
    chrome.storage.onChanged.addListener((changes, area) => {
      if (area !== 'local' || !changes.job) return;
      const j = changes.job.newValue;
      if (j && j.phase === 'start' && j.status !== 'done' && !j.aborted &&
          j.ts && (Date.now() - j.ts) < 30000 &&
          /\/products\//.test(location.href) && !ranProduct) {
        main();
      }
    });
  } catch (e) { /* noop */ }
})();
