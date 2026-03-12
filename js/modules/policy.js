/**
 * 정책 관리 (PolicyManager)
 * 마켓별 가격계산 정책 CRUD, 마진율 계산
 */

class PolicyManager {
    constructor() {
        this.policies = []
    }

    async init() {
        await this.loadPolicies()
    }

    // ==================== CRUD ====================

    async loadPolicies() {
        this.policies = await storage.getAll('policies')
        return this.policies
    }

    async addPolicy(data) {
        const policy = {
            id: 'pol_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            name: data.name || '새 정책',
            siteName: data.siteName || '',
            pricing: data.pricing || {
                shippingCost: 0,
                shippingWeightUnit: 'LB',
                marginRate: 15,
                marginAmount: 0,
                useRangeMargin: true,
                currencyBase: 'KRW',
                rangeMargins: [
                    { min: 0, max: 50000, rate: 15, amount: null },
                    { min: 50000, max: 150000, rate: 14, amount: null },
                    { min: 150000, max: 9999999999, rate: 13, amount: null }
                ],
                extraCharge: 4000,
                customsDuty: false,
                minMarginAmount: 7000,
                discountRate: 0,
                discountAmount: 0,
                individualConsumptionTax: false,
                customFormula: ''
            },
            marketPolicies: data.marketPolicies || {},
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString()
        }
        await storage.save('policies', policy)
        this.policies.push(policy)
        return policy
    }

    async updatePolicy(id, data) {
        const policy = this.policies.find(p => p.id === id)
        if (!policy) return null
        const updated = { ...policy, ...data, updatedAt: new Date().toISOString() }
        await storage.save('policies', updated)
        const idx = this.policies.findIndex(p => p.id === id)
        if (idx !== -1) this.policies[idx] = updated
        return updated
    }

    async deletePolicy(id) {
        await storage.delete('policies', id)
        this.policies = this.policies.filter(p => p.id !== id)
    }

    // ==================== 가격 계산 ====================

    /**
     * 정책 기반 마켓 가격 계산
     */
    calculateMarketPrice(cost, policyId) {
        const policy = this.policies.find(p => p.id === policyId)
        if (!policy) return Math.ceil(cost * 1.15)

        const pricing = policy.pricing
        let price = cost

        // 국제운송료 추가
        price += pricing.shippingCost || 0

        // 마진 계산
        let marginRate = pricing.marginRate || 15
        if (pricing.useRangeMargin && pricing.rangeMargins) {
            marginRate = this.calculateRangeMargin(cost, pricing.rangeMargins)
        }

        // 마진 적용: 판매가 = 원가 / (1 - 마진율/100)
        if (marginRate > 0) {
            price = price / (1 - marginRate / 100)
        }
        if (pricing.marginAmount > 0) {
            price += pricing.marginAmount
        }

        // 추가 요금
        price += pricing.extraCharge || 0

        // 최소 마진 보장
        const profit = price - cost
        if (pricing.minMarginAmount > 0 && profit < pricing.minMarginAmount) {
            price = cost + pricing.minMarginAmount
        }

        // 할인 적용
        if (pricing.discountRate > 0) price *= (1 - pricing.discountRate / 100)
        if (pricing.discountAmount > 0) price -= pricing.discountAmount

        return Math.ceil(price)
    }

    /**
     * 가격범위별 마진율 계산
     */
    calculateRangeMargin(cost, rangeMargins) {
        for (const range of rangeMargins) {
            // Infinity 또는 null(구버전 직렬화) 모두 최대값으로 처리
            const max = (range.max === Infinity || range.max === null) ? 9999999999 : range.max
            if (cost >= range.min && cost < max) {
                return range.rate
            }
        }
        return 15 // 기본값
    }

    /**
     * 커스텀 수식 평가
     */
    evaluateCustomFormula(formula, variables = {}) {
        try {
            const { cost = 0, price = 0, marginRate = 0 } = variables
            // 변수명을 숫자로 치환 후 허용된 문자만 검증 (코드 인젝션 방지)
            let expression = formula
                .replace(/\bmarginRate\b/g, String(marginRate))
                .replace(/\bcost\b/g, String(cost))
                .replace(/\bprice\b/g, String(price))
            // 숫자, 사칙연산자, 괄호, 소수점, 공백만 허용
            if (!/^[\d\s+\-*/().]+$/.test(expression)) return null
            return Function('"use strict"; return (' + expression + ')')()
        } catch {
            return null
        }
    }

    /**
     * 특정 마켓 정책 조회
     */
    getMarketPolicy(policyId, marketAccountId) {
        const policy = this.policies.find(p => p.id === policyId)
        if (!policy) return null
        return policy.marketPolicies[marketAccountId] || null
    }

    /**
     * 상품에 정책 일괄 적용
     */
    async applyPolicyToProducts(policyId, productIds) {
        const results = []
        for (const productId of productIds) {
            const product = await storage.get('collectedProducts', productId)
            if (product) {
                const updated = { ...product, appliedPolicyId: policyId, updatedAt: new Date().toISOString() }
                await storage.save('collectedProducts', updated)
                results.push(updated)
            }
        }
        return results
    }

    /**
     * 가격 계산 미리보기 (원가 → 마켓 전송가)
     */
    getPricePreview(cost, policyId) {
        const marketPrice = this.calculateMarketPrice(cost, policyId)
        const profit = marketPrice - cost
        const profitRate = cost > 0 ? ((profit / marketPrice) * 100).toFixed(1) : 0
        return { cost, marketPrice, profit, profitRate }
    }
}

// 글로벌 인스턴스
const policyManager = new PolicyManager()
