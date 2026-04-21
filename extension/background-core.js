(function () {
  const DEFAULT_PROXY_URL = 'http://localhost:28080'
  const CLOUD_URL = 'https://samba-wave-api-363598397345.asia-northeast3.run.app'
  const API_PREFIX = '/api/v1/samba/proxy'
  const API_GATEWAY_KEY = 'Vtc-wzZY2xU8NKHljIF8hEG01CJOkCHgqzNlRlDJorU'

  const DEFAULT_SELECTORS = {
    kream_size_items: '.select_item',
    kream_bottom_sheet: '.layer_bottom_sheet--open',
    kream_buy_button_text: '????',
    kream_fast_delivery: '????',
    kream_normal_delivery: '????',
  }

  function apiFetch(url, init = {}) {
    const headers = { ...(init.headers || {}), 'X-Api-Key': API_GATEWAY_KEY }
    return fetch(url, { ...init, headers })
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
