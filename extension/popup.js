const API_GATEWAY_KEY = 'Vtc-wzZY2xU8NKHljIF8hEG01CJOkCHgqzNlRlDJorU'
function apiFetch(url, init = {}) {
  const headers = { ...(init.headers || {}), 'X-Api-Key': API_GATEWAY_KEY }
  return fetch(url, { ...init, headers })
}

// 팝업 초기화
document.addEventListener('DOMContentLoaded', () => {
  // 버전 표시
  const ver = chrome.runtime.getManifest().version
  document.getElementById('version').textContent = `v${ver}`

  // 스토어 점수 가져오기 버튼
  const btn = document.getElementById('btnStoreScore')
  const result = document.getElementById('scoreResult')

  btn.addEventListener('click', async () => {
    btn.disabled = true
    btn.textContent = '수집 중...'
    result.textContent = ''

    // 백엔드에서 계정 ID 조회
    let accountId = ''
    try {
      const proxyUrl = await new Promise(resolve => {
        chrome.storage.local.get('proxyUrl', (data) => {
          resolve(data.proxyUrl || 'http://localhost:28080')
        })
      })
      const resp = await apiFetch(`${proxyUrl}/api/v1/samba/monitor/store-scores`)
      const scores = await resp.json()
      const ssAccounts = Object.entries(scores).filter(([, v]) => v.market_type === 'smartstore')
      if (ssAccounts.length > 0) {
        accountId = ssAccounts[0][0]
      }
    } catch { /* 무시 */ }

    chrome.runtime.sendMessage(
      { type: 'SCRAPE_STORE_SCORES', account_id: accountId },
      (res) => {
        btn.disabled = false
        btn.textContent = '스토어 점수 가져오기'
        if (res?.success) {
          const gs = res.good_service ? Object.keys(res.good_service).length + '항목' : '-'
          const pen = res.penalty || '-'
          result.textContent = `굿서비스: ${gs} / 패널티: ${pen}점`
          result.style.color = '#51CF66'
        } else {
          result.textContent = res?.message || '실패'
          result.style.color = '#FF6B6B'
        }
      }
    )
  })
})
