/**
 * 카테고리 맵핑 관리 (CategoryManager)
 * 소싱처 카테고리 → 각 마켓 카테고리 맵핑
 */

class CategoryManager {
    constructor() {
        this.mappings = []

        // 마켓별 카테고리 예시 데이터
        this.marketCategories = {
            smartstore: [
                '패션의류 > 남성의류 > 티셔츠',
                '패션의류 > 남성의류 > 청바지',
                '패션의류 > 남성의류 > 아우터',
                '패션의류 > 여성의류 > 원피스',
                '패션의류 > 여성의류 > 블라우스',
                '패션의류 > 남성신발 > 스니커즈',
                '패션의류 > 여성신발 > 부츠',
                '패션잡화 > 가방 > 백팩',
                '패션잡화 > 가방 > 크로스백',
                '스포츠/레저 > 스포츠의류 > 상의',
                '스포츠/레저 > 스포츠신발 > 운동화',
                '뷰티 > 스킨케어 > 토너',
                '뷰티 > 스킨케어 > 에센스',
                '뷰티 > 선케어 > 선크림'
            ],
            gmarket: [
                '의류/패션 > 남성의류 > 티셔츠/반팔',
                '의류/패션 > 남성의류 > 청바지/팬츠',
                '의류/패션 > 남성신발 > 운동화',
                '의류/패션 > 여성의류 > 원피스/스커트',
                '의류/패션 > 여성신발 > 부츠/힐',
                '뷰티/화장품 > 스킨케어 > 에센스/세럼',
                '스포츠/레저 > 운동화 > 런닝화'
            ],
            coupang: [
                '패션 > 남성의류 > 상의 > 반팔 티셔츠',
                '패션 > 남성의류 > 하의 > 청바지',
                '패션 > 신발 > 운동화 > 스니커즈',
                '패션 > 여성의류 > 원피스',
                '뷰티 > 스킨케어 > 세럼/에센스',
                '스포츠/레저 > 스포츠의류 > 남성 상의'
            ],
            ssg: [
                '패션 > 남성패션 > 티셔츠',
                '패션 > 남성패션 > 청바지',
                '패션 > 신발 > 스니커즈',
                '스포츠/아웃도어 > 스포츠신발 > 런닝화',
                '뷰티/헬스 > 기초화장품 > 에센스'
            ]
        }
    }

    async init() {
        await this.loadMappings()
    }

    // ==================== CRUD ====================

    async loadMappings() {
        this.mappings = await storage.getAll('categoryMappings')
        return this.mappings
    }

    async addMapping(data) {
        const mapping = {
            id: 'cm_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8),
            sourceSite: data.sourceSite || '',
            sourceCategory: data.sourceCategory || '',
            targetMappings: data.targetMappings || {},
            appliedPolicyId: data.appliedPolicyId || null,
            createdAt: new Date().toISOString()
        }
        await storage.save('categoryMappings', mapping)
        this.mappings.push(mapping)
        return mapping
    }

    async updateMapping(id, data) {
        const mapping = this.mappings.find(m => m.id === id)
        if (!mapping) return null
        const updated = { ...mapping, ...data, updatedAt: new Date().toISOString() }
        await storage.save('categoryMappings', updated)
        const idx = this.mappings.findIndex(m => m.id === id)
        if (idx !== -1) this.mappings[idx] = updated
        return updated
    }

    async deleteMapping(id) {
        await storage.delete('categoryMappings', id)
        this.mappings = this.mappings.filter(m => m.id !== id)
    }

    // ==================== 조회 ====================

    findMapping(sourceSite, sourceCategory) {
        return this.mappings.find(m =>
            m.sourceSite === sourceSite && m.sourceCategory === sourceCategory
        )
    }

    /**
     * 유사 카테고리 추천 (키워드 기반)
     */
    suggestCategory(sourceCategory, targetMarket) {
        const categories = this.marketCategories[targetMarket] || []
        const keywords = sourceCategory.toLowerCase().split(/[>\s\/]+/).filter(k => k.length > 1)

        const scored = categories.map(cat => {
            const lower = cat.toLowerCase()
            const score = keywords.reduce((sum, kw) => sum + (lower.includes(kw) ? 1 : 0), 0)
            return { cat, score }
        })

        scored.sort((a, b) => b.score - a.score)
        return scored.slice(0, 5).map(s => s.cat)
    }

    getMarketCategoryList(market) {
        return this.marketCategories[market] || []
    }
}

// 글로벌 인스턴스
const categoryManager = new CategoryManager()
