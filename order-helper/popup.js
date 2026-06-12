// 삼바 주문도우미 — 팝업 (테스트용 작업 시작 트리거)
const $ = (id) => document.getElementById(id);

$('start').addEventListener('click', () => {
  const url = $('url').value.trim();
  const job = {
    status: 'active',
    phase: 'start',
    size: $('size').value.trim(),
    quantity: 1,
    orderId: 'TEST',
    customer: {
      name: $('name').value.trim(),
      phone: $('phone').value.trim(),
      postal: $('postal').value.trim(),
      addr: $('addr').value.trim(),
      addr2: $('addr2').value.trim(),
      memo: $('memo').value.trim(),
    },
  };
  chrome.runtime.sendMessage({ type: 'START_JOB', job, productUrl: url }, (res) => {
    $('status').textContent = res && res.ok
      ? '✅ 시작됨! 새 탭에서 자동 진행됩니다.'
      : '⚠️ 시작 실패';
  });
});

// 현재 작업 상태 표시
chrome.storage.local.get('job', ({ job }) => {
  if (job) {
    $('status').textContent =
      `진행중 job: phase=${job.phase || '-'} addressDone=${!!job.addressDone} status=${job.status}`;
  }
});
