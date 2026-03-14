/**
 * KREAM 리셀 플랫폼 관리 (KreamManager)
 * 소싱처 + 판매처 이중 역할
 * - 소싱: 사이즈별 매수/매도/최근거래 시세 조회
 * - 판매: 매도 입찰 등록/수정/취소
 */

const KREAM_PROXY_URL = 'http://localhost:3001'

class KreamManager {
    constructor() {
        this.isLoggedIn = false
        this.userId = ''
        this._proxyAvailable = false
    }

    async init() {
        // 프록시 연결 확인 (비동기 - 실패해도 앱 동작)
        this.checkProxy().catch(() => {})
    }

    // ==================== 프록시 / 인증 ====================

    async checkProxy() {
        try {
            const res = await fetch(`${KREAM_PROXY_URL}/api/health`, { signal: AbortSignal.timeout(2000) })
            this._proxyAvailable = res.ok
            if (this._proxyAvailable) await this.checkLoginStatus()
        } catch {
            this._proxyAvailable = false
        }
        return this._proxyAvailable
    }

    async checkLoginStatus() {
        try {
            const res = await fetch(`${KREAM_PROXY_URL}/api/kream/auth/status`)
            const data = await res.json()
            this.isLoggedIn = data.isLoggedIn || false
            this.userId = data.userId || ''
            return this.isLoggedIn
        } catch {
            return false
        }
    }

    async login(email, password) {
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        })
        const data = await res.json()
        if (data.success) {
            this.isLoggedIn = true
            this.userId = data.userId || ''
        }
        return data
    }

    async logout() {
        await fetch(`${KREAM_PROXY_URL}/api/kream/auth`, { method: 'DELETE' })
        this.isLoggedIn = false
        this.userId = ''
    }

    async setToken(token, userId = '') {
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/set-token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token, userId })
        })
        const data = await res.json()
        if (data.success) {
            this.isLoggedIn = true
            this.userId = userId
        }
        return data
    }

    // ==================== 소싱 (상품 조회) ====================

    /**
     * KREAM 상품 검색
     * @param {string} keyword - 검색어 (예: '나이키 덩크')
     * @param {number} size - 결과 수 (기본 30)
     */
    async searchProducts(keyword, size = 30) {
        if (!keyword) throw new Error('검색어를 입력해주세요.')
        const params = new URLSearchParams({ keyword, size: String(size) })
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/search?${params}`)
        if (!res.ok) throw new Error(`검색 실패: HTTP ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '검색 실패')
        return data.data || []
    }

    /**
     * KREAM 단일 상품 상세 조회 (사이즈별 시세 포함)
     * @param {string} productId - KREAM 상품 ID
     */
    async getProductDetail(productId) {
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/products/${productId}`)
        if (!res.ok) throw new Error(`상품 조회 실패: HTTP ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '상품 조회 실패')
        return data.data
    }

    /**
     * KREAM 사이즈별 매수/매도/최근거래 시세 조회
     * @param {string} productId - KREAM 상품 ID
     */
    async getSizePrices(productId) {
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/products/${productId}/prices`)
        if (!res.ok) throw new Error(`시세 조회 실패: HTTP ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '시세 조회 실패')
        return data.data
    }

    // ==================== 판매 (매도 입찰) ====================

    /**
     * 매도 입찰 등록
     * @param {string} productId - KREAM 상품 ID
     * @param {string} size - 사이즈 (예: '260')
     * @param {number} price - 매도 희망가
     * @param {string} saleType - 'general' | 'storage' | 'grade95'
     */
    async createAsk(productId, size, price, saleType = 'general') {
        if (!this.isLoggedIn) throw new Error('KREAM 로그인이 필요합니다.')
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/sell/bid`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ productId, size, price, saleType })
        })
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '매도 입찰 등록 실패')
        return data.data
    }

    /**
     * 매도 입찰 수정
     * @param {string} askId - 입찰 ID
     * @param {number} price - 새 희망가
     */
    async updateAsk(askId, price) {
        if (!this.isLoggedIn) throw new Error('KREAM 로그인이 필요합니다.')
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/sell/bid/${askId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ price })
        })
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '입찰 수정 실패')
        return data.data
    }

    /**
     * 매도 입찰 취소
     * @param {string} askId - 입찰 ID
     */
    async cancelAsk(askId) {
        if (!this.isLoggedIn) throw new Error('KREAM 로그인이 필요합니다.')
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/sell/bid/${askId}`, {
            method: 'DELETE'
        })
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '입찰 취소 실패')
        return true
    }

    /**
     * 내 매도 입찰 목록 조회
     */
    async getMyAsks() {
        if (!this.isLoggedIn) throw new Error('KREAM 로그인이 필요합니다.')
        const res = await fetch(`${KREAM_PROXY_URL}/api/kream/sell/my-bids`)
        if (!res.ok) throw new Error(`조회 실패: HTTP ${res.status}`)
        const data = await res.json()
        if (!data.success) throw new Error(data.message || '내 입찰 조회 실패')
        return data.data || []
    }

    // ==================== 유틸 ====================

    /**
     * 사이즈별 최저 매도호가 (즉시구매가) 반환
     * @param {Array} options - 상품 옵션 배열
     */
    getLowestAsk(options = []) {
        const asks = options.map(o => o.kreamAsk || 0).filter(p => p > 0)
        return asks.length > 0 ? Math.min(...asks) : 0
    }

    /**
     * 사이즈별 최고 매수호가 (즉시판매가) 반환
     */
    getHighestBid(options = []) {
        const bids = options.map(o => o.kreamBid || 0).filter(p => p > 0)
        return bids.length > 0 ? Math.max(...bids) : 0
    }
}

// 글로벌 인스턴스
const kreamManager = new KreamManager()
