/**
 * 서브에이전트 모니터 - 재고 소진 / 가격 변동 자동 감지
 * proxy-server.mjs가 실행 중일 때만 동작 (실패 시 조용히 무시)
 */

class AgentMonitor {
  constructor() {
    this.proxyBase = 'http://localhost:3001'
    this._stockTimer = null
    this._priceTimer = null
    this.isRunning = false
    // 기본 주기 (분)
    this.stockIntervalMin = 30
    this.priceIntervalMin = 60
  }

  /**
   * 모니터링 시작
   * @param {Object} opts - { stockIntervalMin, priceIntervalMin }
   */
  start(opts = {}) {
    if (this.isRunning) return
    this.stockIntervalMin = opts.stockIntervalMin || 30
    this.priceIntervalMin = opts.priceIntervalMin || 60
    this.isRunning = true

    // 앱 시작 1분 후 첫 실행 (초기화 완료 대기)
    setTimeout(() => {
      this.runStockCheck()
      this.runPriceMonitor()
    }, 60 * 1000)

    this._stockTimer = setInterval(
      () => this.runStockCheck(),
      this.stockIntervalMin * 60 * 1000
    )
    this._priceTimer = setInterval(
      () => this.runPriceMonitor(),
      this.priceIntervalMin * 60 * 1000
    )

    console.log(
      `[에이전트] 모니터링 시작 (재고: ${this.stockIntervalMin}분, 가격: ${this.priceIntervalMin}분 주기)`
    )
  }

  stop() {
    clearInterval(this._stockTimer)
    clearInterval(this._priceTimer)
    this.isRunning = false
    console.log('[에이전트] 모니터링 중지')
  }

  // ─────────────────────────────────────────────
  // 재고 소진 감지
  // ─────────────────────────────────────────────
  async runStockCheck() {
    try {
      // 수집 상태(collected)인 무신사 상품만 대상
      const allCollected = await storage.getByIndex('collectedProducts', 'status', 'collected')
      const targets = allCollected.filter(p => p.siteProductId && p.sourceSite === 'MUSINSA')
      if (targets.length === 0) return

      const goodsNos = targets.map(p => p.siteProductId)
      const res = await fetch(`${this.proxyBase}/api/agents/stock-check`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goodsNos }),
      })
      if (!res.ok) return
      const data = await res.json()
      if (!data.success) return

      let soldOutCount = 0
      for (const result of data.results) {
        if (!result.isSoldOut) continue
        const product = targets.find(p => p.siteProductId === result.goodsNo)
        if (!product) continue
        await storage.save('collectedProducts', {
          ...product,
          isSoldOut: true,
          stockStatus: 'soldout',
          stockCheckedAt: new Date().toISOString(),
        })
        soldOutCount++
      }

      if (soldOutCount > 0) {
        if (typeof app !== 'undefined') {
          app.showNotification(
            `⚠️ 품절 감지: ${soldOutCount}개 상품이 소싱처에서 품절되었습니다.`,
            'warning',
            true  // 확인 클릭 전까지 유지 + 소리 알람
          )
        }
        console.log(`[재고에이전트] ${soldOutCount}개 품절 처리 완료`)
      } else {
        console.log(`[재고에이전트] 이상 없음 (${targets.length}개 확인)`)
      }
    } catch (e) {
      // 프록시 서버 미실행 시 조용히 무시
      console.debug('[재고에이전트] 건너뜀 (프록시 서버 미연결):', e.message)
    }
  }

  // ─────────────────────────────────────────────
  // 가격 변동 감지
  // ─────────────────────────────────────────────
  async runPriceMonitor() {
    try {
      const allCollected = await storage.getByIndex('collectedProducts', 'status', 'collected')
      // 무신사 상품 + 가격 정보가 있는 것만
      // 무신사 + KREAM 대상
      const musinsaTargets = allCollected.filter(
        p => p.siteProductId && p.sourceSite === 'MUSINSA' && p.salePrice > 0
      )
      const kreamTargets = allCollected.filter(
        p => p.siteProductId && p.sourceSite === 'KREAM' && p.salePrice > 0
      )
      if (musinsaTargets.length === 0 && kreamTargets.length === 0) return

      let changedCount = 0

      // ── 무신사 가격 모니터링 (기존 로직) ──
      if (musinsaTargets.length > 0) {
        const payload = musinsaTargets.map(p => ({
          goodsNo: p.siteProductId,
          productId: p.id,
          storedPrice: p.salePrice,
        }))

        const res = await fetch(`${this.proxyBase}/api/agents/price-monitor`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ products: payload }),
        })
        if (res.ok) {
          const data = await res.json()
          if (data.success) {
            for (const result of data.results) {
              if (!result.changed) continue
              const product = musinsaTargets.find(p => p.siteProductId === result.goodsNo)
              if (!product) continue
              await storage.save('collectedProducts', {
                ...product,
                salePrice: result.currentPrice,
                priceBeforeChange: result.storedPrice,
                priceChangedAt: new Date().toISOString(),
              })
              changedCount++
            }
          }
        }
      }

      // ── KREAM 가격 모니터링 ──
      for (const product of kreamTargets) {
        try {
          const res = await fetch(`${this.proxyBase}/api/kream/products/${product.siteProductId}`)
          if (!res.ok) continue
          const data = await res.json()
          if (!data.success || !data.data) continue

          const newPrice = data.data.salePrice || 0
          if (newPrice > 0 && newPrice !== product.salePrice) {
            await storage.save('collectedProducts', {
              ...product,
              salePrice: newPrice,
              priceBeforeChange: product.salePrice,
              priceChangedAt: new Date().toISOString(),
            })
            changedCount++
          }
        } catch {
          // 개별 상품 오류는 무시하고 계속 진행
        }
      }

      const totalTargets = musinsaTargets.length + kreamTargets.length
      if (changedCount > 0) {
        if (typeof app !== 'undefined') {
          app.showNotification(
            `📊 가격 변동: ${changedCount}개 상품 소싱가가 변경되었습니다. 정책 재확인 권장.`,
            'info',
            true
          )
        }
        console.log(`[가격에이전트] ${changedCount}개 가격 업데이트 완료`)
      } else {
        console.log(`[가격에이전트] 이상 없음 (${totalTargets}개 확인)`)
      }
    } catch (e) {
      console.debug('[가격에이전트] 건너뜀 (프록시 서버 미연결):', e.message)
    }
  }
}

// 글로벌 인스턴스
const agentMonitor = new AgentMonitor()
