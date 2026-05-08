;(function () {

  function interpolate(str, vars) {
    return str.replace(/\{\{(\w+)\}\}/g, (_, k) => vars[k] ?? '')
  }

  function inPage(tabId, func, args = []) {
    return chrome.scripting.executeScript({
      target: { tabId },
      func,
      args,
    }).then(r => r?.[0]?.result)
  }

  function applyTransform(value, transform) {
    if (!transform || value == null) return value
    if (transform === 'parseInt') return parseInt(String(value).replace(/[^0-9]/g, ''), 10) || 0
    if (transform === 'parseFloat') return parseFloat(String(value).replace(/[^0-9.]/g, '')) || 0
    if (transform === 'trim') return String(value).trim()
    if (transform === 'removeComma') return parseInt(String(value).replace(/,/g, ''), 10) || 0
    return value
  }

  async function stepGoto(step, ctx) {
    const url = interpolate(step.url, ctx.vars)
    await new Promise((resolve) => {
      let settled = false
      function done() {
        if (!settled) {
          settled = true
          chrome.tabs.onUpdated.removeListener(listener)
          resolve()
        }
      }
      function listener(tabId, info) {
        if (tabId === ctx.tabId && info.status === 'complete') done()
      }
      chrome.tabs.onUpdated.addListener(listener)
      chrome.tabs.update(ctx.tabId, { url })
      setTimeout(done, 15000)
    })
  }

  async function stepWait(step, ctx) {
    const selector = interpolate(step.selector, ctx.vars)
    const timeout = step.timeout ?? 5000
    const start = Date.now()
    while (Date.now() - start < timeout) {
      const found = await inPage(ctx.tabId, (sel) => !!document.querySelector(sel), [selector])
      if (found) return
      await new Promise(r => setTimeout(r, 300))
    }
    console.warn(`[레시피] wait 타임아웃: ${selector}`)
  }

  async function stepExtract(step, ctx) {
    const fields = step.fields
    const result = await inPage(ctx.tabId, (fields) => {
      const out = {}
      for (const [key, cfg] of Object.entries(fields)) {
        const els = cfg.multiple
          ? Array.from(document.querySelectorAll(cfg.selector))
          : [document.querySelector(cfg.selector)]
        const values = els
          .filter(Boolean)
          .map(el => cfg.attr === 'text' ? el.textContent?.trim() : el.getAttribute(cfg.attr))
          .filter(v => v != null && v !== '')
        out[key] = cfg.multiple ? values : (values[0] ?? null)
      }
      return out
    }, [fields])

    if (result) {
      for (const [key, cfg] of Object.entries(fields)) {
        if (cfg.transform && result[key] !== undefined && result[key] !== null) {
          if (Array.isArray(result[key])) {
            result[key] = result[key].map(v => applyTransform(v, cfg.transform))
          } else {
            result[key] = applyTransform(result[key], cfg.transform)
          }
        }
      }
      Object.assign(ctx.result, result)
    }
  }

  async function stepClick(step, ctx) {
    const selector = interpolate(step.selector, ctx.vars)
    await inPage(ctx.tabId, (sel) => document.querySelector(sel)?.click(), [selector])
    await new Promise(r => setTimeout(r, 500))
  }

  async function stepScroll(step, ctx) {
    const target = interpolate(step.target, ctx.vars)
    if (target === 'bottom') {
      await inPage(ctx.tabId, () => window.scrollTo(0, document.body.scrollHeight))
    } else {
      await inPage(ctx.tabId, (sel) => document.querySelector(sel)?.scrollIntoView(), [target])
    }
    await new Promise(r => setTimeout(r, 500))
  }

  // 서버 레시피의 evaluate 표현식 1차 방어선:
  //  1) 길이 상한 (탈취 시 페이로드 폭증 방지)
  //  2) 위험 토큰 블록리스트 (chrome.* / fetch / XHR / cookie / Function / import / require 등)
  // 근본 해결은 백엔드 HMAC 서명 검증 필요 — 별도 PR.
  const _EVAL_MAX_LEN = 2000
  const _EVAL_DENY_TOKENS = [
    'chrome.', 'browser.', 'fetch(', 'XMLHttpRequest', 'navigator.sendBeacon',
    'document.cookie', 'localStorage', 'sessionStorage', 'indexedDB',
    'Function(', 'new Function', 'import(', 'import ', 'require(',
    'eval(', 'WebAssembly', 'postMessage(', 'BroadcastChannel',
  ]
  function _isEvalExprSafe(expr) {
    if (typeof expr !== 'string') return false
    if (expr.length > _EVAL_MAX_LEN) return false
    for (const tok of _EVAL_DENY_TOKENS) {
      if (expr.includes(tok)) return false
    }
    return true
  }

  async function stepEvaluate(step, ctx) {
    const expression = interpolate(step.expression, ctx.vars)
    if (!_isEvalExprSafe(expression)) {
      console.warn('[recipe] evaluate 차단 (비허용 토큰/초과길이):', expression?.slice?.(0, 80))
      if (step.resultKey) ctx.result[step.resultKey] = null
      return
    }
    const result = await chrome.scripting.executeScript({
      target: { tabId: ctx.tabId },
      world: 'MAIN',
      func: (expr) => {
        try { return eval(expr) } catch { return null } // eslint-disable-line no-eval
      },
      args: [expression],
    }).then(r => r?.[0]?.result ?? null)
    if (step.resultKey && result !== null) {
      ctx.result[step.resultKey] = result
    }
  }

  async function stepLoop(step, ctx) {
    const selector = interpolate(step.selector, ctx.vars)
    const count = await inPage(ctx.tabId, (sel) => document.querySelectorAll(sel).length, [selector])
    const items = []
    for (let i = 0; i < (count || 0); i++) {
      const itemCtx = { tabId: ctx.tabId, vars: { ...ctx.vars, loopIndex: i }, result: {} }
      for (const subStep of step.steps) {
        await executeStep(subStep, itemCtx)
      }
      items.push(itemCtx.result)
    }
    if (step.resultKey) ctx.result[step.resultKey] = items
  }

  async function executeStep(step, ctx) {
    switch (step.type) {
      case 'goto':     return stepGoto(step, ctx)
      case 'wait':     return stepWait(step, ctx)
      case 'extract':  return stepExtract(step, ctx)
      case 'click':    return stepClick(step, ctx)
      case 'scroll':   return stepScroll(step, ctx)
      case 'evaluate': return stepEvaluate(step, ctx)
      case 'loop':     return stepLoop(step, ctx)
      default: console.warn(`[레시피] 알 수 없는 스텝: ${step.type}`)
    }
  }

  async function executeRecipe(recipe, vars, tabId = null) {
    const ownTab = tabId === null
    if (ownTab) {
      const tab = await chrome.tabs.create({ url: 'about:blank', active: false })
      tabId = tab.id
    }
    const ctx = { tabId, vars: vars || {}, result: {} }
    try {
      for (const step of recipe.steps) {
        await executeStep(step, ctx)
      }
      return ctx.result
    } finally {
      if (ownTab) {
        try { await chrome.tabs.remove(tabId) } catch {}
      }
    }
  }

  globalThis.SambaRecipeExecutor = { executeRecipe }
})()
