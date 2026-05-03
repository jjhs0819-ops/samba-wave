;(function () {
  const { apiFetch } = globalThis.SambaBackgroundCore

  const CACHE_KEY = 'recipeCache'

  async function syncRecipes(proxyUrl) {
    try {
      const res = await apiFetch(`${proxyUrl}/api/v1/samba/sourcing-recipes`)
      if (!res.ok) return
      const { recipes } = await res.json()

      const stored = await chrome.storage.local.get(CACHE_KEY)
      const cache = stored[CACHE_KEY] || {}

      for (const { site, version } of recipes) {
        if (cache[site]?.version === version) continue

        try {
          const detail = await apiFetch(`${proxyUrl}/api/v1/samba/sourcing-recipes/${site}`)
          if (!detail.ok) continue
          const recipe = await detail.json()
          cache[site] = recipe
          console.log(`[레시피] ${site} v${version} 캐시 갱신`)
        } catch (e) {
          console.warn(`[레시피] ${site} 다운로드 실패:`, e.message)
        }
      }

      await chrome.storage.local.set({ [CACHE_KEY]: cache })
    } catch (e) {
      console.warn('[레시피] 버전 체크 실패:', e.message)
    }
  }

  async function getRecipe(site) {
    const stored = await chrome.storage.local.get(CACHE_KEY)
    return stored[CACHE_KEY]?.[site] || null
  }

  globalThis.SambaRecipeCache = { syncRecipes, getRecipe }
})()
