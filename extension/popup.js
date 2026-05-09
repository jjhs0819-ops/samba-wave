// ============================================================
// SAMBA-WAVE 팝업 UI 로직
// - 백엔드 URL + API 인증 키 저장
// - 연결 테스트 (/api/v1/health)
// - 스토어 점수 수집 트리거
// ============================================================

async function apiFetch(url, init = {}) {
  const data = await chrome.storage.local.get('apiKey')
  const headers = { ...(init.headers || {}), 'X-Api-Key': data.apiKey || '' }
  return fetch(url, { ...init, headers })
}

function $(id) { return document.getElementById(id) }

function setStatus(el, msg, type = '') {
  el.textContent = msg
  el.className = 'status' + (type ? ' ' + type : '')
}

function normalizeUrl(raw) {
  if (!raw) return ''
  let v = raw.trim().replace(/\/+$/, '')
  if (v && !/^https?:\/\//i.test(v)) {
    v = 'https://' + v
  }
  return v
}

// ============================================================
// 초기화
// ============================================================
document.addEventListener('DOMContentLoaded', async () => {
  $('version').textContent = `v${chrome.runtime.getManifest().version}`

  const status = $('status')
  const urlInput = $('proxyUrl')

  // 저장된 값 로드
  const saved = await chrome.storage.local.get(['proxyUrl'])
  urlInput.value = saved.proxyUrl || ''

  if (!saved.proxyUrl) {
    setStatus(status, '⚠️ 최초 1회 백엔드 URL을 입력하세요', 'err')
  }

  // ============================================================
  // 저장
  // ============================================================
  $('btnSave').addEventListener('click', async () => {
    const url = normalizeUrl(urlInput.value)

    if (!url) {
      setStatus(status, '❌ 백엔드 URL은 필수입니다', 'err')
      return
    }

    // URL 변경 시 이전 서버 키는 무효 → 새 서버에서 자동 재발급
    await chrome.storage.local.set({ proxyUrl: url })
    await chrome.storage.local.remove('apiKey')
    urlInput.value = url
    setStatus(status, '✅ 저장됨 — 확장앱이 이 백엔드를 사용합니다', 'ok')
  })

  // ============================================================
  // 연결 테스트
  // ============================================================
  $('btnTest').addEventListener('click', async () => {
    const url = normalizeUrl(urlInput.value)
    if (!url) {
      setStatus(status, '❌ URL을 먼저 입력하세요', 'err')
      return
    }

    setStatus(status, '⏳ 연결 확인 중...', '')
    const btn = $('btnTest')
    btn.disabled = true
    try {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 8000)
      const res = await fetch(`${url}/api/v1/health`, {
        method: 'GET',
        signal: ctrl.signal,
      })
      clearTimeout(timer)
      if (res.ok) {
        const j = await res.json().catch(() => ({}))
        const w = j.worker?.alive ? ' (worker alive)' : ''
        setStatus(status, `✅ 연결 성공 — HTTP ${res.status}${w}`, 'ok')
      } else {
        setStatus(status, `❌ HTTP ${res.status} — URL 또는 인증 키 확인`, 'err')
      }
    } catch (e) {
      const msg = e.name === 'AbortError' ? '타임아웃 (8초)' : e.message
      setStatus(status, `❌ 연결 실패 — ${msg}`, 'err')
    } finally {
      btn.disabled = false
    }
  })

  // ============================================================
  // 웹사이트 로그인 → 확장앱 API 키 발급
  // ============================================================
  const loginStatus = $('loginStatus')

  // 현재 저장된 키 유무 표시
  const keyData = await chrome.storage.local.get(['apiKey'])
  if (keyData.apiKey) {
    setStatus(loginStatus, '✅ API 키 연결됨', 'ok')
  } else {
    setStatus(loginStatus, '미연결 — 아래 버튼으로 로그인하세요', '')
  }

  $('btnLogin').addEventListener('click', async () => {
    const FRONTEND = 'https://samba-wave.vercel.app'
    const linkUrl = `${FRONTEND}/samba/extension-link`
    await chrome.tabs.create({ url: linkUrl, active: true })
    setStatus(loginStatus, '⏳ 웹페이지에서 키 발급 후 이 팝업을 다시 여세요', '')
  })

  // ============================================================
  // 스토어 점수 수집
  // ============================================================
  const btn = $('btnStoreScore')
  const result = $('scoreResult')

  btn.addEventListener('click', async () => {
    btn.disabled = true
    btn.textContent = '수집 중...'
    setStatus(result, '')

    const saved = await chrome.storage.local.get(['proxyUrl'])
    if (!saved.proxyUrl) {
      setStatus(result, '❌ 백엔드 URL 미설정', 'err')
      btn.disabled = false
      btn.textContent = '스토어 점수 가져오기'
      return
    }

    // 백엔드에서 계정 ID 조회
    let accountId = ''
    try {
      const resp = await apiFetch(`${saved.proxyUrl}/api/v1/samba/monitor/store-scores`)
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
          setStatus(result, `굿서비스: ${gs} / 패널티: ${pen}점`, 'ok')
        } else {
          setStatus(result, res?.message || '실패', 'err')
        }
      },
    )
  })
})
