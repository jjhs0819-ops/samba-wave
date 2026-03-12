/**
 * 마켓 계정 관리 (AccountManager)
 * 다중 사업자/계정 관리 (예: G마켓 bonol06, 쿠팡 myshop01 등)
 */

class AccountManager {
    constructor() {
        this.accounts = []

        // 지원 마켓 목록
        this.supportedMarkets = [
            // 국내
            { id: 'auction', name: '옥션', group: '국내', apiFields: ['apiKey', 'apiSecret'] },
            { id: 'gmarket', name: 'G마켓', group: '국내', apiFields: ['apiKey', 'apiSecret'] },
            { id: '11st', name: '11번가', group: '국내', apiFields: ['apiKey', 'apiSecret'] },
            { id: 'smartstore', name: '스마트스토어', group: '국내', apiFields: ['apiKey', 'apiSecret', 'clientId'] },
            { id: 'coupang', name: '쿠팡', group: '국내', apiFields: ['accessKey', 'secretKey', 'vendorCode'] },
            { id: 'gsshop', name: 'GS샵', group: '국내', apiFields: ['apiKey', 'apiSecret'] }, // 판매마켓 ID (소싱처 GSShop과 별도)
            { id: 'lotteon', name: '롯데ON', group: '국내', apiFields: ['apiKey', 'apiSecret'] }, // 판매마켓 ID (소싱처 LOTTEON과 별도)
            { id: 'ssg', name: '신세계몰', group: '국내', apiFields: ['apiKey', 'apiSecret', 'mallId'] }, // 판매마켓 ID (소싱처 SSG와 별도)
            // 플레이오토
            { id: 'playauto', name: '플레이오토', group: '연동솔루션', apiFields: ['apiKey', 'userId'] },
            // 해외
            { id: 'ebay', name: 'eBay', group: '해외', apiFields: ['appId', 'devId', 'certId', 'authToken'] },
            { id: 'lazada', name: 'Lazada', group: '해외', apiFields: ['appKey', 'appSecret', 'accessToken'] },
            { id: 'shopee', name: 'Shopee', group: '해외', apiFields: ['partnerId', 'shopId', 'accessToken'] },
            { id: 'qoo10', name: 'Qoo10', group: '해외', apiFields: ['apiKey', 'userId'] },
            { id: 'quten', name: '큐텐', group: '해외', apiFields: ['apiKey', 'qUserId'] }
        ]
    }

    async init() {
        await this.loadAccounts()
    }

    // ==================== CRUD ====================

    async loadAccounts() {
        this.accounts = await storage.getAll('marketAccounts')
        return this.accounts
    }

    async addAccount(data) {
        const market = this.supportedMarkets.find(m => m.id === data.marketType)
        const account = {
            id: 'ma_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            marketType: data.marketType || '',
            marketName: market ? market.name : data.marketType,
            accountLabel: data.accountLabel || `${market ? market.name : data.marketType}-${data.sellerId || ''}`,
            sellerId: data.sellerId || '',
            businessName: data.businessName || '',
            apiKey: data.apiKey || '',
            apiSecret: data.apiSecret || '',
            additionalFields: data.additionalFields || {},
            isActive: data.isActive !== undefined ? data.isActive : true,
            createdAt: new Date().toISOString()
        }
        await storage.save('marketAccounts', account)
        this.accounts.push(account)
        return account
    }

    async updateAccount(id, data) {
        const account = this.accounts.find(a => a.id === id)
        if (!account) return null
        const updated = { ...account, ...data, updatedAt: new Date().toISOString() }
        await storage.save('marketAccounts', updated)
        const idx = this.accounts.findIndex(a => a.id === id)
        if (idx !== -1) this.accounts[idx] = updated
        return updated
    }

    async deleteAccount(id) {
        await storage.delete('marketAccounts', id)
        this.accounts = this.accounts.filter(a => a.id !== id)
    }

    async toggleActive(id) {
        const account = this.accounts.find(a => a.id === id)
        if (!account) return null
        return await this.updateAccount(id, { isActive: !account.isActive })
    }

    // ==================== 조회 ====================

    getActiveAccounts() {
        return this.accounts.filter(a => a.isActive)
    }

    getAccountsByMarket(marketType) {
        return this.accounts.filter(a => a.marketType === marketType)
    }

    getAccountLabel(id) {
        const account = this.accounts.find(a => a.id === id)
        return account ? account.accountLabel : id
    }

    getMarketInfo(marketType) {
        return this.supportedMarkets.find(m => m.id === marketType)
    }

    /**
     * The.Mango 스타일 라벨 생성 (예: "G마켓2.0-bonol06")
     */
    formatAccountLabel(account) {
        const market = this.supportedMarkets.find(m => m.id === account.marketType)
        const marketName = market ? market.name : account.marketType
        return account.accountLabel || `${marketName}-${account.sellerId}`
    }
}

// 글로벌 인스턴스
const accountManager = new AccountManager()
