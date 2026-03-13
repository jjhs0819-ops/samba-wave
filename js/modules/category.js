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

    // ==================== 카테고리 트리 영속화 ====================

    /**
     * categoryTree 스토어에서 전체 트리 로드
     * @returns {{ [siteName]: { cat1, cat2, cat3, cat4 } }}
     */
    async loadCategoryTree() {
        const records = await storage.getAll('categoryTree')
        const result = {}
        for (const rec of records) {
            result[rec.siteName] = {
                cat1: rec.cat1 || [],
                cat2: rec.cat2 || {},
                cat3: rec.cat3 || {},
                cat4: rec.cat4 || {}
            }
        }
        return result
    }

    /**
     * 수집 상품 기반 카테고리를 기존 트리에 병합 후 저장
     * 상품이 삭제되어도 한번 생성된 카테고리는 유지됨
     * @param {Object} newCatData - extractCategoriesFromProducts() 결과
     */
    async mergeAndSaveCategories(newCatData) {
        const toSortedArr = (set) => [...set].sort((a, b) => a.localeCompare(b, 'ko'))

        for (const [siteName, newData] of Object.entries(newCatData)) {
            const existing = await storage.get('categoryTree', siteName) || {
                siteName, cat1: [], cat2: {}, cat3: {}, cat4: {}
            }

            // cat1 병합
            const cat1 = toSortedArr(new Set([...existing.cat1, ...newData.cat1]))

            // cat2 병합 (cat1별 하위 목록)
            const cat2 = { ...existing.cat2 }
            for (const [k, arr] of Object.entries(newData.cat2)) {
                cat2[k] = toSortedArr(new Set([...(cat2[k] || []), ...arr]))
            }

            // cat3 병합
            const cat3 = { ...existing.cat3 }
            for (const [k, arr] of Object.entries(newData.cat3)) {
                cat3[k] = toSortedArr(new Set([...(cat3[k] || []), ...arr]))
            }

            // cat4 병합
            const cat4 = { ...existing.cat4 }
            for (const [k, arr] of Object.entries(newData.cat4)) {
                cat4[k] = toSortedArr(new Set([...(cat4[k] || []), ...arr]))
            }

            await storage.save('categoryTree', {
                siteName, cat1, cat2, cat3, cat4,
                updatedAt: new Date().toISOString()
            })
        }
    }

    /**
     * 특정 소싱사이트의 카테고리 트리 삭제
     * @param {string} siteName - 소싱사이트명
     */
    async deleteSiteCategoryTree(siteName) {
        await storage.delete('categoryTree', siteName)
    }

    /**
     * 수집 상품에서 사이트별 카테고리 계층 추출
     * @param {Array} products - collectedProducts 배열
     * @returns {{ [site]: { cat1, cat2, cat3, cat4 } }}
     */
    extractCategoriesFromProducts(products) {
        const raw = {}
        for (const p of products) {
            const site = p.sourceSite
            if (!site) continue
            if (!raw[site]) raw[site] = { cat1: new Set(), cat2: {}, cat3: {}, cat4: {} }

            const c1 = (p.category1 || '').trim()
            const c2 = (p.category2 || '').trim()
            const c3 = (p.category3 || '').trim()
            const c4 = (p.category4 || '').trim()

            if (!c1) continue
            raw[site].cat1.add(c1)

            if (!c2) continue
            if (!raw[site].cat2[c1]) raw[site].cat2[c1] = new Set()
            raw[site].cat2[c1].add(c2)

            if (!c3) continue
            const k12 = `${c1}|${c2}`
            if (!raw[site].cat3[k12]) raw[site].cat3[k12] = new Set()
            raw[site].cat3[k12].add(c3)

            if (!c4) continue
            const k123 = `${c1}|${c2}|${c3}`
            if (!raw[site].cat4[k123]) raw[site].cat4[k123] = new Set()
            raw[site].cat4[k123].add(c4)
        }

        const toArr = set => [...set].sort((a, b) => a.localeCompare(b, 'ko'))
        const result = {}
        for (const [site, data] of Object.entries(raw)) {
            result[site] = {
                cat1: toArr(data.cat1),
                cat2: Object.fromEntries(Object.entries(data.cat2).map(([k, v]) => [k, toArr(v)])),
                cat3: Object.fromEntries(Object.entries(data.cat3).map(([k, v]) => [k, toArr(v)])),
                cat4: Object.fromEntries(Object.entries(data.cat4).map(([k, v]) => [k, toArr(v)]))
            }
        }
        return result
    }
}

// 글로벌 인스턴스
const categoryManager = new CategoryManager()
