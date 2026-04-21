(function () {
  const DEFAULT_PROXY_URL = 'https://samba-wave-api-363598397345.asia-northeast3.run.app'
  const CLOUD_URL = 'https://samba-wave-api-363598397345.asia-northeast3.run.app'
  const API_PREFIX = '/api/v1/samba/proxy'
  const DEFAULT_SELECTORS = {
    kream_size_items: '.select_item',
    kream_bottom_sheet: '.layer_bottom_sheet--open',
    kream_buy_button_text: '구매하기',
    kream_fast_delivery: '빠른배송',
    kream_normal_delivery: '일반배송',
  }

  async function loadApiKey(proxyUrl) {
    const cached = await chrome.storage.local.get('apiKey')
    if (cached.apiKey) return cached.apiKey

    try {
      const url = proxyUrl || DEFAULT_PROXY_URL
      const res = await fetch(`${url}/api/v1/samba/sourcing-accounts/extension-key`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (res.ok) {
        const data = await res.json()
        await chrome.storage.local.set({ apiKey: data.api_key })
        return data.api_key
      }
    } catch {}
    return ''
  }

  async function apiFetch(url, init = {}) {
    const proxyData = await chrome.storage.local.get('proxyUrl')
    const apiKey = await loadApiKey(proxyData.proxyUrl)
    const headers = { ...(init.headers || {}), 'X-Api-Key': apiKey }
    const res = await fetch(url, { ...init, headers })
    if (res.status === 403) {
      await chrome.storage.local.remove('apiKey')
      // 실제 요청 URL의 origin으로 키 재발급 (storage의 proxyUrl이 localhost일 수 있음)
      const serverBase = new URL(url).origin
      const newKey = await loadApiKey(serverBase)
      const retryHeaders = { ...(init.headers || {}), 'X-Api-Key': newKey }
      return fetch(url, { ...init, headers: retryHeaders })
    }
    return res
  }

  async function loadSelectors(proxyUrl) {
    try {
      const res = await apiFetch(`${proxyUrl}${API_PREFIX}/extension-config`)
      const config = res.ok ? await res.json() : null
      if (config?.selectors) {
        return { ...DEFAULT_SELECTORS, ...config.selectors }
      }
    } catch {
      // ignore and use defaults
    }
    return { ...DEFAULT_SELECTORS }
  }

  async function sendSiteCookieToProxy({ proxyUrl, site, cookieStr }) {
    const endpoint = `${API_PREFIX}/${site}/set-cookie`

    if (proxyUrl !== CLOUD_URL) {
      try {
        await apiFetch(`${CLOUD_URL}${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ cookie: cookieStr }),
        })
      } catch {
        // ignore cloud mirror failures
      }
    }

    const res = await apiFetch(`${proxyUrl}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cookie: cookieStr }),
    })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  }

  globalThis.SambaBackgroundCore = {
    API_PREFIX,
    CLOUD_URL,
    DEFAULT_PROXY_URL,
    DEFAULT_SELECTORS,
    apiFetch,
    loadSelectors,
    sendSiteCookieToProxy,
  }
})()
